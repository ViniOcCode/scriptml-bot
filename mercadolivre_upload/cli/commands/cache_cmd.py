"""Comando cache - Gerenciar cache de atributos."""

import logging
from pathlib import Path

import typer
from rich.console import Console

from mercadolivre_upload.infrastructure.cache.attribute_cache import AttributeCache
from mercadolivre_upload.cli.commands.common import resolve_default_category_cache_dir

logger = logging.getLogger(__name__)
console = Console()

app = typer.Typer(name="cache", help="Manage attribute cache")


@app.command()
def clear(
    workspace: Path | None = typer.Option(None, "--workspace"),  # noqa: B008
    cache_root: Path | None = typer.Option(None, "--cache-root"),  # noqa: B008
    cache_dir: Path | None = typer.Option(None, "--cache-dir"),  # noqa: B008
) -> None:
    """Clear attribute cache."""
    resolved_cache_dir = cache_dir or resolve_default_category_cache_dir(
        workspace=workspace, cache_root=cache_root
    )
    cache = AttributeCache(cache_dir=str(resolved_cache_dir))
    cache.clear_cache()
    console.print("[green]Cache cleared![/green]")


@app.command()
def status(
    workspace: Path | None = typer.Option(None, "--workspace"),  # noqa: B008
    cache_root: Path | None = typer.Option(None, "--cache-root"),  # noqa: B008
    cache_dir: Path | None = typer.Option(None, "--cache-dir"),  # noqa: B008
) -> None:
    """Show cache status."""
    # Create cache instance for status checks (no assignment needed)
    resolved_cache_dir = cache_dir or resolve_default_category_cache_dir(
        workspace=workspace, cache_root=cache_root
    )
    AttributeCache(cache_dir=str(resolved_cache_dir))
    # Implementation depends on AttributeCache methods
    console.print("[info]Cache status check[/info]")
