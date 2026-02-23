"""Tests for utility text helpers and parser exceptions."""

from __future__ import annotations

from mercadolivre_upload.adapters.spreadsheet.exceptions import (
    MissingColumnError,
    ParserError,
    ValidationError,
)
from mercadolivre_upload.domain import types as type_defs
from mercadolivre_upload.utils.text import (
    normalize_column_name,
    normalize_for_fuzzy_matching,
    normalize_text,
)


def test_text_normalization_helpers() -> None:
    assert normalize_column_name("Título do Anúncio!!") == "titulo_do_anuncio"
    assert normalize_column_name("") == ""

    assert normalize_text("  Ção  ") == "cao"
    assert normalize_text("  Ção  ", keep_accents=True) == "ção"

    assert normalize_for_fuzzy_matching("Café,  Premium!! 500ml") == "cafe premium 500ml"
    assert normalize_for_fuzzy_matching("") == ""


def test_parser_exceptions_payloads() -> None:
    validation_error = ValidationError("invalid", ["missing title"])
    assert isinstance(validation_error, ParserError)
    assert validation_error.errors == ["missing title"]

    missing = MissingColumnError(["sku", "title"])
    assert isinstance(missing, ParserError)
    assert missing.missing_columns == ["sku", "title"]
    assert "Missing required columns" in str(missing)


def test_typed_dict_definitions_are_usable() -> None:
    site: type_defs.ClipSite = {"site_id": "MLB", "logistic_type": "drop_off"}
    metadata: type_defs.ClipMetadata = {
        "site_id": "MLB",
        "moderation_status": "PUBLISHED",
    }
    clip: type_defs.ClipInfo = {"clip_uuid": "clip-123", "metadata": [metadata]}
    response: type_defs.ClipListResponse = {
        "parent_item_id": "MLB123",
        "parent_user_id": 123,
        "clips": [clip],
    }
    delete_request: type_defs.ClipDeleteRequest = {"sites": [site]}

    assert response["clips"][0]["clip_uuid"] == "clip-123"
    assert delete_request["sites"][0]["site_id"] == "MLB"
