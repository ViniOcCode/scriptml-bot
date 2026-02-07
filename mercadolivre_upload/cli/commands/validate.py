"""Comando validate - Validar produtos antes de publicar."""

import logging
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel

from mercadolivre_upload.adapters.spreadsheet.parser import SpreadsheetParser
from mercadolivre_upload.api.category_adapter import CategoryAdapter
from mercadolivre_upload.api.client import MLApiClient
from mercadolivre_upload.infrastructure.cache.attribute_cache import AttributeCache

logger = logging.getLogger(__name__)
console = Console()
err_console = Console(stderr=True)

app = typer.Typer(name="validate", help="Validate products without publishing")


@app.callback(invoke_without_command=True)
def validate(  # type: ignore[no-untyped-def]
    excel: Path = typer.Option(..., "--excel", "-e", help="Excel file path"),  # noqa: B008
    images: Path = typer.Option(..., "--images", "-i", help="Images directory"),  # noqa: B008
    category: str = typer.Option(..., "--category", "-c", help="Category name"),  # noqa: B008
    cache_dir: Path = typer.Option(Path("cache/categories"), "--cache-dir"),  # noqa: B008
    detailed: bool = typer.Option(False, "--detailed", "-d"),  # noqa: B008
):
    """Validate products without publishing (dry-run)."""
    console.print(Panel.fit("Pre-Validation", style="yellow"))

    # Initialize components
    # Defensive: if cache_dir is OptionInfo, use default
    if isinstance(cache_dir, typer.models.OptionInfo):
        cache_dir = Path("cache/categories")
    elif not isinstance(cache_dir, Path):
        cache_dir = Path(cache_dir)
    AttributeCache(cache_dir=str(cache_dir))
    api_client = MLApiClient()
    CategoryAdapter(api_client)

    parser = SpreadsheetParser()

    # Parse products
    try:
        products = parser.parse(excel)
        console.print(f"Found {len(products)} products")
    except Exception as e:
        err_console.print(f"[red]Error parsing Excel: {e}[/red]")
        raise typer.Exit(1) from e

    # Validate products
    errors = []
    for product in products:
        # Basic validation
        if not product.title:  # type: ignore[attr-defined]
            errors.append(f"{product.sku}: Missing title")  # type: ignore[attr-defined]
        if not product.price or product.price <= 0:  # type: ignore[attr-defined]
            errors.append(f"{product.sku}: Invalid price")  # type: ignore[attr-defined]
        if not product.sku:  # type: ignore[attr-defined]
            errors.append(f"Product {product.title[:30]}: Missing SKU")  # type: ignore[attr-defined]

    if errors:
        console.print(f"[red]✗ Validation failed: {len(errors)} errors[/red]")
        if detailed:
            for error in errors[:10]:
                console.print(f"  • {error}")
    else:
        console.print(f"[green]✓ All {len(products)} products valid![/green]")
