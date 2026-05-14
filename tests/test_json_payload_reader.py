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


def _make_envelope(payload: dict, meta: dict | None = None) -> dict:
    base_meta = {
        "description_plain_text": "Descrição do produto",
        "sku": "ABC-001",
        "category_ai_suggested": False,
    }
    if meta:
        base_meta.update(meta)
    return {"payload": payload, "_meta": base_meta}


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

    def test_read_description_top_level_quando_meta_ausente(self, tmp_path: Path) -> None:
        payload = _make_valid_payload()
        payload.pop("_meta", None)
        path = _write_payload(
            tmp_path,
            {
                "payload": payload,
                "description": "Descrição vindo da raiz",
                "_meta": {"sku": "ABC-001"},
            },
        )
        result = self.reader.read(path)
        assert result.description == "Descrição vindo da raiz"

    def test_read_fiscal_items_extraidos_da_raiz(self, tmp_path: Path) -> None:
        payload = _make_valid_payload()
        payload.pop("_meta", None)
        path = _write_payload(
            tmp_path,
            {
                "payload": payload,
                "_meta": {"sku": "ABC-001"},
                "fiscal": {
                    "items": [
                        {
                            "sku": "ABC-001",
                            "type": "single",
                            "measurement_unit": "UN",
                            "tax_information": {
                                "ncm": "9018.39.29",
                                "origin_type": "reseller",
                                "origin_detail": "0",
                            },
                        }
                    ]
                },
            },
        )
        result = self.reader.read(path)
        assert len(result.fiscal_items) == 1
        assert result.fiscal_items[0]["sku"] == "ABC-001"

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

    # --- variation payload tests ---

    def test_variation_payload_sem_price_root_aceito(self, tmp_path: Path) -> None:
        """price/available_quantity at root are optional when variations present."""
        payload = _make_valid_payload()
        del payload["price"]
        del payload["available_quantity"]
        payload["variations"] = [
            {"price": 59.90, "available_quantity": 5, "attribute_combinations": []}
        ]
        path = _write_payload(tmp_path, payload)
        result = JsonPayloadReader().read(path)
        assert isinstance(result, ReadPayloadResult)

    def test_variation_payload_currency_id_injetado_como_brl(self, tmp_path: Path) -> None:
        """currency_id is injected as 'BRL' when absent (ml-builder omits it)."""
        payload = _make_valid_payload()
        del payload["price"]
        del payload["available_quantity"]
        del payload["currency_id"]
        payload["variations"] = [
            {"price": 59.90, "available_quantity": 5, "attribute_combinations": []}
        ]
        path = _write_payload(tmp_path, payload)
        result = JsonPayloadReader().read(path)
        assert result.payload["currency_id"] == "BRL"

    def test_payload_sem_variation_ainda_exige_price_root(self, tmp_path: Path) -> None:
        """Non-variation payloads must still have price at root."""
        payload = _make_valid_payload()
        del payload["price"]
        path = _write_payload(tmp_path, payload)
        with pytest.raises(InvalidPayloadError, match="price"):
            JsonPayloadReader().read(path)

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

    def test_read_nested_payload_envelope_legacy(self, tmp_path: Path) -> None:
        path = _write_payload(
            tmp_path,
            _make_envelope(
                _make_valid_payload(),
                {"publication": {"model": "legacy_items"}},
            ),
        )
        result = self.reader.read(path)
        assert result.upload_mode == "legacy_items"
        assert result.payload["title"] == "Produto Teste"
        assert "_meta" not in result.payload

    def test_read_nested_payload_envelope_legacy_via_seller_model_items(
        self, tmp_path: Path
    ) -> None:
        path = _write_payload(
            tmp_path,
            _make_envelope(
                _make_valid_payload(),
                {"publication": {"seller_model": "items"}},
            ),
        )
        result = self.reader.read(path)
        assert result.upload_mode == "legacy_items"

    def test_read_nested_payload_envelope_legacy_item_wrapper(self, tmp_path: Path) -> None:
        legacy_payload = _make_valid_payload()
        legacy_payload.pop("_meta", None)
        path = _write_payload(
            tmp_path,
            {
                "payload": {"item": legacy_payload},
                "_meta": {"publication": {"seller_model": "items"}},
            },
        )
        result = self.reader.read(path)
        assert result.upload_mode == "legacy_items"
        assert result.payload["title"] == "Produto Teste"

    def test_read_nested_payload_envelope_user_products(self, tmp_path: Path) -> None:
        path = _write_payload(
            tmp_path,
            _make_envelope(
                {
                    "model": "user_products",
                    "family_name": "Linha Alpha",
                    "items": [
                        {
                            "category_id": "MLB271599",
                            "price": 99.90,
                            "currency_id": "BRL",
                            "available_quantity": 10,
                            "buying_mode": "buy_it_now",
                            "listing_type_id": "gold_special",
                            "condition": "new",
                            "pictures": [{"source": "https://cdn.ml.com/abc.jpg"}],
                        }
                    ],
                },
                {"publication": {"model": "user_products"}},
            ),
        )
        result = self.reader.read(path)
        assert result.upload_mode == "user_products"
        assert result.payload["family_name"] == "Linha Alpha"
        assert "model" not in result.payload
        assert len(result.payload["items"]) == 1

    def test_read_user_products_requires_items(self, tmp_path: Path) -> None:
        path = _write_payload(
            tmp_path,
            _make_envelope(
                {
                    "model": "user_products",
                    "family_name": "Linha Alpha",
                    "items": [],
                },
                {"publication": {"model": "user_products"}},
            ),
        )
        with pytest.raises(InvalidPayloadError, match="items"):
            self.reader.read(path)

    def test_read_user_products_payload_array_via_seller_model(self, tmp_path: Path) -> None:
        path = _write_payload(
            tmp_path,
            {
                "payload": [
                    {
                        "family_name": "Linha Alpha",
                        "category_id": "MLB271599",
                        "price": 99.90,
                        "currency_id": "BRL",
                        "available_quantity": 10,
                        "buying_mode": "buy_it_now",
                        "listing_type_id": "gold_special",
                        "condition": "new",
                        "pictures": [{"source": "https://cdn.ml.com/abc.jpg"}],
                    }
                ],
                "_meta": {"publication": {"seller_model": "user_products"}},
            },
        )
        result = self.reader.read(path)
        assert result.upload_mode == "user_products"
        assert isinstance(result.payload["payload"], list)
        assert len(result.payload["payload"]) == 1
        assert result.category_id == "MLB271599"

    def test_read_user_products_payload_array_requires_family_name_per_item(
        self, tmp_path: Path
    ) -> None:
        path = _write_payload(
            tmp_path,
            {
                "payload": [
                    {
                        "category_id": "MLB271599",
                        "price": 99.90,
                        "currency_id": "BRL",
                        "available_quantity": 10,
                        "buying_mode": "buy_it_now",
                        "listing_type_id": "gold_special",
                        "condition": "new",
                        "pictures": [{"source": "https://cdn.ml.com/abc.jpg"}],
                    }
                ],
                "_meta": {"publication": {"seller_model": "user_products"}},
            },
        )
        with pytest.raises(InvalidPayloadError, match="family_name"):
            self.reader.read(path)

    def test_read_payload_model_mismatch_raises(self, tmp_path: Path) -> None:
        path = _write_payload(
            tmp_path,
            _make_envelope(
                {
                    "model": "user_products",
                    "family_name": "Linha Alpha",
                    "items": [{"category_id": "MLB271599"}],
                },
                {"publication": {"model": "legacy_items"}},
            ),
        )
        with pytest.raises(InvalidPayloadError, match="divergem"):
            self.reader.read(path)

    def test_read_missing_payload_field_raises(self, tmp_path: Path) -> None:
        path = _write_payload(tmp_path, {"_meta": {"sku": "ABC-001"}})
        with pytest.raises(InvalidPayloadError, match="payload"):
            self.reader.read(path)

    # --- new _meta fields ---

    def test_read_publication_ready_true(self, tmp_path: Path) -> None:
        payload = _make_valid_payload()
        payload["_meta"]["publication_ready"] = True  # type: ignore[index]
        path = _write_payload(tmp_path, payload)
        result = self.reader.read(path)
        assert result.publication_ready is True

    def test_read_publication_ready_false_with_blocking_reasons(self, tmp_path: Path) -> None:
        payload = _make_valid_payload()
        payload["_meta"]["publication_ready"] = False  # type: ignore[index]
        payload["_meta"]["blocking_reasons"] = ["fiscal not resolved"]  # type: ignore[index]
        path = _write_payload(tmp_path, payload)
        result = self.reader.read(path)
        assert result.publication_ready is False
        assert "fiscal not resolved" in result.blocking_reasons

    def test_read_publication_ready_absent_is_none(self, tmp_path: Path) -> None:
        """Absent publication_ready in _meta yields None (backward compat)."""
        path = _write_payload(tmp_path, _make_valid_payload())
        result = self.reader.read(path)
        assert result.publication_ready is None

    def test_read_publication_ready_from_meta_publication(self, tmp_path: Path) -> None:
        payload = _make_valid_payload()
        payload["_meta"]["publication"] = {"publication_ready": True}  # type: ignore[index]
        path = _write_payload(tmp_path, payload)
        result = self.reader.read(path)
        assert result.publication_ready is True

    def test_read_category_confidence_extracted(self, tmp_path: Path) -> None:
        payload = _make_valid_payload()
        payload["_meta"]["category_confidence"] = 0.85  # type: ignore[index]
        path = _write_payload(tmp_path, payload)
        result = self.reader.read(path)
        assert result.category_confidence == pytest.approx(0.85)

    def test_read_category_confidence_from_meta_category(self, tmp_path: Path) -> None:
        payload = _make_valid_payload()
        payload["_meta"]["category"] = {"confidence": 0.77}  # type: ignore[index]
        path = _write_payload(tmp_path, payload)
        result = self.reader.read(path)
        assert result.category_confidence == pytest.approx(0.77)

    def test_read_category_confidence_absent_is_none(self, tmp_path: Path) -> None:
        path = _write_payload(tmp_path, _make_valid_payload())
        result = self.reader.read(path)
        assert result.category_confidence is None

    def test_read_reviewed_fiscal_extracted(self, tmp_path: Path) -> None:
        payload = _make_valid_payload()
        payload["_meta"]["reviewed_fiscal"] = True  # type: ignore[index]
        path = _write_payload(tmp_path, payload)
        result = self.reader.read(path)
        assert result.reviewed_fiscal is True

    def test_read_traceability_publish_item_skus(self, tmp_path: Path) -> None:
        payload = _make_valid_payload()
        payload["_meta"]["traceability"] = {"publish_item_skus": [" SKU-A ", "SKU-B", None]}  # type: ignore[index]
        path = _write_payload(tmp_path, payload)
        result = self.reader.read(path)
        assert result.publish_item_skus == ["SKU-A", "SKU-B"]

    # --- picture URL validation ---

    def test_picture_source_http_valid(self, tmp_path: Path) -> None:
        """HTTPS picture sources pass validation without error."""
        path = _write_payload(tmp_path, _make_valid_payload())
        result = self.reader.read(path)
        assert result is not None

    def test_picture_source_local_path_raises(self, tmp_path: Path) -> None:
        payload = _make_valid_payload()
        payload["pictures"] = [{"source": "/tmp/foto.jpg"}]
        path = _write_payload(tmp_path, payload)
        with pytest.raises(InvalidPayloadError, match="local"):
            self.reader.read(path)

    def test_picture_source_relative_path_raises(self, tmp_path: Path) -> None:
        payload = _make_valid_payload()
        payload["pictures"] = [{"source": "images/foto.jpg"}]
        path = _write_payload(tmp_path, payload)
        with pytest.raises(InvalidPayloadError, match="local"):
            self.reader.read(path)

    def test_picture_source_windows_path_raises(self, tmp_path: Path) -> None:
        payload = _make_valid_payload()
        payload["pictures"] = [{"source": "C:\\Users\\foto.jpg"}]
        path = _write_payload(tmp_path, payload)
        with pytest.raises(InvalidPayloadError, match="local"):
            self.reader.read(path)

    # --- user_products per-item required fields ---

    def _make_up_envelope(self, items: list, *, family_name: str = "Linha Alpha") -> dict:
        return _make_envelope(
            {
                "model": "user_products",
                "family_name": family_name,
                "items": items,
            },
            {"publication": {"model": "user_products"}},
        )

    def _valid_up_item(self, **overrides: object) -> dict:
        base: dict = {
            "category_id": "MLB271599",
            "price": 99.90,
            "currency_id": "BRL",
            "available_quantity": 10,
            "buying_mode": "buy_it_now",
            "listing_type_id": "gold_special",
            "condition": "new",
            "pictures": [{"source": "https://cdn.ml.com/abc.jpg"}],
        }
        base.update(overrides)
        return base

    @pytest.mark.parametrize(
        "missing_field",
        [
            "category_id",
            "price",
            "currency_id",
            "available_quantity",
            "buying_mode",
            "listing_type_id",
            "condition",
            "pictures",
        ],
    )
    def test_up_item_missing_required_field_raises(
        self, tmp_path: Path, missing_field: str
    ) -> None:
        item = self._valid_up_item()
        del item[missing_field]
        path = _write_payload(tmp_path, self._make_up_envelope([item]))
        with pytest.raises(InvalidPayloadError, match=missing_field):
            self.reader.read(path)

    def test_up_item_all_required_fields_passes(self, tmp_path: Path) -> None:
        path = _write_payload(tmp_path, self._make_up_envelope([self._valid_up_item()]))
        result = self.reader.read(path)
        assert result.upload_mode == "user_products"

    def test_existing_up_selling_condition_does_not_require_inherited_fields(
        self, tmp_path: Path
    ) -> None:
        envelope = _make_envelope(
            {
                "model": "user_products",
                "items": [
                    {
                        "user_product_id": "MLBU123",
                        "category_id": "MLB271599",
                        "price": 99.90,
                        "currency_id": "BRL",
                        "buying_mode": "buy_it_now",
                        "listing_type_id": "gold_special",
                    }
                ],
            },
            {"publication": {"model": "user_products"}},
        )

        result = self.reader.read(_write_payload(tmp_path, envelope))

        assert result.upload_mode == "user_products"
        assert "family_name" not in result.payload

    def test_existing_up_selling_condition_keeps_classic_contract_separate(
        self, tmp_path: Path
    ) -> None:
        classic_payload = _make_valid_payload()
        classic_payload.pop("pictures")

        with pytest.raises(InvalidPayloadError, match="pictures"):
            self.reader.read(_write_payload(tmp_path, classic_payload))

    def test_up_item_missing_family_name_raises_when_envelope_enabled(self, tmp_path: Path) -> None:
        from mercadolivre_upload.adapters import json_payload_reader

        original = json_payload_reader.VALIDATE_UP_ENVELOPE
        json_payload_reader.VALIDATE_UP_ENVELOPE = True
        try:
            envelope = _make_envelope(
                {"model": "user_products", "items": [self._valid_up_item()]},
                {"publication": {"model": "user_products"}},
            )
            path = _write_payload(tmp_path, envelope)
            with pytest.raises(InvalidPayloadError, match="family_name"):
                self.reader.read(path)
        finally:
            json_payload_reader.VALIDATE_UP_ENVELOPE = original

    def test_up_item_missing_family_name_allowed_when_envelope_disabled(
        self, tmp_path: Path
    ) -> None:
        from mercadolivre_upload.adapters import json_payload_reader

        original = json_payload_reader.VALIDATE_UP_ENVELOPE
        json_payload_reader.VALIDATE_UP_ENVELOPE = False
        try:
            envelope = _make_envelope(
                {"model": "user_products", "items": [self._valid_up_item()]},
                {"publication": {"model": "user_products"}},
            )
            path = _write_payload(tmp_path, envelope)
            result = self.reader.read(path)
            assert result.upload_mode == "user_products"
        finally:
            json_payload_reader.VALIDATE_UP_ENVELOPE = original

    # --- F1: _meta.sku fallback ---

    def test_sku_fallback_from_publish_item_skus(self, tmp_path: Path) -> None:
        """When _meta.sku is absent, fallback to _meta.traceability.publish_item_skus[0]."""
        payload = _make_valid_payload()
        payload["_meta"].pop("sku")  # type: ignore[attr-defined]
        payload["_meta"]["traceability"] = {"publish_item_skus": ["FALLBACK-SKU"]}  # type: ignore[index]
        path = _write_payload(tmp_path, payload)
        result = self.reader.read(path)
        assert result.sku == "FALLBACK-SKU"

    # --- N1: attribute_suggestions ---

    def test_attribute_suggestions_auto_apply_extracted(self, tmp_path: Path) -> None:
        """attribute_suggestions with band=auto_apply are surfaced in ReadPayloadResult."""
        payload = _make_valid_payload()
        payload["_meta"]["attribute_suggestions"] = [  # type: ignore[index]
            {
                "attr_id": "COLOR",
                "canonical_value": "Azul",
                "band": "auto_apply",
                "confidence": 0.95,
            },
            {
                "attr_id": "BRAND",
                "canonical_value": "Nike",
                "band": "auto_apply",
                "confidence": 0.88,
            },
        ]
        path = _write_payload(tmp_path, payload)
        result = self.reader.read(path)
        assert len(result.attribute_suggestions) == 2
        assert result.attribute_suggestions[0]["attr_id"] == "COLOR"
        assert result.attribute_suggestions[1]["attr_id"] == "BRAND"

    def test_attribute_suggestions_filters_non_auto_apply(self, tmp_path: Path) -> None:
        """Suggestions where band != auto_apply are filtered out."""
        payload = _make_valid_payload()
        payload["_meta"]["attribute_suggestions"] = [  # type: ignore[index]
            {
                "attr_id": "COLOR",
                "canonical_value": "Azul",
                "band": "auto_apply",
                "confidence": 0.95,
            },
            {"attr_id": "SIZE", "canonical_value": "M", "band": "manual", "confidence": 0.60},
            {"attr_id": "BRAND", "canonical_value": "Nike", "band": None, "confidence": 0.50},
        ]
        path = _write_payload(tmp_path, payload)
        result = self.reader.read(path)
        assert len(result.attribute_suggestions) == 1
        assert result.attribute_suggestions[0]["attr_id"] == "COLOR"

    def test_attribute_suggestions_absent_is_empty(self, tmp_path: Path) -> None:
        """When attribute_suggestions is absent, result has empty list."""
        path = _write_payload(tmp_path, _make_valid_payload())
        result = self.reader.read(path)
        assert result.attribute_suggestions == []
