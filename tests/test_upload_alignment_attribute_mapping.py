"""Tests for upload alignment attribute mapping behavior."""

from __future__ import annotations

from mercadolivre_upload.application.attribute_builder import AttributeBuilderService
from mercadolivre_upload.domain.attribute_mapper import AttributeMapper
from mercadolivre_upload.domain.attribute_metadata import AttributeMeta
from tests.support.upload_alignment import (
    _build_product,
    _FakeCacheMapper,
    _FakeCategoryResolver,
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
