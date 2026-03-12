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
from mercadolivre_upload.auth import TokenManager
from mercadolivre_upload.cli.commands.batch_reporting import (
    _extract_group_flow_routing,
    _extract_rollout_flags_snapshot,
    _merge_item_observability_fields,
    _resolve_cause_codes,
    _update_cause_code_counters,
)
from mercadolivre_upload.cli.commands.common import (
    coerce_path_option,
    merge_category_resolution_fields,
    parse_products_or_exit,
)
from mercadolivre_upload.cli.commands.upload_reporting import (
    _empty_category_resolution_summary,
    _ensure_observability_evidence,
    _extract_cause_codes,  # noqa: F401
    _extract_decision_classified_codes,  # noqa: F401
    _increment_code_counter,  # noqa: F401
    _is_error_classification,  # noqa: F401
    _is_warning_classification,  # noqa: F401
    _merge_category_resolution_summary,
    _top_code_entries,
    _top_codes_by_status,
)
from mercadolivre_upload.domain.category.resolver import CategoryResolver
from mercadolivre_upload.domain.fiscal.service import FiscalService
from mercadolivre_upload.domain.shipping.resolver import ShippingResolver
from mercadolivre_upload.infrastructure.cache.attribute_cache import AttributeCache
from mercadolivre_upload.shared.utils.config_loader import (
    RUNTIME_SPLIT_CONFIG_PATHS,
    load_merged_yaml_config,
)

logger = logging.getLogger(__name__)


def load_config() -> dict[str, Any]:
    """Load runtime configs from split files."""
    return load_merged_yaml_config(*RUNTIME_SPLIT_CONFIG_PATHS)


def build_publish_use_case(
    *,
    images: Path,
    cache_dir: Path,
    config: dict[str, Any],
    dry_run: bool = False,
    validation_only: bool = False,
) -> PublishProductUseCase:
    """Build upload/validate use case with shared dependency wiring."""
    auth_manager = TokenManager()
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


def _build_row_category_metadata(row: dict[str, Any], default_category: str) -> dict[str, Any]:
    row_category = _extract_row_category(row)
    normalized_default = default_category.strip().casefold()
    normalized_row = row_category.strip().casefold() if isinstance(row_category, str) else ""
    return {
        "row_category_detected": row_category,
        "row_category_mismatch": bool(normalized_row and normalized_row != normalized_default),
    }


def _prime_category_resolution_context(
    use_case: PublishProductUseCase,
    products: list[dict[str, Any]],
    category: str,
) -> None:
    resolver = getattr(use_case, "_resolve_category_context", None)
    if not callable(resolver):
        return
    try:
        resolver(products, category, use_cache=False)
    except TypeError:
        try:
            resolver(products, category)
        except Exception as exc:
            logger.warning("Could not pre-resolve category context for batch run: %s", exc)
    except Exception as exc:
        logger.warning("Could not pre-resolve category context for batch run: %s", exc)


