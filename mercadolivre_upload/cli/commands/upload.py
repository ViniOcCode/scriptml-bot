"""Comando upload - Publicar produtos no Mercado Livre."""

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import typer
from rich.console import Console
from rich.panel import Panel

from mercadolivre_upload.adapters.image_uploader import ImageUploader
from mercadolivre_upload.adapters.spreadsheet.parser import SpreadsheetParser
from mercadolivre_upload.api.category_adapter import CategoryAdapter
from mercadolivre_upload.api.client import MLApiClient
from mercadolivre_upload.application.publish_product import PublishProductUseCase
from mercadolivre_upload.auth import AuthManager
from mercadolivre_upload.domain.category.resolver import CategoryResolver
from mercadolivre_upload.domain.fiscal.service import FiscalService
from mercadolivre_upload.domain.shipping.resolver import ShippingResolver
from mercadolivre_upload.infrastructure.cache.attribute_cache import AttributeCache
from mercadolivre_upload.shared.utils.config_loader import load_yaml_config as _load_yaml_config

logger = logging.getLogger(__name__)


def _normalize_cause_codes(raw_codes: Any) -> list[str]:
    if not isinstance(raw_codes, list):
        return []
    normalized: list[str] = []
    for code in raw_codes:
        code_text = str(code).strip().lower()
        if code_text and code_text not in normalized:
            normalized.append(code_text)
    return normalized


def _normalize_cause_taxonomy(raw_taxonomy: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_taxonomy, list):
        return []
    return [dict(cause) for cause in raw_taxonomy if isinstance(cause, dict)]


def _default_validation_decision(status: str) -> dict[str, Any]:
    action = "block" if status.strip().lower() == "failed" else "allow"
    return {
        "mode": "unknown",
        "strict_warning_gate_mode": "unknown",
        "strict_attribute_warnings": None,
        "action": action,
        "reason": "missing_validation_decision",
        "classification_counts": {
            "blocking_error": 0,
            "retryable_error": 0,
            "critical_warning": 0,
            "informational_warning": 0,
        },
        "classification_codes": {
            "blocking_error": [],
            "retryable_error": [],
            "critical_warning": [],
            "informational_warning": [],
        },
    }


