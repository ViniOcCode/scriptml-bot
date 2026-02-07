"""Comando upload - Publicar produtos no Mercado Livre."""

import logging
from pathlib import Path

import typer
import yaml
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

logger = logging.getLogger(__name__)


def load_config():  # type: ignore[no-untyped-def]
    """Load configuration from YAML file."""
    config_path = Path("config/generic_mappings.yaml")
    if config_path.exists():
        try:
            with open(config_path, encoding="utf-8") as f:
                return yaml.safe_load(f)
        except Exception as e:
            logger.warning(f"Failed to load config: {e}")
    return {}


console = Console()
err_console = Console(stderr=True)

app = typer.Typer(name="upload", help="Upload products from Excel")


@app.callback(invoke_without_command=True)
def upload(  # type: ignore[no-untyped-def]
    excel: Path = typer.Option(..., "--excel", "-e", help="Excel file path"),  # noqa: B008
    images: Path = typer.Option(..., "--images", "-i", help="Images directory"),  # noqa: B008
    category: str = typer.Option(..., "--category", "-c", help="Category name"),  # noqa: B008
    cache_dir: Path = typer.Option(Path("cache/categories"), "--cache-dir"),  # noqa: B008
    dry_run: bool = typer.Option(False, "--dry-run", "-n", help="Validate only"),  # noqa: B008
    detailed: bool = typer.Option(False, "--detailed", "-d"),  # noqa: B008
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
        cache_dir=str(cache_dir),
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

    # Execute use case
    results = use_case.execute(products, category)  # type: ignore[arg-type]

    # Report results
    console.print(f"\n[green]Published: {results['published']}[/green]")
    if results["failed"] > 0:
        console.print(f"[red]Failed: {results['failed']}[/red]")

    # Report clip results
    clips_uploaded = results.get("clips_uploaded", 0)
    clips_failed = results.get("clips_failed", 0)
    if clips_uploaded > 0:
        console.print(f"[cyan]Clips uploaded: {clips_uploaded}[/cyan]")
    if clips_failed > 0:
        console.print(f"[yellow]Clips failed: {clips_failed}[/yellow]")

    if results["errors"] and detailed:
        console.print("\n[yellow]Errors:[/yellow]")
        for error in results["errors"][:10]:
            console.print(f"  • {error}")

    if detailed and results.get("clips_details"):
        console.print("\n[cyan]Clip details:[/cyan]")
        for clip_info in results["clips_details"]:
            sku = clip_info.get("sku", "?")
            for r in clip_info.get("results", []):
                status_color = "green" if r.get("clip_uuid") else "red"
                status = r.get("status", "unknown")
                console.print(
                    f"  • [{status_color}]{sku}/{r.get('file', '?')}: " f"{status}[/{status_color}]"
                )
