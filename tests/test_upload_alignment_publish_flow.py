"""Publish-flow-heavy tests split from upload alignment suite."""

from __future__ import annotations

from typing import Any

import pytest

from mercadolivre_upload.application.attribute_builder import AttributeBuilderService
from mercadolivre_upload.application.publish_product import PublishProductUseCase
from mercadolivre_upload.domain.attribute_metadata import AttributeMeta
from mercadolivre_upload.domain.cache_attribute_mapper import CachedAttributeMapper
from mercadolivre_upload.domain.product.model import Product
from tests.test_upload_alignment import (
    _build_product,
    _FakeCategoryResolver,
    _FakeImageUploader,
    _FakePublisher,
    _FixedShippingResolver,
    _StaticAttributeCache,
)


def test_publish_attribute_normalization_uses_attribute_id_for_weights() -> None:
    use_case = object.__new__(PublishProductUseCase)
    use_case.config = {}

    item = {
        "attributes": [
            {"id": "WEIGHT", "value_name": "0,220"},
            {"id": "WIDTH", "value_name": "23"},
            {"id": "SELLER_PACKAGE_WEIGHT", "value_name": "214"},
        ]
    }

    PublishProductUseCase._normalize_item_attributes(use_case, item)

    values = {a["id"]: a["value_name"] for a in item["attributes"]}
    assert values["WEIGHT"] == "0.220 kg"
    assert values["WIDTH"] == "23 cm"
    assert values["SELLER_PACKAGE_WEIGHT"] == "214 g"


def test_publish_attribute_normalization_skips_non_dict_attributes() -> None:
    use_case = object.__new__(PublishProductUseCase)
    use_case.config = {}

    item = {
        "attributes": [
            {"id": "WIDTH", "value_name": "23"},
            "invalid-attribute",
            None,
        ]
    }

    PublishProductUseCase._normalize_item_attributes(use_case, item)

    assert item["attributes"][0]["value_name"] == "23 cm"
    assert item["attributes"][1] == "invalid-attribute"
    assert item["attributes"][2] is None


def test_publish_flow_uses_available_listing_type_and_description_endpoint() -> None:
    resolver = _FakeCategoryResolver(
        [
            AttributeMeta(id="BRAND", name="Marca", value_type="string", required=False),
        ]
    )
    publisher = _FakePublisher(
        listing_types=[{"id": "gold_special"}, {"id": "free"}],
        sale_terms=[{"id": "WARRANTY_TYPE", "tags": {"required": True}}],
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
                    "listing_type_id": "gold_pro",
                    "channels": ["marketplace"],
                    "item_condition": {
                        "id": "ITEM_CONDITION",
                        "values": {
                            "new": {
                                "value_id": "2230284",
                                "value_name": "Novo",
                            }
                        },
                    },
                    "sale_terms": [
                        {"id": "WARRANTY_TYPE", "value_name": "Garantia do vendedor"},
                        {"id": "UNSUPPORTED_TERM", "value_name": "x"},
                    ],
                }
            },
            "shipping": {
                "default_mode": "not_specified",
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

    product = _build_product({})
    assert use_case._publish_one(product, "MLB123")

    assert publisher.validated_items
    assert publisher.created_items
    created_item = publisher.created_items[0]
    assert created_item["listing_type_id"] == "gold_special"
    assert created_item["sale_terms"] == [
        {"id": "WARRANTY_TYPE", "value_name": "Garantia do vendedor"}
    ]
    assert "description" not in created_item
    assert "description" not in publisher.validated_items[0]
    assert publisher.description_calls == [("MLB1234567890", "Desc")]

    assert resolver.last_conditional_payload is not None
    assert resolver.last_conditional_payload["description"] == {"plain_text": "Desc"}


def test_publish_listing_type_fallback_uses_site_listing_types() -> None:
    resolver = _FakeCategoryResolver(
        [
            AttributeMeta(id="BRAND", name="Marca", value_type="string", required=False),
        ]
    )
    publisher = _FakePublisher(
        listing_types=[],
        sale_terms=[],
        site_listing_types=[{"id": "free"}],
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

    assert use_case._publish_one(_build_product({}), "MLB123") is True
    created_item = publisher.created_items[0]
    assert created_item["listing_type_id"] == "free"


def test_publish_sale_terms_complete_required_ids_with_default_fallback() -> None:
    resolver = _FakeCategoryResolver(
        [
            AttributeMeta(id="BRAND", name="Marca", value_type="string", required=False),
        ]
    )
    publisher = _FakePublisher(
        listing_types=[{"id": "gold_special"}],
        sale_terms=[
            {"id": "WARRANTY_TYPE", "tags": {"required": True}},
            {"id": "WARRANTY_TIME", "tags": {}},
        ],
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
                    "sale_terms": [{"id": "WARRANTY_TYPE", "value_name": "Garantia do vendedor"}],
                }
            },
        },
        dry_run=False,
        min_attribute_score=0,
        enable_feedback=False,
        enable_fiscal_submission=False,
    )

    class _DynamicSaleTermsBuilder:
        def build_attributes(
            self,
            product: Product,
            category_id: str,
        ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str], list[str]]:
            del product, category_id
            return (
                [{"id": "BRAND", "value_name": "Marca X"}],
                [{"id": "WARRANTY_TIME", "value_name": "90 dias"}],
                [],
                [],
            )

        def set_cache_mapper(self, cache_mapper: Any) -> None:  # pragma: no cover - compat hook
            del cache_mapper

    use_case._attribute_builder = _DynamicSaleTermsBuilder()  # type: ignore[assignment]

    assert use_case._publish_one(_build_product({}), "MLB123") is True
    created_item = publisher.created_items[0]
    sale_terms_by_id = {sale_term["id"]: sale_term for sale_term in created_item["sale_terms"]}
    assert sale_terms_by_id["WARRANTY_TIME"]["value_name"] == "90 dias"
    assert sale_terms_by_id["WARRANTY_TYPE"]["value_name"] == "Garantia do vendedor"


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
        ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str], list[str]]:
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
        ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str], list[str]]:
            del product, category_id
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


