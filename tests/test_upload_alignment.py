"""Tests for upload logic alignment (units + shipping mode resolution)."""

from __future__ import annotations

from mercadolivre_upload.application.attribute_builder import AttributeBuilderService
from mercadolivre_upload.application.publish_product import PublishProductUseCase
from mercadolivre_upload.domain.attribute_metadata import AttributeMeta
from mercadolivre_upload.domain.fiscal.data import FiscalData
from mercadolivre_upload.domain.product.model import Product
from mercadolivre_upload.domain.shipping.resolver import ShippingResolver


class _FakeCategoryResolver:
    def __init__(self, metadata: list[AttributeMeta]):
        self._metadata = metadata

    def get_attribute_metadata(self, category_id: str) -> list[AttributeMeta]:
        return self._metadata

    def get_conditional_attributes(
        self, category_id: str, attributes: dict[str, str]
    ) -> list[dict[str, str]]:
        return []


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


def test_explicit_mapping_is_not_bypassed_by_cache_mapper() -> None:
    resolver = _FakeCategoryResolver(
        [
            AttributeMeta(id="WEIGHT", name="Peso", value_type="number_unit", required=False),
        ]
    )
    service = AttributeBuilderService(
        category_resolver=resolver,
        config={
            "explicit_mappings": {
                "Peso físico (kg) Embalagem com o produto dentro": {
                    "target": "attribute",
                    "id": "WEIGHT",
                    "unit_suffix": " kg",
                }
            }
        },
        min_attribute_score=0,
    )

    cache_mapper = _FakeCacheMapper()
    service.set_cache_mapper(cache_mapper)  # type: ignore[arg-type]

    product = _build_product({"Peso físico (kg) Embalagem com o produto dentro": "0,220"})
    attrs, sale_terms, warnings, errors = service.build_attributes(product, "MLB123")

    assert not sale_terms
    assert not warnings
    assert not errors
    assert {a["id"]: a["value_name"] for a in attrs}["WEIGHT"] == "0.220 kg"
    assert cache_mapper.map_calls == 0


def test_cache_mapper_map_value_is_used_for_number_unit_attributes() -> None:
    resolver = _FakeCategoryResolver(
        [
            AttributeMeta(id="WIDTH", name="Largura", value_type="number_unit", required=False),
        ]
    )
    service = AttributeBuilderService(
        category_resolver=resolver,
        config={"explicit_mappings": {}},
        min_attribute_score=0,
    )

    cache_mapper = _FakeCacheMapper()
    service.set_cache_mapper(cache_mapper)  # type: ignore[arg-type]

    product = _build_product({"Largura": "23"})
    attrs, _, _, _ = service.build_attributes(product, "MLB123")

    assert {a["id"]: a["value_name"] for a in attrs}["WIDTH"] == "23 cm"
    assert cache_mapper.map_calls == 1


def test_shipping_resolver_uses_shipping_preferences_modes() -> None:
    provider = _FakeShippingProvider(
        user_info={"id": 123, "shipping_modes": ["me1", "me2"]},
        shipping_preferences={"modes": ["me2", "custom"]},
    )
    resolver = ShippingResolver(
        provider,
        config={"mode_priority": ["me1", "me2"], "default_mode": "not_specified"},
    )

    assert resolver.get_best_shipping_mode() == "me2"
    assert provider.requested_user_id == "123"


def test_shipping_resolver_falls_back_to_users_me_modes_if_preferences_fail() -> None:
    provider = _FakeShippingProvider(
        user_info={"id": 321, "shipping_modes": ["me2"]},
        raise_preferences=True,
    )
    resolver = ShippingResolver(
        provider,
        config={"mode_priority": ["me1", "me2"], "default_mode": "not_specified"},
    )

    assert resolver.get_best_shipping_mode() == "me2"


def test_shipping_resolver_returns_default_when_no_modes_available() -> None:
    provider = _FakeShippingProvider(user_info={"id": 123}, shipping_preferences={"modes": []})
    resolver = ShippingResolver(
        provider,
        config={"mode_priority": ["me1", "me2"], "default_mode": "not_specified"},
    )

    assert resolver.get_best_shipping_mode() == "not_specified"


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
