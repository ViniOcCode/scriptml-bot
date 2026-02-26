"""Shared helpers for upload-alignment publish-flow tests."""

from __future__ import annotations

from typing import Any

from mercadolivre_upload.domain.attribute_metadata import AttributeMeta
from mercadolivre_upload.domain.fiscal.data import FiscalData
from mercadolivre_upload.domain.product.model import Product


class _FakeCategoryResolver:
    def __init__(
        self,
        metadata: list[AttributeMeta],
        conditional_attrs: list[dict[str, Any]] | None = None,
        all_attributes: list[dict[str, Any]] | None = None,
        settings: dict[str, Any] | None = None,
    ):
        self._metadata = metadata
        self._conditional_attrs = conditional_attrs or []
        self.last_conditional_payload: dict[str, Any] | None = None
        if all_attributes is None:
            normalized_attributes: list[dict[str, Any]] = []
            for meta in metadata:
                attribute_row: dict[str, Any] = {"id": meta.id, "tags": sorted(meta.tags)}
                if isinstance(meta.allowed_values, set) and meta.allowed_values:
                    attribute_row["values"] = [
                        {"name": value} for value in sorted(meta.allowed_values)
                    ]
                normalized_attributes.append(attribute_row)
            self._all_attributes = normalized_attributes
        else:
            self._all_attributes = all_attributes
        base_settings = {"status": "enabled", "listing_allowed": True}
        if isinstance(settings, dict):
            base_settings.update(settings)
        self._settings = base_settings

    def get_attribute_metadata(self, category_id: str) -> list[AttributeMeta]:
        return self._metadata

    def get_conditional_attributes(
        self, category_id: str, attributes: dict[str, Any]
    ) -> list[dict[str, Any]]:
        self.last_conditional_payload = attributes
        return self._conditional_attrs

    def get_category_data(self, category_id: str) -> dict[str, Any]:
        return {
            "id": category_id,
            "status": "enabled",
            "settings": dict(self._settings),
        }

    def get_all_attributes(self, category_id: str) -> list[dict[str, Any]]:
        del category_id
        return list(self._all_attributes)


class _FakeCacheMapper:
    def __init__(self):
        self.map_calls = 0

    def find_attribute_by_name(self, excel_header: str) -> dict[str, str] | None:
        if "peso" in excel_header.lower():
            return {"id": "WEIGHT"}
        if "largura" in excel_header.lower():
            return {"id": "WIDTH"}
        return None

    def map_value(self, attribute_id: str, excel_value: str) -> dict[str, str]:
        self.map_calls += 1
        if attribute_id == "WEIGHT":
            return {"id": "WEIGHT", "value_name": "999 g"}
        if attribute_id == "WIDTH":
            return {"id": "WIDTH", "value_name": "23 cm"}
        return {"id": attribute_id, "value_name": excel_value}


class _FakeShippingProvider:
    def __init__(
        self,
        user_info: dict,
        shipping_preferences: dict | None = None,
        raise_preferences: bool = False,
    ):
        self.user_info = user_info
        self.shipping_preferences = shipping_preferences or {}
        self.raise_preferences = raise_preferences
        self.requested_user_id: str | None = None

    def get_users_me(self) -> dict:
        return self.user_info

    def get_user_shipping_preferences(self, user_id: str) -> dict:
        self.requested_user_id = user_id
        if self.raise_preferences:
            raise RuntimeError("preferences unavailable")
        return self.shipping_preferences


class _FakeImageUploader:
    def __init__(self, image_urls: list[str] | None = None):
        self.image_urls = image_urls or ["https://example.com/image.jpg"]
        self._uploads = [
            {"url": url, "id": f"PIC-{index + 1}"} for index, url in enumerate(self.image_urls)
        ]

    def upload_images(self, sku: str) -> list[str]:
        return self.image_urls

    def get_uploaded_images(self) -> list[dict[str, str]]:
        return list(self._uploads)


class _FixedShippingResolver:
    def __init__(self, mode: str):
        self.mode = mode

    def get_best_shipping_mode(self) -> str:
        return self.mode


class _FakePublisher:
    def __init__(
        self,
        listing_types: list[dict[str, str]] | None = None,
        sale_terms: list[dict[str, Any]] | None = None,
        site_listing_types: list[dict[str, str]] | None = None,
    ):
        self.listing_types = listing_types or []
        self.sale_terms = sale_terms or []
        self.site_listing_types = site_listing_types or []
        self.validated_items: list[dict[str, Any]] = []
        self.created_items: list[dict[str, Any]] = []
        self.description_calls: list[tuple[str, str]] = []

    def get_available_listing_types(self, category_id: str) -> list[dict[str, str]]:
        return self.listing_types

    def get_site_listing_types(self, site_id: str) -> list[dict[str, str]]:
        return self.site_listing_types

    def get_category_sale_terms(self, category_id: str) -> list[dict[str, Any]]:
        return self.sale_terms

    def validate_item(self, item: dict[str, Any]) -> dict[str, Any]:
        self.validated_items.append(item)
        return {"cause": []}

    def create_item(self, item: dict[str, Any]) -> dict[str, Any]:
        self.created_items.append(item)
        return {"id": "MLB1234567890"}

    def create_item_description(self, item_id: str, plain_text: str) -> dict[str, str]:
        self.description_calls.append((item_id, plain_text))
        return {"id": f"{item_id}-description"}


class _StaticAttributeCache:
    def __init__(self, attributes: list[dict[str, Any]]):
        self._attributes = attributes

    def get_attributes(self, category_id: str) -> list[dict[str, Any]]:
        return self._attributes


def _build_product(attributes: dict[str, str]) -> Product:
    fiscal = FiscalData(sku="SKU-1", title="Produto teste")
    return Product(
        sku="SKU-1",
        title="Produto teste",
        description="Desc",
        price=10.0,
        available_quantity=1,
        condition="new",
        fiscal=fiscal,
        attributes=attributes,
    )
