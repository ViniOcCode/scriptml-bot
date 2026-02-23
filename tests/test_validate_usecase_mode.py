"""Tests for PublishProductUseCase validation-only execution mode."""

from __future__ import annotations

from typing import Any

from mercadolivre_upload.application.publish_product import PublishProductUseCase
from mercadolivre_upload.domain.attribute_metadata import AttributeMeta
from mercadolivre_upload.domain.fiscal.data import FiscalData
from mercadolivre_upload.domain.product.model import Product


class _ValidationResolver:
    def resolve_to_leaf(self, category_id: str) -> str:
        return category_id

    def is_listing_allowed(self, _category_id: str) -> bool:
        return True

    def get_attribute_metadata(self, _category_id: str) -> list[AttributeMeta]:
        return [AttributeMeta(id="BRAND", name="Marca", value_type="string", required=False)]

    def get_conditional_attributes(
        self, _category_id: str, _item_context: dict[str, Any]
    ) -> list[dict[str, Any]]:
        return []


class _ValidationPublisher:
    def __init__(self, causes: list[dict[str, Any]] | None = None):
        self.causes = causes or []
        self.validated_items: list[dict[str, Any]] = []
        self.created_items: list[dict[str, Any]] = []

    def validate_item(self, item: dict[str, Any]) -> dict[str, Any]:
        self.validated_items.append(item)
        return {"cause": self.causes}

    def create_item(self, item: dict[str, Any]) -> dict[str, Any]:
        self.created_items.append(item)
        return {"id": "MLB1234567890"}


class _ImageUploader:
    def upload_images(self, _sku: str) -> list[str]:
        return ["https://example.com/image.jpg"]


def _build_product() -> Product:
    title = "Produto teste"
    return Product(
        sku="SKU-1",
        title=title,
        description="Desc",
        price=10.0,
        available_quantity=1,
        condition="new",
        fiscal=FiscalData(sku="SKU-1", title=title),
        attributes={},
    )


def _base_config() -> dict[str, Any]:
    return {
        "core_item_fields": {
            "defaults": {
                "currency_id": "BRL",
                "buying_mode": "buy_it_now",
                "listing_type_id": "gold_special",
                "sale_terms": [],
            }
        }
    }


def test_validation_only_mode_validates_without_publishing() -> None:
    publisher = _ValidationPublisher()
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

    assert result["success"] is True
    assert result["validated"] == 1
    assert result["published"] == 1
    assert result["failed"] == 0
    assert len(publisher.validated_items) == 1
    assert publisher.created_items == []
    assert result["item_results"][0]["status"] == "success"


def test_validation_only_mode_surfaces_validation_cause_codes() -> None:
    publisher = _ValidationPublisher(
        causes=[
            {
                "type": "error",
                "code": "body.invalid_fields",
                "message": "The fields [price] are invalid for requested call.",
            }
        ]
    )
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

    assert result["success"] is False
    assert result["validated"] == 0
    assert result["failed"] == 1
    assert len(publisher.validated_items) == 1
    assert publisher.created_items == []
    assert result["item_results"][0]["status"] == "failed"
    assert result["item_results"][0]["cause_codes"] == ["body.invalid_fields"]
