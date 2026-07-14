"""Typed publication outcome contract shared by publisher entry points."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

PublicationStatus = Literal[
    "published",
    "published_but_not_grouped",
    "skipped",
    "failed",
    "unknown",
]
SideEffectState = Literal["none", "confirmed", "partial", "unknown"]
PublicationPhaseName = Literal[
    "payload_validation",
    "policy_validation",
    "remote_validation",
    "item_creation",
    "pause",
    "description",
    "grouping",
    "fiscal",
]
PublicationPhaseStatus = Literal["succeeded", "failed", "skipped", "unknown"]


class PublicationPhase(BaseModel):
    """Observable result of one publication phase."""

    model_config = ConfigDict(extra="forbid")

    name: PublicationPhaseName
    status: PublicationPhaseStatus
    required: bool = True
    item_id: str | None = None
    detail: str | None = None


class PublicationOutcome(BaseModel):
    """Stable result of one payload publication attempt.

    ``status`` describes the workflow result. ``side_effect_state`` independently
    describes what is known about remote Mercado Livre mutations.
    """

    model_config = ConfigDict(extra="forbid")

    sku: str | None
    path: str
    status: PublicationStatus
    side_effect_state: SideEffectState = "none"
    phases: list[PublicationPhase] = Field(default_factory=list)
    item_id: str | None = None
    item_ids: list[str] = Field(default_factory=list)
    user_product_id: str | None = None
    publish_endpoints: list[str] = Field(default_factory=list)
    error: str | None = None
    warnings: list[str] = Field(default_factory=list)
    validation_status: str | None = None
    validation_report: dict[str, Any] | None = None
    fiscal_status: str | None = None
    fiscal_report: list[dict[str, Any]] = Field(default_factory=list)
    reconciliation_required: bool = False
    report_path: str | None = None

    @model_validator(mode="after")
    def outcome_semantics_are_consistent(self) -> PublicationOutcome:
        """Reject contradictory success and side-effect combinations."""
        if self.status == "published":
            if self.side_effect_state != "confirmed":
                raise ValueError("published status requires confirmed side effects")
            if self.reconciliation_required:
                raise ValueError("published status cannot require reconciliation")
        if self.status == "unknown":
            if self.side_effect_state not in {"partial", "unknown"}:
                raise ValueError("unknown status requires partial or unknown side effects")
            if not self.reconciliation_required:
                raise ValueError("unknown status requires reconciliation")
        if self.status == "published_but_not_grouped" and (
            self.side_effect_state != "partial" or not self.reconciliation_required
        ):
            raise ValueError(
                "published_but_not_grouped requires partial side effects and reconciliation"
            )
        if self.status == "skipped" and (
            self.side_effect_state != "none" or self.reconciliation_required
        ):
            raise ValueError("skipped status cannot have remote side effects")
        if self.side_effect_state in {"partial", "unknown"} and not self.reconciliation_required:
            raise ValueError("partial or unknown side effects require reconciliation")
        remote_identifiers = bool(
            self.item_id or self.item_ids or self.user_product_id or self.publish_endpoints
        )
        if remote_identifiers and self.side_effect_state == "none":
            raise ValueError("remote identifiers are incompatible with side_effect_state='none'")
        return self


__all__ = ["PublicationOutcome", "PublicationPhase"]
