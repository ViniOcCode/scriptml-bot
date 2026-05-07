"""Shared helpers for upload/validate CLI flows."""

from pathlib import Path
from typing import Any, Protocol
from ml_workflow_contracts.runtime_paths import resolve_ml_bot_paths

import typer
from rich.console import Console


class SpreadsheetParserPort(Protocol):
    """Protocol for spreadsheet parser adapters used by CLI commands."""

    def parse(
        self,
        file_path: str | Path,
        sheet_name: str | int | None = None,
        header_row: int | None = None,
    ) -> list[dict[str, Any]]:
        """Parse spreadsheet rows into dictionaries."""
        ...


def coerce_path_option(
    path_value: Path | str | typer.models.OptionInfo,
    *,
    default: Path,
) -> Path:
    """Normalize Typer option values to Path instances."""
    if isinstance(path_value, typer.models.OptionInfo):
        return default
    if isinstance(path_value, Path):
        return path_value
    return Path(path_value)


def resolve_scriptml_workspace(workspace: Path | str | None) -> Path:
    if workspace is not None:
        return Path(workspace).expanduser().resolve()
    return (resolve_ml_bot_paths().runs_root / "scriptml-standalone").resolve()


def resolve_scriptml_cache_root(cache_root: Path | str | None) -> Path:
    if cache_root is not None:
        return Path(cache_root).expanduser().resolve()
    return (resolve_ml_bot_paths().cache_root / "scriptml").resolve()


def resolve_default_category_cache_dir(
    *,
    workspace: Path | str | None,
    cache_root: Path | str | None,
) -> Path:
    del workspace
    return resolve_scriptml_cache_root(cache_root) / "mercadolivre" / "categories"


def resolve_default_report_dir(workspace: Path | str | None) -> Path:
    return resolve_scriptml_workspace(workspace) / "publish"


def parse_products_or_exit(
    *,
    parser: SpreadsheetParserPort,
    excel: Path,
    err_console: Console,
) -> list[dict[str, Any]]:
    """Parse spreadsheet rows and normalize parser errors to CLI exit behavior."""
    try:
        return parser.parse(excel)
    except (FileNotFoundError, ValueError) as exc:
        err_console.print(f"[red]Error parsing Excel: {exc}[/red]")
        raise typer.Exit(1) from exc


def merge_category_resolution_fields(
    target: dict[str, Any],
    source: dict[str, Any],
    default_input: str | None = None,
) -> None:
    """Copy category-resolution metadata with deterministic defaults."""
    category_input = source.get("category_input")
    if not isinstance(category_input, str) or not category_input:
        category_input = default_input
    target["category_input"] = category_input

    category_resolved_id = source.get("category_resolved_id")
    if isinstance(category_resolved_id, str) and category_resolved_id:
        target["category_resolved_id"] = category_resolved_id
    else:
        target["category_resolved_id"] = None

    category_path = source.get("category_path")
    target["category_path"] = list(category_path) if isinstance(category_path, list) else []

    resolution_strategy = source.get("resolution_strategy")
    if isinstance(resolution_strategy, str) and resolution_strategy:
        target["resolution_strategy"] = resolution_strategy
    else:
        target["resolution_strategy"] = "unresolved"
