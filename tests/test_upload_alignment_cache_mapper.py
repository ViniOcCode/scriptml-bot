"""Tests for upload alignment cache mapper behavior."""

from __future__ import annotations

from mercadolivre_upload.application.attribute_builder import AttributeBuilderService
from mercadolivre_upload.domain.attribute_metadata import AttributeMeta
from mercadolivre_upload.domain.cache_attribute_mapper import CachedAttributeMapper
from tests.support.upload_alignment import (
    _build_product,
    _FakeCacheMapper,
    _FakeCategoryResolver,
    _StaticAttributeCache,
)


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
