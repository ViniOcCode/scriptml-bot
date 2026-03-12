"""Comando doctor - Verificar saúde do ambiente."""

import logging

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from mercadolivre_upload.auth import TokenManager
from mercadolivre_upload.auth.exceptions import AuthError

logger = logging.getLogger(__name__)
console = Console()

app = typer.Typer(name="doctor", help="Run health checks")


@app.callback(invoke_without_command=True)
def check() -> None:
    """Run health check on environment."""
    console.print(Panel.fit("Health Check", style="cyan"))

    table = Table(show_header=True, header_style="bold")
    table.add_column("Component")
    table.add_column("Status")

    # Check auth
    try:
        auth = TokenManager()
        token = auth.get_access_token(auto_refresh=False)
        auth_ok = token is not None
        table.add_row(
            "Authentication", "[green]✓ OK[/green]" if auth_ok else "[red]✗ Not authenticated[/red]"
        )
    except (AuthError, FileNotFoundError, ValueError):
        table.add_row("Authentication", "[red]✗ Error: Not authenticated[/red]")

    # Check config
    table.add_row("Config", "[yellow]⚠ Not checked[/yellow]")

    console.print(table)
