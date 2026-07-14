"""Publisher-side run_manifest.json validator."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class PublicationPayloadVariant(BaseModel):
    """One payload variant candidate for publishing."""

    model_config = ConfigDict(extra="forbid")

    variant: str
    payload_path: str = ""
    listing_type_id: str = ""
    publishable: bool
    artifact_source: str = ""
    created_at: datetime | None = None
    block_reason: str | None = None
    skip_reason: str | None = None


class PublicationCandidate(BaseModel):
    """One group-level publication candidate."""

    model_config = ConfigDict(extra="forbid")

    group_id: str
    family_id: str = ""
    sku_scope: list[str] = Field(default_factory=list)
    topology: str = ""
    build_status: Literal["success", "partial_success", "failed", "skipped", "not_publishable"]
    payloads: list[PublicationPayloadVariant] = Field(default_factory=list)
    errors: list[dict[str, Any]] = Field(default_factory=list)
    override_status: Literal["none", "applied", "partially_applied", "rejected", "unsupported"] = (
        "none"
    )
    review_overrides_applied: list[dict[str, Any]] = Field(default_factory=list)
    override_rejection_reason: str | None = None


class BuildFailure(BaseModel):
    """Non-publishable failure emitted by the builder."""

    model_config = ConfigDict(extra="forbid")

    sku: str
    group_id: str
    stage: str
    reason: str
    publishable: Literal[False] = False
    review_issues: list[dict[str, Any]] = Field(default_factory=list)
    override_status: Literal["none", "applied", "partially_applied", "rejected", "unsupported"] = (
        "none"
    )
    review_overrides_applied: list[dict[str, Any]] = Field(default_factory=list)
    override_rejection_reason: str | None = None


class RunManifest(BaseModel):
    """Current run manifest contract consumed by publish-manifest."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    created_at: datetime
    workspace_path: str
    status: Literal["success", "partial_success", "failed"]
    publication_candidates: list[PublicationCandidate]
    build_failures: list[BuildFailure] = Field(default_factory=list)
    diagnostics: dict[str, str | None] = Field(default_factory=dict)
    review_overrides: list[dict[str, Any]] = Field(default_factory=list)


def load_run_manifest(path: Path) -> RunManifest:
    """Read and validate run_manifest.json from an explicit manifest path."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    return RunManifest.model_validate(raw)
