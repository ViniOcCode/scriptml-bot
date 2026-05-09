"""Tests for the public publish_payload API and CLI command."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from mercadolivre_upload.adapters.json_payload_reader import JsonPayloadReader
from mercadolivre_upload.application import publish_payload as publish_payload_api
from mercadolivre_upload.application.publish_json_use_case import PublishJsonResult
from mercadolivre_upload.cli import app


def _minimal_builder_payload() -> dict[str, object]:
    return {
        "payload": {
            "title": "Produto Teste",
            "category_id": "MLB271599",
            "price": 50.0,
            "currency_id": "BRL",
            "available_quantity": 10,
            "buying_mode": "buy_it_now",
            "listing_type_id": "gold_special",
            "condition": "new",
            "pictures": [{"id": "PIC123"}],
            "attributes": [{"id": "SELLER_SKU", "value_name": "ABC-001"}],
        },
        "description": "Descricao do produto",
        "_meta": {
            "sku": "ABC-001",
            "publication": {"publication_ready": True},
            "traceability": {"publish_item_skus": ["ABC-001"]},
        },
    }


def test_invalid_payload_file_returns_clear_error(tmp_path: Path) -> None:
    payload_path = tmp_path / "70_payload.json"
    payload_path.write_text("{invalid", encoding="utf-8")

    result = publish_payload_api.publish_payload_file(payload_path)

    assert result["status"] == "failed"
    assert "Invalid JSON payload" in result["errors"][0]


def test_minimal_valid_builder_payload_normalizes(tmp_path: Path) -> None:
    payload_path = tmp_path / "70_payload.json"
    payload_path.write_text(json.dumps(_minimal_builder_payload()), encoding="utf-8")

    result = JsonPayloadReader().read(payload_path)

    assert result.sku == "ABC-001"
    assert result.payload["category_id"] == "MLB271599"
    assert result.publication_ready is True
    assert result.description == "Descricao do produto"


def test_publish_payload_file_uses_mocked_use_case(tmp_path: Path, monkeypatch) -> None:
    payload_path = tmp_path / "70_payload.json"
    payload_path.write_text(json.dumps(_minimal_builder_payload()), encoding="utf-8")
    mock_use_case = MagicMock()
    mock_use_case.execute.return_value = PublishJsonResult(
        sku="ABC-001",
        path=str(payload_path),
        status="published",
        item_id="MLB123",
    )
    build_use_case = MagicMock(return_value=mock_use_case)
    monkeypatch.setattr(publish_payload_api, "_build_use_case", build_use_case)

    result = publish_payload_api.publish_payload_file(
        payload_path,
        report_dir=tmp_path / "reports",
        dry_run=False,
        publish_inactive=True,
    )

    build_use_case.assert_called_once_with(publish_inactive=True)
    mock_use_case.execute.assert_called_once_with(payload_path, dry_run=False)
    assert result["status"] == "published"
    assert result["item_id"] == "MLB123"
    assert result["errors"] == []
    assert Path(result["report_path"]).exists()


def test_publish_payload_cli_delegates_to_public_api(tmp_path: Path) -> None:
    payload_path = tmp_path / "70_payload.json"
    payload_path.write_text(json.dumps(_minimal_builder_payload()), encoding="utf-8")
    mock_module = MagicMock()
    mock_module.publish_payload_file.return_value = {
        "status": "published",
        "sku": "ABC-001",
        "item_id": "MLB123",
        "item_ids": [],
        "user_product_id": None,
        "errors": [],
        "warnings": [],
        "report_path": None,
    }

    with patch("mercadolivre_upload.cli.app.import_module", return_value=mock_module):
        result = CliRunner().invoke(app, ["publish-payload", str(payload_path)])

    assert result.exit_code == 0
    mock_module.publish_payload_file.assert_called_once()
    call_args = mock_module.publish_payload_file.call_args
    assert call_args.args == (payload_path,)
    assert call_args.kwargs["dry_run"] is False
    assert call_args.kwargs["publish_inactive"] is False
