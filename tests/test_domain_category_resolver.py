"""Tests for domain category resolver edge cases and caches."""

from __future__ import annotations

from typing import Any

from mercadolivre_upload.domain.category.resolver import CategoryResolver


class _FakeApi:
    def __init__(self) -> None:
        self.predict_calls = 0
        self.raise_predict = False
        self.raise_conditional = False
        self.raise_tech_specs = False
        self.predictions: list[dict[str, Any]] = []
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
        _ = limit
        if self.raise_predict:
            raise RuntimeError("predict error")
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
    cache.data[("MLB", "Produto Teste")] = [{"category_id": "MLB123", "category_name": "Teste"}]
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


def test_call_domain_discovery_returns_empty_on_exception() -> None:
    api = _FakeApi()
    api.raise_predict = True
    resolver = CategoryResolver(api)

    assert resolver._call_domain_discovery("Notebook Gamer", "MLB") == []


def test_get_category_cached_returns_empty_on_exception() -> None:
    api = _FakeApi()
    api.categories["ERR"] = RuntimeError("boom")

    def _raise_on_err(category_id: str) -> dict[str, Any]:
        if category_id == "ERR":
            raise RuntimeError("boom")
        return {"children_categories": []}

    api.get_category = _raise_on_err  # type: ignore[assignment]
    resolver = CategoryResolver(api)

    assert resolver._get_category_cached("ERR") == {}


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


def test_resolve_to_leaf_selects_most_populated_child() -> None:
    api = _FakeApi()
    api.categories["MLB1"] = {
        "children_categories": [
            {"id": "MLB11", "name": "Child A", "total_items_in_this_category": 2},
            {"id": "MLB12", "name": "Child B", "total_items_in_this_category": 8},
        ]
    }
    api.categories["MLB12"] = {"children_categories": []}
    resolver = CategoryResolver(api)

    assert resolver.resolve_to_leaf("MLB1") == "MLB12"


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
