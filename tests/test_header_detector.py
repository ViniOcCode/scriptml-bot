"""Tests for spreadsheet header detector."""

from __future__ import annotations

import pandas as pd

from mercadolivre_upload.adapters.spreadsheet.header_detector import (
    HeaderDetector,
    _load_header_config,
)


def test_load_header_config_fallback(monkeypatch) -> None:
    def _raise(*_args, **_kwargs):
        raise ValueError("invalid config")

    monkeypatch.setattr(
        "mercadolivre_upload.adapters.spreadsheet.header_detector.load_yaml_config",
        _raise,
    )

    config = _load_header_config()
    assert config["column_patterns"] == {}
    assert config["header_indicators"] == []
    assert config["max_cell_length"] == 100
    assert config["max_row_length"] == 800


def test_detect_and_process_header_row() -> None:
    detector = HeaderDetector(
        config={
            "column_patterns": {
                "sku": [r"sku"],
                "titulo": [r"titulo"],
                "preco": [r"preco"],
            },
            "header_indicators": [(r"sku", 10), (r"titulo", 5), (r"preco", 5)],
            "max_cell_length": 80,
            "max_row_length": 400,
        }
    )

    df = pd.DataFrame(
        [
            ["texto muito longo " * 40, "", ""],
            ["100", "200", "300"],
            ["SKU", "Titulo", "Preco"],
            ["A1", "Produto", 10.0],
        ]
    )

    header_idx = detector.detect_header_row(df)
    assert header_idx == 2

    data_df, mapping = detector.process(df)
    assert detector.header_row == 2
    assert mapping["sku"] == "SKU"
    assert mapping["titulo"] == "Titulo"
    assert mapping["preco"] == "Preco"
    assert list(data_df.columns) == ["SKU", "Titulo", "Preco"]
    assert data_df.iloc[0]["SKU"] == "A1"


def test_build_column_mapping_ignores_duplicates() -> None:
    detector = HeaderDetector(
        config={
            "column_patterns": {
                "sku": [r"codigo", r"sku"],
                "titulo": [r"titulo"],
            },
            "header_indicators": [],
            "max_cell_length": 80,
            "max_row_length": 400,
        }
    )

    mapping = detector.build_column_mapping(["codigo sku", "titulo", "codigo sku"])
    assert mapping["sku"] == "codigo sku"
    assert mapping["titulo"] == "titulo"
