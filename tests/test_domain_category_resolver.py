"""Tests for domain category resolver edge cases and caches."""

from __future__ import annotations

from typing import Any

import pytest

from mercadolivre_upload.domain.category.errors import CategoryApiUnavailableError
from mercadolivre_upload.domain.category.resolver import CategoryResolver


class _FakeApi:
    def __init__(self) -> None:
        self.predict_calls = 0
        self.raise_predict = False
        self.raise_conditional = False
        self.raise_tech_specs = False
        self.predictions: list[dict[str, Any]] = []
        self.predictions_by_title: dict[str, list[dict[str, Any]]] = {}
        self.predict_limits: list[int | None] = []
        self.predict_titles: list[str] = []
        self.categories: dict[str, Any] = {}
        self.attributes: list[dict[str, Any]] = []
        self.conditional_result: Any = []
        self.technical_specs: dict[str, Any] = {}

    def get_site_categories(self, _site_id: str) -> list[dict[str, Any]]:
        return [{"id": "MLB1", "name": "Livros"}]

    def get_category(self, category_id: str) -> dict[str, Any] | str:
        if category_id in self.categories:
            return self.categories[category_id]
        return {"children_categories": []}

    def get_category_attributes(self, _category_id: str) -> list[dict[str, Any]]:
        return self.attributes

    def get_category_technical_specs(self, _category_id: str) -> dict[str, Any]:
        if self.raise_tech_specs:
            raise RuntimeError("tech specs error")
        return self.technical_specs

    def get_category_conditional_attributes(
        self, _category_id: str, _item_context: dict[str, Any]
    ) -> Any:
        if self.raise_conditional:
            raise RuntimeError("conditional error")
        return self.conditional_result

    def predict_category(
        self, _title: str, _site_id: str, limit: int | None = None
    ) -> list[dict[str, Any]]:
        self.predict_calls += 1
        self.predict_limits.append(limit)
        self.predict_titles.append(_title)
        if self.raise_predict:
            raise RuntimeError("predict error")
        if _title in self.predictions_by_title:
            return self.predictions_by_title[_title]
        return self.predictions


class _FakePredictionCache:
    def __init__(self) -> None:
        self.data: dict[tuple[str, str], list[dict[str, Any]]] = {}
        self.set_calls = 0

    def get(self, title: str, site_id: str) -> list[dict[str, Any]] | None:
        return self.data.get((site_id, title))

    def set(self, title: str, predictions: list[dict[str, Any]], site_id: str) -> None:
        self.set_calls += 1
        self.data[(site_id, title)] = predictions


class _FakeAttributeCache:
    def __init__(self, cached: list[dict[str, Any]] | None = None) -> None:
        self.cached = cached
        self.saved: dict[str, list[dict[str, Any]]] = {}

    def get_attributes(self, _category_id: str) -> list[dict[str, Any]] | None:
        return self.cached

    def save_attributes(self, category_id: str, attributes: list[dict[str, Any]]) -> None:
        self.saved[category_id] = attributes


def test_predict_category_from_title_uses_cached_predictions() -> None:
    api = _FakeApi()
    cache = _FakePredictionCache()
    cache.data[("MLB", "produto teste")] = [{"category_id": "MLB123", "category_name": "Teste"}]
    resolver = CategoryResolver(api, prediction_cache=cache)

    result = resolver.predict_category_from_title("Produto Teste")

    assert result == "MLB123"
    assert api.predict_calls == 0


def test_predict_category_from_title_caches_api_predictions() -> None:
    api = _FakeApi()
    api.predictions = [{"category_id": "MLB999", "category_name": "Categoria"}]
    cache = _FakePredictionCache()
    resolver = CategoryResolver(api, prediction_cache=cache)

    result = resolver.predict_category_from_title("Notebook Gamer")

    assert result == "MLB999"
    assert api.predict_calls == 1
    assert cache.set_calls == 1
    assert cache.data[("MLB", "notebook gamer")] == api.predictions


def test_predict_category_from_title_caches_empty_predictions() -> None:
    api = _FakeApi()
    cache = _FakePredictionCache()
    resolver = CategoryResolver(api, prediction_cache=cache)

    first_result = resolver.predict_category_from_title("Notebook Sem Categoria")
    second_result = resolver.predict_category_from_title("  notebook sem categoria  ")

    assert first_result is None
    assert second_result is None
    assert api.predict_calls == 1


