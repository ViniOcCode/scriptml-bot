"""CLI command implementation for publication reconciliation."""

from __future__ import annotations

import json
from pathlib import Path

import requests
import typer
from rich.console import Console
from rich.table import Table

from mercadolivre_upload.api.client import MLApiClient
from mercadolivre_upload.api.exceptions import MLApiError
from mercadolivre_upload.application.reconcile import (
    ReconcileOperationalError,
    ReconcileReport,
    ReconcileUsageError,
    ReconcileUseCase,
)
from mercadolivre_upload.auth.exceptions import AuthError
from mercadolivre_upload.auth.publisher_context import build_publisher_auth_context

console = Console()
err_console = Console(stderr=True)


def _format_list(values: list[str]) -> str:
    return ",".join(values)


def _print_table(report: ReconcileReport) -> None:
    table = Table(title="Publication reconcile")
    for column, ratio in (
        ("status", 1),
        ("group_id", 1),
        ("family_id", 1),
        ("sku_scope", 2),
        ("variant", 1),
        ("listing_type_id", 1),
        ("ml_item_id", 1),
        ("ml_status", 1),
        ("payload_path", 3),
        ("error_reason", 2),
    ):
        table.add_column(column, overflow="fold", ratio=ratio)

    for row in report.rows:
        table.add_row(
            row.status,
            row.group_id or "",
            row.family_id or "",
            _format_list(row.sku_scope),
            row.variant or "",
            row.listing_type_id or "",
            row.ml_item_id or "",
            row.ml_status or "",
            row.payload_path or "",
            row.error_reason or "",
        )
    table_console = Console(
        width=max(console.width, 240),
        force_terminal=console.is_terminal,
        color_system=console.color_system,
    )
    table_console.print(table)
    summary = ", ".join(f"{key}={value}" for key, value in report.summary.items())
    console.print(f"[cyan]Summary:[/cyan] {summary}")
    if report.report_path:
        console.print(f"[cyan]Report path:[/cyan] {report.report_path}")


def _print_json(report: ReconcileReport) -> None:
    typer.echo(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))


def reconcile(
    *,
    workspace_root: Path,
    seller_config: Path,
    from_manifest: bool = False,
    manifest: Path | None = None,
    run_id: str | None = None,
    all_manifests: bool = False,
    output: str = "table",
    save_report: bool = False,
) -> None:
    """Run generated-vs-published reconciliation."""
    output_format = output.strip().lower()
    if output_format not in {"table", "json"}:
        err_console.print("[red]Erro:[/red] --output must be table or json")
        raise typer.Exit(2)

    try:
        auth_context = build_publisher_auth_context(
            settings_file=seller_config,
            workspace_root=workspace_root,
            strict=True,
        )
        use_case = ReconcileUseCase(MLApiClient(auth_context.token_manager))
        report = use_case.execute(
            workspace_root=workspace_root,
            from_manifest=from_manifest,
            manifest_path=manifest,
            run_id=run_id,
            all_manifests=all_manifests,
            save_report=save_report,
        )
    except ReconcileUsageError as exc:
        err_console.print(f"[red]Erro:[/red] {exc}")
        raise typer.Exit(2) from exc
    except (
        AuthError,
        FileNotFoundError,
        MLApiError,
        requests.RequestException,
        ReconcileOperationalError,
    ) as exc:
        err_console.print(f"[red]Erro:[/red] {exc}")
        raise typer.Exit(1) from exc

    if output_format == "json":
        _print_json(report)
    else:
        _print_table(report)

    explicit_manifest = from_manifest and (manifest is not None or bool(run_id))
    if explicit_manifest and report.summary.get("manifest_error", 0):
        raise typer.Exit(2)
