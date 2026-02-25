"""Tests for upload logic alignment (units + shipping mode resolution)."""

from __future__ import annotations

from typing import Any

from mercadolivre_upload.application.attribute_builder import AttributeBuilderService
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


def test_explicit_mapping_accepts_dynamic_conditional_metadata() -> None:
    resolver = _FakeCategoryResolver(
        [AttributeMeta(id="BRAND", name="Marca", value_type="string", required=False)],
        conditional_attrs=[{"id": "SIZE", "name": "Tamanho", "value_type": "string"}],
    )
    service = AttributeBuilderService(
        category_resolver=resolver,
        config={"explicit_mappings": {"Tamanho": {"target": "attribute", "id": "SIZE"}}},
        min_attribute_score=0,
    )

    attrs, sale_terms, warnings, errors = service.build_attributes(
        _build_product({"Tamanho": "M"}),
        "MLB123",
    )

    assert not sale_terms
    assert not warnings
    assert not errors
    assert {a["id"]: a["value_name"] for a in attrs}["SIZE"] == "M"
    assert resolver.last_conditional_payload is not None
    assert resolver.last_conditional_payload["description"] == {"plain_text": "Desc"}


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


def test_cached_mapper_ignores_operational_and_unit_headers_but_maps_varia_por_hint() -> None:
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
    assert mapper.extract_variation_hint("Varia por: Cor da armação") == "cor da armacao"
    assert mapper.find_attribute_by_name("Varia por: Cor da armação")["id"] == "FRAME_COLOR"
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


def test_attribute_mapper_maps_varia_por_header_and_extracts_variation_candidates() -> None:
    mapper = AttributeMapper(similarity_threshold=0.7)

    mapped_attrs, _ = mapper.map_product_attributes(
        {"Varia por: Cor": "Azul, Verde"},
        [{"id": "COLOR", "name": "Cor"}],
        explicit_mappings={},
        auto_explicit_mappings=[],
    )

    assert mapped_attrs[0] == {
        "id": "COLOR",
        "name": "Cor",
        "value_name": "Azul, Verde",
    }
    assert mapped_attrs[1] == {
        "_variation_candidates": {
            "COLOR": [{"id": None, "name": "Azul"}, {"id": None, "name": "Verde"}]
        }
    }


def test_attribute_builder_keeps_boolean_attributes_with_same_no_value() -> None:
    resolver = _FakeCategoryResolver(
        [
            AttributeMeta(
                id="INCLUDES_FRAME",
                name="Inclui armação",
                value_type="boolean",
                required=False,
                allowed_values={"Não", "Sim"},
                relevance=1.0,
            ),
            AttributeMeta(
                id="WITH_GLASS",
                name="Com vidro",
                value_type="boolean",
                required=False,
                allowed_values={"Não", "Sim"},
                relevance=1.0,
            ),
            AttributeMeta(
                id="WITH_PHRASES",
                name="Com frases",
                value_type="boolean",
                required=False,
                allowed_values={"Não", "Sim"},
                relevance=1.0,
            ),
        ]
    )
    service = AttributeBuilderService(
        category_resolver=resolver,
        config={
            "explicit_mappings": {
                "Armação": {"target": "attribute", "id": "INCLUDES_FRAME"},
                "Vidro": {"target": "attribute", "id": "WITH_GLASS"},
                "Frases": {"target": "attribute", "id": "WITH_PHRASES"},
            }
        },
        min_attribute_score=50,
    )

    attrs, sale_terms, warnings, errors = service.build_attributes(
        _build_product({"Armação": "Não", "Vidro": "Não", "Frases": "Não"}),
        "MLB40280",
    )

    assert not sale_terms
    assert not warnings
    assert not errors
    assert {attr["id"]: attr["value_name"] for attr in attrs} == {
        "INCLUDES_FRAME": "Não",
        "WITH_GLASS": "Não",
        "WITH_PHRASES": "Não",
    }


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


