"""Publisher-side run_manifest.json validator."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CandidatePayloadVariant(BaseModel):
    """One concrete payload variant for a publication candidate."""

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
    """One publishable unit candidate (group-level or per-SKU for independent topology)."""

    model_config = ConfigDict(extra="forbid")

    group_id: str
    family_id: str = ""
    sku_scope: list[str] = Field(default_factory=list)
    topology: str = ""
    build_status: Literal["success", "partial_success", "failed", "skipped", "not_publishable"]
    payloads: list[CandidatePayloadVariant] = Field(default_factory=list)
    errors: list[dict[str, Any]] = Field(default_factory=list)
    override_status: Literal["none", "applied", "partially_applied", "rejected", "unsupported"] = (
        "none"
    )
    review_overrides_applied: list[dict[str, Any]] = Field(default_factory=list)
    override_rejection_reason: str | None = None


class BuildFailure(BaseModel):
    """Build failure entry for non-publishable groups/SKUs."""

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


class LegacyRunManifestV1(BaseModel):
    """Reader-only persisted v1 manifest contract."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    created_at: datetime
    workspace_path: str
    execution_profile: Literal["dev", "paid"]
    status: Literal["success", "partial_success", "failed"]
    publication_candidates: list[PublicationCandidate]
    build_failures: list[BuildFailure] = Field(default_factory=list)
    diagnostics: dict[str, str | None] = Field(default_factory=dict)
    review_overrides: list[dict[str, Any]] = Field(default_factory=list)

    @model_validator(mode="after")
    def dev_profile_is_never_publishable(self) -> LegacyRunManifestV1:
        if self.execution_profile == "dev" and any(
            payload.publishable
            for candidate in self.publication_candidates
            for payload in candidate.payloads
        ):
            raise ValueError("v1 dev manifest payloads must not be publishable")
        return self


class RunManifest(BaseModel):
    """Cross-app handoff manifest consumed by publisher/orchestrator."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    created_at: datetime
    workspace_path: str
    manifest_version: Literal[2]
    trust_profile: Literal["production", "development"]
    run_mode: Literal["autonomous", "diagnostic"]
    model_policy: Literal["free_only", "quality_first"]
    generation_outcome: Literal["complete", "needs_input", "failed"]
    quality_gate_status: Literal["passed", "incomplete", "failed"]
    publication_ready: bool
    blocking_gaps: list[dict[str, Any]] = Field(default_factory=list)
    status: Literal["success", "partial_success", "failed"]
    publication_candidates: list[PublicationCandidate]
    build_failures: list[BuildFailure] = Field(default_factory=list)
    diagnostics: dict[str, str | None] = Field(default_factory=dict)
    review_overrides: list[dict[str, Any]] = Field(default_factory=list)

    @model_validator(mode="after")
    def publication_requires_common_quality_gates(self) -> RunManifest:
        """Apply the shared trust and quality contract before publication."""
        has_publishable_payload = any(
            payload.publishable
            for candidate in self.publication_candidates
            for payload in candidate.payloads
        )
        if self.run_mode == "diagnostic" and self.publication_ready:
            raise ValueError("diagnostic manifests cannot be publication_ready")
        if self.trust_profile != "production" and self.publication_ready:
            raise ValueError("development manifests cannot be publication_ready")
        if self.publication_ready and self.generation_outcome != "complete":
            raise ValueError("publication_ready requires generation_outcome=complete")
        if self.publication_ready and self.quality_gate_status != "passed":
            raise ValueError("publication_ready requires quality_gate_status=passed")
        if self.publication_ready and self.blocking_gaps:
            raise ValueError("publication_ready manifests cannot contain blocking_gaps")
        if self.publication_ready and not has_publishable_payload:
            raise ValueError("publication_ready requires a publishable payload")
        return self


def _legacy_execution_profile_manifest_policy(
    execution_profile: Literal["dev", "paid"],
) -> dict[str, object]:
    if execution_profile == "paid":
        return {
            "manifest_version": 2,
            "trust_profile": "production",
            "run_mode": "autonomous",
            "model_policy": "quality_first",
        }
    return {
        "manifest_version": 2,
        "trust_profile": "development",
        "run_mode": "diagnostic",
        "model_policy": "free_only",
    }


def read_run_manifest(raw: dict[str, Any]) -> RunManifest:
    """Read a v2 manifest or explicitly quarantine a persisted v1 artifact."""
    if raw.get("manifest_version") == 2:
        return RunManifest.model_validate(raw)
    if "manifest_version" in raw:
        raise ValueError("unsupported run manifest version")
    legacy = LegacyRunManifestV1.model_validate(raw)
    generation_outcome: Literal["complete", "needs_input", "failed"] = (
        "complete"
        if legacy.status == "success"
        else "needs_input"
        if legacy.status == "partial_success"
        else "failed"
    )
    return RunManifest(
        run_id=legacy.run_id,
        created_at=legacy.created_at,
        workspace_path=legacy.workspace_path,
        **_legacy_execution_profile_manifest_policy(legacy.execution_profile),
        generation_outcome=generation_outcome,
        quality_gate_status="incomplete",
        publication_ready=False,
        blocking_gaps=[
            {"sku": failure.sku, "stage": failure.stage, "reason": failure.reason}
            for failure in legacy.build_failures
        ],
        status=legacy.status,
        publication_candidates=legacy.publication_candidates,
        build_failures=legacy.build_failures,
        diagnostics={**legacy.diagnostics, "legacy_manifest_version": "1"},
        review_overrides=legacy.review_overrides,
    )


def load_run_manifest(path: Path) -> RunManifest:
    """Read and validate run_manifest.json from an explicit manifest path."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("run manifest must be a JSON object")
    return read_run_manifest(raw)
