"""Publish flow tests for warnings and N/A policy behavior."""

from __future__ import annotations

from typing import Any

from mercadolivre_upload.application.publish_product import PublishProductUseCase
from mercadolivre_upload.domain.attribute_metadata import AttributeMeta
from tests.support.upload_alignment import (
    _build_product,
    _FakeCategoryResolver,
    _FakeImageUploader,
    _FakePublisher,
    _FixedShippingResolver,
)


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
    with caplog.at_level("DEBUG"):
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
