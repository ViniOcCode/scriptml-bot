"""Tests for upload logic alignment (units + shipping mode resolution)."""

from __future__ import annotations

from typing import Any

from mercadolivre_upload.application.attribute_builder import AttributeBuilderService
from mercadolivre_upload.application.publish_product import PublishProductUseCase
from mercadolivre_upload.domain.attribute_mapper import AttributeMapper
from mercadolivre_upload.domain.attribute_metadata import AttributeMeta
from mercadolivre_upload.domain.cache_attribute_mapper import CachedAttributeMapper
from mercadolivre_upload.domain.fiscal.data import FiscalData
from mercadolivre_upload.domain.product.model import Product
from mercadolivre_upload.domain.shipping.resolver import ShippingResolver


class _FakeCategoryResolver:
    def __init__(
        self,
        metadata: list[AttributeMeta],
        conditional_attrs: list[dict[str, Any]] | None = None,
    ):
        self._metadata = metadata
        self._conditional_attrs = conditional_attrs or []
        self.last_conditional_payload: dict[str, Any] | None = None

    def get_attribute_metadata(self, category_id: str) -> list[AttributeMeta]:
        return self._metadata

    def get_conditional_attributes(
        self, category_id: str, attributes: dict[str, Any]
    ) -> list[dict[str, Any]]:
        self.last_conditional_payload = attributes
        return self._conditional_attrs


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
    ):
        self.listing_types = listing_types or []
        self.sale_terms = sale_terms or []
        self.validated_items: list[dict[str, Any]] = []
        self.created_items: list[dict[str, Any]] = []
        self.description_calls: list[tuple[str, str]] = []

    def get_available_listing_types(self, category_id: str) -> list[dict[str, str]]:
        return self.listing_types

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


_AUTO_WEIGHT_RULES = [
    {
        "match": {
            "contains": ["peso fisico"],
            "excludes": ["peso liquido", "peso bruto"],
        },
        "mapping": {
            "target": "attribute",
            "id": "WEIGHT",
            "unit_suffix": " kg",
        },
    }
]


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


def test_peso_fisico_variants_are_mapped_without_explicit_config() -> None:
    resolver = _FakeCategoryResolver(
        [
            AttributeMeta(id="WEIGHT", name="Peso", value_type="number_unit", required=False),
        ]
    )
    service = AttributeBuilderService(
        category_resolver=resolver,
        config={"explicit_mappings": {}, "auto_explicit_mappings": _AUTO_WEIGHT_RULES},
        min_attribute_score=0,
    )

    cache_mapper = _FakeCacheMapper()
    service.set_cache_mapper(cache_mapper)  # type: ignore[arg-type]

    product = _build_product({"PESO FISICO (KG)": "0,220"})
    attrs, sale_terms, warnings, errors = service.build_attributes(product, "MLB123")

    assert not sale_terms
    assert not warnings
    assert not errors
    assert {a["id"]: a["value_name"] for a in attrs}["WEIGHT"] == "0.220 kg"
    assert cache_mapper.map_calls == 0


def test_peso_fisico_auto_rule_does_not_match_fiscal_weight_headers() -> None:
    mapper = AttributeMapper()

    mapped = mapper.get_explicitly_mapped_columns(
        {
            "Peso líquido": "0,100",
            "Peso bruto": "0,120",
        },
        explicit_mappings={},
        auto_explicit_mappings=_AUTO_WEIGHT_RULES,
    )

    assert mapped == set()


def test_cached_mapper_ignores_operational_and_unit_headers() -> None:
    mapper = CachedAttributeMapper(
        _StaticAttributeCache(
            [
                {
                    "id": "WIDTH",
                    "name": "Largura",
                    "value_type": "number_unit",
                    "default_unit": "cm",
                },
                {
                    "id": "COLOR",
                    "name": "Cor",
                    "value_type": "string",
                    "values": [
                        {"id": "1", "name": "Azul"},
                        {"id": "2", "name": "Verde"},
                    ],
                },
                {
                    "id": "FRAME_COLOR",
                    "name": "Cor da armação",
                    "value_type": "string",
                    "values": [{"id": "10", "name": "Preto"}],
                },
            ]
        ),
        "MLB40280",
    )

    assert mapper.find_attribute_by_name("Unidade de Largura") is None
    assert mapper.find_attribute_by_name("Varia por: Cor da armação") is None
    assert mapper.find_attribute_by_name("Forma de envio") is None
    assert mapper.find_attribute_by_name("Largura")["id"] == "WIDTH"


