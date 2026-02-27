"""Publish flow tests for variations behavior."""

from __future__ import annotations

from typing import Any

from mercadolivre_upload.application.publish_product import PublishProductUseCase
from mercadolivre_upload.domain.attribute_metadata import AttributeMeta
from mercadolivre_upload.domain.cache_attribute_mapper import CachedAttributeMapper
from mercadolivre_upload.domain.product.model import Product
from tests.support.upload_alignment import (
    _build_product,
    _FakeCategoryResolver,
    _FakeImageUploader,
    _FakePublisher,
    _FixedShippingResolver,
    _StaticAttributeCache,
)


def test_publish_builds_variations_from_marked_candidates() -> None:
    resolver = _FakeCategoryResolver(
        [
            AttributeMeta(id="BRAND", name="Marca", value_type="string", required=False),
            AttributeMeta(id="COLOR", name="Cor", value_type="string", required=False),
        ]
    )
    publisher = _FakePublisher(
        listing_types=[{"id": "gold_pro"}, {"id": "gold_special"}],
        sale_terms=[],
    )
    use_case = PublishProductUseCase(
        category_resolver=resolver,  # type: ignore[arg-type]
        publisher=publisher,  # type: ignore[arg-type]
        image_uploader=_FakeImageUploader(),  # type: ignore[arg-type]
        shipping_resolver=_FixedShippingResolver("me2"),  # type: ignore[arg-type]
        fiscal_service=None,
        clip_uploader=None,
        config={
            "core_item_fields": {
                "defaults": {
                    "currency_id": "BRL",
                    "buying_mode": "buy_it_now",
                    "listing_type_id": "gold_special",
                    "sale_terms": [],
                }
            },
            "shipping": {
                "default_mode": "me2",
                "modes": {
                    "me2": {
                        "local_pick_up": False,
                        "logistic_type": "drop_off",
                        "methods": [],
                        "tags": [],
                        "dimensions": None,
                        "free_shipping": False,
                        "store_pick_up": False,
                    }
                },
            },
        },
        dry_run=False,
        min_attribute_score=0,
        enable_feedback=False,
        enable_fiscal_submission=False,
    )

    class _VariationMarkerBuilder:
        def build_attributes(
            self,
            product: Product,
            category_id: str,
            *,
            drop_invalid_domain_values: bool = True,
        ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str], list[str]]:
            del drop_invalid_domain_values
            return (
                [
                    {"id": "BRAND", "value_name": "Marca X"},
                    {"id": "COLOR", "value_name": "Azul"},
                    {"id": "GTIN", "value_name": "1234567890123"},
                    {
                        "_variation_candidates": {
                            "COLOR": [
                                {"id": "1", "name": "Azul"},
                                {"id": "2", "name": "Verde"},
                            ]
                        }
                    },
                    {"_listing_type_id": "gold_pro"},
                ],
                [],
                [],
                [],
            )

        def set_cache_mapper(self, cache_mapper: Any) -> None:  # pragma: no cover - compat hook
            del cache_mapper

    use_case._attribute_builder = _VariationMarkerBuilder()  # type: ignore[assignment]

    assert use_case._publish_one(_build_product({}), "MLB123") is True
    created_item = publisher.created_items[0]
    assert created_item["listing_type_id"] == "gold_pro"
    assert len(created_item["variations"]) == 2
    assert all(
        variation["attribute_combinations"][0]["id"] == "COLOR"
        for variation in created_item["variations"]
    )
    assert all("picture_ids" in variation for variation in created_item["variations"])
    assert all(attr["id"] != "COLOR" for attr in created_item["attributes"])


def test_publish_builds_variations_from_varia_por_cache_hint() -> None:
    resolver = _FakeCategoryResolver(
        [
            AttributeMeta(id="COLOR", name="Cor", value_type="string", required=False),
        ]
    )
    publisher = _FakePublisher(listing_types=[{"id": "gold_special"}], sale_terms=[])
    use_case = PublishProductUseCase(
        category_resolver=resolver,  # type: ignore[arg-type]
        publisher=publisher,  # type: ignore[arg-type]
        image_uploader=_FakeImageUploader(),  # type: ignore[arg-type]
        shipping_resolver=_FixedShippingResolver("me2"),  # type: ignore[arg-type]
        fiscal_service=None,
        clip_uploader=None,
        config={
            "core_item_fields": {
                "defaults": {
                    "currency_id": "BRL",
                    "buying_mode": "buy_it_now",
                    "listing_type_id": "gold_special",
                    "sale_terms": [],
                }
            },
            "shipping": {
                "default_mode": "me2",
                "modes": {
                    "me2": {
                        "local_pick_up": False,
                        "logistic_type": "drop_off",
                        "methods": [],
                        "tags": [],
                        "dimensions": None,
                        "free_shipping": False,
                        "store_pick_up": False,
                    }
                },
            },
        },
        dry_run=False,
        min_attribute_score=0,
        enable_feedback=False,
        enable_fiscal_submission=False,
    )

    cache_mapper = CachedAttributeMapper(
        _StaticAttributeCache(
            [
                {
                    "id": "COLOR",
                    "name": "Cor",
                    "value_type": "string",
                    "values": [
                        {"id": "1", "name": "Azul"},
                        {"id": "2", "name": "Verde"},
                    ],
                }
            ]
        ),
        "MLB123",
    )
    use_case._attribute_builder.set_cache_mapper(cache_mapper)  # type: ignore[attr-defined]

    assert use_case._publish_one(_build_product({"Varia por: Cor": "Azul, Verde"}), "MLB123")
    created_item = publisher.created_items[0]
    assert [v["attribute_combinations"][0]["value_name"] for v in created_item["variations"]] == [
        "Azul",
        "Verde",
    ]
    assert all(attr["id"] != "COLOR" for attr in created_item["attributes"])


