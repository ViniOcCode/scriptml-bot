"""Tests for policy snapshot/schema contract compilation."""

from mercadolivre_upload.application.policy_snapshot import (
    compile_policy_snapshot,
    compile_schema_contract,
)


def test_compile_policy_snapshot_is_deterministic_across_input_order() -> None:
    first = compile_policy_snapshot(
        category_id="MLB1234",
        category_data={"status": "enabled", "settings": {"listing_allowed": True}},
        attributes=[
            {"id": "MODEL", "tags": {"allow_variations": True}},
            {"id": "BRAND", "tags": {"required": True}},
        ],
        listing_types=[{"id": "gold_special"}, {"id": "free"}, {"id": "gold_special"}],
        sale_terms=[
            {"id": "WARRANTY_TYPE", "tags": {"required": True}},
            {"id": "WARRANTY_TIME", "tags": ["new_required"]},
        ],
    )
    second = compile_policy_snapshot(
        category_id="MLB1234",
        category_data={"settings": {"listing_allowed": True}, "status": "enabled"},
        attributes=[
            {"id": "BRAND", "tags": {"required": True}},
            {"id": "MODEL", "tags": {"allow_variations": True}},
        ],
        listing_types=[{"id": "free"}, {"id": "gold_special"}],
        sale_terms=[
            {"id": "WARRANTY_TIME", "tags": ["new_required"]},
            {"id": "WARRANTY_TYPE", "tags": {"required": True}},
        ],
    )

    assert first["policy_hash"] == second["policy_hash"]
    assert first["policy_snapshot"] == second["policy_snapshot"]


def test_compile_policy_snapshot_exposes_compact_summary() -> None:
    compiled = compile_policy_snapshot(
        category_id="MLB999",
        category_data={
            "status": "enabled",
            "settings": {"status": "enabled", "listing_allowed": False},
        },
        attributes=[
            {"id": "GTIN", "tags": {"catalog_listing_required": True}},
            {"id": "BRAND", "tags": {"required": True}},
        ],
        listing_types=["free", "gold_special"],
        sale_terms=[{"id": "WARRANTY_TYPE", "tags": {"required": True}}],
    )

    summary = compiled["policy_summary"]
    assert summary["category_id"] == "MLB999"
    assert summary["listing_allowed"] is False
    assert summary["attribute_count"] == 2
    assert summary["attribute_tag_summary"]["required"] == 1
    assert summary["attribute_tag_summary"]["catalog_listing_required"] == 1
    assert summary["listing_types"] == ["free", "gold_special"]
    assert summary["required_sale_term_count"] == 1


def test_compile_schema_contract_extracts_required_tags_sale_terms_and_limits() -> None:
    compiled = compile_schema_contract(
        category_id="MLB1234",
        category_data={
            "settings": {
                "max_pictures_per_item": 6,
                "max_variations_allowed": "2",
            }
        },
        attributes=[
            {"id": "BRAND", "tags": {"required": True}},
            {"id": "MODEL", "tags": {"new_required": True}},
            {"id": "GTIN", "tags": {"catalog_listing_required": True}},
            {
                "id": "EMPTY_GTIN_REASON",
                "tags": {},
                "values": [{"id": "17055158", "name": "Outro motivo"}],
            },
            {"id": "SIZE", "tags": {"conditional_required": True}},
            {"id": "COLOR", "tags": {"allow_variations": True}},
        ],
        sale_terms=[
            {"id": "WARRANTY_TYPE", "tags": {"required": True}},
            {"id": "WARRANTY_TIME", "tags": []},
        ],
    )

    contract = compiled["schema_contract"]
    assert contract["attribute_ids_by_tag"]["required"] == ["BRAND"]
    assert contract["attribute_ids_by_tag"]["new_required"] == ["MODEL"]
    assert contract["attribute_ids_by_tag"]["catalog_listing_required"] == ["GTIN"]
    assert contract["attribute_ids_by_tag"]["conditional_required"] == ["SIZE"]
    assert contract["allow_variations_attribute_ids"] == ["COLOR"]
    assert contract["required_attribute_ids"] == ["BRAND", "GTIN", "MODEL", "SIZE"]
    assert contract["sale_terms"]["required_ids"] == ["WARRANTY_TYPE"]
    assert contract["sale_terms"]["optional_ids"] == ["WARRANTY_TIME"]
    assert contract["limits"] == {"max_pictures": 6, "max_variations_allowed": 2}
    assert contract["identifier_contract"]["gtin_required"] is True
    assert contract["identifier_contract"]["gtin_attribute_id"] == "GTIN"
    assert contract["identifier_contract"]["empty_gtin_reason_attribute_id"] == "EMPTY_GTIN_REASON"
    assert contract["identifier_contract"]["empty_gtin_reason_allowed_value_ids"] == ["17055158"]
    assert contract["identifier_contract"]["empty_gtin_reason_allowed_value_names"] == [
        "Outro motivo"
    ]

    summary = compiled["schema_contract_summary"]
    assert summary["required_attribute_count"] == 4
    assert summary["allow_variations_attribute_count"] == 1
    assert summary["required_sale_term_count"] == 1
    assert summary["max_pictures"] == 6
    assert summary["max_variations_allowed"] == 2
    assert summary["gtin_required"] is True
    assert summary["empty_gtin_reason_allowed_value_count"] == 1
