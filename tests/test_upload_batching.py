"""Tests for upload batching and report artifacts."""

import json
from unittest.mock import MagicMock

import pandas as pd
import pytest
import typer

from mercadolivre_upload.cli.commands import upload as upload_cmd


def _build_rows(count: int) -> list[dict[str, object]]:
    return [
        {
            "sku": f"SKU{i:03d}",
            "titulo": f"Produto {i}",
            "preco": 10.0 + i,
            "quantidade": 1,
            "condicao": "novo",
        }
        for i in range(1, count + 1)
    ]


def _make_item_result(
    index: int,
    sku: str,
    status: str,
    error: str | None = None,
) -> dict[str, object]:
    result: dict[str, object] = {
        "index": index,
        "sku": sku,
        "title": f"Produto {index + 1}",
        "status": status,
    }
    if error is not None:
        result["error"] = error
    return result


def test_upload_batches_and_writes_reports(tmp_path, monkeypatch):
    rows = _build_rows(10)

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
    use_case_instance.execute.side_effect = [
        {
            "published": 4,
            "failed": 1,
            "errors": ["SKU005: invalid attribute"],
            "clips_uploaded": 0,
            "clips_failed": 0,
            "clips_details": [],
            "item_results": [
                _make_item_result(0, "SKU001", "success"),
                _make_item_result(1, "SKU002", "success"),
                _make_item_result(2, "SKU003", "success"),
                _make_item_result(3, "SKU004", "success"),
                _make_item_result(4, "SKU005", "failed", "SKU005: invalid attribute"),
            ],
        },
        {
            "published": 4,
            "failed": 1,
            "errors": ["SKU009: API error"],
            "clips_uploaded": 0,
            "clips_failed": 0,
            "clips_details": [],
            "item_results": [
                _make_item_result(0, "SKU006", "success"),
                _make_item_result(1, "SKU007", "success"),
                _make_item_result(2, "SKU008", "success"),
                _make_item_result(3, "SKU009", "failed", "SKU009: API error"),
                _make_item_result(4, "SKU010", "success"),
            ],
        },
    ]
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

    assert use_case_instance.execute.call_count == 2
    first_call_products, first_call_category = use_case_instance.execute.call_args_list[0].args
    second_call_products, second_call_category = use_case_instance.execute.call_args_list[1].args
    assert first_call_products == rows[:5]
    assert second_call_products == rows[5:]
    assert first_call_category == "MLB-CAT"
    assert second_call_category == "MLB-CAT"

    summary_files = list(report_dir.glob("upload-summary-*.json"))
    failed_files = list(report_dir.glob("failed-items-*.xlsx"))
    assert len(summary_files) == 1
    assert len(failed_files) == 1

    summary_data = json.loads(summary_files[0].read_text(encoding="utf-8"))
    assert summary_data["batch_size"] == 5
    assert summary_data["total_items"] == 10
    assert summary_data["published"] == 8
    assert summary_data["failed"] == 2
    assert len(summary_data["batches"]) == 2
    assert len(summary_data["items"]) == 10

    failed_df = pd.read_excel(failed_files[0])
    assert set(failed_df["sku"].tolist()) == {"SKU005", "SKU009"}
    assert "_error" in failed_df.columns


def test_upload_uses_row_level_categories_when_available(tmp_path, monkeypatch):
    rows = _build_rows(3)
    rows[0]["category_id"] = "MLB1000"
    rows[1]["category_id"] = "MLB1000"
    rows[2]["category_id"] = "MLB2000"

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
    use_case_instance.execute.side_effect = [
        {
            "published": 2,
            "failed": 0,
            "errors": [],
            "clips_uploaded": 0,
            "clips_failed": 0,
            "clips_details": [],
            "item_results": [
                _make_item_result(0, "SKU001", "success"),
                _make_item_result(1, "SKU002", "success"),
            ],
        },
        {
            "published": 1,
            "failed": 0,
            "errors": [],
            "clips_uploaded": 0,
            "clips_failed": 0,
            "clips_details": [],
            "item_results": [_make_item_result(0, "SKU003", "success")],
        },
    ]
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
        category="MLB-DEFAULT",
        cache_dir=tmp_path / "cache",
        dry_run=False,
        detailed=False,
        batch_size=5,
        report_dir=report_dir,
    )

    assert use_case_instance.execute.call_count == 2
    first_products, first_category = use_case_instance.execute.call_args_list[0].args
    second_products, second_category = use_case_instance.execute.call_args_list[1].args
    assert first_products == rows[:2]
    assert second_products == rows[2:]
    assert first_category == "MLB1000"
    assert second_category == "MLB2000"

    summary_files = list(report_dir.glob("upload-summary-*.json"))
    failed_files = list(report_dir.glob("failed-items-*.xlsx"))
    assert len(summary_files) == 1
    assert len(failed_files) == 0

    summary_data = json.loads(summary_files[0].read_text(encoding="utf-8"))
    assert summary_data["total_items"] == 3
    assert summary_data["published"] == 3
    assert summary_data["failed"] == 0
    assert len(summary_data["items"]) == 3


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
