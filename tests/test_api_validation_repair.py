"""Tests for API validation repair helpers."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from mercadolivre_upload.application.publish.internals.api_validation_repair import (
    extract_prune_candidate_ids,
    prune_item_attributes,
    validate_item_with_api_repair,
)


def test_extract_prune_candidate_ids_conservative_reads_references_and_message() -> None:
    causes = [
        {
            "code": "item.attributes.invalid",
            "message": "Attribute [PAINTING_THEME] is not valid",
            "references": ["item.attributes[FRAME_COLOR]"],
        }
    ]

    candidate_ids = extract_prune_candidate_ids(causes, detect_mode="conservative")

    assert candidate_ids == {"FRAME_COLOR", "PAINTING_THEME"}


def test_prune_item_attributes_keeps_required_when_drop_required_disabled() -> None:
    item: dict[str, Any] = {
        "attributes": [
            {"id": "FRAME_COLOR", "value_name": "Borda Infinita"},
            {"id": "BRAND", "value_name": "Genérica"},
        ]
    }

    result = prune_item_attributes(
        item=item,
        prune_candidate_ids={"FRAME_COLOR", "BRAND"},
        required_attribute_ids={"BRAND"},
        drop_required_attributes=False,
    )

    assert result["removed_attribute_ids"] == ["FRAME_COLOR"]
    assert result["skipped_required_attribute_ids"] == ["BRAND"]
    assert item["attributes"] == [{"id": "BRAND", "value_name": "Genérica"}]


def test_validate_item_with_api_repair_prunes_once_and_then_passes() -> None:
    validations = [
        {
            "cause": [
                {
                    "type": "error",
                    "code": "item.attributes.invalid",
                    "message": "Attribute [FRAME_COLOR] is not valid",
                    "references": ["item.attributes[FRAME_COLOR]"],
                }
            ]
        },
        {"cause": []},
    ]

    call_state = {"index": 0}

    def _validate_item_for_flow(*, item: dict[str, Any], selected_flow: str) -> dict[str, Any]:
        index = call_state["index"]
        call_state["index"] += 1
        return validations[index]

    use_case = SimpleNamespace(
        api_validation_repair_max_attempts=3,
        api_validation_repair_detect_mode="conservative",
        api_validation_repair_drop_required_attributes=False,
        api_validation_repair_scope="all",
        _validate_item_for_flow=_validate_item_for_flow,
    )
    item: dict[str, Any] = {
        "attributes": [
            {"id": "FRAME_COLOR", "value_name": "Borda Infinita"},
            {"id": "BRAND", "value_name": "Genérica"},
        ]
    }

    validation, artifact = validate_item_with_api_repair(
        use_case=use_case,
        item=item,
        selected_flow="legacy",
        required_attribute_ids={"BRAND"},
    )

    assert validation == {"cause": []}
    assert artifact["attempt_count"] == 2
    assert artifact["stop_reason"] == "validation_passed"
    assert artifact["pruned_attribute_ids"] == ["FRAME_COLOR"]
    assert item["attributes"] == [{"id": "BRAND", "value_name": "Genérica"}]
