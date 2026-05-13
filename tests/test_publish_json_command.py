"""Tests for single-file JSON publish helper command."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
import typer

import mercadolivre_upload.cli.commands.publish_json as publish_json_cmd
from mercadolivre_upload.application.publish_json_use_case import PublishJsonResult, PublishJsonUseCase


def _make_mock_use_case(status: str = "published", item_id: str = "MLB987654321") -> MagicMock:
    mock_use_case = MagicMock(spec=PublishJsonUseCase)
    mock_use_case.execute.return_value = PublishJsonResult(
        sku="ABC-001",
        path="payload.json",
        status=status,  # type: ignore[arg-type]
        item_id=item_id if status == "published" else None,
        warnings=[],
    )
    return mock_use_case


def test_publish_json_cmd_success(tmp_path: Path, monkeypatch) -> None:
    payload_path = tmp_path / "payload.json"
    payload_path.write_text("{}", encoding="utf-8")
    mock_use_case = _make_mock_use_case(status="published")
    monkeypatch.setattr(publish_json_cmd, "_build_use_case", lambda: mock_use_case)

    publish_json_cmd.publish_json(payload_path, report_dir=tmp_path / "reports")

    mock_use_case.execute.assert_called_once_with(payload_path, dry_run=False)


def test_publish_json_cmd_dry_run(tmp_path: Path, monkeypatch) -> None:
    payload_path = tmp_path / "payload.json"
    payload_path.write_text("{}", encoding="utf-8")
    mock_use_case = _make_mock_use_case(status="skipped")
    monkeypatch.setattr(publish_json_cmd, "_build_use_case", lambda: mock_use_case)

    publish_json_cmd.publish_json(payload_path, dry_run=True, report_dir=tmp_path / "reports")

    mock_use_case.execute.assert_called_once_with(payload_path, dry_run=True)


def test_publish_json_cmd_failure_exits_one(tmp_path: Path, monkeypatch) -> None:
    payload_path = tmp_path / "payload.json"
    payload_path.write_text("{}", encoding="utf-8")
    mock_use_case = _make_mock_use_case(status="failed")
    mock_use_case.execute.return_value = PublishJsonResult(
        sku=None, path=str(payload_path), status="failed", error="campos ausentes"
    )
    monkeypatch.setattr(publish_json_cmd, "_build_use_case", lambda: mock_use_case)

    with pytest.raises(typer.Exit) as exc_info:
        publish_json_cmd.publish_json(payload_path, report_dir=tmp_path / "reports")
    assert exc_info.value.exit_code == 1

