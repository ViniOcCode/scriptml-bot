"""Publish flow tests for listing type and sale terms behavior."""

from __future__ import annotations

from typing import Any

from mercadolivre_upload.application.publish_product import PublishProductUseCase
from mercadolivre_upload.domain.attribute_metadata import AttributeMeta
from mercadolivre_upload.domain.product.model import Product
from tests.support.upload_alignment import (
    _build_product,
    _FakeCategoryResolver,
    _FakeImageUploader,
    _FakePublisher,
    _FixedShippingResolver,
)


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
