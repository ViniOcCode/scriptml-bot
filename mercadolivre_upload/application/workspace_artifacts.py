"""Fail-closed resolution for publisher-owned workspace artifacts."""

from __future__ import annotations

import stat
from pathlib import Path


def resolve_workspace_artifact(
    path: Path,
    *,
    workspace_root: Path,
    suffixes: frozenset[str],
) -> Path:
    """Return one regular non-symlink artifact confined to ``workspace_root``."""
    workspace = workspace_root.expanduser().resolve(strict=True)
    candidate = path.expanduser()
    resolved = candidate.resolve(strict=True)
    if resolved.suffix.lower() not in suffixes or not resolved.is_relative_to(workspace):
        raise ValueError("Artifact path is outside the allowed workspace.")
    relative = resolved.relative_to(workspace)
    current = workspace
    for component in relative.parts:
        current /= component
        mode = current.lstat().st_mode
        if stat.S_ISLNK(mode):
            raise ValueError("Symlinked artifact paths are not allowed.")
    if not stat.S_ISREG(resolved.stat().st_mode):
        raise ValueError("Workspace artifact must be a regular file.")
    return resolved


__all__ = ["resolve_workspace_artifact"]