def test_cached_mapper_splits_multi_value_enum_and_maps_first_match() -> None:
    mapper = CachedAttributeMapper(
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
        "MLB40280",
    )

    mapped = mapper.map_value("COLOR", "Azul, bege, verde")
    assert mapped["id"] == "COLOR"
    assert mapped["value_id"] == "1"
    assert mapped["value_name"] == "Azul"


def test_cached_mapper_extracts_all_matching_enum_values() -> None:
    mapper = CachedAttributeMapper(
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
        "MLB40280",
    )

    mapped_values = mapper.map_all_values("COLOR", "Azul, bege, verde")
    assert [value["name"] for value in mapped_values] == ["Azul", "Verde"]


def test_attribute_mapper_skips_operational_header_fuzzy_mapping() -> None:
    mapper = AttributeMapper(similarity_threshold=0.7)

    mapped_attrs, _ = mapper.map_product_attributes(
        {
            "Forma de envio": "Mercado Envios",
            "Formato de venda": "Unidade",
        },
        [{"id": "SALE_FORMAT", "name": "Formato de venda"}],
        explicit_mappings={},
        auto_explicit_mappings=[],
    )

    assert len(mapped_attrs) == 1
    assert mapped_attrs[0]["id"] == "SALE_FORMAT"
    assert mapped_attrs[0]["value_name"] == "Unidade"


def test_listing_type_explicit_mapping_uses_gold_pro_for_premium() -> None:
    mapper = AttributeMapper(similarity_threshold=0.7)

    mapped_attrs, _ = mapper.map_product_attributes(
        {"Tipo do anúncio": "Premium"},
        [],
        explicit_mappings={
            "Tipo do anúncio": {
                "target": "listing_type_id",
                "id": "gold_special",
            }
        },
        auto_explicit_mappings=[],
    )

    assert mapped_attrs == [{"_listing_type_id": "gold_pro"}]


def test_attribute_mapper_skips_unsupported_explicit_attribute() -> None:
    mapper = AttributeMapper(similarity_threshold=0.7)

    mapped_attrs, _ = mapper.map_product_attributes(
        {"Profundidade (cm)": "20"},
        [{"id": "WIDTH", "name": "Largura"}],
        explicit_mappings={
            "Profundidade (cm)": {
                "target": "attribute",
                "id": "DEPTH",
                "unit_suffix": " cm",
            }
        },
        auto_explicit_mappings=[],
    )

    assert mapped_attrs == []


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


def test_attribute_builder_deduplicates_unit_only_dimension_values() -> None:
    class _DuplicateHeightCacheMapper:
        def find_attribute_by_name(self, excel_header: str) -> dict[str, str] | None:
            lowered = excel_header.lower()
            if lowered == "altura":
                return {"id": "HEIGHT"}
            if lowered == "unidade de altura":
                return {"id": "HEIGHT"}
            return None

        def map_value(self, attribute_id: str, excel_value: str) -> dict[str, str]:
            if excel_value == "60":
                return {"id": "HEIGHT", "value_name": "60 cm"}
            return {"id": "HEIGHT", "value_name": "cm"}

    resolver = _FakeCategoryResolver(
        [
            AttributeMeta(id="HEIGHT", name="Altura", value_type="number_unit", required=False),
        ]
    )
    service = AttributeBuilderService(
        category_resolver=resolver,
        config={"explicit_mappings": {}},
        min_attribute_score=0,
    )
    service.set_cache_mapper(_DuplicateHeightCacheMapper())  # type: ignore[arg-type]

    product = _build_product({"Altura": "60", "Unidade de Altura": "cm"})
    attrs, _, warnings, errors = service.build_attributes(product, "MLB123")

    assert not warnings
    assert not errors
    assert attrs == [{"id": "HEIGHT", "value_name": "60 cm"}]


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
    assert "SIZE" not in attrs_by_id
    assert "ISBN" not in attrs_by_id
    assert resolver.last_conditional_payload is not None
    assert resolver.last_conditional_payload["description"] == {"plain_text": "Desc"}
    assert any("Skipped N/A auto-fill" in message for message in caplog.messages)


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