def test_publish_blocks_on_critical_validation_warning_by_default() -> None:
    resolver = _FakeCategoryResolver(
        [
            AttributeMeta(id="BRAND", name="Marca", value_type="string", required=False),
        ]
    )

    class _CriticalWarningPublisher(_FakePublisher):
        def validate_item(self, item: dict[str, Any]) -> dict[str, Any]:
            self.validated_items.append(item)
            return {
                "cause": [
                    {
                        "type": "warning",
                        "code": "item.attributes.omitted",
                        "message": (
                            "Attribute WIDTH with value cm was omitted. "
                            "You can use a number followed by unit."
                        ),
                    }
                ]
            }

    publisher = _CriticalWarningPublisher(
        listing_types=[{"id": "gold_special"}],
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

    assert use_case._publish_one(_build_product({}), "MLB123") is False
    assert publisher.created_items == []
    assert use_case.failed == 1
    assert any("critical validation warnings" in error for error in use_case.errors)
    assert use_case._current_cause_taxonomy[0]["classification"] == "critical_warning"
    assert use_case._current_validation_decision["action"] == "block"
    assert use_case._current_validation_decision["mode"] == "strict"


def test_publish_allows_critical_warning_when_strict_gate_disabled() -> None:
    resolver = _FakeCategoryResolver(
        [
            AttributeMeta(id="BRAND", name="Marca", value_type="string", required=False),
        ]
    )

    class _CriticalWarningPublisher(_FakePublisher):
        def validate_item(self, item: dict[str, Any]) -> dict[str, Any]:
            self.validated_items.append(item)
            return {
                "cause": [
                    {
                        "type": "warning",
                        "code": "item.attributes.omitted",
                        "message": "Attribute WIDTH with value cm was omitted.",
                    }
                ]
            }

    publisher = _CriticalWarningPublisher(
        listing_types=[{"id": "gold_special"}],
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
            "strict_attribute_warnings": False,
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

    assert use_case._publish_one(_build_product({}), "MLB123") is True
    assert len(publisher.created_items) == 1
    assert use_case._current_cause_taxonomy[0]["classification"] == "critical_warning"
    assert use_case._current_validation_decision["action"] == "allow"


def test_publish_allows_critical_warning_in_controlled_mode() -> None:
    resolver = _FakeCategoryResolver(
        [
            AttributeMeta(id="BRAND", name="Marca", value_type="string", required=False),
        ]
    )

    class _CriticalWarningPublisher(_FakePublisher):
        def validate_item(self, item: dict[str, Any]) -> dict[str, Any]:
            self.validated_items.append(item)
            return {
                "cause": [
                    {
                        "type": "warning",
                        "code": "item.attributes.omitted",
                        "message": "Attribute WIDTH with value cm was omitted.",
                    }
                ]
            }

    publisher = _CriticalWarningPublisher(
        listing_types=[{"id": "gold_special"}],
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
            "validation_decision_mode": "controlled",
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

    assert use_case._publish_one(_build_product({}), "MLB123") is True
    assert len(publisher.created_items) == 1
    assert use_case._current_cause_taxonomy[0]["classification"] == "critical_warning"
    assert use_case._current_validation_decision["action"] == "allow"
    assert use_case._current_validation_decision["mode"] == "controlled"


def test_auto_na_policy_fills_optional_and_skips_non_eligible(caplog) -> None:  # type: ignore[no-untyped-def]
    resolver = _FakeCategoryResolver(
        metadata=[
            AttributeMeta(id="BRAND", name="Marca", value_type="string", required=False),
            AttributeMeta(id="COLOR", name="Cor", value_type="string", required=False),
            AttributeMeta(id="ISBN", name="ISBN", value_type="string", required=True),
            AttributeMeta(
                id="MODEL",
                name="Modelo",
                value_type="string",
                required=False,
                tags={"allow_variations"},
            ),
            AttributeMeta(
                id="GTIN",
                name="GTIN",
                value_type="string",
                required=False,
                tags={"catalog_listing_required"},
            ),
            AttributeMeta(
                id="SELLER_SKU",
                name="SKU vendedor",
                value_type="string",
                required=False,
                tags={"variation_attribute"},
            ),
            AttributeMeta(id="SIZE", name="Tamanho", value_type="string", required=False),
        ],
        conditional_attrs=[{"id": "SIZE"}],
    )

    use_case = object.__new__(PublishProductUseCase)
    use_case.config = {
        "na_policy": {
            "enabled": True,
            "value_id": "-1",
            "value_name": None,
            "skip_tags": [
                "required",
                "new_required",
                "conditional_required",
                "catalog_listing_required",
                "allow_variations",
            ],
        }
    }
    use_case.category_resolver = resolver

    item = {"attributes": [{"id": "BRAND", "value_name": "Marca X"}]}
    with caplog.at_level("WARNING"):
        conditional_required_ids = PublishProductUseCase._inject_optional_na_attributes(
            use_case,
            category_id="MLB123",
            item=item,
            sku="SKU-1",
            description="Desc",
        )

    attrs_by_id = {attr["id"]: attr for attr in item["attributes"]}
    assert conditional_required_ids == {"SIZE"}
    assert attrs_by_id["COLOR"] == {"id": "COLOR", "value_id": "-1", "value_name": None}
    assert "MODEL" not in attrs_by_id
    assert "GTIN" not in attrs_by_id
    assert "SELLER_SKU" not in attrs_by_id
    assert "SIZE" not in attrs_by_id
    assert "ISBN" not in attrs_by_id
    assert resolver.last_conditional_payload is not None
    assert resolver.last_conditional_payload["description"] == {"plain_text": "Desc"}
    assert any("Skipped N/A auto-fill" in message for message in caplog.messages)


def test_auto_na_policy_skips_non_fillable_tags() -> None:
    resolver = _FakeCategoryResolver(
        metadata=[
            AttributeMeta(id="VISIBLE", name="Visível", value_type="string", required=False),
            AttributeMeta(
                id="HIDDEN_ATTR",
                name="Oculto",
                value_type="string",
                required=False,
                tags={"hidden"},
            ),
            AttributeMeta(
                id="READ_ONLY_ATTR",
                name="Somente leitura",
                value_type="string",
                required=False,
                tags={"read-only"},
            ),
            AttributeMeta(
                id="LOCKED_ATTR",
                name="Bloqueado",
                value_type="string",
                required=False,
                tags={"non-modifiable"},
            ),
            AttributeMeta(
                id="COND_VISIBLE",
                name="Condicional",
                value_type="string",
                required=False,
            ),
            AttributeMeta(
                id="COND_HIDDEN",
                name="Condicional oculto",
                value_type="string",
                required=False,
                tags={"hidden"},
            ),
        ],
        conditional_attrs=[{"id": "COND_VISIBLE"}, {"id": "COND_HIDDEN"}],
    )

    use_case = object.__new__(PublishProductUseCase)
    use_case.config = {"na_policy": {"enabled": True, "value_id": "-1", "value_name": None}}
    use_case.category_resolver = resolver

    item = {"attributes": []}
    conditional_required_ids = PublishProductUseCase._inject_optional_na_attributes(
        use_case,
        category_id="MLB123",
        item=item,
        sku="SKU-1",
        description="Desc",
    )

    attrs_by_id = {attr["id"]: attr for attr in item["attributes"]}
    assert attrs_by_id["VISIBLE"] == {"id": "VISIBLE", "value_id": "-1", "value_name": None}
    assert "HIDDEN_ATTR" not in attrs_by_id
    assert "READ_ONLY_ATTR" not in attrs_by_id
    assert "LOCKED_ATTR" not in attrs_by_id
    assert "COND_VISIBLE" not in attrs_by_id
    assert "COND_HIDDEN" not in attrs_by_id
    assert conditional_required_ids == {"COND_VISIBLE"}


def test_missing_conditional_attributes_ignores_non_fillable_ids() -> None:
    resolver = _FakeCategoryResolver(
        metadata=[
            AttributeMeta(
                id="COND_HIDDEN",
                name="Condicional oculto",
                value_type="string",
                required=False,
                tags={"read_only"},
            ),
            AttributeMeta(
                id="COND_VISIBLE",
                name="Condicional visível",
                value_type="string",
                required=False,
            ),
        ],
        conditional_attrs=[{"id": "COND_HIDDEN"}, {"id": "COND_VISIBLE"}],
    )

    use_case = object.__new__(PublishProductUseCase)
    use_case.category_resolver = resolver

    missing = PublishProductUseCase._get_missing_conditional_attributes(
        use_case,
        category_id="MLB123",
        item={"attributes": []},
        description="Desc",
    )

    assert missing == ["COND_VISIBLE"]


def test_build_product_reads_descricao_header() -> None:
    use_case = object.__new__(PublishProductUseCase)
    product = PublishProductUseCase._build_product_from_dict(
        use_case,
        {
            "Título": "Meu livro",
            "Preço": 29.9,
            "Estoque": 2,
            "Condição": "Novo",
            "SKU": "SKU-ABC",
            "Descrição": "Descrição vinda da planilha",
        },
    )

    assert product.description == "Descrição vinda da planilha"


@pytest.mark.parametrize(
    ("row", "expected"),
    [
        (
            {
                "Título do anúncio": "Notebook Gamer",
                "Preço": "4999,90",
                "Estoque disponível": "2",
                "Condição": "Novo",
                "Código interno": "SKU-NOTE-01",
                "Descrição": "Linha premium",
            },
            {
                "sku": "SKU-NOTE-01",
                "title": "Notebook gamer",
                "price": 4999.9,
                "quantity": 2,
                "condition": "new",
                "description": "Linha premium",
            },
        ),
        (
            {
                "Title": "Camiseta Dry Fit",
                "Price": "79.5",
                "Stock": "12",
                "Condition": "used",
                "Code": "SKU-CAM-12",
            },
            {
                "sku": "SKU-CAM-12",
                "title": "Camiseta dry fit",
                "price": 79.5,
                "quantity": 12,
                "condition": "used",
                "description": "",
            },
        ),
        (
            {
                "Título do livro": "Título incorreto",
                "Título do anúncio": "Fone Bluetooth",
                "Preço unitário": "129,99",
                "Quantidade em estoque": "7",
                "Condição": "1",
                "SKU": "SKU-FONE-7",
                "Descrição completa": "Com cancelamento de ruído",
                "Varia por: Cor": "Preto, Branco",
            },
            {
                "sku": "SKU-FONE-7",
                "title": "Fone bluetooth",
                "price": 129.99,
                "quantity": 7,
                "condition": "used",
                "description": "Com cancelamento de ruído",
            },
        ),
    ],
)
def test_build_product_handles_messy_header_variants_matrix(
    row: dict[str, Any], expected: dict[str, Any]
) -> None:
    use_case = object.__new__(PublishProductUseCase)

    product = PublishProductUseCase._build_product_from_dict(use_case, row)

    assert product.sku == expected["sku"]
    assert product.title == expected["title"]
    assert product.price == expected["price"]
    assert product.available_quantity == expected["quantity"]
    assert product.condition == expected["condition"]
    assert product.description == expected["description"]
    if "Varia por: Cor" in row:
        assert product.attributes["Varia por: Cor"] == "Preto, Branco"


def test_execute_variation_heavy_row_surfaces_preflight_artifacts() -> None:
    class _ResolverWithExecute(_FakeCategoryResolver):
        def resolve_to_leaf(self, category_id: str) -> str:
            return category_id

        def find_category(self, _name: str) -> str | None:
            return None

        def find_category_with_predictor(
            self,
            _category_name: str,
            _product_titles: list[str],
            _site_id: str = "MLB",
        ) -> str | None:
            return None

        def predict_category_from_title(self, _title: str, _site_id: str = "MLB") -> str | None:
            return None

        def is_listing_allowed(self, _category_id: str) -> bool:
            return True

    class _WarningPublisher(_FakePublisher):
        def validate_item(self, item: dict[str, Any]) -> dict[str, Any]:
            self.validated_items.append(item)
            return {
                "cause": [
                    {
                        "type": "warning",
                        "code": "item.title.normalized",
                        "message": "Title normalized for publish matrix",
                    }
                ]
            }

    class _DiagnosticImageUploader(_FakeImageUploader):
        def diagnose_images(
            self,
            *,
            sku: str,
            category_id: str,
            title: str | None,
            picture_urls: list[str],
            picture_ids: list[str] | None = None,
        ) -> dict[str, Any]:
            del sku, category_id, title, picture_ids
            return {
                "status": "passed",
                "available": True,
                "checked": len(picture_urls),
                "issues": [],
                "results": [],
            }

    resolver = _ResolverWithExecute(
        [
            AttributeMeta(id="COLOR", name="Cor", value_type="string", required=False),
            AttributeMeta(id="GTIN", name="GTIN", value_type="string", required=False),
        ]
    )
    publisher = _WarningPublisher(listing_types=[{"id": "gold_special"}], sale_terms=[])
    use_case = PublishProductUseCase(
        category_resolver=resolver,  # type: ignore[arg-type]
        publisher=publisher,  # type: ignore[arg-type]
        image_uploader=_DiagnosticImageUploader(),  # type: ignore[arg-type]
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
        validation_only=True,
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

    row = {
        "Título do anúncio": "Camiseta Esportiva",
        "Preço de venda": "59,90",
        "Estoque atual": "4",
        "Condição": "Novo",
        "Código interno": "SKU-CAM-1",
        "Descrição completa": "Tecido dry fit",
        "Varia por: Cor": "Azul, Verde",
        "EAN / GTIN": "7891234567895",
    }

    result = use_case.execute([row], "MLB123")

    assert result["success"] is True
    assert result["validated"] == 1
    item_result = result["item_results"][0]
    assert item_result["resolution_strategy"] == "direct_id"
    assert item_result["category_resolved_id"] == "MLB123"
    assert item_result["identifier_gate"]["checked"] is True
    assert item_result["image_diagnostics"]["status"] == "passed"
    assert item_result["shipping_policy"]["decision"]["selected_mode"] == "me2"
    assert item_result["validation_decision"]["action"] == "allow"

    validated_item = publisher.validated_items[0]
    variation_values = sorted(
        variation["attribute_combinations"][0]["value_name"]
        for variation in validated_item["variations"]
    )
    assert variation_values == ["Azul", "Verde"]


def test_gtin_source_priority_scores_universal_code_higher_than_isbn() -> None:
    resolver = _FakeCategoryResolver(
        [
            AttributeMeta(id="GTIN", name="GTIN", value_type="string", required=False),
        ]
    )
    service = AttributeBuilderService(
        category_resolver=resolver,
        config={
            "gtin_source_priority": [
                "Código de produtos universal",
                "EAN / GTIN",
                "ISBN",
                "IBSN",
            ]
        },
        min_attribute_score=0,
    )
    meta = resolver.get_attribute_metadata("MLB123")[0]

    universal_score = service._score_attribute_payload(
        {
            "id": "GTIN",
            "value_name": "1234567890123",
            "_source_column": "Código de produtos universal",
        },
        meta,
    )
    isbn_score = service._score_attribute_payload(
        {"id": "GTIN", "value_name": "1234567890123", "_source_column": "ISBN"},
        meta,
    )

    assert universal_score > isbn_score