def _ensure_observability_evidence(
    item: dict[str, Any],
    *,
    row_status: str,
    default_flow_routing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized = dict(item)
    normalized["cause_codes"] = _normalize_cause_codes(normalized.get("cause_codes"))
    normalized["cause_taxonomy"] = _normalize_cause_taxonomy(normalized.get("cause_taxonomy"))

    validation_decision = normalized.get("validation_decision")
    if isinstance(validation_decision, dict):
        normalized["validation_decision"] = dict(validation_decision)
    else:
        normalized["validation_decision"] = _default_validation_decision(row_status)

    policy_hash = normalized.get("policy_hash")
    normalized["policy_hash"] = (
        policy_hash if isinstance(policy_hash, str) and policy_hash else None
    )
    policy_summary = normalized.get("policy_summary")
    normalized["policy_summary"] = dict(policy_summary) if isinstance(policy_summary, dict) else {}

    schema_contract_hash = normalized.get("schema_contract_hash")
    normalized["schema_contract_hash"] = (
        schema_contract_hash
        if isinstance(schema_contract_hash, str) and schema_contract_hash
        else None
    )
    schema_contract_summary = normalized.get("schema_contract_summary")
    normalized["schema_contract_summary"] = (
        dict(schema_contract_summary) if isinstance(schema_contract_summary, dict) else {}
    )

    flow_routing = normalized.get("flow_routing")
    if isinstance(flow_routing, dict):
        normalized["flow_routing"] = dict(flow_routing)
    elif isinstance(default_flow_routing, dict):
        normalized["flow_routing"] = dict(default_flow_routing)
    else:
        normalized["flow_routing"] = {}

    identifier_gate = normalized.get("identifier_gate")
    if isinstance(identifier_gate, dict):
        normalized["identifier_gate"] = dict(identifier_gate)

    image_diagnostics = normalized.get("image_diagnostics")
    if isinstance(image_diagnostics, dict):
        normalized["image_diagnostics"] = dict(image_diagnostics)

    shipping_policy = normalized.get("shipping_policy")
    if isinstance(shipping_policy, dict):
        normalized["shipping_policy"] = dict(shipping_policy)

    rollout_flags = normalized.get("rollout_flags")
    if isinstance(rollout_flags, dict):
        normalized["rollout_flags"] = dict(rollout_flags)
    else:
        normalized["rollout_flags"] = {}

    return normalized


def _is_warning_classification(classification: str) -> bool:
    return classification in {"critical_warning", "informational_warning"}


def _is_error_classification(classification: str) -> bool:
    return classification in {"blocking_error", "retryable_error"}


def _increment_code_counter(counter: dict[str, int], code: str) -> None:
    normalized = code.strip().lower()
    if not normalized:
        return
    counter[normalized] = counter.get(normalized, 0) + 1


def _top_code_entries(counter: dict[str, int], limit: int = 5) -> list[dict[str, Any]]:
    return [
        {"code": code, "count": count}
        for code, count in sorted(counter.items(), key=lambda item: (-item[1], item[0]))[:limit]
    ]


def _top_codes_by_status(
    counters: dict[str, dict[str, int]], limit: int = 5
) -> dict[str, list[dict[str, Any]]]:
    return {status: _top_code_entries(counter, limit=limit) for status, counter in counters.items()}


def load_config() -> dict[str, Any]:
    """Load configuration from split YAML files with legacy fallback."""
    config: dict[str, Any] = {}
    for path in [
        Path("config/standard_fields.yaml"),
        Path("config/shipping.yaml"),
        Path("config/attribute_rules.yaml"),
        Path("config/header_detection.yaml"),
    ]:
        config.update(_load_yaml_config(path))

    legacy_config = _load_yaml_config(Path("config/generic_mappings.yaml"))
    if legacy_config:
        for key, value in legacy_config.items():
            config.setdefault(key, value)

    return config


def build_publish_use_case(
    *,
    images: Path,
    cache_dir: Path,
    config: dict[str, Any],
    dry_run: bool = False,
    validation_only: bool = False,
) -> PublishProductUseCase:
    """Build upload/validate use case with shared dependency wiring."""
    auth_manager = AuthManager()
    api_client = MLApiClient(auth_manager)
    cache = AttributeCache(cache_dir=str(cache_dir))

    from mercadolivre_upload.infrastructure.cache.prediction_cache import PredictionCache

    prediction_cache = PredictionCache(cache_dir=str(cache_dir / "predictions"))
    category_adapter = CategoryAdapter(api_client)
    image_uploader = ImageUploader(api_client, images)

    from mercadolivre_upload.adapters.clip_uploader import ClipUploader

    clip_uploader = ClipUploader(api_client, base_path=images)
    category_resolver = CategoryResolver(
        category_adapter, attribute_cache=cache, prediction_cache=prediction_cache
    )
    shipping_resolver = ShippingResolver(api_client)
    fiscal_service = FiscalService(api_client)  # type: ignore[arg-type]

    return PublishProductUseCase(
        category_resolver=category_resolver,
        publisher=api_client,
        image_uploader=image_uploader,
        shipping_resolver=shipping_resolver,
        fiscal_service=fiscal_service,
        clip_uploader=clip_uploader,
        config=config,
        dry_run=dry_run,
        validation_only=validation_only,
        attribute_cache=cache,
    )


console = Console()
err_console = Console(stderr=True)

app = typer.Typer(name="upload", help="Upload products from Excel")


def _extract_row_identity(row: dict[str, Any]) -> tuple[str | None, str | None]:
    sku = None
    for key in ("sku", "codigo", "código", "code"):
        value = row.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            sku = text
            break

    title = None
    for key in ("titulo", "título", "title", "nome"):
        value = row.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            title = text
            break

    return sku, title


def _extract_row_category(row: dict[str, Any]) -> str | None:
    direct_keys = ("category_id", "category", "categoria", "categoria_id", "my_category")
    for key in direct_keys:
        value = row.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text

    for key, value in row.items():
        normalized = str(key).strip().lower().replace(" ", "_").replace("-", "_")
        if normalized in direct_keys:
            text = str(value).strip()
            if text:
                return text

    return None


def _merge_category_resolution_fields(
    target: dict[str, Any], source: dict[str, Any], default_input: str | None = None
) -> None:
    category_input = source.get("category_input")
    if not isinstance(category_input, str) or not category_input:
        category_input = default_input
    target["category_input"] = category_input

    category_resolved_id = source.get("category_resolved_id")
    if isinstance(category_resolved_id, str) and category_resolved_id:
        target["category_resolved_id"] = category_resolved_id
    else:
        target["category_resolved_id"] = None

    category_path = source.get("category_path")
    target["category_path"] = list(category_path) if isinstance(category_path, list) else []

    resolution_strategy = source.get("resolution_strategy")
    if isinstance(resolution_strategy, str) and resolution_strategy:
        target["resolution_strategy"] = resolution_strategy
    else:
        target["resolution_strategy"] = "unresolved"


@app.callback(invoke_without_command=True)
def upload(
    excel: Path = typer.Option(..., "--excel", "-e", help="Excel file path"),  # noqa: B008
    images: Path = typer.Option(..., "--images", "-i", help="Images directory"),  # noqa: B008
    category: str = typer.Option(..., "--category", "-c", help="Category name"),  # noqa: B008
    cache_dir: Path = typer.Option(Path("cache/categories"), "--cache-dir"),  # noqa: B008
    dry_run: bool = typer.Option(False, "--dry-run", "-n", help="Validate only"),  # noqa: B008
    detailed: bool = typer.Option(False, "--detailed", "-d"),  # noqa: B008
    batch_size: int = typer.Option(5, "--batch-size", min=1, help="Items per batch"),  # noqa: B008
    report_dir: Path = typer.Option(Path("cache/reports"), "--report-dir"),  # noqa: B008
) -> Any:
    """Upload products from Excel to Mercado Livre."""
    console.print(Panel.fit("Mercado Livre Bulk Upload", style="cyan"))

    # Load configuration
    config = load_config()

    # Defensive: if cache_dir is OptionInfo, use default
    if isinstance(cache_dir, typer.models.OptionInfo):
        cache_dir = Path("cache/categories")
    elif not isinstance(cache_dir, Path):
        cache_dir = Path(cache_dir)

    # Defensive: if report_dir is OptionInfo, use default
    if isinstance(report_dir, typer.models.OptionInfo):
        report_dir = Path("cache/reports")
    elif not isinstance(report_dir, Path):
        report_dir = Path(report_dir)

    if batch_size < 1:
        err_console.print("[red]batch-size must be greater than zero[/red]")
        raise typer.Exit(1)

    use_case = build_publish_use_case(
        images=images,
        cache_dir=cache_dir,
        config=config,
        dry_run=dry_run,
    )

    # Parse products
    parser = SpreadsheetParser()
    try:
        products = parser.parse(excel)
        console.print(f"Found {len(products)} products")
    except (FileNotFoundError, ValueError) as e:
        err_console.print(f"[red]Error parsing Excel: {e}[/red]")
        raise typer.Exit(1) from e

    if dry_run:
        console.print("[yellow]Dry run mode - validating only[/yellow]")
        return

    total_products = len(products)
    total_batches = (total_products + batch_size - 1) // batch_size
    console.print(f"Batch size: {batch_size} ({total_batches} batches)")

    all_item_results: list[dict[str, Any]] = []
    failed_rows_for_export: list[dict[str, Any]] = []
    batch_summaries: list[dict[str, Any]] = []
    all_errors: list[str] = []
    total_published = 0
    total_failed = 0
    total_clips_uploaded = 0
    total_clips_failed = 0
    cause_code_counts: dict[str, int] = {}
    warning_code_counts: dict[str, dict[str, int]] = {"success": {}, "failed": {}}
    error_code_counts: dict[str, dict[str, int]] = {"success": {}, "failed": {}}

    for start in range(0, total_products, batch_size):
        batch_index = (start // batch_size) + 1
        batch_products = products[start : start + batch_size]
        console.print(f"[cyan]Processing batch {batch_index}/{total_batches}...[/cyan]")

        item_results: list[dict[str, Any]] = []
        for index, row in enumerate(batch_products):
            sku, title = _extract_row_identity(row)
            input_category = _extract_row_category(row) or category
            base_item = {
                "index": index,
                "sku": sku,
                "title": title,
                "status": "failed",
                "error": "Missing item result from use case",
            }
            _merge_category_resolution_fields(base_item, {}, input_category)
            item_results.append(base_item)
        grouped_products: dict[str, list[tuple[int, dict[str, Any]]]] = {}
        for index, row in enumerate(batch_products):
            row_category = _extract_row_category(row) or category
            grouped_products.setdefault(row_category, []).append((index, row))

        batch_published = 0
        batch_failed = 0
        batch_clips_uploaded = 0
        batch_clips_failed = 0
        batch_errors: list[str] = []

        for group_category, indexed_rows in grouped_products.items():
            rows_for_category = [row for _, row in indexed_rows]
            results = use_case.execute(rows_for_category, group_category)  # type: ignore[arg-type]
            raw_group_flow_routing = results.get("flow_routing")
            group_flow_routing = (
                dict(raw_group_flow_routing) if isinstance(raw_group_flow_routing, dict) else None
            )

            batch_published += int(results.get("published", 0))
            batch_failed += int(results.get("failed", 0))
            batch_clips_uploaded += int(results.get("clips_uploaded", 0))
            batch_clips_failed += int(results.get("clips_failed", 0))
            batch_errors.extend(str(error) for error in results.get("errors", []))

            grouped_results: list[dict[str, Any]] = []
            for group_index, (_, row) in enumerate(indexed_rows):
                sku, title = _extract_row_identity(row)
                base_item = {
                    "index": group_index,
                    "sku": sku,
                    "title": title,
                    "status": "failed",
                    "error": "Missing item result from use case",
                }
                _merge_category_resolution_fields(base_item, {}, group_category)
                grouped_results.append(base_item)

            raw_item_results = results.get("item_results", [])
            if isinstance(raw_item_results, list):
                for position, item in enumerate(raw_item_results):
                    if not isinstance(item, dict):
                        continue

                    target_index = item.get("index")
                    if not isinstance(target_index, int):
                        target_index = position
                    if target_index < 0 or target_index >= len(indexed_rows):
                        continue

                    row_status = str(item.get("status", "failed")).lower()
                    mapped_item = {
                        "index": target_index,
                        "sku": item.get("sku") or grouped_results[target_index]["sku"],
                        "title": item.get("title") or grouped_results[target_index]["title"],
                        "status": "success" if row_status == "success" else "failed",
                        "error": item.get("error"),
                    }
                    cause_codes = item.get("cause_codes")
                    if isinstance(cause_codes, list):
                        normalized_codes = [str(code) for code in cause_codes if str(code).strip()]
                        if normalized_codes:
                            mapped_item["cause_codes"] = normalized_codes
                    cause_taxonomy = item.get("cause_taxonomy")
                    if isinstance(cause_taxonomy, list):
                        normalized_taxonomy = [
                            dict(cause) for cause in cause_taxonomy if isinstance(cause, dict)
                        ]
                        if normalized_taxonomy:
                            mapped_item["cause_taxonomy"] = normalized_taxonomy
                    validation_decision = item.get("validation_decision")
                    if isinstance(validation_decision, dict):
                        mapped_item["validation_decision"] = dict(validation_decision)
                    _merge_category_resolution_fields(
                        mapped_item,
                        item,
                        grouped_results[target_index].get("category_input"),
                    )
                    policy_hash = item.get("policy_hash")
                    if isinstance(policy_hash, str) and policy_hash:
                        mapped_item["policy_hash"] = policy_hash
                    policy_summary = item.get("policy_summary")
                    if isinstance(policy_summary, dict):
                        mapped_item["policy_summary"] = policy_summary
                    schema_contract_hash = item.get("schema_contract_hash")
                    if isinstance(schema_contract_hash, str) and schema_contract_hash:
                        mapped_item["schema_contract_hash"] = schema_contract_hash
                    schema_contract_summary = item.get("schema_contract_summary")
                    if isinstance(schema_contract_summary, dict):
                        mapped_item["schema_contract_summary"] = schema_contract_summary
                    identifier_gate = item.get("identifier_gate")
                    if isinstance(identifier_gate, dict):
                        mapped_item["identifier_gate"] = identifier_gate
                    flow_routing = item.get("flow_routing")
                    if isinstance(flow_routing, dict):
                        mapped_item["flow_routing"] = flow_routing
                    elif group_flow_routing is not None:
                        mapped_item["flow_routing"] = dict(group_flow_routing)
                    image_diagnostics = item.get("image_diagnostics")
                    if isinstance(image_diagnostics, dict):
                        mapped_item["image_diagnostics"] = image_diagnostics
                    shipping_policy = item.get("shipping_policy")
                    if isinstance(shipping_policy, dict):
                        mapped_item["shipping_policy"] = shipping_policy
                    rollout_flags = item.get("rollout_flags")
                    if isinstance(rollout_flags, dict):
                        mapped_item["rollout_flags"] = rollout_flags
                    grouped_results[target_index] = _ensure_observability_evidence(
                        mapped_item,
                        row_status=mapped_item["status"],
                        default_flow_routing=group_flow_routing,
                    )

            for group_index, (batch_index_pos, _) in enumerate(indexed_rows):
                mapped = _ensure_observability_evidence(
                    dict(grouped_results[group_index]),
                    row_status=str(grouped_results[group_index].get("status", "failed")),
                    default_flow_routing=group_flow_routing,
                )
                mapped["index"] = batch_index_pos
                item_results[batch_index_pos] = mapped

        total_published += batch_published
        total_failed += batch_failed
        total_clips_uploaded += batch_clips_uploaded
        total_clips_failed += batch_clips_failed
        all_errors.extend(batch_errors)

        for index, row in enumerate(batch_products):
            item_result = item_results[index]
            row_status = str(item_result.get("status", "failed")).lower()
            normalized = {
                "batch": batch_index,
                "index": start + index,
                "sku": item_result.get("sku"),
                "title": item_result.get("title"),
                "status": row_status,
                "error": item_result.get("error"),
            }
            cause_codes = item_result.get("cause_codes")
            if isinstance(cause_codes, list):
                normalized_codes = [str(code) for code in cause_codes if str(code).strip()]
                if normalized_codes:
                    normalized["cause_codes"] = normalized_codes
            cause_taxonomy = item_result.get("cause_taxonomy")
            if isinstance(cause_taxonomy, list):
                normalized_taxonomy = [
                    dict(cause) for cause in cause_taxonomy if isinstance(cause, dict)
                ]
                if normalized_taxonomy:
                    normalized["cause_taxonomy"] = normalized_taxonomy
            validation_decision = item_result.get("validation_decision")
            if isinstance(validation_decision, dict):
                normalized["validation_decision"] = dict(validation_decision)
            _merge_category_resolution_fields(
                normalized,
                item_result,
                item_result.get("category_input"),
            )
            policy_hash = item_result.get("policy_hash")
            if isinstance(policy_hash, str) and policy_hash:
                normalized["policy_hash"] = policy_hash
            policy_summary = item_result.get("policy_summary")
            if isinstance(policy_summary, dict):
                normalized["policy_summary"] = policy_summary
            schema_contract_hash = item_result.get("schema_contract_hash")
            if isinstance(schema_contract_hash, str) and schema_contract_hash:
                normalized["schema_contract_hash"] = schema_contract_hash
            schema_contract_summary = item_result.get("schema_contract_summary")
            if isinstance(schema_contract_summary, dict):
                normalized["schema_contract_summary"] = schema_contract_summary
            identifier_gate = item_result.get("identifier_gate")
            if isinstance(identifier_gate, dict):
                normalized["identifier_gate"] = identifier_gate
            flow_routing = item_result.get("flow_routing")
            if isinstance(flow_routing, dict):
                normalized["flow_routing"] = flow_routing
            image_diagnostics = item_result.get("image_diagnostics")
            if isinstance(image_diagnostics, dict):
                normalized["image_diagnostics"] = image_diagnostics
            shipping_policy = item_result.get("shipping_policy")
            if isinstance(shipping_policy, dict):
                normalized["shipping_policy"] = shipping_policy
            rollout_flags = item_result.get("rollout_flags")
            if isinstance(rollout_flags, dict):
                normalized["rollout_flags"] = rollout_flags
            normalized = _ensure_observability_evidence(normalized, row_status=row_status)
            all_item_results.append(normalized)

            status_bucket = "success" if row_status == "success" else "failed"
            cause_codes = normalized.get("cause_codes", [])
            normalized_codes = (
                [str(code).strip().lower() for code in cause_codes if str(code).strip()]
                if isinstance(cause_codes, list)
                else []
            )
            warning_codes_for_row: set[str] = set()
            error_codes_for_row: set[str] = set()
            all_codes_for_row: set[str] = set(normalized_codes)
            taxonomy = normalized.get("cause_taxonomy")
            if isinstance(taxonomy, list):
                for cause in taxonomy:
                    if not isinstance(cause, dict):
                        continue
                    code = str(cause.get("code", "")).strip().lower()
                    if not code:
                        continue
                    all_codes_for_row.add(code)
                    classification = str(cause.get("classification", "")).strip().lower()
                    if _is_warning_classification(classification):
                        warning_codes_for_row.add(code)
                    elif _is_error_classification(classification):
                        error_codes_for_row.add(code)
                    else:
                        cause_type = str(cause.get("type", "")).strip().lower()
                        if cause_type == "warning":
                            warning_codes_for_row.add(code)
                        elif cause_type == "error":
                            error_codes_for_row.add(code)

            if not warning_codes_for_row and not error_codes_for_row:
                if status_bucket == "success":
                    warning_codes_for_row.update(normalized_codes)
                else:
                    error_codes_for_row.update(normalized_codes)

            for code in all_codes_for_row:
                _increment_code_counter(cause_code_counts, code)
            for code in warning_codes_for_row:
                _increment_code_counter(warning_code_counts[status_bucket], code)
            for code in error_codes_for_row:
                _increment_code_counter(error_code_counts[status_bucket], code)

            if row_status != "success":
                failed_row = dict(row)
                failed_row["_batch"] = batch_index
                failed_row["_error"] = item_result.get("error")
                if normalized_codes:
                    failed_row["_cause_codes"] = ", ".join(normalized_codes)
                normalized_taxonomy = normalized.get("cause_taxonomy", [])
                if isinstance(normalized_taxonomy, list) and normalized_taxonomy:
                    failed_row["_cause_taxonomy"] = json.dumps(
                        normalized_taxonomy, ensure_ascii=False
                    )
                normalized_decision = normalized.get("validation_decision")
                if isinstance(normalized_decision, dict):
                    failed_row["_validation_decision"] = json.dumps(
                        normalized_decision, ensure_ascii=False
                    )
                failed_rows_for_export.append(failed_row)

        batch_summaries.append(
            {
                "batch": batch_index,
                "size": len(batch_products),
                "published": batch_published,
                "failed": batch_failed,
            }
        )
        console.print(
            f"[green]Batch {batch_index}: {batch_published} published[/green], "
            f"[red]{batch_failed} failed[/red]"
        )

    report_dir.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    summary_path = report_dir / f"upload-summary-{run_id}.json"
    failed_items_path = report_dir / f"failed-items-{run_id}.xlsx"
    rollout_flags_snapshot: dict[str, Any] = {}
    for item in all_item_results:
        raw_rollout_flags = item.get("rollout_flags")
        if isinstance(raw_rollout_flags, dict) and raw_rollout_flags:
            rollout_flags_snapshot = dict(raw_rollout_flags)
            break

    summary_report = {
        "run_id": run_id,
        "source_file": str(excel),
        "category": category,
        "batch_size": batch_size,
        "total_items": total_products,
        "total_batches": total_batches,
        "published": total_published,
        "failed": total_failed,
        "clips_uploaded": total_clips_uploaded,
        "clips_failed": total_clips_failed,
        "cause_code_counts": cause_code_counts,
        "warning_code_counts": warning_code_counts,
        "error_code_counts": error_code_counts,
        "top_cause_codes": _top_code_entries(cause_code_counts),
        "top_warning_codes_by_status": _top_codes_by_status(warning_code_counts),
        "top_error_codes_by_status": _top_codes_by_status(error_code_counts),
        "rollout_flags": rollout_flags_snapshot,
        "batches": batch_summaries,
        "items": all_item_results,
    }
    summary_path.write_text(
        json.dumps(summary_report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    if failed_rows_for_export:
        pd.DataFrame(failed_rows_for_export).to_excel(failed_items_path, index=False)

    # Report final results
    console.print(f"\n[green]Published: {total_published}[/green]")
    if total_failed > 0:
        console.print(f"[red]Failed: {total_failed}[/red]")

    if total_clips_uploaded > 0:
        console.print(f"[cyan]Clips uploaded: {total_clips_uploaded}[/cyan]")
    if total_clips_failed > 0:
        console.print(f"[yellow]Clips failed: {total_clips_failed}[/yellow]")

    console.print(f"[cyan]Summary report: {summary_path}[/cyan]")
    if failed_rows_for_export:
        console.print(f"[yellow]Failed items file: {failed_items_path}[/yellow]")
    else:
        console.print("[green]No failed items file generated (all items succeeded).[/green]")

    if detailed and all_errors:
        console.print("\n[yellow]Errors:[/yellow]")
        for error in all_errors[:20]:
            console.print(f"  • {error}")
