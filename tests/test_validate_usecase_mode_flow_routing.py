"""Flow routing tests for validation-only publish flow."""

from __future__ import annotations

from typing import Any

from mercadolivre_upload.application.publish_product import PublishProductUseCase
from tests.support.validate_usecase_mode import (
    _base_config,
    _build_product,
    _ImageUploader,
    _ValidationPublisher,
    _ValidationResolver,
)


def test_validation_only_mode_includes_auto_flow_routing_metadata() -> None:
    publisher = _ValidationPublisher(users_me={"id": 1234, "tags": []})
    use_case = PublishProductUseCase(
        category_resolver=_ValidationResolver(),  # type: ignore[arg-type]
        publisher=publisher,  # type: ignore[arg-type]
        image_uploader=_ImageUploader(),  # type: ignore[arg-type]
        config=_base_config(),
        validation_only=True,
        enable_feedback=False,
        enable_fiscal_submission=False,
    )

    result = use_case.execute([_build_product()], "MLB1234")

    routing = result["item_results"][0]["flow_routing"]
    assert routing["mode"] == "auto"
    assert routing["selected_flow"] == "legacy"
    assert routing["seller_has_user_product_seller_tag"] is False
    assert routing["seller_capability_source"] == "users/me"
    assert routing["blocked"] is False
    assert "using legacy flow" in routing["reason"]


def test_flow_routing_prefers_publisher_users_me_when_available() -> None:
    class _PreferredPublisher(_ValidationPublisher):
        def get_publisher_users_me(self) -> dict[str, Any]:
            return {"id": 4321, "tags": ["user_product_seller"]}

        def get_users_me(self) -> dict[str, Any]:
            return {"id": 4321, "tags": []}

    publisher = _PreferredPublisher()
    use_case = PublishProductUseCase(
        category_resolver=_ValidationResolver(),  # type: ignore[arg-type]
        publisher=publisher,  # type: ignore[arg-type]
        image_uploader=_ImageUploader(),  # type: ignore[arg-type]
        config=_base_config(),
        validation_only=True,
        enable_feedback=False,
        enable_fiscal_submission=False,
    )

    result = use_case.execute([_build_product()], "MLB1234")

    routing = result["item_results"][0]["flow_routing"]
    assert routing["seller_capability_source"] == "publisher/get_users_me"
    assert routing["seller_has_user_product_seller_tag"] is True
    assert routing["selected_flow"] == "user_products"


def test_auto_flow_routing_falls_back_to_legacy_when_user_products_routes_are_unavailable() -> None:
    class _LegacyOnlyPublisher:
        def __init__(self) -> None:
            self.validated_items: list[dict[str, Any]] = []
            self.created_items: list[dict[str, Any]] = []

        def get_users_me(self) -> dict[str, Any]:
            return {"id": 1234, "tags": ["user_product_seller"]}

        def get_available_listing_types(self, _category_id: str) -> list[dict[str, Any]]:
            return [{"id": "gold_special"}]

        def get_category_sale_terms(self, _category_id: str) -> list[dict[str, Any]]:
            return []

        def validate_item(self, item: dict[str, Any]) -> dict[str, Any]:
            self.validated_items.append(item)
            return {"cause": []}

        def create_item(self, item: dict[str, Any]) -> dict[str, Any]:
            self.created_items.append(item)
            return {"id": "MLB1234567890"}

    publisher = _LegacyOnlyPublisher()
    use_case = PublishProductUseCase(
        category_resolver=_ValidationResolver(),  # type: ignore[arg-type]
        publisher=publisher,  # type: ignore[arg-type]
        image_uploader=_ImageUploader(),  # type: ignore[arg-type]
        config=_base_config(),
        validation_only=True,
        enable_feedback=False,
        enable_fiscal_submission=False,
    )

    result = use_case.execute([_build_product()], "MLB1234")

    routing = result["item_results"][0]["flow_routing"]
    assert routing["selected_flow"] == "legacy"
    assert routing["user_products_route_supported"] is False
    assert "publisher adapter does not support user-products endpoints" in routing["reason"]


def test_forced_user_products_flow_falls_back_to_legacy_when_configured() -> None:
    publisher = _ValidationPublisher(users_me={"id": 1234, "tags": []})
    config = _base_config()
    config["flow_routing"] = {
        "mode": "forced",
        "forced_flow": "user_products",
        "blocked_behavior": "fallback_legacy",
    }
    use_case = PublishProductUseCase(
        category_resolver=_ValidationResolver(),  # type: ignore[arg-type]
        publisher=publisher,  # type: ignore[arg-type]
        image_uploader=_ImageUploader(),  # type: ignore[arg-type]
        config=config,
        validation_only=True,
        enable_feedback=False,
        enable_fiscal_submission=False,
    )

    result = use_case.execute([_build_product()], "MLB1234")

    assert result["success"] is True
    assert result["validated"] == 1
    assert result["failed"] == 0
    assert len(publisher.validated_items) == 1
    assert publisher.validated_user_product_items == []
    routing = result["item_results"][0]["flow_routing"]
    assert routing["selected_flow"] == "legacy"
    assert routing["fallback_applied"] is True
    assert routing["blocked"] is False
    assert "requires seller tag" in routing["fallback_reason"]
    assert result["item_results"][0]["rollout_flags"]["flow_blocked_behavior"] == "fallback_legacy"


def test_forced_user_products_flow_requires_explicit_family_name() -> None:
    publisher = _ValidationPublisher(users_me={"id": 1234, "tags": ["user_product_seller"]})
    config = _base_config()
    config["flow_routing"] = {"mode": "forced", "forced_flow": "user_products"}
    use_case = PublishProductUseCase(
        category_resolver=_ValidationResolver(),  # type: ignore[arg-type]
        publisher=publisher,  # type: ignore[arg-type]
        image_uploader=_ImageUploader(),  # type: ignore[arg-type]
        config=config,
        enable_feedback=False,
        enable_fiscal_submission=False,
    )

    result = use_case.execute([_build_product()], "MLB1234")

    assert result["success"] is False
    assert result["published"] == 0
    assert result["failed"] == 1
    assert publisher.created_user_product_items == []
    assert "missing required field 'family_name'" in result["errors"][0]
    routing = result["item_results"][0]["flow_routing"]
    assert routing["mode"] == "forced"
    assert routing["selected_flow"] == "user_products"
    assert routing["blocked"] is False


def test_dry_run_executes_validation_pipeline_and_skips_publish_create_step() -> None:
    publisher = _ValidationPublisher()
    use_case = PublishProductUseCase(
        category_resolver=_ValidationResolver(),  # type: ignore[arg-type]
        publisher=publisher,  # type: ignore[arg-type]
        image_uploader=_ImageUploader(),  # type: ignore[arg-type]
        config=_base_config(),
        dry_run=True,
        enable_feedback=False,
        enable_fiscal_submission=False,
    )

    result = use_case.execute([_build_product()], "MLB1234")

    assert result["success"] is True
    assert result["published"] == 1
    assert result["failed"] == 0
    assert len(publisher.validated_items) == 1
    assert publisher.created_items == []