@app.callback(invoke_without_command=True)
def upload(
    excel: Path = typer.Option(..., "--excel", "-e", help="Excel file path"),  # noqa: B008
    images: Path = typer.Option(..., "--images", "-i", help="Images directory"),  # noqa: B008
    category: str = typer.Option(..., "--category", "-c", help="Category name"),  # noqa: B008
    cache_dir: Path = typer.Option(Path("cache/categories"), "--cache-dir"),  # noqa: B008
    detailed: bool = typer.Option(False, "--detailed", "-d"),  # noqa: B008
    batch_size: int = typer.Option(5, "--batch-size", min=1, help="Items per batch"),  # noqa: B008
    report_dir: Path = typer.Option(Path("cache/reports"), "--report-dir"),  # noqa: B008
) -> Any:
    """Upload products from Excel to Mercado Livre."""
    console.print(Panel.fit("Mercado Livre Bulk Upload", style="cyan"))

    # Load configuration
    config = load_config()

    cache_dir = coerce_path_option(cache_dir, default=Path("cache/categories"))
    report_dir = coerce_path_option(report_dir, default=Path("cache/reports"))

    if batch_size < 1:
        err_console.print("[red]batch-size must be greater than zero[/red]")
        raise typer.Exit(1)

    use_case = build_publish_use_case(
        images=images,
        cache_dir=cache_dir,
        config=config,
    )

    # Parse products
    parser = SpreadsheetParser()
    products = parse_products_or_exit(parser=parser, excel=excel, err_console=err_console)
    console.print(f"Found {len(products)} products")

    _prime_category_resolution_context(use_case, products, category)

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
    total_fiscal = {
        "submitted": 0,
        "verified": 0,
        "pending_verification": 0,
        "failed": 0,
        "skipped_invalid": 0,
        "already_exists": 0,
        "registered": 0,
    }
    cause_code_counts: dict[str, int] = {}
    warning_code_counts: dict[str, dict[str, int]] = {"success": {}, "failed": {}}
    error_code_counts: dict[str, dict[str, int]] = {"success": {}, "failed": {}}
    category_resolution_summary = _empty_category_resolution_summary()
    row_category_signals = {"detected": 0, "mismatched": 0}

    for start in range(0, total_products, batch_size):
        batch_index = (start // batch_size) + 1
        batch_products = products[start : start + batch_size]
        console.print(f"[cyan]Processing batch {batch_index}/{total_batches}...[/cyan]")

        item_results: list[dict[str, Any]] = []
        for index, row in enumerate(batch_products):
            sku, title = _extract_row_identity(row)
            row_category_metadata = _build_row_category_metadata(row, category)
            base_item = {
                "index": index,
                "sku": sku,
                "title": title,
                "status": "failed",
                "error": "Missing item result from use case",
                "row_category_detected": row_category_metadata["row_category_detected"],
                "row_category_mismatch": row_category_metadata["row_category_mismatch"],
            }
            merge_category_resolution_fields(base_item, {}, category)
            item_results.append(base_item)
            if row_category_metadata["row_category_detected"]:
                row_category_signals["detected"] += 1
            if row_category_metadata["row_category_mismatch"]:
                row_category_signals["mismatched"] += 1

        results = use_case.execute(batch_products, category)  # type: ignore[arg-type]
        _merge_category_resolution_summary(
            category_resolution_summary,
            results.get("category_resolution"),
        )
        group_flow_routing = _extract_group_flow_routing(results)

        batch_published = int(results.get("published", 0))
        batch_failed = int(results.get("failed", 0))
        batch_clips_uploaded = int(results.get("clips_uploaded", 0))
        batch_clips_failed = int(results.get("clips_failed", 0))
        batch_errors = [str(error) for error in results.get("errors", [])]
        batch_fiscal = {
            "submitted": 0,
            "verified": 0,
            "pending_verification": 0,
            "failed": 0,
            "skipped_invalid": 0,
            "already_exists": 0,
            "registered": 0,
        }
        batch_fiscal_raw = results.get("fiscal")
        if isinstance(batch_fiscal_raw, dict):
            for key in batch_fiscal:
                batch_fiscal[key] = int(batch_fiscal_raw.get(key, 0) or 0)
        else:
            legacy_fiscal_success = int(results.get("fiscal_submitted", 0) or 0)
            legacy_fiscal_failed = int(results.get("fiscal_failed", 0) or 0)
            batch_fiscal["submitted"] = legacy_fiscal_success + legacy_fiscal_failed
            batch_fiscal["verified"] = legacy_fiscal_success
            batch_fiscal["failed"] = legacy_fiscal_failed

        raw_item_results = results.get("item_results", [])
        if isinstance(raw_item_results, list):
            for position, item in enumerate(raw_item_results):
                if not isinstance(item, dict):
                    continue

                target_index = item.get("index")
                if not isinstance(target_index, int):
                    target_index = position
                if target_index < 0 or target_index >= len(batch_products):
                    continue

                row_status = str(item.get("status", "failed")).lower()
                error_text = item.get("error")
                mapped_item = {
                    "index": target_index,
                    "sku": item.get("sku") or item_results[target_index]["sku"],
                    "title": item.get("title") or item_results[target_index]["title"],
                    "status": "success" if row_status == "success" else "failed",
                    "error": error_text,
                    "row_category_detected": item_results[target_index].get(
                        "row_category_detected"
                    ),
                    "row_category_mismatch": item_results[target_index].get(
                        "row_category_mismatch", False
                    ),
                }
                normalized_codes = _resolve_cause_codes(item.get("cause_codes"), error_text)
                if normalized_codes:
                    mapped_item["cause_codes"] = normalized_codes
                _merge_item_observability_fields(
                    mapped_item,
                    item,
                    category_input=item_results[target_index].get("category_input"),
                    default_flow_routing=group_flow_routing,
                )
                item_results[target_index] = _ensure_observability_evidence(
                    mapped_item,
                    row_status=mapped_item["status"],
                    default_flow_routing=group_flow_routing,
                )

        for index, mapped_item in enumerate(item_results):
            normalized_item = _ensure_observability_evidence(
                dict(mapped_item),
                row_status=str(mapped_item.get("status", "failed")),
                default_flow_routing=group_flow_routing,
            )
            normalized_item["index"] = index
            item_results[index] = normalized_item

        total_published += batch_published
        total_failed += batch_failed
        total_clips_uploaded += batch_clips_uploaded
        total_clips_failed += batch_clips_failed
        all_errors.extend(batch_errors)
        for key in total_fiscal:
            total_fiscal[key] += batch_fiscal[key]

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
                "row_category_detected": item_result.get("row_category_detected"),
                "row_category_mismatch": bool(item_result.get("row_category_mismatch", False)),
            }
            normalized_codes = _resolve_cause_codes(
                item_result.get("cause_codes"),
                item_result.get("error"),
            )
            if normalized_codes:
                normalized["cause_codes"] = normalized_codes
            _merge_item_observability_fields(
                normalized,
                item_result,
                category_input=item_result.get("category_input"),
            )
            normalized = _ensure_observability_evidence(normalized, row_status=row_status)
            all_item_results.append(normalized)

            status_bucket = "success" if row_status == "success" else "failed"
            _update_cause_code_counters(
                normalized,
                status_bucket=status_bucket,
                cause_code_counts=cause_code_counts,
                warning_code_counts=warning_code_counts,
                error_code_counts=error_code_counts,
            )

            if row_status != "success":
                failed_row = dict(row)
                failed_row["_batch"] = batch_index
                failed_row["_error"] = item_result.get("error")
                failed_row["_row_category_detected"] = item_result.get("row_category_detected")
                failed_row["_row_category_mismatch"] = bool(
                    item_result.get("row_category_mismatch", False)
                )
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
                "fiscal": batch_fiscal,
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
    rollout_flags_snapshot = _extract_rollout_flags_snapshot(all_item_results)

    summary_report = {
        "run_id": run_id,
        "source_file": str(excel),
        "category": category,
        "batch_size": batch_size,
        "total_items": total_products,
        "total_batches": total_batches,
        "published": total_published,
        "failed": total_failed,
        "fiscal": total_fiscal,
        "clips_uploaded": total_clips_uploaded,
        "clips_failed": total_clips_failed,
        "cause_code_counts": cause_code_counts,
        "warning_code_counts": warning_code_counts,
        "error_code_counts": error_code_counts,
        "top_cause_codes": _top_code_entries(cause_code_counts),
        "top_warning_codes_by_status": _top_codes_by_status(warning_code_counts),
        "top_error_codes_by_status": _top_codes_by_status(error_code_counts),
        "category_resolution": category_resolution_summary,
        "row_category_signals": row_category_signals,
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
    if total_fiscal["submitted"] > 0:
        console.print(
            "[cyan]Fiscal: "
            f"submitted={total_fiscal['submitted']}, "
            f"verified={total_fiscal['verified']}, "
            f"pending={total_fiscal['pending_verification']}, "
            f"failed={total_fiscal['failed']}, "
            f"skipped_invalid={total_fiscal['skipped_invalid']}[/cyan]"
        )

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
