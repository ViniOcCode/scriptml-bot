"""Tests for publish_json and publish_batch CLI command functions."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import typer

import mercadolivre_upload.cli.commands.publish_json as publish_json_cmd
from mercadolivre_upload.adapters.json_payload_reader import (
    ReadPayloadResult,
)
from mercadolivre_upload.application.publish_json_use_case import (
    PublishJsonResult,
    PublishJsonUseCase,
)
from mercadolivre_upload.application.validators.seller_policy import default_seller_config


def _make_read_result(
    sku: str = "ABC-001",
    category_id: str = "MLB271599",
    listing_type_id: str = "gold_special",
    price: float = 50.0,
    description: str | None = "Descrição",
    ai_suggested: bool = False,
) -> ReadPayloadResult:
    return ReadPayloadResult(
        payload={
            "title": "Produto",
            "category_id": category_id,
            "price": price,
            "currency_id": "BRL",
            "available_quantity": 1,
            "buying_mode": "buy_it_now",
            "listing_type_id": listing_type_id,
            "condition": "new",
            "pictures": [{"source": "https://cdn.ml.com/img.jpg"}],
        },
        description=description,
        sku=sku,
        category_id=category_id,
        ai_suggested=ai_suggested,
    )


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


class TestPublishJsonCmd:
    def test_publish_json_cmd_sucesso(self, tmp_path: Path, monkeypatch) -> None:
        payload_path = tmp_path / "payload.json"
        payload_path.write_text("{}", encoding="utf-8")

        mock_use_case = _make_mock_use_case(status="published")
        monkeypatch.setattr(publish_json_cmd, "_build_use_case", lambda: mock_use_case)

        publish_json_cmd.publish_json(payload_path, report_dir=tmp_path / "reports")

        mock_use_case.execute.assert_called_once_with(payload_path, dry_run=False)

    def test_publish_json_cmd_dry_run(self, tmp_path: Path, monkeypatch) -> None:
        payload_path = tmp_path / "payload.json"
        payload_path.write_text("{}", encoding="utf-8")

        mock_use_case = _make_mock_use_case(status="skipped")
        monkeypatch.setattr(publish_json_cmd, "_build_use_case", lambda: mock_use_case)

        publish_json_cmd.publish_json(payload_path, dry_run=True, report_dir=tmp_path / "reports")

        mock_use_case.execute.assert_called_once_with(payload_path, dry_run=True)

    def test_publish_json_cmd_invalido_exit_1(self, tmp_path: Path, monkeypatch) -> None:
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


class TestPublishBatchCmd:
    def _setup_batch_dir(self, tmp_path: Path, skus: list[str]) -> Path:
        batch_dir = tmp_path / "batch"
        cat_dir = batch_dir / "MLB271599"
        for sku in skus:
            sku_dir = cat_dir / sku
            sku_dir.mkdir(parents=True)
            (sku_dir / "payload.json").write_text("{}", encoding="utf-8")
        return batch_dir

    def test_publish_batch_cmd_dir(self, tmp_path: Path, monkeypatch) -> None:
        batch_dir = self._setup_batch_dir(tmp_path, ["SKU001", "SKU002", "SKU003"])
        mock_reader = MagicMock()
        mock_reader.read_batch.return_value = [
            (batch_dir / f"MLB271599/SKU{i:03d}/payload.json", _make_read_result(sku=f"SKU{i:03d}"))
            for i in range(1, 4)
        ]
        mock_use_case = MagicMock(spec=PublishJsonUseCase)
        mock_use_case.execute.side_effect = [
            PublishJsonResult(sku=f"SKU{i:03d}", path="p", status="published", item_id=f"MLB{i}")
            for i in range(1, 4)
        ]

        monkeypatch.setattr(publish_json_cmd, "_build_use_case", lambda: mock_use_case)
        monkeypatch.setattr(
            publish_json_cmd, "JsonPayloadReader", MagicMock(return_value=mock_reader)
        )

        publish_json_cmd.publish_batch(batch_dir, report_dir=tmp_path / "reports")

        assert mock_use_case.execute.call_count == 3

    def test_publish_batch_cmd_dry_run(self, tmp_path: Path, monkeypatch) -> None:
        batch_dir = self._setup_batch_dir(tmp_path, ["SKU001"])
        mock_reader = MagicMock()
        mock_reader.read_batch.return_value = [
            (batch_dir / "MLB271599/SKU001/payload.json", _make_read_result())
        ]
        mock_use_case = MagicMock(spec=PublishJsonUseCase)
        mock_use_case.execute.return_value = PublishJsonResult(
            sku="SKU001", path="p", status="skipped"
        )

        monkeypatch.setattr(publish_json_cmd, "_build_use_case", lambda: mock_use_case)
        monkeypatch.setattr(
            publish_json_cmd, "JsonPayloadReader", MagicMock(return_value=mock_reader)
        )

        publish_json_cmd.publish_batch(batch_dir, dry_run=True, report_dir=tmp_path / "reports")

        mock_use_case.execute.assert_called_once_with(
            batch_dir / "MLB271599/SKU001/payload.json", dry_run=True
        )

    def test_publish_batch_manifesto_pula_sku_falho(self, tmp_path: Path, monkeypatch) -> None:
        batch_dir = self._setup_batch_dir(tmp_path, ["SKU001", "SKU002"])
        # Write manifest with SKU002 as failed
        (batch_dir / "batch_manifest.json").write_text(
            json.dumps({"category_id": "MLB271599", "failed_skus": ["SKU002"]}),
            encoding="utf-8",
        )
        mock_reader = MagicMock()
        mock_reader.read_batch.return_value = [
            (batch_dir / "MLB271599/SKU001/payload.json", _make_read_result(sku="SKU001")),
            (batch_dir / "MLB271599/SKU002/payload.json", _make_read_result(sku="SKU002")),
        ]
        mock_use_case = MagicMock(spec=PublishJsonUseCase)
        mock_use_case.execute.return_value = PublishJsonResult(
            sku="SKU001", path="p", status="published", item_id="MLB1"
        )

        monkeypatch.setattr(publish_json_cmd, "_build_use_case", lambda: mock_use_case)
        monkeypatch.setattr(
            publish_json_cmd, "JsonPayloadReader", MagicMock(return_value=mock_reader)
        )

        publish_json_cmd.publish_batch(batch_dir, report_dir=tmp_path / "reports")

        # Only SKU001 should be published; SKU002 skipped
        assert mock_use_case.execute.call_count == 1

    def test_publish_batch_ai_bloqueado(self, tmp_path: Path, monkeypatch) -> None:
        batch_dir = self._setup_batch_dir(tmp_path, ["SKU001"])
        (batch_dir / "batch_manifest.json").write_text(
            json.dumps(
                {
                    "category_id": "MLB271599",
                    "ai_suggested_category": True,
                    "human_reviewed": False,
                }
            ),
            encoding="utf-8",
        )
        mock_reader = MagicMock()
        mock_use_case = MagicMock(spec=PublishJsonUseCase)

        monkeypatch.setattr(publish_json_cmd, "_build_use_case", lambda: mock_use_case)
        monkeypatch.setattr(
            publish_json_cmd, "JsonPayloadReader", MagicMock(return_value=mock_reader)
        )
        monkeypatch.setattr(
            publish_json_cmd,
            "default_seller_config",
            lambda: default_seller_config(),
        )
        monkeypatch.setattr(
            publish_json_cmd,
            "load_seller_config",
            lambda _path: default_seller_config(),
        )

        with pytest.raises(typer.Exit) as exc_info:
            publish_json_cmd.publish_batch(batch_dir, report_dir=tmp_path / "reports")
        assert exc_info.value.exit_code == 1
        mock_use_case.execute.assert_not_called()

    def test_report_gerado(self, tmp_path: Path, monkeypatch) -> None:
        batch_dir = self._setup_batch_dir(tmp_path, ["SKU001"])
        mock_reader = MagicMock()
        mock_reader.read_batch.return_value = [
            (batch_dir / "MLB271599/SKU001/payload.json", _make_read_result(sku="SKU001"))
        ]
        mock_use_case = MagicMock(spec=PublishJsonUseCase)
        mock_use_case.execute.return_value = PublishJsonResult(
            sku="SKU001", path="p", status="published", item_id="MLB999"
        )

        monkeypatch.setattr(publish_json_cmd, "_build_use_case", lambda: mock_use_case)
        monkeypatch.setattr(
            publish_json_cmd, "JsonPayloadReader", MagicMock(return_value=mock_reader)
        )

        report_dir = tmp_path / "reports"
        publish_json_cmd.publish_batch(batch_dir, report_dir=report_dir)

        report_files = list(report_dir.glob("publish-summary-*.json"))
        assert len(report_files) == 1
        report_data = json.loads(report_files[0].read_text())
        assert report_data["summary"]["published"] == 1
        assert report_data["results"][0]["sku"] == "SKU001"
        assert report_data["results"][0]["item_ids"] == []
        assert report_data["results"][0]["user_product_id"] is None

    def test_report_gerado_com_campos_up(self, tmp_path: Path, monkeypatch) -> None:
        batch_dir = self._setup_batch_dir(tmp_path, ["SKU001"])
        mock_reader = MagicMock()
        mock_reader.read_batch.return_value = [
            (batch_dir / "MLB271599/SKU001/payload.json", _make_read_result(sku="SKU001"))
        ]
        mock_use_case = MagicMock(spec=PublishJsonUseCase)
        mock_use_case.execute.return_value = PublishJsonResult(
            sku="SKU001",
            path="p",
            status="published",
            item_id="MLB999",
            item_ids=["MLB999", "MLB1000"],
            user_product_id="MLBU123",
        )

        monkeypatch.setattr(publish_json_cmd, "_build_use_case", lambda: mock_use_case)
        monkeypatch.setattr(
            publish_json_cmd, "JsonPayloadReader", MagicMock(return_value=mock_reader)
        )

        report_dir = tmp_path / "reports"
        publish_json_cmd.publish_batch(batch_dir, report_dir=report_dir)

        report_files = list(report_dir.glob("publish-summary-*.json"))
        assert len(report_files) == 1
        report_data = json.loads(report_files[0].read_text())
        assert report_data["results"][0]["item_id"] == "MLB999"
        assert report_data["results"][0]["item_ids"] == ["MLB999", "MLB1000"]
        assert report_data["results"][0]["user_product_id"] == "MLBU123"
