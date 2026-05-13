"""Publisher-side run_manifest.json validator."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

RUN_MANIFEST_SCHEMA_VERSION = "1.0.0"


class RunArtifact(BaseModel):
    """One artifact entry from builder run_manifest."""

    model_config = ConfigDict(extra="forbid")

    sku: str
    status: Literal["done", "review_required", "error", "skipped"]
    payload_paths: list[str] = Field(default_factory=list)
    category_id: str = ""
    category_name: str = ""
    error: Any | None = None


class RunManifest(BaseModel):
    """Run manifest contract consumed by publisher/orchestrator."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str
    run_id: str
    created_at: datetime
    workspace_path: str
    artifacts: list[RunArtifact]
    blocking_issues: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    diagnostics: dict[str, str | None] = Field(default_factory=dict)


def load_run_manifest(path: Path) -> RunManifest:
    """Read and validate run_manifest.json from an explicit manifest path."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    manifest = RunManifest.model_validate(raw)
    if manifest.schema_version != RUN_MANIFEST_SCHEMA_VERSION:
        raise ValueError(
            "Unsupported run_manifest schema_version "
            f"{manifest.schema_version!r}; expected {RUN_MANIFEST_SCHEMA_VERSION!r}"
        )
    return manifest

