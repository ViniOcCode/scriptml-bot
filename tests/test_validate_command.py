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
                _make_item_result(0, "SKU001", status="success"),
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
    assert summary["cause_code_counts"] == {}
    assert len(summary["items"]) == 3
    assert {item["status"] for item in summary["items"]} == {"valid"}


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
    assert summary["items"][0]["category_used"] == "MLB1000"
