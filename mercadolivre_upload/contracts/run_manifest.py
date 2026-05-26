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
    payload_path: str | None = None
    listing_type_id: str
    publishable: bool
    artifact_source: str | None = None
    created_at: datetime | None = None
    block_reason: str | None = None
    skip_reason: str | None = None


class PublicationCandidate(BaseModel):
    """One group-level publication candidate."""

    model_config = ConfigDict(extra="forbid")

    group_id: str
    family_id: str | None = None
    sku_scope: list[str] = Field(default_factory=list)
    topology: str | None = None
    build_status: Literal["success", "partial_success", "failed", "skipped", "not_publishable"]
    payloads: list[PublicationPayloadVariant] = Field(default_factory=list)
    errors: list[Any] = Field(default_factory=list)


class BuildFailure(BaseModel):
    """Non-publishable failure emitted by the builder."""

    model_config = ConfigDict(extra="allow")

    sku: str | None = None
    group_id: str | None = None
    family_id: str | None = None
    stage: str | None = None
    reason: str | None = None
    publishable: bool = False


class RunManifest(BaseModel):
    """Current run manifest contract consumed by publish-manifest."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    created_at: datetime
    workspace_path: str
    status: Literal["success", "partial_success", "failed"]
    publication_candidates: list[PublicationCandidate]
    build_failures: list[BuildFailure]
    diagnostics: dict[str, str | None]


def load_run_manifest(path: Path) -> RunManifest:
    """Read and validate run_manifest.json from an explicit manifest path."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    return RunManifest.model_validate(raw)
