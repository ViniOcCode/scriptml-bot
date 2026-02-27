"""Tests for category adapter error handling."""

from unittest.mock import MagicMock

import pytest
import requests

from mercadolivre_upload.api.category_adapter import CategoryAdapter
from mercadolivre_upload.domain.category.errors import CategoryApiUnavailableError


def test_get_site_categories_raises_on_http_error() -> None:
    client = MagicMock()
    client.get_site_categories.side_effect = requests.HTTPError("boom")
    adapter = CategoryAdapter(client)  # type: ignore[arg-type]

    with pytest.raises(CategoryApiUnavailableError):
        adapter.get_site_categories("MLB")


def test_get_category_raises_for_invalid_payload_type() -> None:
    client = MagicMock()
    client.get_category.return_value = "invalid"
    adapter = CategoryAdapter(client)  # type: ignore[arg-type]

    with pytest.raises(CategoryApiUnavailableError):
        adapter.get_category("MLB123")


def test_get_category_conditionals_accepts_required_attributes_dict() -> None:
    client = MagicMock()
    client.get_category_conditional_attributes.return_value = {
        "required_attributes": [{"id": "BRAND"}]
    }
    adapter = CategoryAdapter(client)  # type: ignore[arg-type]

    result = adapter.get_category_conditional_attributes("MLB123", {"title": "x"})
    assert result == [{"id": "BRAND"}]


def test_get_category_conditionals_rejects_non_list_required_attributes() -> None:
    client = MagicMock()
    client.get_category_conditional_attributes.return_value = {"required_attributes": "invalid"}
    adapter = CategoryAdapter(client)  # type: ignore[arg-type]

    result = adapter.get_category_conditional_attributes("MLB123", {"title": "x"})
    assert result == []


def test_validate_item_returns_invalid_payload_on_recoverable_error() -> None:
    client = MagicMock()
    client.validate_item.side_effect = ValueError("invalid payload")
    adapter = CategoryAdapter(client)  # type: ignore[arg-type]

    result = adapter.validate_item({"title": "x"})
    assert result["valid"] is False
    assert "invalid payload" in result["error"]
