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
from mercadolivre_upload.cli.commands.upload import (
    _build_row_category_metadata,
    _extract_row_identity,
    _prime_category_resolution_context,
    build_publish_use_case,
    load_config,
)
from mercadolivre_upload.cli.commands.upload_reporting import (
    _empty_category_resolution_summary,
    _ensure_observability_evidence,
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
    _prime_category_resolution_context(use_case, products, category)

    total_items = len(products)
    total_batches = (total_items + batch_size - 1) // batch_size if total_items else 0
    console.print(f"Batch size: {batch_size} ({total_batches} batches)")

    all_item_results: list[dict[str, Any]] = []
    all_errors: list[str] = []
    cause_code_counts: dict[str, int] = {}
    warning_code_counts: dict[str, dict[str, int]] = {"valid": {}, "failed": {}}
    error_code_counts: dict[str, dict[str, int]] = {"valid": {}, "failed": {}}
    category_resolution_summary = _empty_category_resolution_summary()
    row_category_signals = {"detected": 0, "mismatched": 0}
    total_validated = 0
    total_failed = 0

    for start in range(0, total_items, batch_size):
        batch_number = (start // batch_size) + 1
        batch_products = products[start : start + batch_size]
        console.print(f"[cyan]Validating batch {batch_number}/{total_batches}...[/cyan]")

        item_results: list[dict[str, Any]] = []
        for index, row in enumerate(batch_products):
            sku, title = _extract_row_identity(row)
            row_category_metadata = _build_row_category_metadata(row, category)
            base_item: dict[str, Any] = {
                "index": index,
                "sku": sku,
                "title": title,
                "category_used": category,
                "status": "failed",
                "error": "Missing item result from validation use case",
                "cause_codes": [],
                "row_category_detected": row_category_metadata["row_category_detected"],
                "row_category_mismatch": row_category_metadata["row_category_mismatch"],
            }
            merge_category_resolution_fields(base_item, {}, category)
            item_results.append(base_item)
            if row_category_metadata["row_category_detected"]:
                row_category_signals["detected"] += 1
            if row_category_metadata["row_category_mismatch"]:
                row_category_signals["mismatched"] += 1

        batch_validated = 0
        batch_failed = 0
        batch_errors: list[str] = []
        results = use_case.execute(batch_products, category)  # type: ignore[arg-type]
        _merge_category_resolution_summary(
            category_resolution_summary,
            results.get("category_resolution"),
        )
        group_flow_routing = _extract_group_flow_routing(results)

        batch_validated += int(results.get("validated", results.get("published", 0)))
        batch_failed += int(results.get("failed", 0))
        batch_errors.extend(str(error) for error in results.get("errors", []))

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
                cause_codes = _resolve_cause_codes(item.get("cause_codes"), error_text)

                item_results[target_index] = {
                    "index": target_index,
                    "sku": item.get("sku") or item_results[target_index]["sku"],
                    "title": item.get("title") or item_results[target_index]["title"],
                    "category_used": category,
                    "status": "valid" if row_status == "success" else "failed",
                    "error": error_text,
                    "cause_codes": cause_codes,
                    "row_category_detected": item_results[target_index].get(
                        "row_category_detected"
                    ),
                    "row_category_mismatch": item_results[target_index].get(
                        "row_category_mismatch"
                    ),
                }
                _merge_item_observability_fields(
                    item_results[target_index],
                    item,
                    category_input=item_results[target_index].get("category_input"),
                    default_flow_routing=group_flow_routing,
                )
                item_results[target_index] = _ensure_observability_evidence(
                    item_results[target_index],
                    row_status=item_results[target_index]["status"],
                    default_flow_routing=group_flow_routing,
                )

        for index, mapped_item in enumerate(item_results):
            mapped = _ensure_observability_evidence(
                dict(mapped_item),
                row_status=str(mapped_item.get("status", "failed")),
                default_flow_routing=group_flow_routing,
            )
            mapped["index"] = index
            item_results[index] = mapped

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
            _update_cause_code_counters(
                normalized_item,
                status_bucket=status_bucket,
                cause_code_counts=cause_code_counts,
                warning_code_counts=warning_code_counts,
                error_code_counts=error_code_counts,
            )

        console.print(
            f"[green]Batch {batch_number}: {batch_validated} valid[/green], "
            f"[red]{batch_failed} failed[/red]"
        )

    report_dir.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    summary_path = report_dir / f"validation-summary-{run_id}.json"
    rollout_flags_snapshot = _extract_rollout_flags_snapshot(all_item_results)
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
        "row_category_signals": row_category_signals,
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
