"""Tests for API-level CategoryResolver."""

from __future__ import annotations

from typing import Any

from mercadolivre_upload.api.category_resolver import CategoryResolver


class _FakeClient:
    def __init__(self) -> None:
        self.site_calls = 0
        self.category_calls: dict[str, int] = {}
        self.attribute_calls: dict[str, int] = {}

    def get_site_categories(self, _site_id: str) -> list[dict[str, str]]:
        self.site_calls += 1
        return [
            {"id": "MLB1", "name": "Livros"},
            {"id": "MLB2", "name": "Eletronicos"},
        ]

    def get_category(self, category_id: str) -> dict[str, Any]:
        self.category_calls[category_id] = self.category_calls.get(category_id, 0) + 1
        if category_id == "ERR":
            raise RuntimeError("boom")
        if category_id == "MLB1":
            return {"children_categories": [{"id": "MLB11", "name": "Livros Fisicos"}]}
        if category_id == "MLB11":
            return {"children_categories": [{"id": "MLB111", "name": "Romance"}]}
        return {"children_categories": []}

    def get_category_attributes(self, category_id: str) -> list[dict[str, Any]]:
        self.attribute_calls[category_id] = self.attribute_calls.get(category_id, 0) + 1
        return [
            {"id": "BOOK_TITLE", "name": "Title", "allowed_units": [{"id": "u"}]},
            {"id": "AUTHOR", "name": "Author", "tags": {"required": True}},
            {"id": "PAGES", "name": "Pages", "tags": {"required": False}},
        ]


def test_find_category_exact_partial_and_hierarchy() -> None:
    resolver = CategoryResolver(_FakeClient())

    assert resolver.find_category("Livros") == "MLB1"
    assert resolver.find_category("Livro") == "MLB1"
    assert resolver.find_category("Romance") == "MLB111"


def test_get_category_helpers_and_caching() -> None:
    client = _FakeClient()
    resolver = CategoryResolver(client)

    resolver.find_category("Livros")

    data_first = resolver.get_category_data("MLB1")
    data_second = resolver.get_category_data("MLB1")
    assert data_first == data_second
    assert client.category_calls["MLB1"] == 1

    mandatory = resolver.get_mandatory_attributes("MLB11")
    assert len(mandatory) == 1
    assert mandatory[0]["id"] == "AUTHOR"

    attr_map = resolver.build_attribute_map("MLB11")
    assert "title" in attr_map
    assert "book title" in attr_map
    assert attr_map["book title"]["id"] == "BOOK_TITLE"


def test_get_category_children_handles_client_error() -> None:
    resolver = CategoryResolver(_FakeClient())
    children = resolver._get_category_children("ERR")
    assert children == []
