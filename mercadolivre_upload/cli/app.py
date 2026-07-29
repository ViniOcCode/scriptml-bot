"""CLI principal para Mercado Livre Bulk Upload.

Apenas inicialização e configuração. Comandos estão em cli/commands/.
"""

import json
from importlib import import_module
from pathlib import Path

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


def setup_logging(verbose: bool = False) -> None:
    """Configure logging based on verbosity."""
    setup_app_logging(level="DEBUG" if verbose else "INFO")


# Importar comandos


@app.command()
def publish_payload(
    path: Path = typer.Argument(..., help="Path to payload.json or 70_payload.json"),  # noqa: B008
    dry_run: bool = typer.Option(
        True, "--dry-run", help="Validate without publishing."
    ),  # noqa: B008
    execute: bool = typer.Option(
        False,
        "--execute",
        help="Permit a real publication when paired with --confirm PUBLICAR.",
    ),  # noqa: B008
    confirmation: str | None = typer.Option(
        None,
        "--confirm",
        "--confirmation",
        help="Literal confirmation required for real publication: PUBLICAR.",
    ),  # noqa: B008
    publish_inactive: bool = typer.Option(  # noqa: B008
        True,
        "--publish-inactive/--no-publish-inactive",
        help="Publish items in paused (inactive) state. Items can be activated later.",
    ),
    workspace: Path = typer.Option(..., "--workspace"),  # noqa: B008
    seller_config: Path = typer.Option(  # noqa: B008
        Path(".canonical-publisher-config"), "--config"
    ),
) -> None:
    """Publish a ready-made builder payload JSON file."""
    setup_logging()
    runtime = import_module("mercadolivre_upload.cli.commands.publish_runtime")
    try:
        workspace_root = runtime.resolve_workspace_root(
            workspace=workspace, seller_config=seller_config
        )
    except ValueError as exc:
        err_console.print(f"[error]{exc}[/error]")
        raise typer.Exit(2) from exc
    report_dir = runtime.build_attempt_report_dir(workspace_root=workspace_root)
    api = import_module("mercadolivre_upload.application.publish_payload")
    result = api.publish_payload_file(
        path,
        report_dir=report_dir,
        dry_run=not execute,
        execute=execute,
        confirmation=confirmation,
        publish_inactive=publish_inactive,
        seller_config_path=seller_config,
        workspace_root=workspace_root,
    )
    if result.get("validation_status") == "validation_passed_with_warnings":
        console.print("[yellow]Validation passed with warnings; continuing publication.[/yellow]")
    console.print(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("status") in {"failed", "unknown", "published_but_not_grouped"}:
        raise typer.Exit(1)


@app.command()
def publish_manifest(
    manifest_path: Path = typer.Argument(..., help="Path to run_manifest.json"),  # noqa: B008
    dry_run: bool = typer.Option(
        True, "--dry-run", help="Validate without publishing."
    ),  # noqa: B008
    execute: bool = typer.Option(
        False,
        "--execute",
        help="Permit real publication when paired with --confirm PUBLICAR.",
    ),  # noqa: B008
    confirmation: str | None = typer.Option(
        None,
        "--confirm",
        "--confirmation",
        help="Literal confirmation required for real publication: PUBLICAR.",
    ),  # noqa: B008
    publish_inactive: bool = typer.Option(  # noqa: B008
        True,
        "--publish-inactive/--no-publish-inactive",
        help="Publish items in paused (inactive) state. Items can be activated later.",
    ),
    workspace: Path = typer.Option(..., "--workspace"),  # noqa: B008
    seller_config: Path = typer.Option(  # noqa: B008
        Path(".canonical-publisher-config"), "--config"
    ),
) -> None:
    """Publish payloads declared in run_manifest.json."""
    setup_logging()
    runtime = import_module("mercadolivre_upload.cli.commands.publish_runtime")
    try:
        workspace_root = runtime.resolve_workspace_root(
            workspace=workspace, seller_config=seller_config
        )
    except ValueError as exc:
        err_console.print(f"[error]{exc}[/error]")
        raise typer.Exit(2) from exc
    report_dir = runtime.build_attempt_report_dir(workspace_root=workspace_root)
    cmd = import_module("mercadolivre_upload.cli.commands.publish_manifest")
    cmd.publish_manifest(
        manifest_path=manifest_path,
        dry_run=not execute,
        execute=execute,
        confirmation=confirmation,
        publish_inactive=publish_inactive,
        workspace_root=workspace_root,
        report_dir=report_dir,
        seller_config=seller_config,
    )


@app.command()
def reconcile(
    workspace: Path = typer.Option(..., "--workspace"),  # noqa: B008
    seller_config: Path = typer.Option(  # noqa: B008
        Path(".canonical-publisher-config"), "--config"
    ),
    from_manifest: bool = typer.Option(
        True,
        "--from-manifest/--from-artifacts",
        help="Use run manifests; artifact scan is available only with --execution-profile dev.",
    ),  # noqa: B008
    manifest: Path | None = typer.Option(None, "--manifest"),  # noqa: B008
    run_id: str | None = typer.Option(None, "--run-id"),  # noqa: B008
    all_manifests: bool = typer.Option(False, "--all-manifests"),  # noqa: B008
    execution_profile: str = typer.Option(
        "paid",
        "--execution-profile",
        help="Reconcile paid production manifests or explicit dev artifacts/manifests.",
    ),  # noqa: B008
    output: str = typer.Option("table", "--output"),  # noqa: B008
    save_report: bool = typer.Option(False, "--save-report"),  # noqa: B008
) -> None:
    """Reconcile generated payloads with live Mercado Livre inventory."""
    setup_logging()
    runtime = import_module("mercadolivre_upload.cli.commands.publish_runtime")
    try:
        workspace_root = runtime.resolve_workspace_root(
            workspace=workspace, seller_config=seller_config
        )
    except ValueError as exc:
        err_console.print(f"[error]{exc}[/error]")
        raise typer.Exit(2) from exc
    cmd = import_module("mercadolivre_upload.cli.commands.reconcile")
    cmd.reconcile(
        workspace_root=workspace_root,
        seller_config=seller_config,
        from_manifest=from_manifest,
        manifest=manifest,
        run_id=run_id,
        all_manifests=all_manifests,
        execution_profile=execution_profile,
        output=output,
        save_report=save_report,
    )


def main() -> None:
    """Compatibility entry point for tests."""
    import_module("mercadolivre_upload.cli").app()


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
