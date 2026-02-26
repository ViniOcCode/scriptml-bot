"""Tests for upload batching validation behavior and code aggregation."""

import json
from unittest.mock import MagicMock

import pytest
import typer

from mercadolivre_upload.cli.commands import upload as upload_cmd
from tests.cli_report_builders import _build_rows, _make_item_result


def test_upload_rejects_invalid_batch_size(tmp_path):
    with pytest.raises(typer.Exit) as exc_info:
        upload_cmd.upload(
            excel=tmp_path / "products.xlsx",
            images=tmp_path / "images",
            category="MLB-CAT",
            cache_dir=tmp_path / "cache",
            dry_run=False,
            detailed=False,
            batch_size=0,
            report_dir=tmp_path / "reports",
        )

    assert exc_info.value.exit_code == 1


def test_upload_uses_validation_decision_codes_when_taxonomy_is_missing(tmp_path, monkeypatch):
    rows = _build_rows(1)

    monkeypatch.setattr(upload_cmd, "load_config", lambda: {})
    monkeypatch.setattr(upload_cmd, "AuthManager", MagicMock(return_value=MagicMock()))
    monkeypatch.setattr(upload_cmd, "MLApiClient", MagicMock(return_value=MagicMock()))
    monkeypatch.setattr(upload_cmd, "AttributeCache", MagicMock(return_value=MagicMock()))
    monkeypatch.setattr(upload_cmd, "CategoryAdapter", MagicMock(return_value=MagicMock()))
    monkeypatch.setattr(upload_cmd, "ImageUploader", MagicMock(return_value=MagicMock()))
    monkeypatch.setattr(upload_cmd, "CategoryResolver", MagicMock(return_value=MagicMock()))
    monkeypatch.setattr(upload_cmd, "ShippingResolver", MagicMock(return_value=MagicMock()))
    monkeypatch.setattr(upload_cmd, "FiscalService", MagicMock(return_value=MagicMock()))

    parser_instance = MagicMock()
    parser_instance.parse.return_value = rows
    monkeypatch.setattr(upload_cmd, "SpreadsheetParser", MagicMock(return_value=parser_instance))

    use_case_instance = MagicMock()
    use_case_instance.execute.return_value = {
        "published": 0,
        "failed": 1,
        "errors": ["SKU001: publish failed"],
        "clips_uploaded": 0,
        "clips_failed": 0,
        "clips_details": [],
        "item_results": [
            _make_item_result(
                0,
                "SKU001",
                "failed",
                "SKU001: publish failed",
                cause_codes=["item.pictures.without_main"],
                validation_decision={
                    "mode": "strict",
                    "action": "allow",
                    "classification_codes": {
                        "blocking_error": [],
                        "retryable_error": [],
                        "critical_warning": [],
                        "informational_warning": ["item.pictures.without_main"],
                    },
                },
            )
        ],
    }
    monkeypatch.setattr(
        upload_cmd,
        "PublishProductUseCase",
        MagicMock(return_value=use_case_instance),
    )

    import mercadolivre_upload.adapters.clip_uploader as clip_uploader_module
    import mercadolivre_upload.infrastructure.cache.prediction_cache as prediction_cache_module

    monkeypatch.setattr(clip_uploader_module, "ClipUploader", MagicMock(return_value=MagicMock()))
    monkeypatch.setattr(
        prediction_cache_module,
        "PredictionCache",
        MagicMock(return_value=MagicMock()),
    )

    excel = tmp_path / "products.xlsx"
    excel.write_text("dummy", encoding="utf-8")
    images = tmp_path / "images"
    images.mkdir()
    report_dir = tmp_path / "reports"

    upload_cmd.upload(
        excel=excel,
        images=images,
        category="MLB-CAT",
        cache_dir=tmp_path / "cache",
        dry_run=False,
        detailed=False,
        batch_size=5,
        report_dir=report_dir,
    )

    summary_files = list(report_dir.glob("upload-summary-*.json"))
    assert len(summary_files) == 1
    summary_data = json.loads(summary_files[0].read_text(encoding="utf-8"))
    assert summary_data["cause_code_counts"] == {"item.pictures.without_main": 1}
    assert summary_data["warning_code_counts"] == {
        "success": {},
        "failed": {"item.pictures.without_main": 1},
    }
    assert summary_data["error_code_counts"] == {"success": {}, "failed": {}}
