"""Tests for spreadsheet adapter helpers kept outside legacy callbacks."""

from unittest.mock import MagicMock

from mercadolivre_upload.cli.commands.spreadsheet_inputs import (
    build_row_category_metadata,
    extract_row_identity,
    prime_category_resolution_context,
)


def test_extract_row_identity_uses_first_non_empty_supported_values() -> None:
    sku, title = extract_row_identity(
        {"sku": "  ", "código": " SKU-001 ", "title": "  Produto A  "}
    )

    assert sku == "SKU-001"
    assert title == "Produto A"


def test_row_category_metadata_normalizes_header_and_comparison() -> None:
    metadata = build_row_category_metadata(
        {"my category": " mlb123 "},
        "MLB123",
    )

    assert metadata == {
        "row_category_detected": "mlb123",
        "row_category_mismatch": False,
    }


def test_prime_category_resolution_context_uses_non_cached_resolution() -> None:
    resolver = MagicMock()
    use_case = MagicMock(_resolve_category_context=resolver)
    products = [{"sku": "SKU-001"}]

    prime_category_resolution_context(use_case, products, "MLB123")

    resolver.assert_called_once_with(products, "MLB123", use_cache=False)


def test_prime_category_resolution_context_falls_back_for_older_resolvers() -> None:
    resolver = MagicMock(side_effect=[TypeError("legacy signature"), None])
    use_case = MagicMock(_resolve_category_context=resolver)
    products = [{"sku": "SKU-001"}]

    prime_category_resolution_context(use_case, products, "MLB123")

    assert resolver.call_args_list[0].args == (products, "MLB123")
    assert resolver.call_args_list[0].kwargs == {"use_cache": False}
    assert resolver.call_args_list[1].args == (products, "MLB123")
    assert resolver.call_args_list[1].kwargs == {}