def test_call_domain_discovery_raises_on_exception() -> None:
    api = _FakeApi()
    api.raise_predict = True
    resolver = CategoryResolver(api)

    with pytest.raises(RuntimeError, match="predict error"):
        resolver._call_domain_discovery("Notebook Gamer", "MLB")


def test_call_domain_discovery_requests_limit_three() -> None:
    api = _FakeApi()
    api.predictions = [{"category_id": "MLB1", "category_name": "Livros"}]
    resolver = CategoryResolver(api)

    result = resolver._call_domain_discovery("Notebook Gamer", "MLB")

    assert result == [{"category_id": "MLB1", "category_name": "Livros"}]
    assert api.predict_limits == [3]


def test_get_category_cached_raises_on_exception() -> None:
    api = _FakeApi()
    api.categories["ERR"] = RuntimeError("boom")

    def _raise_on_err(category_id: str) -> dict[str, Any]:
        if category_id == "ERR":
            raise RuntimeError("boom")
        return {"children_categories": []}

    api.get_category = _raise_on_err  # type: ignore[assignment]
    resolver = CategoryResolver(api)

    with pytest.raises(RuntimeError, match="boom"):
        resolver._get_category_cached("ERR")


def test_get_category_cached_raises_on_invalid_payload_type() -> None:
    api = _FakeApi()
    api.categories["BAD"] = "invalid"
    resolver = CategoryResolver(api)

    with pytest.raises(CategoryApiUnavailableError, match="invalid response type"):
        resolver._get_category_cached("BAD")


def test_get_conditional_attributes_handles_invalid_payloads_and_exceptions() -> None:
    api = _FakeApi()
    resolver = CategoryResolver(api)

    api.conditional_result = {"error": "bad request"}
    assert resolver.get_conditional_attributes("MLB1", {}) == []

    api.conditional_result = "not-a-list"
    assert resolver.get_conditional_attributes("MLB1", {}) == []

    api.conditional_result = 123
    assert resolver.get_conditional_attributes("MLB1", {}) == []

    api.raise_conditional = True
    assert resolver.get_conditional_attributes("MLB1", {}) == []


def test_resolve_to_leaf_returns_original_for_non_dict_category() -> None:
    api = _FakeApi()
    api.categories["MLB1"] = "invalid"
    resolver = CategoryResolver(api)

    assert resolver.resolve_to_leaf("MLB1") == "MLB1"


def test_resolve_to_leaf_does_not_cache_empty_children_on_api_failure() -> None:
    api = _FakeApi()
    call_count = 0

    def _get_category(category_id: str) -> dict[str, Any]:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise CategoryApiUnavailableError("boom", operation=f"get_category:{category_id}")
        return {"children_categories": []}

    api.get_category = _get_category  # type: ignore[assignment]
    resolver = CategoryResolver(api)

    with pytest.raises(CategoryApiUnavailableError):
        resolver.resolve_to_leaf("MLB1")

    assert "MLB1" not in resolver._children_cache
    assert resolver.resolve_to_leaf("MLB1") == "MLB1"
    assert call_count == 2


def test_resolve_to_leaf_keeps_parent_when_children_are_ambiguous() -> None:
    api = _FakeApi()
    api.categories["MLB1"] = {
        "children_categories": [
            {"id": "MLB12", "name": "Child B", "total_items_in_this_category": 8},
            {"id": "MLB11", "name": "Child A", "total_items_in_this_category": 2},
        ]
    }
    api.categories["MLB11"] = {"children_categories": []}
    api.categories["MLB12"] = {"children_categories": []}
    resolver = CategoryResolver(api)

    assert resolver.resolve_to_leaf("MLB1") == "MLB1"


def test_resolve_to_leaf_descends_when_single_child_path_exists() -> None:
    api = _FakeApi()
    api.categories["MLB1"] = {
        "children_categories": [
            {"id": "MLB11", "name": "Child A", "total_items_in_this_category": 2},
        ]
    }
    api.categories["MLB11"] = {"children_categories": [{"id": "MLB111", "name": "Grandchild"}]}
    api.categories["MLB111"] = {"children_categories": []}
    resolver = CategoryResolver(api)

    assert resolver.resolve_to_leaf("MLB1") == "MLB111"


