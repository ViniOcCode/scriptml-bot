"""Tests for deterministic preflight attribute gather logic."""

import pytest

from mercadolivre_upload.tools.preflight_gather import (
    CATEGORY_ID_PATTERN,
    _build_attr_indexes,
    evaluate_readiness,
    resolve_attribute_value,
    resolve_category,
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


class _PreflightResolverStub:
    def __init__(
        self,
        *,
        predictor_result: str | None = None,
        leaf_result: str = "MLB1000",
        category_name: str = "Categoria Teste",
    ) -> None:
        self.predictor_result = predictor_result
        self.leaf_result = leaf_result
        self.category_name = category_name
        self.predictor_calls: list[tuple[str, list[str], str]] = []

    def find_category_with_predictor(
        self, category_name: str, product_titles: list[str], site_id: str = "MLB"
    ) -> str | None:
        self.predictor_calls.append((category_name, product_titles, site_id))
        return self.predictor_result

    def resolve_to_leaf(self, category_id: str) -> str:
        assert isinstance(category_id, str)
        return self.leaf_result

    def get_category_data(self, _category_id: str) -> dict[str, str]:
        return {"name": self.category_name}


def test_resolve_category_uses_predictor_with_category_input() -> None:
    resolver = _PreflightResolverStub(predictor_result="MLB2000", leaf_result="MLB2200")

    category_id, category_name = resolve_category(resolver, "livros fisicos", "MLB")

    assert category_id == "MLB2200"
    assert category_name == "Categoria Teste"
    assert resolver.predictor_calls == [("livros fisicos", ["livros fisicos"], "MLB")]


def test_resolve_category_skips_predictor_for_direct_category_id() -> None:
    assert CATEGORY_ID_PATTERN.match("MLB1234")
    resolver = _PreflightResolverStub(leaf_result="MLB1234")

    category_id, category_name = resolve_category(resolver, "MLB1234", "MLB")

    assert category_id == "MLB1234"
    assert category_name == "Categoria Teste"
    assert resolver.predictor_calls == []


def test_resolve_category_fails_when_predictor_has_no_match() -> None:
    resolver = _PreflightResolverStub(predictor_result=None)

    with pytest.raises(ValueError, match="Could not resolve category from input with predictor"):
        resolve_category(resolver, "quadros decorativos", "MLB")
