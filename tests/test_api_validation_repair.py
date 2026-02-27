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


def test_extract_prune_candidate_ids_resolves_attribute_index_references() -> None:
    causes = [
        {
            "code": "item.attributes.invalid",
            "message": "Attribute is not valid",
            "references": ["item.attributes[1].value_name"],
        }
    ]
    item = {
        "attributes": [
            {"id": "FRAME_COLOR", "value_name": "Borda Infinita"},
            {"id": "PAINTING_THEME", "value_name": "Abstrato"},
        ]
    }

    candidate_ids = extract_prune_candidate_ids(causes, detect_mode="conservative", item=item)

    assert candidate_ids == {"PAINTING_THEME"}


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


def test_validate_item_with_api_repair_stops_on_non_attribute_blocking_error() -> None:
    use_case = SimpleNamespace(
        _validate_item_for_flow=lambda **_: {
            "cause": [
                {
                    "type": "error",
                    "code": "shipping.mode.invalid",
                    "message": "Shipping mode is not allowed for this seller",
                    "references": ["shipping.mode"],
                }
            ]
        }
    )
    item: dict[str, Any] = {"attributes": [{"id": "BRAND", "value_name": "Genérica"}]}

    validation, artifact = validate_item_with_api_repair(
        use_case=use_case,
        item=item,
        selected_flow="legacy",
        required_attribute_ids=set(),
    )

    assert validation["cause"][0]["code"] == "shipping.mode.invalid"
    assert artifact["attempt_count"] == 1
    assert artifact["stop_reason"] == "non_attribute_blocking_errors"
    assert artifact["non_attribute_blocking_codes"] == ["shipping.mode.invalid"]
    assert artifact["pruned_attribute_ids"] == []