def test_find_category_uses_hierarchy_context_deterministically() -> None:
    api = _FakeApi()
    api.categories["MLB1"] = {"children_categories": [{"id": "MLB11", "name": "Romance"}]}
    api.categories["MLB2"] = {"children_categories": [{"id": "MLB21", "name": "Romance"}]}
    api.categories["MLB11"] = {"children_categories": []}
    api.categories["MLB21"] = {"children_categories": []}
    api.get_site_categories = lambda _site_id: [  # type: ignore[assignment]
        {"id": "MLB1", "name": "Eletrônicos"},
        {"id": "MLB2", "name": "Livros"},
    ]
    resolver = CategoryResolver(api)

    assert resolver.find_category("Romance") == "MLB11"
    assert resolver.find_category("Livros > Romance") == "MLB21"


def test_predict_category_from_title_filters_invalid_ids_for_site() -> None:
    api = _FakeApi()
    api.predictions = [
        {"category_id": "BAD-ID", "category_name": "Inválida", "confidence": 0.99},
        {"category_id": "MLM999", "category_name": "Outro site", "confidence": 0.95},
        {"category_id": "MLB777", "category_name": "Categoria válida", "confidence": 0.5},
    ]
    resolver = CategoryResolver(api)

    assert resolver.predict_category_from_title("Notebook Gamer", site_id="MLB") == "MLB777"


def test_find_category_with_predictor_prefers_context_path_match() -> None:
    api = _FakeApi()
    api.predictions = [
        {"category_id": "MLB100", "category_name": "Romance", "confidence": 0.7},
        {"category_id": "MLB200", "category_name": "Romance", "confidence": 0.8},
    ]
    api.categories["MLB100"] = {
        "children_categories": [],
        "path_from_root": [
            {"id": "MLB2", "name": "Livros"},
            {"id": "MLB100", "name": "Romance"},
        ],
    }
    api.categories["MLB200"] = {
        "children_categories": [],
        "path_from_root": [
            {"id": "MLB1", "name": "Eletrônicos"},
            {"id": "MLB200", "name": "Romance"},
        ],
    }
    resolver = CategoryResolver(api)

    result = resolver.find_category_with_predictor("Livros > Romance", ["Livro XPTO"])

    assert result == "MLB100"


def test_find_category_with_predictor_uses_only_top_three_predictions() -> None:
    api = _FakeApi()
    api.predictions = [
        {"category_id": "MLB101", "category_name": "Eletrônicos", "confidence": 0.99},
        {"category_id": "MLB102", "category_name": "Moda", "confidence": 0.98},
        {"category_id": "MLB103", "category_name": "Esportes", "confidence": 0.97},
        {"category_id": "MLB104", "category_name": "Livros", "confidence": 0.96},
    ]
    api.categories["MLB101"] = {
        "children_categories": [],
        "path_from_root": [{"id": "MLB101", "name": "Eletrônicos"}],
    }
    api.categories["MLB102"] = {
        "children_categories": [],
        "path_from_root": [{"id": "MLB102", "name": "Moda"}],
    }
    api.categories["MLB103"] = {
        "children_categories": [],
        "path_from_root": [{"id": "MLB103", "name": "Esportes"}],
    }
    api.categories["MLB104"] = {
        "children_categories": [],
        "path_from_root": [{"id": "MLB104", "name": "Livros"}],
    }
    resolver = CategoryResolver(api)

    result = resolver.find_category_with_predictor("Livros", ["Produto XPTO"])

    assert result is None


def test_find_category_with_predictor_stops_after_first_reliable_title_match() -> None:
    api = _FakeApi()
    api.predictions_by_title = {
        "Livro XPTO": [
            {"category_id": "MLB100", "category_name": "Romance", "confidence": 0.9},
        ],
        "Segundo título": [
            {"category_id": "MLB200", "category_name": "Romance", "confidence": 0.95},
        ],
    }
    api.categories["MLB100"] = {
        "children_categories": [],
        "path_from_root": [
            {"id": "MLB2", "name": "Livros"},
            {"id": "MLB100", "name": "Romance"},
        ],
    }
    api.categories["MLB200"] = {
        "children_categories": [],
        "path_from_root": [
            {"id": "MLB1", "name": "Eletrônicos"},
            {"id": "MLB200", "name": "Romance"},
        ],
    }
    resolver = CategoryResolver(api)

    result = resolver.find_category_with_predictor(
        "Livros > Romance", ["Livro XPTO", "Segundo título"]
    )

    assert result == "MLB100"
    assert api.predict_calls == 1
    assert api.predict_titles == ["Livro XPTO"]


