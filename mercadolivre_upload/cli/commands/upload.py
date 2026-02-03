"""Comando upload - Publicar produtos no Mercado Livre."""

import logging
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
)

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
import yaml

logger = logging.getLogger(__name__)


def load_config():
    """Load configuration from YAML file."""
    config_path = Path("config/generic_mappings.yaml")
    if config_path.exists():
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f)
        except Exception as e:
            logger.warning(f"Failed to load config: {e}")
    return {}
console = Console()
err_console = Console(stderr=True)

app = typer.Typer(name="upload", help="Upload products from Excel")


@app.callback(invoke_without_command=True)
def upload(
    excel: Path = typer.Option(..., "--excel", "-e", help="Excel file path"),
    images: Path = typer.Option(..., "--images", "-i", help="Images directory"),
    category: str = typer.Option(..., "--category", "-c", help="Category name"),
    cache_dir: Path = typer.Option(Path("cache/categories"), "--cache-dir"),
    dry_run: bool = typer.Option(False, "--dry-run", "-n", help="Validate only"),
    detailed: bool = typer.Option(False, "--detailed", "-d"),
):
    """Upload products from Excel to Mercado Livre."""
    console.print(Panel.fit("Mercado Livre Bulk Upload", style="cyan"))
    
    # Load configuration
    config = load_config()
    
    # Initialize infrastructure
    auth_manager = AuthManager()
    api_client = MLApiClient(auth_manager)
    cache = AttributeCache(cache_dir=str(cache_dir))
    
    # Initialize adapters
    category_adapter = CategoryAdapter(api_client)
    image_uploader = ImageUploader(api_client, images)
    
    # Initialize domain services
    category_resolver = CategoryResolver(category_adapter, attribute_cache=cache)
    shipping_resolver = ShippingResolver(api_client)
    fiscal_service = FiscalService(api_client)
    
    # Initialize use case
    use_case = PublishProductUseCase(
        category_resolver=category_resolver,
        publisher=api_client,
        image_uploader=image_uploader,
        shipping_resolver=shipping_resolver,
        fiscal_service=fiscal_service,
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
        raise typer.Exit(1)
    
    if dry_run:
        console.print("[yellow]Dry run mode - validating only[/yellow]")
        return
    
    # Execute use case
    results = use_case.execute(products, category)
    
    # Report results
    console.print(f"\n[green]Published: {results['published']}[/green]")
    if results['failed'] > 0:
        console.print(f"[red]Failed: {results['failed']}[/red]")
    
    if results['errors'] and detailed:
        console.print("\n[yellow]Errors:[/yellow]")
        for error in results['errors'][:10]:
            console.print(f"  • {error}")
