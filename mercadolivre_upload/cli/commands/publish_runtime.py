"""Runtime path resolution shared by publish commands."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import yaml


def resolve_workspace_root(*, workspace: Path | None, seller_config: Path) -> Path:
    """Resolve workspace root for strict publication flows."""
    if workspace is not None:
        return workspace.expanduser().resolve()

    try:
        payload = yaml.safe_load(seller_config.read_text(encoding="utf-8")) or {}
    except OSError as exc:
        raise ValueError(f"Could not read publisher config for workspace resolution: {seller_config}") from exc
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid publisher config YAML: {seller_config}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"Publisher config must be a mapping: {seller_config}")

    runtime = payload.get("runtime")
    workspace_root = runtime.get("workspace_root") if isinstance(runtime, dict) else None
    if not isinstance(workspace_root, str) or not workspace_root.strip():
        raise ValueError(
            "Missing workspace_root for publication. Provide --workspace or set "
            f"runtime.workspace_root in {seller_config}"
        )
    candidate = Path(workspace_root).expanduser()
    if not candidate.is_absolute():
        candidate = seller_config.parent / candidate
    return candidate.resolve()


def build_attempt_report_dir(*, workspace_root: Path) -> Path:
    """Build the attempt report folder under workspace cache/report/<timestamp>."""
    attempt_id = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return workspace_root / "cache" / "report" / attempt_id
