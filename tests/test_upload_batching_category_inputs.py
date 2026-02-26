"""Tests for upload batching category input grouping."""

import json
from unittest.mock import MagicMock

from mercadolivre_upload.cli.commands import upload as upload_cmd
from tests.cli_report_builders import _build_rows, _make_item_result


def test_upload_uses_mixed_row_level_category_inputs_and_default_fallback(tmp_path, monkeypatch):
    rows = _build_rows(4)
    rows[0]["category_id"] = "MLB1000"
    rows[1]["my category"] = "MLB1000"
    rows[2]["categoria-id"] = "MLB2000"

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
        {
            "published": 1,
            "failed": 0,
            "errors": [],
            "clips_uploaded": 0,
            "clips_failed": 0,
            "clips_details": [],
            "item_results": [_make_item_result(0, "SKU004", "success")],
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

    assert use_case_instance.execute.call_count == 3
    first_products, first_category = use_case_instance.execute.call_args_list[0].args
    second_products, second_category = use_case_instance.execute.call_args_list[1].args
    third_products, third_category = use_case_instance.execute.call_args_list[2].args
    assert first_products == rows[:2]
    assert second_products == rows[2:3]
    assert third_products == rows[3:]
    assert first_category == "MLB1000"
    assert second_category == "MLB2000"
    assert third_category == "MLB-DEFAULT"

    summary_files = list(report_dir.glob("upload-summary-*.json"))
    failed_files = list(report_dir.glob("failed-items-*.xlsx"))
    assert len(summary_files) == 1
    assert len(failed_files) == 0

    summary_data = json.loads(summary_files[0].read_text(encoding="utf-8"))
    assert summary_data["total_items"] == 4
    assert summary_data["published"] == 4
    assert summary_data["failed"] == 0
    assert len(summary_data["items"]) == 4
    categories_by_sku = {item["sku"]: item["category_input"] for item in summary_data["items"]}
    assert categories_by_sku == {
        "SKU001": "MLB1000",
        "SKU002": "MLB1000",
        "SKU003": "MLB2000",
        "SKU004": "MLB-DEFAULT",
    }
