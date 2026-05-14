"""Shared helpers for validation-only publish use-case tests."""

from __future__ import annotations

from typing import Any

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

    def get_category_data(self, category_id: str) -> dict[str, Any]:
        return {
            "id": category_id,
            "status": "enabled",
            "settings": {"status": "enabled", "listing_allowed": True},
        }

    def get_all_attributes(self, _category_id: str) -> list[dict[str, Any]]:
        return [
            {"id": "BRAND", "tags": {}},
            {"id": "MODEL", "tags": {"allow_variations": True}},
        ]


class _ValidationPublisher:
    def __init__(
        self,
        causes: list[dict[str, Any]] | None = None,
        users_me: dict[str, Any] | None = None,
    ):
        self.causes = causes or []
        self.listing_type_calls = 0
        self.sale_terms_calls = 0
        self.validated_items: list[dict[str, Any]] = []
        self.created_items: list[dict[str, Any]] = []
        self.validated_user_product_items: list[dict[str, Any]] = []
        self.created_user_product_items: list[dict[str, Any]] = []
        self.listing_types = [{"id": "gold_special"}, {"id": "free"}]
        self.sale_terms = [{"id": "WARRANTY_TYPE", "tags": {"required": True}}]
        self.users_me = users_me or {"id": 1234, "tags": []}

    def get_available_listing_types(self, _category_id: str) -> list[dict[str, Any]]:
        self.listing_type_calls += 1
        return list(self.listing_types)

    def get_category_sale_terms(self, _category_id: str) -> list[dict[str, Any]]:
        self.sale_terms_calls += 1
        return list(self.sale_terms)

    def validate_item(self, item: dict[str, Any]) -> dict[str, Any]:
        self.validated_items.append(item)
        if not self.causes:
            return {}
        return {"cause": self.causes}

    def validate_user_product_item(self, item: dict[str, Any]) -> dict[str, Any]:
        self.validated_user_product_items.append(item)
        return self.validate_item(item)

    def create_item(self, item: dict[str, Any]) -> dict[str, Any]:
        self.created_items.append(item)
        return {"id": "MLB1234567890"}

    def create_user_product_item(self, item: dict[str, Any]) -> dict[str, Any]:
        self.created_user_product_items.append(item)
        return self.create_item(item)

    def get_users_me(self) -> dict[str, Any]:
        return dict(self.users_me)


class _ImageUploader:
    def __init__(
        self,
        image_urls: list[str] | None = None,
        diagnostic_result: dict[str, Any] | None = None,
    ):
        self.image_urls = image_urls or ["https://example.com/image.jpg"]
        self.diagnostic_result = diagnostic_result

    def upload_images(self, _sku: str) -> list[str]:
        return list(self.image_urls)

    def get_uploaded_images(self) -> list[dict[str, str]]:
        return [
            {"url": image_url, "id": f"PIC-{index + 1}"}
            for index, image_url in enumerate(self.image_urls)
        ]

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
        if self.diagnostic_result is None:
            return {
                "status": "unavailable",
                "available": False,
                "checked": 0,
                "issues": [],
                "results": [],
                "message": "Image diagnostics unavailable in test uploader.",
            }
        result = dict(self.diagnostic_result)
        result.setdefault("checked", len(picture_urls))
        result.setdefault("results", [])
        result.setdefault("issues", [])
        return result


class _FixedShippingResolver:
    def __init__(self, mode: str):
        self.mode = mode

    def get_best_shipping_mode(self) -> str:
        return self.mode


class _SelectionShippingResolver:
    def __init__(
        self,
        mode: str,
        logistic_type: str | None = None,
        tags: list[str] | None = None,
        free_shipping: bool | None = None,
        constraints: dict[str, Any] | None = None,
    ):
        self.mode = mode
        self.logistic_type = logistic_type
        self.tags = tags
        self.free_shipping = free_shipping
        self.constraints = constraints

    def get_best_shipping_selection(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"mode": self.mode, "logistic_type": self.logistic_type}
        if self.tags is not None:
            payload["tags"] = list(self.tags)
        if self.free_shipping is not None:
            payload["free_shipping"] = self.free_shipping
        if self.constraints is not None:
            payload["constraints"] = dict(self.constraints)
        return payload


class _SchemaContractResolver(_ValidationResolver):
    def __init__(
        self,
        *,
        all_attributes: list[dict[str, Any]] | None = None,
        settings: dict[str, Any] | None = None,
    ):
        if all_attributes is None:
            self._all_attributes = super().get_all_attributes("MLB1234")
        else:
            self._all_attributes = all_attributes
        merged_settings = {"status": "enabled", "listing_allowed": True}
        if isinstance(settings, dict):
            merged_settings.update(settings)
        self._settings = merged_settings

    def get_category_data(self, category_id: str) -> dict[str, Any]:
        return {
            "id": category_id,
            "status": "enabled",
            "settings": dict(self._settings),
        }

    def get_all_attributes(self, _category_id: str) -> list[dict[str, Any]]:
        return list(self._all_attributes)


def _build_product(attributes: dict[str, Any] | None = None) -> Product:
    title = "Produto teste"
    return Product(
        sku="SKU-1",
        title=title,
        description="Desc",
        price=10.0,
        available_quantity=1,
        condition="new",
        fiscal=FiscalData(sku="SKU-1", title=title),
        attributes=attributes or {},
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


def _shipping_config() -> dict[str, Any]:
    return {
        "default_mode": "not_specified",
        "modes": {
            "not_specified": {"local_pick_up": True, "free_shipping": False},
            "me2": {"local_pick_up": False, "free_shipping": False, "logistic_type": "drop_off"},
        },
    }
