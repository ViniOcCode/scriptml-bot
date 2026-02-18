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


def load_config():  # type: ignore[no-untyped-def]
    """Load configuration from split YAML files with legacy fallback."""
    config = {}
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


@app.callback(invoke_without_command=True)
def upload(  # type: ignore[no-untyped-def]
    excel: Path = typer.Option(..., "--excel", "-e", help="Excel file path"),  # noqa: B008
    images: Path = typer.Option(..., "--images", "-i", help="Images directory"),  # noqa: B008
    category: str = typer.Option(..., "--category", "-c", help="Category name"),  # noqa: B008
    cache_dir: Path = typer.Option(Path("cache/categories"), "--cache-dir"),  # noqa: B008
    dry_run: bool = typer.Option(False, "--dry-run", "-n", help="Validate only"),  # noqa: B008
    detailed: bool = typer.Option(False, "--detailed", "-d"),  # noqa: B008
    batch_size: int = typer.Option(5, "--batch-size", min=1, help="Items per batch"),  # noqa: B008
    report_dir: Path = typer.Option(Path("cache/reports"), "--report-dir"),  # noqa: B008
):
    """Upload products from Excel to Mercado Livre."""
    console.print(Panel.fit("Mercado Livre Bulk Upload", style="cyan"))

    # Load configuration
    config = load_config()  # type: ignore[no-untyped-call]

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

    # Initialize infrastructure
    auth_manager = AuthManager()
    api_client = MLApiClient(auth_manager)
    cache = AttributeCache(cache_dir=str(cache_dir))

    # Initialize prediction cache
    from mercadolivre_upload.infrastructure.cache.prediction_cache import PredictionCache

    prediction_cache = PredictionCache(cache_dir=str(cache_dir / "predictions"))

    # Initialize adapters
    category_adapter = CategoryAdapter(api_client)
    image_uploader = ImageUploader(api_client, images)

    # Initialize clip uploader (discovers videos in same images directory)
    from mercadolivre_upload.adapters.clip_uploader import ClipUploader

    clip_uploader = ClipUploader(api_client, base_path=images)

    # Initialize domain services
    category_resolver = CategoryResolver(
        category_adapter, attribute_cache=cache, prediction_cache=prediction_cache
    )
    shipping_resolver = ShippingResolver(api_client)
    fiscal_service = FiscalService(api_client)  # type: ignore[arg-type]

    # Initialize use case
    use_case = PublishProductUseCase(
        category_resolver=category_resolver,
        publisher=api_client,
        image_uploader=image_uploader,
        shipping_resolver=shipping_resolver,
        fiscal_service=fiscal_service,
        clip_uploader=clip_uploader,
        config=config,
        dry_run=dry_run,
        attribute_cache=cache,
    )

    # Parse products
    parser = SpreadsheetParser()
    try:
        products = parser.parse(excel)
        console.print(f"Found {len(products)} products")
    except Exception as e:
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

    for start in range(0, total_products, batch_size):
        batch_index = (start // batch_size) + 1
        batch_products = products[start : start + batch_size]
        console.print(f"[cyan]Processing batch {batch_index}/{total_batches}...[/cyan]")

        results = use_case.execute(batch_products, category)  # type: ignore[arg-type]
        batch_published = int(results.get("published", 0))
        batch_failed = int(results.get("failed", 0))
        total_published += batch_published
        total_failed += batch_failed
        total_clips_uploaded += int(results.get("clips_uploaded", 0))
        total_clips_failed += int(results.get("clips_failed", 0))
        all_errors.extend(str(error) for error in results.get("errors", []))

        raw_item_results = results.get("item_results", [])
        item_results: list[dict[str, Any]] = []
        for index, row in enumerate(batch_products):
            sku, title = _extract_row_identity(row)
            item_results.append(
                {
                    "index": index,
                    "sku": sku,
                    "title": title,
                    "status": "failed",
                    "error": "Missing item result from use case",
                }
            )

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
                item_results[target_index] = {
                    "index": target_index,
                    "sku": item.get("sku") or item_results[target_index]["sku"],
                    "title": item.get("title") or item_results[target_index]["title"],
                    "status": "success" if row_status == "success" else "failed",
                    "error": item.get("error"),
                }

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
            all_item_results.append(normalized)

            if row_status != "success":
                failed_row = dict(row)
                failed_row["_batch"] = batch_index
                failed_row["_error"] = item_result.get("error")
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
