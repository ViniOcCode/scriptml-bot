"""Comando validate - Validar produtos antes de publicar."""

import json
import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.panel import Panel

from mercadolivre_upload.adapters.spreadsheet.parser import SpreadsheetParser
from mercadolivre_upload.cli.commands.upload import (
    _extract_row_category,
    _extract_row_identity,
    build_publish_use_case,
    load_config,
)

logger = logging.getLogger(__name__)
console = Console()
err_console = Console(stderr=True)

app = typer.Typer(name="validate", help="Validate products without publishing")

_CAUSE_CODE_PATTERN = re.compile(r"\b[a-z]+(?:[._-][a-z0-9]+)+\b")


def _extract_cause_codes(error: str | None) -> list[str]:
    if not error:
        return []
    return list(dict.fromkeys(_CAUSE_CODE_PATTERN.findall(error.lower())))


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

    if isinstance(cache_dir, typer.models.OptionInfo):
        cache_dir = Path("cache/categories")
    elif not isinstance(cache_dir, Path):
        cache_dir = Path(cache_dir)

    if isinstance(report_dir, typer.models.OptionInfo):
        report_dir = Path("cache/reports")
    elif not isinstance(report_dir, Path):
        report_dir = Path(report_dir)

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

    try:
        products = parser.parse(excel)
        console.print(f"Found {len(products)} products")
    except (FileNotFoundError, ValueError) as e:
        err_console.print(f"[red]Error parsing Excel: {e}[/red]")
        raise typer.Exit(1) from e

    total_items = len(products)
    total_batches = (total_items + batch_size - 1) // batch_size if total_items else 0
    console.print(f"Batch size: {batch_size} ({total_batches} batches)")

    all_item_results: list[dict[str, Any]] = []
    all_errors: list[str] = []
    cause_code_counts: dict[str, int] = {}
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
            item_results.append(
                {
                    "index": index,
                    "sku": sku,
                    "title": title,
                    "category_input": input_category,
                    "category_used": input_category,
                    "status": "failed",
                    "error": "Missing item result from validation use case",
                    "cause_codes": [],
                }
            )

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

            batch_validated += int(results.get("validated", results.get("published", 0)))
            batch_failed += int(results.get("failed", 0))
            batch_errors.extend(str(error) for error in results.get("errors", []))

            grouped_results: list[dict[str, Any]] = []
            for group_index, (_, row) in enumerate(indexed_rows):
                sku, title = _extract_row_identity(row)
                grouped_results.append(
                    {
                        "index": group_index,
                        "sku": sku,
                        "title": title,
                        "category_input": _extract_row_category(row) or category,
                        "category_used": group_category,
                        "status": "failed",
                        "error": "Missing item result from validation use case",
                        "cause_codes": [],
                    }
                )

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
                        "category_input": grouped_results[target_index]["category_input"],
                        "category_used": group_category,
                        "status": "valid" if row_status == "success" else "failed",
                        "error": error_text,
                        "cause_codes": cause_codes,
                    }

            for group_index, (batch_index_pos, _) in enumerate(indexed_rows):
                mapped = dict(grouped_results[group_index])
                mapped["index"] = batch_index_pos
                item_results[batch_index_pos] = mapped

        total_validated += batch_validated
        total_failed += batch_failed
        all_errors.extend(batch_errors)

        for index, item_result in enumerate(item_results):
            item_result["batch"] = batch_number
            item_result["index"] = start + index
            all_item_results.append(item_result)
            for code in item_result.get("cause_codes", []):
                cause_code_counts[code] = cause_code_counts.get(code, 0) + 1

        console.print(
            f"[green]Batch {batch_number}: {batch_validated} valid[/green], "
            f"[red]{batch_failed} failed[/red]"
        )

    report_dir.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    summary_path = report_dir / f"validation-summary-{run_id}.json"
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
