"""Comando cache - Gerenciar cache de atributos."""

import logging
from pathlib import Path

import typer
from rich.console import Console

from mercadolivre_upload.infrastructure.cache.attribute_cache import AttributeCache

logger = logging.getLogger(__name__)
console = Console()

app = typer.Typer(name="cache", help="Manage attribute cache")


@app.command()
def clear(  # type: ignore[no-untyped-def]
    cache_dir: Path = typer.Option(Path("cache/categories"), "--cache-dir"),  # noqa: B008
):
    """Clear attribute cache."""
    cache = AttributeCache(cache_dir=str(cache_dir))
    cache.clear_cache()
    console.print("[green]Cache cleared![/green]")


@app.command()
def status(  # type: ignore[no-untyped-def]
    cache_dir: Path = typer.Option(Path("cache/categories"), "--cache-dir"),  # noqa: B008
):
    """Show cache status."""
    # Create cache instance for status checks (no assignment needed)
    AttributeCache(cache_dir=str(cache_dir))
    # Implementation depends on AttributeCache methods
    console.print("[info]Cache status check[/info]")
