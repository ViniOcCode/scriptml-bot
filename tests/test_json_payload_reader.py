"""Tests for JsonPayloadReader adapter."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mercadolivre_upload.adapters.json_payload_reader import (
    InvalidPayloadError,
    JsonPayloadReader,
    ReadPayloadResult,
)


def _make_valid_payload(**overrides: object) -> dict:
    base: dict = {
        "title": "Produto Teste",
        "category_id": "MLB271599",
        "price": 99.90,
        "currency_id": "BRL",
        "available_quantity": 10,
        "buying_mode": "buy_it_now",
        "listing_type_id": "gold_special",
        "condition": "new",
        "pictures": [{"source": "https://cdn.ml.com/abc.jpg"}],
        "_meta": {
            "description_plain_text": "Descrição do produto",
            "sku": "ABC-001",
            "category_ai_suggested": False,
        },
    }
    base.update(overrides)
    return base


def _write_payload(tmp_path: Path, payload: dict, name: str = "payload.json") -> Path:
    p = tmp_path / name
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


class TestJsonPayloadReader:
    reader = JsonPayloadReader()

    def test_read_campos_completos(self, tmp_path: Path) -> None:
        path = _write_payload(tmp_path, _make_valid_payload())
        result = self.reader.read(path)
        assert isinstance(result, ReadPayloadResult)
        assert result.category_id == "MLB271599"
        assert result.sku == "ABC-001"
        assert result.description == "Descrição do produto"
        assert result.ai_suggested is False
        assert result.payload["title"] == "Produto Teste"

    def test_read_campos_ausentes(self, tmp_path: Path) -> None:
        payload = _make_valid_payload()
        del payload["category_id"]
        path = _write_payload(tmp_path, payload)
        with pytest.raises(InvalidPayloadError, match="category_id"):
            self.reader.read(path)

    def test_read_pictures_vazio(self, tmp_path: Path) -> None:
        payload = _make_valid_payload()
        payload["pictures"] = []
        path = _write_payload(tmp_path, payload)
        with pytest.raises(InvalidPayloadError, match="pictures"):
            self.reader.read(path)

    def test_read_strip_meta(self, tmp_path: Path) -> None:
        path = _write_payload(tmp_path, _make_valid_payload())
        result = self.reader.read(path)
        assert "_meta" not in result.payload

    def test_read_description_extraida(self, tmp_path: Path) -> None:
        payload = _make_valid_payload()
        payload["_meta"]["description_plain_text"] = "Descrição especial"  # type: ignore[index]
        path = _write_payload(tmp_path, payload)
        result = self.reader.read(path)
        assert result.description == "Descrição especial"

    def test_read_sku_extraido(self, tmp_path: Path) -> None:
        payload = _make_valid_payload()
        payload["_meta"]["sku"] = "XYZ-999"  # type: ignore[index]
        path = _write_payload(tmp_path, payload)
        result = self.reader.read(path)
        assert result.sku == "XYZ-999"

    def test_read_ai_suggested(self, tmp_path: Path) -> None:
        payload = _make_valid_payload()
        payload["_meta"]["category_ai_suggested"] = True  # type: ignore[index]
        path = _write_payload(tmp_path, payload)
        result = self.reader.read(path)
        assert result.ai_suggested is True

    def test_read_arquivo_nao_existe(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            self.reader.read(tmp_path / "inexistente.json")

    def test_read_json_invalido(self, tmp_path: Path) -> None:
        p = tmp_path / "payload.json"
        p.write_text("{ invalid json }", encoding="utf-8")
        with pytest.raises(json.JSONDecodeError):
            self.reader.read(p)

    def test_read_batch_estrutura_correta(self, tmp_path: Path) -> None:
        cat_dir = tmp_path / "MLB271599"
        for sku in ("ABC-001", "ABC-002", "ABC-003"):
            sku_dir = cat_dir / sku
            sku_dir.mkdir(parents=True)
            _write_payload(sku_dir, _make_valid_payload(), "payload.json")

        results = JsonPayloadReader().read_batch(tmp_path)
        assert len(results) == 3
        _, payloads = zip(*results, strict=False)
        assert all(isinstance(r, ReadPayloadResult) for r in payloads)

    def test_read_batch_falha_individual(self, tmp_path: Path) -> None:
        cat_dir = tmp_path / "MLB271599"
        for sku in ("OK-001", "OK-002"):
            sku_dir = cat_dir / sku
            sku_dir.mkdir(parents=True)
            _write_payload(sku_dir, _make_valid_payload(), "payload.json")

        bad_dir = cat_dir / "BAD-003"
        bad_dir.mkdir(parents=True)
        bad_payload = _make_valid_payload()
        del bad_payload["category_id"]
        _write_payload(bad_dir, bad_payload, "payload.json")

        results = JsonPayloadReader().read_batch(tmp_path)
        assert len(results) == 3
        successes = [r for _, r in results if isinstance(r, ReadPayloadResult)]
        failures = [r for _, r in results if isinstance(r, Exception)]
        assert len(successes) == 2
        assert len(failures) == 1
        assert isinstance(failures[0], InvalidPayloadError)
