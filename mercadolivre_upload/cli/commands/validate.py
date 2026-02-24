"""Comando validate - Validar produtos antes de publicar."""

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.panel import Panel

from mercadolivre_upload.adapters.spreadsheet.parser import SpreadsheetParser
from mercadolivre_upload.cli.commands.common import (
    coerce_path_option,
    merge_category_resolution_fields,
    parse_products_or_exit,
)
from mercadolivre_upload.cli.commands.upload import (
    _extract_row_category,
    _extract_row_identity,
    build_publish_use_case,
    load_config,
)
from mercadolivre_upload.cli.commands.upload_reporting import (
    _empty_category_resolution_summary,
    _ensure_observability_evidence,
    _extract_cause_codes,
    _extract_decision_classified_codes,
    _increment_code_counter,
    _is_error_classification,
    _is_warning_classification,
    _merge_category_resolution_summary,
    _top_code_entries,
    _top_codes_by_status,
)

logger = logging.getLogger(__name__)
console = Console()
err_console = Console(stderr=True)

app = typer.Typer(name="validate", help="Validate products without publishing")


@app.callback(invoke_without_command=True)
def validate(
    excel: Path = typer.Option(..., "--excel", "-e", help="Excel file path"),  # noqa: B008
    images: Path = typer.Option(..., "--images", "-i", help="Images directory"),  # noqa: B008
    category: str = typer.Option(..., "--category", "-c", help="Category name"),  # noqa: B008
    cache_dir: Path = typer.Option(Path("cache/categories"), "--cache-dir"),  # noqa: B008
    detailed: bool = typer.Option(False, "--detailed", "-d"),  # noqa: B008
    batch_size: int = typer.Option(5, "--batch-size", min=1, help="Items per batch"),  # noqa: B008
    report_dir: Path = typer.Option(Path("cache/reports"), "--report-dir"),  # noqa: B008
) -> None:
    """Validate products against Mercado Livre APIs without publishing."""
    console.print(Panel.fit("Pre-Validation", style="yellow"))

    cache_dir = coerce_path_option(cache_dir, default=Path("cache/categories"))
    report_dir = coerce_path_option(report_dir, default=Path("cache/reports"))

    if batch_size < 1:
        err_console.print("[red]batch-size must be greater than zero[/red]")
        raise typer.Exit(1)

    config = load_config()
    use_case = build_publish_use_case(
        images=images,
        cache_dir=cache_dir,
        config=config,
        validation_only=True,
    )
    parser = SpreadsheetParser()

    products = parse_products_or_exit(parser=parser, excel=excel, err_console=err_console)
    console.print(f"Found {len(products)} products")

    total_items = len(products)
    total_batches = (total_items + batch_size - 1) // batch_size if total_items else 0
    console.print(f"Batch size: {batch_size} ({total_batches} batches)")

    all_item_results: list[dict[str, Any]] = []
    all_errors: list[str] = []
    cause_code_counts: dict[str, int] = {}
    warning_code_counts: dict[str, dict[str, int]] = {"valid": {}, "failed": {}}
    error_code_counts: dict[str, dict[str, int]] = {"valid": {}, "failed": {}}
    category_resolution_summary = _empty_category_resolution_summary()
    total_validated = 0
    total_failed = 0

    for start in range(0, total_items, batch_size):
        batch_number = (start // batch_size) + 1
        batch_products = products[start : start + batch_size]
        console.print(f"[cyan]Validating batch {batch_number}/{total_batches}...[/cyan]")

        item_results: list[dict[str, Any]] = []
        for index, row in enumerate(batch_products):
            sku, title = _extract_row_identity(row)
            input_category = _extract_row_category(row) or category
            base_item: dict[str, Any] = {
                "index": index,
                "sku": sku,
                "title": title,
                "category_used": input_category,
                "status": "failed",
                "error": "Missing item result from validation use case",
                "cause_codes": [],
            }
            merge_category_resolution_fields(base_item, {}, input_category)
            item_results.append(base_item)

        grouped_products: dict[str, list[tuple[int, dict[str, Any]]]] = {}
        for index, row in enumerate(batch_products):
            row_category = _extract_row_category(row) or category
            grouped_products.setdefault(row_category, []).append((index, row))

        batch_validated = 0
        batch_failed = 0
        batch_errors: list[str] = []

        for group_category, indexed_rows in grouped_products.items():
            rows_for_category = [row for _, row in indexed_rows]
            results = use_case.execute(rows_for_category, group_category)  # type: ignore[arg-type]
            _merge_category_resolution_summary(
                category_resolution_summary,
                results.get("category_resolution"),
            )
            raw_group_flow_routing = results.get("flow_routing")
            group_flow_routing = (
                dict(raw_group_flow_routing) if isinstance(raw_group_flow_routing, dict) else None
            )

            batch_validated += int(results.get("validated", results.get("published", 0)))
            batch_failed += int(results.get("failed", 0))
            batch_errors.extend(str(error) for error in results.get("errors", []))

            grouped_results: list[dict[str, Any]] = []
            for group_index, (_, row) in enumerate(indexed_rows):
                sku, title = _extract_row_identity(row)
                row_input_category = _extract_row_category(row) or category
                base_item = {
                    "index": group_index,
                    "sku": sku,
                    "title": title,
                    "category_used": group_category,
                    "status": "failed",
                    "error": "Missing item result from validation use case",
                    "cause_codes": [],
                }
                merge_category_resolution_fields(base_item, {}, row_input_category)
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
                    raw_codes = item.get("cause_codes")
                    cause_codes: list[str] = []
                    if isinstance(raw_codes, list):
                        cause_codes = [str(code) for code in raw_codes if str(code).strip()]
                    error_text = item.get("error")
                    if not cause_codes:
                        cause_codes = _extract_cause_codes(str(error_text) if error_text else None)

                    grouped_results[target_index] = {
                        "index": target_index,
                        "sku": item.get("sku") or grouped_results[target_index]["sku"],
                        "title": item.get("title") or grouped_results[target_index]["title"],
                        "category_used": group_category,
                        "status": "valid" if row_status == "success" else "failed",
                        "error": error_text,
                        "cause_codes": cause_codes,
                    }
                    cause_taxonomy = item.get("cause_taxonomy")
                    if isinstance(cause_taxonomy, list):
                        normalized_taxonomy = [
                            dict(cause) for cause in cause_taxonomy if isinstance(cause, dict)
                        ]
                        if normalized_taxonomy:
                            grouped_results[target_index]["cause_taxonomy"] = normalized_taxonomy
                    validation_decision = item.get("validation_decision")
                    if isinstance(validation_decision, dict):
                        grouped_results[target_index]["validation_decision"] = dict(
                            validation_decision
                        )
                    merge_category_resolution_fields(
                        grouped_results[target_index],
                        item,
                        grouped_results[target_index].get("category_input"),
                    )
                    category_resolution_decision = item.get("category_resolution_decision")
                    if isinstance(category_resolution_decision, dict):
                        grouped_results[target_index]["category_resolution_decision"] = dict(
                            category_resolution_decision
                        )
                    policy_hash = item.get("policy_hash")
                    if isinstance(policy_hash, str) and policy_hash:
                        grouped_results[target_index]["policy_hash"] = policy_hash
                    policy_summary = item.get("policy_summary")
                    if isinstance(policy_summary, dict):
                        grouped_results[target_index]["policy_summary"] = policy_summary
                    schema_contract_hash = item.get("schema_contract_hash")
                    if isinstance(schema_contract_hash, str) and schema_contract_hash:
                        grouped_results[target_index]["schema_contract_hash"] = schema_contract_hash
                    schema_contract_summary = item.get("schema_contract_summary")
                    if isinstance(schema_contract_summary, dict):
                        grouped_results[target_index][
                            "schema_contract_summary"
                        ] = schema_contract_summary
                    identifier_gate = item.get("identifier_gate")
                    if isinstance(identifier_gate, dict):
                        grouped_results[target_index]["identifier_gate"] = identifier_gate
                    flow_routing = item.get("flow_routing")
                    if isinstance(flow_routing, dict):
                        grouped_results[target_index]["flow_routing"] = flow_routing
                    elif group_flow_routing is not None:
                        grouped_results[target_index]["flow_routing"] = dict(group_flow_routing)
                    image_diagnostics = item.get("image_diagnostics")
                    if isinstance(image_diagnostics, dict):
                        grouped_results[target_index]["image_diagnostics"] = image_diagnostics
                    shipping_policy = item.get("shipping_policy")
                    if isinstance(shipping_policy, dict):
                        grouped_results[target_index]["shipping_policy"] = shipping_policy
                    rollout_flags = item.get("rollout_flags")
                    if isinstance(rollout_flags, dict):
                        grouped_results[target_index]["rollout_flags"] = rollout_flags
                    grouped_results[target_index] = _ensure_observability_evidence(
                        grouped_results[target_index],
                        row_status=grouped_results[target_index]["status"],
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

        total_validated += batch_validated
        total_failed += batch_failed
        all_errors.extend(batch_errors)

        for index, item_result in enumerate(item_results):
            row_status = str(item_result.get("status", "failed")).lower()
            normalized_item = _ensure_observability_evidence(item_result, row_status=row_status)
            normalized_item["batch"] = batch_number
            normalized_item["index"] = start + index
            all_item_results.append(normalized_item)
            status_bucket = "valid" if row_status == "valid" else "failed"
            raw_codes = normalized_item.get("cause_codes", [])
            cause_codes = (
                [str(code).strip().lower() for code in raw_codes if str(code).strip()]
                if isinstance(raw_codes, list)
                else []
            )

            warning_codes_for_row: set[str] = set()
            error_codes_for_row: set[str] = set()
            all_codes_for_row: set[str] = set(cause_codes)
            taxonomy = normalized_item.get("cause_taxonomy")
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
                decision_warning_codes, decision_error_codes = _extract_decision_classified_codes(
                    normalized_item.get("validation_decision")
                )
                warning_codes_for_row.update(decision_warning_codes)
                error_codes_for_row.update(decision_error_codes)
                all_codes_for_row.update(decision_warning_codes)
                all_codes_for_row.update(decision_error_codes)

            if not warning_codes_for_row and not error_codes_for_row:
                if status_bucket == "valid":
                    warning_codes_for_row.update(cause_codes)
                else:
                    error_codes_for_row.update(cause_codes)

            for code in all_codes_for_row:
                _increment_code_counter(cause_code_counts, code)
            for code in warning_codes_for_row:
                _increment_code_counter(warning_code_counts[status_bucket], code)
            for code in error_codes_for_row:
                _increment_code_counter(error_code_counts[status_bucket], code)

        console.print(
            f"[green]Batch {batch_number}: {batch_validated} valid[/green], "
            f"[red]{batch_failed} failed[/red]"
        )

    report_dir.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    summary_path = report_dir / f"validation-summary-{run_id}.json"
    rollout_flags_snapshot: dict[str, Any] = {}
    for item in all_item_results:
        raw_rollout_flags = item.get("rollout_flags")
        if isinstance(raw_rollout_flags, dict) and raw_rollout_flags:
            rollout_flags_snapshot = dict(raw_rollout_flags)
            break
    summary_report = {
        "run_id": run_id,
        "source_file": str(excel),
        "default_category": category,
        "batch_size": batch_size,
        "total_items": total_items,
        "total_batches": total_batches,
        "validated": total_validated,
        "failed": total_failed,
        "cause_code_counts": cause_code_counts,
        "warning_code_counts": warning_code_counts,
        "error_code_counts": error_code_counts,
        "top_cause_codes": _top_code_entries(cause_code_counts),
        "top_warning_codes_by_status": _top_codes_by_status(warning_code_counts),
        "top_error_codes_by_status": _top_codes_by_status(error_code_counts),
        "category_resolution": category_resolution_summary,
        "rollout_flags": rollout_flags_snapshot,
        "items": all_item_results,
    }
    summary_path.write_text(
        json.dumps(summary_report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    console.print(f"[green]Validated: {total_validated}[/green]")
    if total_failed > 0:
        console.print(f"[red]Failed: {total_failed}[/red]")
    console.print(f"[cyan]Summary report: {summary_path}[/cyan]")

    if detailed and all_errors:
        console.print("\n[yellow]Errors:[/yellow]")
        for error in all_errors[:20]:
            console.print(f"  • {error}")

    if total_failed > 0:
        raise typer.Exit(1)
