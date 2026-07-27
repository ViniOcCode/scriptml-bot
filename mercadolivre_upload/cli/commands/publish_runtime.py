"""Runtime path resolution shared by publish commands."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path


def resolve_workspace_root(*, workspace: Path | None, seller_config: Path) -> Path:
    """Resolve workspace root for strict publication flows."""
    if workspace is not None:
        return workspace.expanduser().resolve()
    raise ValueError(
        "Missing workspace_root for publication. Provide --workspace; "
        "operational paths are not loaded from publisher YAML."
    )


def build_attempt_report_dir(*, workspace_root: Path) -> Path:
    """Build the attempt report folder under workspace cache/report/<timestamp>."""
    attempt_id = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return workspace_root / "cache" / "report" / attempt_id
