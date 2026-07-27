from __future__ import annotations

import pytest

from mercadolivre_upload.application.user_product_contract import (
    expand_effective_payloads,
)


def test_envelope_expands_items_and_removes_local_fields() -> None:
    expanded = expand_effective_payloads(
        {
            "family_name": "Linha Alpha",
            "description": "local only",
            "fiscal": {"items": []},
            "_meta": {"sku": "local"},
            "items": [
                {
                    "category_id": "MLB123",
                    "listing_type_id": "gold_special",
                    "attributes": [{"id": "SELLER_SKU", "value_name": "SKU-1"}],
                    "description_by_sku": {"SKU-1": "local only"},
                },
                {
                    "category_id": "MLB123",
                    "listing_type_id": "gold_special",
                    "attributes": [{"id": "SELLER_SKU", "value_name": "SKU-2"}],
                    "_meta": {"sku": "local"},
                },
            ],
        },
        "user_products",
    )

    assert [item["family_name"] for item in expanded] == [
        "Linha Alpha",
        "Linha Alpha",
    ]
    assert [item["attributes"][0]["value_name"] for item in expanded] == [
        "SKU-1",
        "SKU-2",
    ]
    assert all(
        local_field not in item
        for item in expanded
        for local_field in (
            "_meta",
            "description",
            "description_by_sku",
            "fiscal",
            "items",
            "payload",
        )
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"family_name": "Linha Alpha", "items": []},
        {"family_name": "Linha Alpha", "items": ["not-an-object"]},
    ],
)
def test_malformed_user_product_items_fail_instead_of_being_skipped(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValueError, match="user_products"):
        expand_effective_payloads(payload, "user_products")


def test_item_cannot_override_envelope_family_identity() -> None:
    with pytest.raises(ValueError, match="family_name conflicts"):
        expand_effective_payloads(
            {
                "family_name": "Linha Alpha",
                "items": [{"family_name": "Linha Beta", "category_id": "MLB123"}],
            },
            "user_products",
        )


def test_payload_array_preserves_each_family_and_sku_scope() -> None:
    expanded = expand_effective_payloads(
        {
            "payload": [
                {
                    "family_name": "Linha Alpha",
                    "listing_type_id": "gold_special",
                    "attributes": [{"id": "SELLER_SKU", "value_name": "SKU-A"}],
                },
                {
                    "family_name": "Linha Beta",
                    "listing_type_id": "gold_pro",
                    "attributes": [{"id": "SELLER_SKU", "value_name": "SKU-B"}],
                },
            ]
        },
        "user_products",
    )

    assert [
        (
            item["family_name"],
            item["listing_type_id"],
            item["attributes"][0]["value_name"],
        )
        for item in expanded
    ] == [
        ("Linha Alpha", "gold_special", "SKU-A"),
        ("Linha Beta", "gold_pro", "SKU-B"),
    ]