def test_find_category_with_predictor_deduplicates_normalized_batch_titles() -> None:
    api = _FakeApi()
    api.predictions_by_title = {
        "Segundo título": [
            {"category_id": "MLB100", "category_name": "Romance", "confidence": 0.9},
        ],
    }
    api.categories["MLB100"] = {
        "children_categories": [],
        "path_from_root": [
            {"id": "MLB2", "name": "Livros"},
            {"id": "MLB100", "name": "Romance"},
        ],
    }
    resolver = CategoryResolver(api)

    result = resolver.find_category_with_predictor(
        "Livros > Romance",
        ["Livro XPTO", "  livro xpto  ", "Segundo título", "SEGUNDO TITULO"],
    )

    assert result == "MLB100"
    assert api.predict_calls == 2
    assert api.predict_titles == ["Livro XPTO", "Segundo título"]


def test_find_category_with_predictor_caches_empty_predictions_for_normalized_title() -> None:
    api = _FakeApi()
    cache = _FakePredictionCache()
    resolver = CategoryResolver(api, prediction_cache=cache)

    first_result = resolver.find_category_with_predictor("Livros", ["Livro Sem Categoria"])
    second_result = resolver.find_category_with_predictor("Livros", ["  livro sem categoria  "])

    assert first_result is None
    assert second_result is None
    assert api.predict_calls == 1


def test_find_category_with_predictor_returns_predicted_id_for_path_match() -> None:
    api = _FakeApi()
    api.predictions = [
        {"category_id": "MLB900", "category_name": "Romance", "confidence": 0.9},
    ]
    api.categories["MLB900"] = {
        "children_categories": [],
        "path_from_root": [
            {"id": "MLB2", "name": "Livros"},
            {"id": "MLB900", "name": "Romance"},
        ],
    }
    resolver = CategoryResolver(api)

    result = resolver.find_category_with_predictor("Livros", ["Livro XPTO"])

    assert result == "MLB900"


def test_is_listing_allowed_uses_category_settings() -> None:
    api = _FakeApi()
    api.categories["ENABLED"] = {
        "settings": {"listing_allowed": True, "status": "enabled"},
        "children_categories": [],
    }
    api.categories["NOT_ALLOWED"] = {
        "settings": {"listing_allowed": False, "status": "enabled"},
        "children_categories": [],
    }
    api.categories["PAUSED"] = {
        "settings": {"listing_allowed": True, "status": "disabled"},
        "children_categories": [],
    }
    resolver = CategoryResolver(api)

    assert resolver.is_listing_allowed("ENABLED") is True
    assert resolver.is_listing_allowed("NOT_ALLOWED") is False
    assert resolver.is_listing_allowed("PAUSED") is False


def test_get_attribute_metadata_handles_technical_specs_failure() -> None:
    api = _FakeApi()
    api.attributes = [{"id": "BRAND", "name": "Marca", "value_type": "string"}]
    api.raise_tech_specs = True
    cache = _FakeAttributeCache(cached=api.attributes)
    resolver = CategoryResolver(api, attribute_cache=cache)

    metadata = resolver.get_attribute_metadata("MLB123")

    assert len(metadata) == 1
    assert metadata[0].id == "BRAND"
    assert "MLB123" in cache.saved


def test_get_attribute_metadata_merges_technical_specs_data() -> None:
    api = _FakeApi()
    api.attributes = [{"id": "BRAND", "name": "Marca", "value_type": "string"}]
    api.technical_specs = {
        "groups": [
            {
                "components": [
                    {
                        "attributes": [
                            {
                                "id": "BRAND",
                                "relevance": "0.9",
                                "hierarchy": "parent",
                                "tags": ["catalog_listing_required"],
                            }
                        ]
                    }
                ]
            }
        ]
    }
    resolver = CategoryResolver(api)

    metadata = resolver.get_attribute_metadata("MLB123")

    assert len(metadata) == 1
    assert metadata[0].id == "BRAND"
    assert metadata[0].relevance == 0.9
    assert metadata[0].hierarchy == "parent"
    assert "catalog_listing_required" in metadata[0].tags
