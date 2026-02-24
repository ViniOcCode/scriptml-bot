"""Tests for validate command batching and reporting."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
import typer

from mercadolivre_upload.cli.commands import validate as validate_cmd


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
    *,
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


def test_validate_groups_by_row_category_and_writes_summary(tmp_path, monkeypatch) -> None:
    rows = _build_rows(3)
    rows[0]["category_id"] = "MLB1000"
    rows[1]["category_id"] = "MLB1000"
    rows[2]["category_id"] = "MLB2000"

    parser_instance = MagicMock()
    parser_instance.parse.return_value = rows
    monkeypatch.setattr(validate_cmd, "SpreadsheetParser", MagicMock(return_value=parser_instance))
    monkeypatch.setattr(validate_cmd, "load_config", lambda: {})

    use_case_instance = MagicMock()
    use_case_instance.execute.side_effect = [
        {
            "validated": 2,
            "published": 2,
            "failed": 0,
            "errors": [],
            "item_results": [
                _make_item_result(
                    0,
                    "SKU001",
                    status="success",
                    cause_codes=["item.pictures.without_main"],
                    cause_taxonomy=[
                        {
                            "type": "warning",
                            "code": "item.pictures.without_main",
                            "message": "Main picture is recommended.",
                            "classification": "informational_warning",
                        }
                    ],
                    validation_decision={"mode": "strict", "action": "allow"},
                    policy_hash="hash-1000",
                    policy_summary={"category_id": "MLB1000"},
                    schema_contract_hash="schema-hash-1000",
                    schema_contract_summary={
                        "category_id": "MLB1000",
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
                    category_input="MLB1000",
                    category_resolved_id="MLB1000",
                    category_path=[{"id": "MLB1000", "name": "Cat 1000"}],
                    resolution_strategy="direct_id",
                ),
                _make_item_result(1, "SKU002", status="success"),
            ],
        },
        {
            "validated": 1,
            "published": 1,
            "failed": 0,
            "errors": [],
            "item_results": [_make_item_result(0, "SKU003", status="success")],
        },
    ]
    build_use_case_mock = MagicMock(return_value=use_case_instance)
    monkeypatch.setattr(validate_cmd, "build_publish_use_case", build_use_case_mock)

    excel = tmp_path / "products.xlsx"
    excel.write_text("dummy", encoding="utf-8")
    images = tmp_path / "images"
    images.mkdir()
    report_dir = tmp_path / "reports"

    validate_cmd.validate(
        excel=excel,
        images=images,
        category="MLB-DEFAULT",
        cache_dir=tmp_path / "cache",
        detailed=False,
        batch_size=5,
        report_dir=report_dir,
    )

    build_use_case_mock.assert_called_once()
    assert build_use_case_mock.call_args.kwargs["validation_only"] is True

    assert use_case_instance.execute.call_count == 2
    first_rows, first_category = use_case_instance.execute.call_args_list[0].args
    second_rows, second_category = use_case_instance.execute.call_args_list[1].args
    assert first_rows == rows[:2]
    assert second_rows == rows[2:]
    assert first_category == "MLB1000"
    assert second_category == "MLB2000"

    summary_files = list(report_dir.glob("validation-summary-*.json"))
    assert len(summary_files) == 1
    summary = json.loads(summary_files[0].read_text(encoding="utf-8"))
    assert summary["validated"] == 3
    assert summary["failed"] == 0
    assert summary["cause_code_counts"] == {"item.pictures.without_main": 1}
    assert summary["warning_code_counts"] == {
        "valid": {"item.pictures.without_main": 1},
        "failed": {},
    }
    assert summary["error_code_counts"] == {"valid": {}, "failed": {}}
    assert summary["top_cause_codes"] == [{"code": "item.pictures.without_main", "count": 1}]
    assert summary["top_warning_codes_by_status"] == {
        "valid": [{"code": "item.pictures.without_main", "count": 1}],
        "failed": [],
    }
    assert summary["top_error_codes_by_status"] == {"valid": [], "failed": []}
    assert len(summary["items"]) == 3
    assert {item["status"] for item in summary["items"]} == {"valid"}
    assert summary["items"][0]["cause_taxonomy"][0]["classification"] == "informational_warning"
    assert summary["items"][0]["validation_decision"]["action"] == "allow"
    assert summary["items"][0]["policy_hash"] == "hash-1000"
    assert summary["items"][0]["policy_summary"]["category_id"] == "MLB1000"
    assert summary["items"][0]["schema_contract_hash"] == "schema-hash-1000"
    assert summary["items"][0]["schema_contract_summary"]["category_id"] == "MLB1000"
    assert summary["items"][0]["identifier_gate"]["checked"] is True
    assert summary["items"][0]["category_resolved_id"] == "MLB1000"
    assert summary["items"][0]["resolution_strategy"] == "direct_id"
    assert summary["items"][0]["category_path"] == [{"id": "MLB1000", "name": "Cat 1000"}]
    assert summary["items"][0]["flow_routing"]["selected_flow"] == "user_products"
    assert summary["items"][0]["flow_routing"]["selected_model"] == "Model X"
    assert summary["items"][0]["flow_routing"]["up_family_name"] == "Linha Alpha"
    assert summary["items"][0]["image_diagnostics"]["status"] == "passed"
    assert summary["items"][0]["rollout_flags"]["strict_warning_gate_mode"] == "enforce"
    assert summary["items"][0]["shipping_policy"]["decision"]["source"] == "shipping_resolver"
    assert summary["rollout_flags"]["image_diagnostics_gate_mode"] == "enforce"
    success_without_explicit_evidence = next(
        item for item in summary["items"] if item["sku"] == "SKU002"
    )
    assert success_without_explicit_evidence["policy_hash"] is None
    assert success_without_explicit_evidence["policy_summary"] == {}
    assert success_without_explicit_evidence["schema_contract_hash"] is None
    assert success_without_explicit_evidence["schema_contract_summary"] == {}
    assert success_without_explicit_evidence["cause_taxonomy"] == []
    assert success_without_explicit_evidence["validation_decision"]["action"] == "allow"
    assert isinstance(success_without_explicit_evidence["flow_routing"], dict)


def test_validate_exits_with_failure_and_reports_cause_codes(tmp_path, monkeypatch) -> None:
    rows = _build_rows(1)

    parser_instance = MagicMock()
    parser_instance.parse.return_value = rows
    monkeypatch.setattr(validate_cmd, "SpreadsheetParser", MagicMock(return_value=parser_instance))
    monkeypatch.setattr(validate_cmd, "load_config", lambda: {})

    use_case_instance = MagicMock()
    use_case_instance.execute.return_value = {
        "validated": 0,
        "published": 0,
        "failed": 1,
        "errors": ["SKU001: body.invalid_fields: invalid attribute"],
        "item_results": [
            _make_item_result(
                0,
                "SKU001",
                status="failed",
                error="SKU001: body.invalid_fields: invalid attribute",
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
            )
        ],
    }
    monkeypatch.setattr(
        validate_cmd,
        "build_publish_use_case",
        MagicMock(return_value=use_case_instance),
    )

    excel = tmp_path / "products.xlsx"
    excel.write_text("dummy", encoding="utf-8")
    images = tmp_path / "images"
    images.mkdir()
    report_dir = tmp_path / "reports"

    with pytest.raises(typer.Exit) as exc_info:
        validate_cmd.validate(
            excel=excel,
            images=images,
            category="MLB1000",
            cache_dir=tmp_path / "cache",
            detailed=False,
            batch_size=5,
            report_dir=report_dir,
        )

    assert exc_info.value.exit_code == 1
    summary_files = list(report_dir.glob("validation-summary-*.json"))
    assert len(summary_files) == 1
    summary = json.loads(summary_files[0].read_text(encoding="utf-8"))
    assert summary["validated"] == 0
    assert summary["failed"] == 1
    assert summary["cause_code_counts"] == {"body.invalid_fields": 1}
    assert summary["warning_code_counts"] == {"valid": {}, "failed": {}}
    assert summary["error_code_counts"] == {"valid": {}, "failed": {"body.invalid_fields": 1}}
    assert summary["top_cause_codes"] == [{"code": "body.invalid_fields", "count": 1}]
    assert summary["top_warning_codes_by_status"] == {"valid": [], "failed": []}
    assert summary["top_error_codes_by_status"] == {
        "valid": [],
        "failed": [{"code": "body.invalid_fields", "count": 1}],
    }
    assert summary["items"][0]["cause_taxonomy"][0]["classification"] == "blocking_error"
    assert summary["items"][0]["validation_decision"]["action"] == "block"
    assert summary["items"][0]["category_used"] == "MLB1000"
    assert summary["items"][0]["policy_hash"] is None
    assert summary["items"][0]["policy_summary"] == {}
    assert summary["items"][0]["schema_contract_hash"] is None
    assert summary["items"][0]["schema_contract_summary"] == {}


def test_validate_uses_validation_decision_codes_when_taxonomy_is_missing(
    tmp_path, monkeypatch
) -> None:
    rows = _build_rows(1)

    parser_instance = MagicMock()
    parser_instance.parse.return_value = rows
    monkeypatch.setattr(validate_cmd, "SpreadsheetParser", MagicMock(return_value=parser_instance))
    monkeypatch.setattr(validate_cmd, "load_config", lambda: {})

    use_case_instance = MagicMock()
    use_case_instance.execute.return_value = {
        "validated": 0,
        "published": 0,
        "failed": 1,
        "errors": ["SKU001: publish failed"],
        "item_results": [
            _make_item_result(
                0,
                "SKU001",
                status="failed",
                error="SKU001: publish failed",
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
        validate_cmd,
        "build_publish_use_case",
        MagicMock(return_value=use_case_instance),
    )

    excel = tmp_path / "products.xlsx"
    excel.write_text("dummy", encoding="utf-8")
    images = tmp_path / "images"
    images.mkdir()
    report_dir = tmp_path / "reports"

    with pytest.raises(typer.Exit) as exc_info:
        validate_cmd.validate(
            excel=excel,
            images=images,
            category="MLB1000",
            cache_dir=tmp_path / "cache",
            detailed=False,
            batch_size=5,
            report_dir=report_dir,
        )

    assert exc_info.value.exit_code == 1
    summary_files = list(report_dir.glob("validation-summary-*.json"))
    assert len(summary_files) == 1
    summary = json.loads(summary_files[0].read_text(encoding="utf-8"))
    assert summary["cause_code_counts"] == {"item.pictures.without_main": 1}
    assert summary["warning_code_counts"] == {
        "valid": {},
        "failed": {"item.pictures.without_main": 1},
    }
    assert summary["error_code_counts"] == {"valid": {}, "failed": {}}
