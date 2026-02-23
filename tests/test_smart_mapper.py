"""Tests for SmartAttributeMapper."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mercadolivre_upload.domain.smart_mapper import SmartAttributeMapper


class _FakeApiClient:
    def __init__(self, payloads: dict[str, Any]):
        self.payloads = payloads
        self.calls: list[str] = []

    def get_category_attributes(self, category_id: str) -> Any:
        self.calls.append(category_id)
        payload = self.payloads[category_id]
        if isinstance(payload, Exception):
            raise payload
        return payload


def _write_config(tmp_path: Path) -> Path:
    config_path = tmp_path / "standard_fields.yaml"
    config_path.write_text(
        """
standard_fields:
  sku:
    exact_matches: ["sku", "codigo"]
    patterns: []
    exclude_patterns: []
  weight:
    exact_matches: []
    patterns: ["peso fisico"]
    exclude_patterns: ["peso liquido"]
fiscal_fields:
  ncm:
    patterns: ["ncm"]
    exclude_patterns: []
image_fields: {}
excluded_columns: ["ignorar"]
""".strip(),
        encoding="utf-8",
    )
    return config_path


def test_map_columns_with_standard_and_api_matches(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    api = _FakeApiClient(
        {
            "cat1": [
                {"id": "BRAND", "name": "Marca"},
                {"id": "AUTHOR", "name": "Autor do Livro"},
            ]
        }
    )
    mapper = SmartAttributeMapper(api, config_path=str(config_path), min_confidence=0.8)

    mappings, unmapped = mapper.map_columns(
        ["SKU", "Marca", "Autor", "Peso Fisico", "Peso Liquido", "Ignorar", "Sem Match"],
        "cat1",
    )

    by_col = {m.excel_column: m for m in mappings}
    assert by_col["SKU"].mapping_type == "exact_standard"
    assert by_col["SKU"].target_field == "sku"
    assert by_col["Marca"].mapping_type == "exact_api"
    assert by_col["Marca"].target_field == "BRAND"
    assert by_col["Autor"].mapping_type == "fuzzy_api"
    assert by_col["Autor"].target_field == "AUTHOR"
    assert by_col["Peso Fisico"].mapping_type == "pattern_standard"

    assert "Ignorar" not in by_col
    unmapped_cols = {u.excel_column for u in unmapped}
    assert "Sem Match" in unmapped_cols
    assert "Peso Liquido" in unmapped_cols

    summary = mapper.get_mapping_summary(mappings, unmapped)
    assert summary["mapped"] == len(mappings)
    assert summary["unmapped"] == len(unmapped)
    assert summary["total_columns"] == len(mappings) + len(unmapped)


def test_get_category_attributes_cache_and_error_paths(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    api = _FakeApiClient(
        {
            "cat1": [{"id": "A", "name": "Atributo"}],
            "bad": {"id": "A"},
            "boom": RuntimeError("boom"),
        }
    )
    mapper = SmartAttributeMapper(api, config_path=str(config_path))

    attrs_first = mapper._get_category_attributes("cat1")
    attrs_second = mapper._get_category_attributes("cat1")
    assert attrs_first == attrs_second
    assert api.calls.count("cat1") == 1

    assert mapper._get_category_attributes("bad") == []
    assert mapper._get_category_attributes("boom") == []


def test_simplify_portuguese_words(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    mapper = SmartAttributeMapper(_FakeApiClient({"cat": []}), config_path=str(config_path))
    assert mapper._simplify_portuguese("titulo do livro de romance") == "titulo livro romance"