def test_publish_legacy_variations_prefer_contract_allow_variations_ids() -> None:
    resolver = _FakeCategoryResolver(
        [
            AttributeMeta(id="COLOR", name="Cor", value_type="string", required=False),
            AttributeMeta(id="SIZE", name="Tamanho", value_type="string", required=False),
        ],
        all_attributes=[
            {"id": "COLOR", "tags": {}},
            {"id": "SIZE", "tags": {"allow_variations": True}},
        ],
    )
    publisher = _FakePublisher(listing_types=[{"id": "gold_special"}], sale_terms=[])
    use_case = PublishProductUseCase(
        category_resolver=resolver,  # type: ignore[arg-type]
        publisher=publisher,  # type: ignore[arg-type]
        image_uploader=_FakeImageUploader(),  # type: ignore[arg-type]
        shipping_resolver=_FixedShippingResolver("me2"),  # type: ignore[arg-type]
        fiscal_service=None,
        clip_uploader=None,
        config={
            "core_item_fields": {
                "defaults": {
                    "currency_id": "BRL",
                    "buying_mode": "buy_it_now",
                    "listing_type_id": "gold_special",
                    "sale_terms": [],
                }
            },
            "shipping": {
                "default_mode": "me2",
                "modes": {
                    "me2": {
                        "local_pick_up": False,
                        "logistic_type": "drop_off",
                        "methods": [],
                        "tags": [],
                        "dimensions": None,
                        "free_shipping": False,
                        "store_pick_up": False,
                    }
                },
            },
        },
        dry_run=False,
        min_attribute_score=0,
        enable_feedback=False,
        enable_fiscal_submission=False,
    )

    class _VariationMarkerBuilder:
        def build_attributes(
            self,
            product: Product,
            category_id: str,
            *,
            drop_invalid_domain_values: bool = True,
        ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str], list[str]]:
            del product, category_id, drop_invalid_domain_values
            return (
                [
                    {"id": "COLOR", "value_name": "Azul"},
                    {"id": "SIZE", "value_name": "M"},
                    {
                        "_variation_candidates": {
                            "COLOR": [
                                {"id": "1", "name": "Azul"},
                                {"id": "2", "name": "Verde"},
                            ]
                        }
                    },
                    {
                        "_variation_candidates": {
                            "SIZE": [
                                {"id": "10", "name": "M"},
                                {"id": "11", "name": "G"},
                            ]
                        }
                    },
                ],
                [],
                [],
                [],
            )

        def set_cache_mapper(self, cache_mapper: Any) -> None:  # pragma: no cover - compat hook
            del cache_mapper

    use_case._attribute_builder = _VariationMarkerBuilder()  # type: ignore[assignment]

    assert use_case._publish_one(_build_product({}), "MLB123")
    created_item = publisher.created_items[0]
    assert len(created_item["variations"]) == 2
    assert all(
        [attr["id"] for attr in variation["attribute_combinations"]] == ["SIZE"]
        for variation in created_item["variations"]
    )
    assert any(attr["id"] == "COLOR" for attr in created_item["attributes"])
    assert all(attr["id"] != "SIZE" for attr in created_item["attributes"])


def test_publish_legacy_variations_apply_limits_picture_cap_and_seller_sku() -> None:
    resolver = _FakeCategoryResolver(
        [
            AttributeMeta(id="COLOR", name="Cor", value_type="string", required=False),
        ],
        all_attributes=[{"id": "COLOR", "tags": {"allow_variations": True}}],
        settings={"max_variations_allowed": 2, "max_pictures_per_item": 1},
    )
    publisher = _FakePublisher(listing_types=[{"id": "gold_special"}], sale_terms=[])
    use_case = PublishProductUseCase(
        category_resolver=resolver,  # type: ignore[arg-type]
        publisher=publisher,  # type: ignore[arg-type]
        image_uploader=_FakeImageUploader(),  # type: ignore[arg-type]
        shipping_resolver=_FixedShippingResolver("me2"),  # type: ignore[arg-type]
        fiscal_service=None,
        clip_uploader=None,
        config={
            "core_item_fields": {
                "defaults": {
                    "currency_id": "BRL",
                    "buying_mode": "buy_it_now",
                    "listing_type_id": "gold_special",
                    "sale_terms": [],
                }
            }
        },
        dry_run=False,
        min_attribute_score=0,
        enable_feedback=False,
        enable_fiscal_submission=False,
    )

    use_case._current_publish_category_id = "MLB123"
    use_case._current_publish_sku = "SKU-1"
    use_case._current_variation_reference_attributes = [{"id": "COLOR", "value_name": "Azul"}]

    variations = use_case._build_variations_from_candidates(
        variation_candidates={
            "COLOR": [
                {"id": "2", "name": "Verde"},
                {"id": "1", "name": "Azul"},
                {"id": "3", "name": "Preto"},
            ]
        },
        quantity=1,
        price=10.0,
        picture_ids=["PIC-1", "PIC-2", "PIC-3"],
    )

    assert len(variations) == 2
    assert variations[0]["attribute_combinations"][0]["value_name"] == "Azul"
    assert all(variation["picture_ids"] == ["PIC-1"] for variation in variations)
    assert [variation["attributes"][0]["value_name"] for variation in variations] == [
        "SKU-1-001",
        "SKU-1-002",
    ]
