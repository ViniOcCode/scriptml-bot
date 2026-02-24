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
    cause_codes: list[str] | None = None,
    cause_taxonomy: list[dict[str, object]] | None = None,
    validation_decision: dict[str, object] | None = None,
    policy_hash: str | None = None,
    policy_summary: dict[str, object] | None = None,
    schema_contract_hash: str | None = None,
    schema_contract_summary: dict[str, object] | None = None,
    identifier_gate: dict[str, object] | None = None,
    flow_routing: dict[str, object] | None = None,
    image_diagnostics: dict[str, object] | None = None,
    shipping_policy: dict[str, object] | None = None,
    rollout_flags: dict[str, object] | None = None,
    category_input: str | None = None,
    category_resolved_id: str | None = None,
    category_path: list[dict[str, object]] | None = None,
    resolution_strategy: str | None = None,
) -> dict[str, object]:
    result: dict[str, object] = {
        "index": index,
        "sku": sku,
        "title": f"Produto {index + 1}",
        "status": status,
    }
    if error is not None:
        result["error"] = error
    if cause_codes is not None:
        result["cause_codes"] = cause_codes
    if cause_taxonomy is not None:
        result["cause_taxonomy"] = cause_taxonomy
    if validation_decision is not None:
        result["validation_decision"] = validation_decision
    if policy_hash is not None:
        result["policy_hash"] = policy_hash
    if policy_summary is not None:
        result["policy_summary"] = policy_summary
    if schema_contract_hash is not None:
        result["schema_contract_hash"] = schema_contract_hash
    if schema_contract_summary is not None:
        result["schema_contract_summary"] = schema_contract_summary
    if identifier_gate is not None:
        result["identifier_gate"] = identifier_gate
    if flow_routing is not None:
        result["flow_routing"] = flow_routing
    if image_diagnostics is not None:
        result["image_diagnostics"] = image_diagnostics
    if shipping_policy is not None:
        result["shipping_policy"] = shipping_policy
    if rollout_flags is not None:
        result["rollout_flags"] = rollout_flags
    if category_input is not None:
        result["category_input"] = category_input
    if category_resolved_id is not None:
        result["category_resolved_id"] = category_resolved_id
    if category_path is not None:
        result["category_path"] = category_path
    if resolution_strategy is not None:
        result["resolution_strategy"] = resolution_strategy
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
                _make_item_result(
                    0,
                    "SKU001",
                    "success",
                    policy_hash="hash-cat",
                    policy_summary={"category_id": "MLB-CAT"},
                    schema_contract_hash="schema-hash-cat",
                    schema_contract_summary={
                        "category_id": "MLB-CAT",
                        "required_attribute_count": 1,
                    },
                    identifier_gate={"checked": True, "violations": []},
                    flow_routing={
                        "mode": "forced",
                        "selected_flow": "user_products",
                        "reason": "Using user-products flow",
                        "selected_model": "Model X",
                        "up_family_name": "Linha Alpha",
                    },
                    image_diagnostics={
                        "status": "passed",
                        "available": True,
                        "checked": 1,
                        "issues": [],
                        "results": [],
                    },
                    shipping_policy={
                        "decision": {"source": "shipping_resolver", "selected_mode": "me2"}
                    },
                    rollout_flags={
                        "validation_decision_mode": "strict",
                        "strict_warning_gate_mode": "enforce",
                        "image_diagnostics_gate_mode": "enforce",
                        "flow_user_products_enabled": True,
                        "flow_blocked_behavior": "fail",
                    },
                    category_input="MLB-CAT",
                    category_resolved_id="MLB-CAT",
                    category_path=[{"id": "MLB-CAT", "name": "Root"}],
                    resolution_strategy="direct_id",
                ),
                _make_item_result(1, "SKU002", "success"),
                _make_item_result(2, "SKU003", "success"),
                _make_item_result(3, "SKU004", "success"),
                _make_item_result(
                    4,
                    "SKU005",
                    "failed",
                    "SKU005: invalid attribute",
                    cause_codes=["body.invalid_fields"],
                    cause_taxonomy=[
                        {
                            "type": "error",
                            "code": "body.invalid_fields",
                            "message": "invalid attribute",
                            "classification": "blocking_error",
                        }
                    ],
                    validation_decision={"mode": "strict", "action": "block"},
                ),
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
    assert summary_data["cause_code_counts"] == {"body.invalid_fields": 1}
    assert summary_data["warning_code_counts"] == {"success": {}, "failed": {}}
    assert summary_data["error_code_counts"] == {
        "success": {},
        "failed": {"body.invalid_fields": 1},
    }
    assert summary_data["top_cause_codes"] == [{"code": "body.invalid_fields", "count": 1}]
    assert summary_data["top_warning_codes_by_status"] == {"success": [], "failed": []}
    assert summary_data["top_error_codes_by_status"] == {
        "success": [],
        "failed": [{"code": "body.invalid_fields", "count": 1}],
    }
    assert len(summary_data["batches"]) == 2
    assert len(summary_data["items"]) == 10
    assert summary_data["items"][0]["policy_hash"] == "hash-cat"
    assert summary_data["items"][0]["policy_summary"]["category_id"] == "MLB-CAT"
    assert summary_data["items"][0]["schema_contract_hash"] == "schema-hash-cat"
    assert summary_data["items"][0]["schema_contract_summary"]["category_id"] == "MLB-CAT"
    assert summary_data["items"][0]["identifier_gate"]["checked"] is True
    assert summary_data["items"][0]["category_input"] == "MLB-CAT"
    assert summary_data["items"][0]["category_resolved_id"] == "MLB-CAT"
    assert summary_data["items"][0]["resolution_strategy"] == "direct_id"
    assert summary_data["items"][0]["category_path"] == [{"id": "MLB-CAT", "name": "Root"}]
    assert summary_data["items"][0]["flow_routing"]["selected_flow"] == "user_products"
    assert summary_data["items"][0]["flow_routing"]["selected_model"] == "Model X"
    assert summary_data["items"][0]["flow_routing"]["up_family_name"] == "Linha Alpha"
    assert summary_data["items"][0]["image_diagnostics"]["status"] == "passed"
    assert summary_data["items"][0]["rollout_flags"]["strict_warning_gate_mode"] == "enforce"
    assert summary_data["rollout_flags"]["image_diagnostics_gate_mode"] == "enforce"
    assert summary_data["items"][0]["shipping_policy"]["decision"]["source"] == "shipping_resolver"
    success_without_explicit_evidence = next(
        item for item in summary_data["items"] if item["sku"] == "SKU002"
    )
    assert success_without_explicit_evidence["policy_hash"] is None
    assert success_without_explicit_evidence["policy_summary"] == {}
    assert success_without_explicit_evidence["schema_contract_hash"] is None
    assert success_without_explicit_evidence["schema_contract_summary"] == {}
    assert success_without_explicit_evidence["cause_taxonomy"] == []
    assert success_without_explicit_evidence["validation_decision"]["action"] == "allow"
    assert isinstance(success_without_explicit_evidence["flow_routing"], dict)
    failed_item = next(item for item in summary_data["items"] if item["sku"] == "SKU005")
    assert failed_item["cause_codes"] == ["body.invalid_fields"]
    assert failed_item["cause_taxonomy"][0]["classification"] == "blocking_error"
    assert failed_item["validation_decision"]["action"] == "block"

    failed_df = pd.read_excel(failed_files[0])
    assert set(failed_df["sku"].tolist()) == {"SKU005", "SKU009"}
    assert "_error" in failed_df.columns
    assert "_cause_codes" in failed_df.columns
    assert "_cause_taxonomy" in failed_df.columns
    assert "_validation_decision" in failed_df.columns


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
