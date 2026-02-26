"""User-products payload tests for validation-only publish flow."""

from __future__ import annotations

from typing import Any

from mercadolivre_upload.application.publish_product import PublishProductUseCase
from mercadolivre_upload.domain.product.model import Product
from tests.support.validate_usecase_mode import (
    _base_config,
    _build_product,
    _ImageUploader,
    _ValidationPublisher,
    _ValidationResolver,
)


def test_user_products_flow_builds_distinct_pxv_payload_and_artifacts() -> None:
    class _VariationMarkerBuilder:
        def build_attributes(
            self,
            _product: Product,
            _category_id: str,
        ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str], list[str]]:
            return (
                [
                    {"id": "MODEL", "value_name": "Model X"},
                    {"id": "COLOR", "value_name": "Azul"},
                    {
                        "_variation_candidates": {
                            "COLOR": [
                                {"id": "1", "name": "Azul"},
                                {"id": "2", "name": "Verde"},
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
    use_case._attribute_builder = _VariationMarkerBuilder()  # type: ignore[assignment]

    result = use_case.execute([_build_product({"family_name": "Linha Alpha"})], "MLB1234")

    assert result["success"] is True
    assert publisher.created_user_product_items
    created_item = publisher.created_user_product_items[0]
    assert "variations" not in created_item
    assert "title" not in created_item
    assert created_item["family_name"] == "Linha Alpha"
    assert "user_product" not in created_item
    attribute_ids = {
        attr.get("id") for attr in created_item["attributes"] if isinstance(attr, dict)
    }
    assert "MODEL" in attribute_ids
    assert "COLOR" in attribute_ids
    routing = result["item_results"][0]["flow_routing"]
    assert routing["selected_flow"] == "user_products"
    assert routing["payload_builder"] == "user_products_pxv"
    assert routing["selected_model"] == "Model X"
    assert routing["up_family_name"] == "Linha Alpha"
    assert routing["up_family_name_source"] == "attribute"
    assert routing["up_attribute_ids"] == ["COLOR"]
    assert routing["up_variation_count"] == 2
