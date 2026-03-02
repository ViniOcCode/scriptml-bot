"""Tests for deterministic preflight attribute gather logic."""

from mercadolivre_upload.tools.preflight_gather import (
    _build_attr_indexes,
    evaluate_readiness,
    resolve_attribute_value,
    resolve_header,
)


def test_resolve_header_exact_name() -> None:
    attributes = [
        {"id": "COLOR", "name": "Cor", "value_type": "list", "values": []},
        {"id": "HEIGHT", "name": "Altura", "value_type": "number_unit", "values": []},
    ]
    _, by_name, by_id_token = _build_attr_indexes(attributes)

    result = resolve_header(
        "Cor",
        attributes=attributes,
        by_name=by_name,
        by_id_token=by_id_token,
    )

    assert result["status"] == "resolved"
    assert result["match"]["attribute_id"] == "COLOR"
    assert result["match"]["method"] == "exact_name"


def test_resolve_header_ambiguous_for_duplicate_exact_name() -> None:
    attributes = [
        {"id": "COLOR", "name": "Cor", "value_type": "list", "values": []},
        {"id": "FRAME_COLOR", "name": "Cor", "value_type": "list", "values": []},
    ]
    _, by_name, by_id_token = _build_attr_indexes(attributes)

    result = resolve_header(
        "Cor",
        attributes=attributes,
        by_name=by_name,
        by_id_token=by_id_token,
    )

    assert result["status"] == "ambiguous"
    assert result["match"] is None
    assert len(result["candidates"]) == 2


def test_resolve_attribute_value_list_exact_token_to_value_id() -> None:
    attribute = {
        "id": "COLOR",
        "name": "Cor",
        "value_type": "list",
        "values": [
            {"id": "1", "name": "Azul"},
            {"id": "2", "name": "Verde"},
        ],
    }

    resolved = resolve_attribute_value(attribute, "Azul", enable_translate=False)

    assert resolved["status"] == "resolved"
    assert resolved["primary"] == {"value_id": "1", "value_name": "Azul"}


def test_resolve_attribute_value_number_unit_uses_default_unit() -> None:
    attribute = {
        "id": "HEIGHT",
        "name": "Altura",
        "value_type": "number_unit",
        "default_unit": "cm",
        "allowed_units": [{"id": "cm", "name": "cm"}],
    }

    resolved = resolve_attribute_value(attribute, "25", enable_translate=False)

    assert resolved["status"] == "resolved"
    assert resolved["primary"] == {"value_id": None, "value_name": "25 cm"}


def test_evaluate_readiness_blocks_missing_required_when_strict() -> None:
    status, blocking, warnings = evaluate_readiness(
        resolved_headers={"Cor": "COLOR"},
        value_resolution=[
            {
                "column": "Cor",
                "attribute_id": "COLOR",
                "unresolved_samples": 0,
                "total_samples": 2,
            }
        ],
        required_base_ids={"COLOR", "BRAND"},
        required_conditional_ids={"MODEL"},
        strict=True,
    )

    assert status == "FAIL"
    assert len(blocking) == 2
    assert not warnings
