"""CLI principal para Mercado Livre Bulk Upload.

Apenas inicialização e configuração. Comandos estão em cli/commands/.
"""

import json
from importlib import import_module
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.theme import Theme

from mercadolivre_upload.infrastructure.logging import setup_logging as setup_app_logging

# Configure custom theme
console_theme = Theme(
    {
        "info": "cyan",
        "success": "green",
        "warning": "yellow",
        "error": "red bold",
        "highlight": "magenta",
    }
)

console = Console(theme=console_theme)
err_console = Console(stderr=True, theme=console_theme)

# Typer app
app = typer.Typer(
    name="ml-upload",
    help="Mercado Livre Bulk Upload Tool",
    rich_markup_mode="rich",
    add_completion=False,
)

# Global state
state = {"verbose": False, "output_format": "text"}


def _get_auth_manager_cls() -> Any:
    return import_module("mercadolivre_upload.cli").AuthManager


def setup_logging(verbose: bool = False) -> None:
    """Configure logging based on verbosity."""
    setup_app_logging(level="DEBUG" if verbose else "INFO")


def print_json(data: dict[str, Any]) -> None:
    """Print data as JSON."""
    console.print(json.dumps(data, indent=2, default=str))


def print_result(
    result: dict[str, Any], success_message: str = "", error_message: str = ""
) -> None:
    """Print result based on output format."""
    if state["output_format"] == "json":
        print_json(result)
    else:
        if result.get("success"):
            if success_message:
                console.print(f"✓ {success_message}", style="success")
        else:
            if error_message:
                err_console.print(f"✗ {error_message}", style="error")
            if result.get("errors"):
                for error in result["errors"]:
                    err_console.print(f"  • {error}", style="error")


# Importar comandos


@app.command()
def upload(
    excel: Path | None = typer.Argument(None, help="Path to Excel file"),  # noqa: B008
    excel_option: Path | None = typer.Option(None, "--excel", "-e"),  # noqa: B008
    images: Path | None = typer.Option(None, "--images", "-i"),  # noqa: B008
    category: str | None = typer.Option(None, "--category", "-c"),  # noqa: B008
    verbose: bool = typer.Option(False, "--verbose", "-v"),  # noqa: B008
    dry_run: bool = typer.Option(False, "--dry-run", "-n"),  # noqa: B008
    detailed: bool = typer.Option(False, "--detailed", "-d"),  # noqa: B008
    batch_size: int = typer.Option(5, "--batch-size", min=1),  # noqa: B008
    report_dir: Path = typer.Option(Path("cache/reports"), "--report-dir"),  # noqa: B008
) -> Any:
    """Upload products using the new CLI implementation only."""
    setup_logging(verbose)
    selected_excel = excel_option or excel
    if selected_excel is None or not selected_excel.exists():
        err_console.print("Arquivo não encontrado")
        raise typer.Exit(1)
    if images is None or category is None:
        err_console.print("Parametros obrigatorios: --images e --category")
        raise typer.Exit(1)

    upload_cmd = import_module("mercadolivre_upload.cli.commands.upload")
    return upload_cmd.upload(
        excel=selected_excel,
        images=images,
        category=category,
        cache_dir=Path("cache/categories"),
        dry_run=dry_run,
        detailed=detailed,
        batch_size=batch_size,
        report_dir=report_dir,
    )


@app.command()
def validate(
    excel: Path | None = typer.Argument(None, help="Path to Excel file"),  # noqa: B008
    excel_option: Path | None = typer.Option(None, "--excel", "-e"),  # noqa: B008
    images: Path | None = typer.Option(None, "--images", "-i"),  # noqa: B008
    category: str | None = typer.Option(None, "--category", "-c"),  # noqa: B008
    detailed: bool = typer.Option(False, "--detailed", "-d"),  # noqa: B008
    batch_size: int = typer.Option(5, "--batch-size", min=1),  # noqa: B008
    report_dir: Path = typer.Option(Path("cache/reports"), "--report-dir"),  # noqa: B008
) -> Any:
    """Validate products using the new CLI implementation only."""
    selected_excel = excel_option or excel
    if selected_excel is None or not selected_excel.exists():
        err_console.print("Arquivo não encontrado")
        raise typer.Exit(1)
    if images is None or category is None:
        err_console.print("Parametros obrigatorios: --images e --category")
        raise typer.Exit(1)

    validate_cmd = import_module("mercadolivre_upload.cli.commands.validate")
    return validate_cmd.validate(
        excel=selected_excel,
        images=images,
        category=category,
        cache_dir=Path("cache/categories"),
        detailed=detailed,
        batch_size=batch_size,
        report_dir=report_dir,
    )


@app.command()
def auth(
    token: str | None = typer.Option(None, "--token"),  # noqa: B008
    refresh: bool = typer.Option(False, "--refresh"),  # noqa: B008
) -> None:
    """Manage authentication tokens."""
    manager = _get_auth_manager_cls()()
    if token:
        manager.set_token(token)
        console.print("Token configurado")
        return
    if refresh:
        try:
            manager.refresh_token()
            console.print("Token atualizado")
        except Exception as err:
            err_console.print("Erro ao atualizar token")
            raise typer.Exit(1) from err
        return
    status = manager.get_auth_status()
    if isinstance(status, dict):
        authenticated = bool(status.get("authenticated"))
        user_id = status.get("user_id")
    else:
        authenticated = bool(getattr(status, "authenticated", False))
        user_id = getattr(status, "user_id", None)
    if authenticated:
        console.print(f"Autenticado: {user_id}")
    else:
        console.print("Não autenticado")


def main() -> None:
    """Compatibility entry point for tests."""
    import_module("mercadolivre_upload.cli").app()


from .commands import (  # noqa: E402
    cache_cmd,
    doctor,
)

# Register command groups
app.add_typer(cache_cmd.app, name="cache")
app.add_typer(doctor.app, name="doctor")


@app.callback()
def main_callback(
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Enable verbose logging"
    ),  # noqa: B008
    output: str = typer.Option(
        "text", "--output", "-o", help="Output format: text or json"
    ),  # noqa: B008
) -> None:
    """Mercado Livre Bulk Upload Tool."""
    state["verbose"] = verbose
    state["output_format"] = output
    setup_logging(verbose)


if __name__ == "__main__":
    app()
