"""CLI principal para Mercado Livre Bulk Upload.

Apenas inicialização e configuração. Comandos estão em cli/commands/.
"""

import json
import logging

import typer
from rich.console import Console
from rich.theme import Theme

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


def setup_logging(verbose: bool = False):
    """Configure logging based on verbosity."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )


def print_json(data: dict):
    """Print data as JSON."""
    console.print(json.dumps(data, indent=2, default=str))


def print_result(result: dict, success_message: str = "", error_message: str = ""):
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
from .commands import cache_cmd, doctor, upload, validate  # noqa: E402

app.add_typer(upload.app, name="upload")
app.add_typer(validate.app, name="validate")
app.add_typer(cache_cmd.app, name="cache")
app.add_typer(doctor.app, name="doctor")


@app.callback()
def main(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable verbose logging"),
    output: str = typer.Option("text", "--output", "-o", help="Output format: text or json"),
):
    """Mercado Livre Bulk Upload Tool."""
    state["verbose"] = verbose
    state["output_format"] = output
    setup_logging(verbose)


if __name__ == "__main__":
    app()
