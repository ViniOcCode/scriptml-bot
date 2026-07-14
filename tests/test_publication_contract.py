"""Contract tests for publication outcomes shared with dashboard consumers."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from mercadolivre_upload.contracts.publication import PublicationOutcome


def _outcome(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "sku": "SKU-1",
        "path": "payload_classic.json",
        "status": "failed",
    }
    values.update(overrides)
    return values


def test_published_requires_confirmed_side_effects() -> None:
    with pytest.raises(ValidationError, match="published status requires confirmed"):
        PublicationOutcome.model_validate(_outcome(status="published"))


def test_unknown_requires_reconciliation() -> None:
    with pytest.raises(ValidationError, match="unknown status requires partial or unknown"):
        PublicationOutcome.model_validate(_outcome(status="unknown"))


def test_partial_side_effects_require_reconciliation() -> None:
    with pytest.raises(ValidationError, match="partial or unknown side effects"):
        PublicationOutcome.model_validate(_outcome(side_effect_state="partial"))


def test_remote_ids_cannot_claim_no_side_effects() -> None:
    with pytest.raises(ValidationError, match="remote identifiers are incompatible"):
        PublicationOutcome.model_validate(_outcome(item_id="MLB123"))


def test_grouping_failure_requires_reconciliation() -> None:
    with pytest.raises(ValidationError, match="published_but_not_grouped requires"):
        PublicationOutcome.model_validate(_outcome(status="published_but_not_grouped"))


def test_partial_failure_with_reconciliation_is_valid() -> None:
    outcome = PublicationOutcome.model_validate(
        _outcome(
            side_effect_state="partial",
            item_id="MLB123",
            item_ids=["MLB123"],
            reconciliation_required=True,
        )
    )

    assert outcome.status == "failed"
    assert outcome.reconciliation_required is True