def test_attribute_mapper_maps_sale_terms_from_excel_values() -> None:
    mapper = AttributeMapper(similarity_threshold=0.7)

    mapped_attrs, sale_terms = mapper.map_product_attributes(
        {
            "Tipo de garantia": "Garantia do fabricante",
            "Tempo de garantia": "90",
            "Unidade de tempo de garantia": "dias",
        },
        [],
        explicit_mappings={
            "Tipo de garantia": {
                "target": "sale_terms",
                "id": "WARRANTY_TYPE",
                "name": "Tipo de garantia",
                "value_type": "list",
                "value_name": "Garantia do vendedor",
            },
            "Tempo de garantia": {
                "target": "sale_terms",
                "id": "WARRANTY_TIME",
                "name": "Tempo de garantia",
                "value_type": "number_unit",
                "unit_from_column": "Unidade de tempo de garantia",
                "value_name": "30 dias",
                "value_struct": {"number": 30, "unit": "dias"},
            },
        },
        auto_explicit_mappings=[],
    )

    assert mapped_attrs == []
    mapped_sale_terms = {sale_term["id"]: sale_term for sale_term in sale_terms}
    assert mapped_sale_terms["WARRANTY_TYPE"]["value_name"] == "Garantia do fabricante"
    assert mapped_sale_terms["WARRANTY_TIME"]["value_name"] == "90 dias"
    assert mapped_sale_terms["WARRANTY_TIME"]["value_struct"] == {
        "number": 90,
        "unit": "dias",
    }


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


def test_shipping_resolver_selection_reads_modes_and_logistic_type_from_logistics() -> None:
    provider = _FakeShippingProvider(
        user_info={"id": 123, "shipping_modes": []},
        shipping_preferences={
            "modes": [],
            "logistics": [
                {
                    "mode": "me2",
                    "types": [{"type": "drop_off"}, {"type": "fulfillment", "default": True}],
                },
                {"mode": "me1", "types": [{"type": "cross_docking", "default": True}]},
            ],
        },
    )
    resolver = ShippingResolver(
        provider,
        config={"mode_priority": ["me2", "me1"], "default_mode": "not_specified"},
    )

    selection = resolver.get_best_shipping_selection()

    assert selection["mode"] == "me2"
    assert selection["logistic_type"] == "fulfillment"
    assert provider.requested_user_id == "123"


def test_shipping_resolver_selection_uses_first_logistic_type_when_no_default() -> None:
    provider = _FakeShippingProvider(
        user_info={"id": 456},
        shipping_preferences={
            "modes": [],
            "logistics": [{"mode": "me1", "types": [{"type": "xd_drop_off"}, {"type": "self"}]}],
        },
    )
    resolver = ShippingResolver(
        provider,
        config={"mode_priority": ["me1", "me2"], "default_mode": "not_specified"},
    )

    selection = resolver.get_best_shipping_selection()

    assert selection["mode"] == "me1"
    assert selection["logistic_type"] == "xd_drop_off"


def test_shipping_resolver_selection_exposes_runtime_policy_hints() -> None:
    provider = _FakeShippingProvider(
        user_info={"id": 789},
        shipping_preferences={
            "modes": [],
            "logistics": [
                {
                    "mode": "me2",
                    "types": [{"type": "drop_off", "default": True}],
                    "tags": ["mandatory_free_shipping", "cross_border"],
                    "free_shipping": {"required": True},
                    "constraints": {"carrier": "me2", "dimensions": "required"},
                }
            ],
        },
    )
    resolver = ShippingResolver(
        provider,
        config={"mode_priority": ["me2", "me1"], "default_mode": "not_specified"},
    )

    selection = resolver.get_best_shipping_selection()

    assert selection["mode"] == "me2"
    assert selection["logistic_type"] == "drop_off"
    assert selection["tags"] == ["mandatory_free_shipping", "cross_border"]
    assert selection["free_shipping"] is True
    assert selection["constraints"] == {"carrier": "me2", "dimensions": "required"}
