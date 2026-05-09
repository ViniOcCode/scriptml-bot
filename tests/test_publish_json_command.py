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


class TestPublishedSkusIdempotency:
    def _setup_batch_dir(self, tmp_path: Path, skus: list[str]) -> Path:
        batch_dir = tmp_path / "batch"
        for sku in skus:
            d = batch_dir / "MLB271599" / sku
            d.mkdir(parents=True)
            (d / "payload.json").write_text("{}")
        return batch_dir

    def test_skips_already_published_sku(self, tmp_path: Path, monkeypatch) -> None:
        """SKUs present in batch_manifest.json must be skipped."""
        batch_dir = self._setup_batch_dir(tmp_path, ["SKU001", "SKU002"])
        manifest = {"published_skus": ["SKU001"]}
        (batch_dir / "batch_manifest.json").write_text(json.dumps(manifest))

        mock_reader = MagicMock()
        mock_reader.read_batch.return_value = [
            (batch_dir / "MLB271599/SKU001/payload.json", _make_read_result(sku="SKU001")),
            (batch_dir / "MLB271599/SKU002/payload.json", _make_read_result(sku="SKU002")),
        ]
        mock_use_case = MagicMock(spec=PublishJsonUseCase)
        mock_use_case.execute.return_value = PublishJsonResult(
            sku="SKU002", path="p", status="published", item_id="MLB999"
        )

        monkeypatch.setattr(publish_json_cmd, "_build_use_case", lambda: mock_use_case)
        monkeypatch.setattr(
            publish_json_cmd, "JsonPayloadReader", MagicMock(return_value=mock_reader)
        )

        publish_json_cmd.publish_batch(batch_dir, report_dir=tmp_path / "reports")

        # execute() should be called only once (for SKU002)
        assert mock_use_case.execute.call_count == 1
        called_path = str(mock_use_case.execute.call_args[0][0])
        assert "SKU002" in called_path

    def test_in_run_duplicate_skipped(self, tmp_path: Path, monkeypatch) -> None:
        """SKU already published in the same run must not be re-published."""
        batch_dir = self._setup_batch_dir(tmp_path, ["SKU001", "SKU001b"])
        mock_reader = MagicMock()
        # Return same SKU twice to simulate a dup in read_batch
        mock_reader.read_batch.return_value = [
            (batch_dir / "MLB271599/SKU001/payload.json", _make_read_result(sku="SKU001")),
            (batch_dir / "MLB271599/SKU001b/payload.json", _make_read_result(sku="SKU001")),
        ]
        call_count = {"n": 0}

        def side_effect(path, dry_run: bool = False):
            call_count["n"] += 1
            return PublishJsonResult(
                sku="SKU001", path=str(path), status="published", item_id=f"MLB{call_count['n']}"
            )

        mock_use_case = MagicMock(spec=PublishJsonUseCase)
        mock_use_case.execute.side_effect = side_effect

        monkeypatch.setattr(publish_json_cmd, "_build_use_case", lambda: mock_use_case)
        monkeypatch.setattr(
            publish_json_cmd, "JsonPayloadReader", MagicMock(return_value=mock_reader)
        )

        publish_json_cmd.publish_batch(batch_dir, report_dir=tmp_path / "reports")

        assert mock_use_case.execute.call_count == 1

    def test_no_manifest_all_skus_published(self, tmp_path: Path, monkeypatch) -> None:
        """If batch_manifest.json is absent, all SKUs must be published normally."""
        batch_dir = self._setup_batch_dir(tmp_path, ["SKU001", "SKU002"])

        mock_reader = MagicMock()
        mock_reader.read_batch.return_value = [
            (batch_dir / "MLB271599/SKU001/payload.json", _make_read_result(sku="SKU001")),
            (batch_dir / "MLB271599/SKU002/payload.json", _make_read_result(sku="SKU002")),
        ]
        mock_use_case = MagicMock(spec=PublishJsonUseCase)
        mock_use_case.execute.side_effect = lambda path, dry_run=False: PublishJsonResult(
            sku=path.parent.name, path=str(path), status="published", item_id="MLB100"
        )

        monkeypatch.setattr(publish_json_cmd, "_build_use_case", lambda: mock_use_case)
        monkeypatch.setattr(
            publish_json_cmd, "JsonPayloadReader", MagicMock(return_value=mock_reader)
        )

        publish_json_cmd.publish_batch(batch_dir, report_dir=tmp_path / "reports")

        assert mock_use_case.execute.call_count == 2


class TestBatchManifestWriteBack:
    """F2: published_skus/failed_skus must be persisted after each publish."""

    def _setup_batch_dir(self, tmp_path: Path, skus: list[str]) -> Path:
        batch_dir = tmp_path / "batch_f2"
        for sku in skus:
            d = batch_dir / "MLB271599" / sku
            d.mkdir(parents=True)
            (d / "payload.json").write_text("{}")
        return batch_dir

    def test_published_sku_written_to_manifest(self, tmp_path: Path, monkeypatch) -> None:
        batch_dir = self._setup_batch_dir(tmp_path, ["SKU001"])

        mock_reader = MagicMock()
        mock_reader.read_batch.return_value = [
            (batch_dir / "MLB271599/SKU001/payload.json", _make_read_result(sku="SKU001")),
        ]
        mock_use_case = MagicMock(spec=PublishJsonUseCase)
        mock_use_case.execute.return_value = PublishJsonResult(
            sku="SKU001", path="p", status="published", item_id="MLB1"
        )

        write_calls = []

        def tracking_write(manifest_path, manifest):
            write_calls.append(dict(manifest))

        monkeypatch.setattr(publish_json_cmd, "_build_use_case", lambda: mock_use_case)
        monkeypatch.setattr(
            publish_json_cmd, "JsonPayloadReader", MagicMock(return_value=mock_reader)
        )
        monkeypatch.setattr(publish_json_cmd, "_write_batch_manifest", tracking_write)

        publish_json_cmd.publish_batch(batch_dir, report_dir=tmp_path / "reports")

        assert len(write_calls) >= 1
        assert "SKU001" in write_calls[-1].get("published_skus", [])

    def test_failed_sku_written_to_manifest(self, tmp_path: Path, monkeypatch) -> None:
        batch_dir = self._setup_batch_dir(tmp_path, ["SKU001"])

        mock_reader = MagicMock()
        mock_reader.read_batch.return_value = [
            (batch_dir / "MLB271599/SKU001/payload.json", _make_read_result(sku="SKU001")),
        ]
        mock_use_case = MagicMock(spec=PublishJsonUseCase)
        mock_use_case.execute.return_value = PublishJsonResult(
            sku="SKU001", path="p", status="failed", error="error"
        )

        write_calls = []

        def tracking_write(manifest_path, manifest):
            write_calls.append(dict(manifest))

        monkeypatch.setattr(publish_json_cmd, "_build_use_case", lambda: mock_use_case)
        monkeypatch.setattr(
            publish_json_cmd, "JsonPayloadReader", MagicMock(return_value=mock_reader)
        )
        monkeypatch.setattr(publish_json_cmd, "_write_batch_manifest", tracking_write)

        with pytest.raises(typer.Exit):
            publish_json_cmd.publish_batch(batch_dir, report_dir=tmp_path / "reports")

        assert len(write_calls) >= 1
        assert "SKU001" in write_calls[-1].get("failed_skus", [])


class TestUseCaseDirect:
    """Tests for PublishJsonUseCase internals (F3, N1, N2)."""

    def test_reviewed_fiscal_none_with_fiscal_items_warns(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """F3: reviewed_fiscal=None + fiscal_items non-empty → warning log."""
        from mercadolivre_upload.application.publish_json_use_case import (
            PublishJsonUseCase,
        )
        from mercadolivre_upload.adapters.json_payload_reader import ReadPayloadResult

        warnings_list = []

        def mock_execute_side_effect(*args, **kwargs):
            return PublishJsonResult(
                sku="SKU001",
                path=str(tmp_path / "p.json"),
                status="published",
                warnings=warnings_list,
            )

        mock_reader = MagicMock()
        mock_reader.read.return_value = ReadPayloadResult(
            payload={
                "title": "Test",
                "category_id": "MLB271599",
                "price": 100.0,
                "currency_id": "BRL",
                "available_quantity": 1,
                "buying_mode": "buy_it_now",
                "listing_type_id": "gold_special",
                "condition": "new",
                "pictures": [{"source": "https://cdn.ml.com/img.jpg"}],
            },
            description=None,
            sku="SKU001",
            category_id="MLB271599",
            ai_suggested=False,
            publication_ready=True,
            reviewed_fiscal=None,
            fiscal_items=[{"sku": "SKU001", "type": "single", "measurement_unit": "UN"}],
        )

        mock_policy = MagicMock()
        mock_policy.apply_overrides.side_effect = lambda p: dict(p)
        mock_policy.validate.return_value = MagicMock(violations=[])

        mock_publisher = MagicMock()
        mock_publisher.create_item.return_value = {"id": "MLB123"}

        use_case = PublishJsonUseCase(
            reader=mock_reader,
            policy=mock_policy,
            publisher=mock_publisher,
        )

        result = use_case.execute(tmp_path / "p.json")

        assert len(result.warnings) == 1
        assert "Fiscal" in result.warnings[0] or "fiscal" in result.warnings[0].lower()

    def test_apply_attribute_suggestions_merges_new(self) -> None:
        """N1: _apply_attribute_suggestions adds missing attrs, skips existing."""
        from mercadolivre_upload.application.publish_json_use_case import (
            _apply_attribute_suggestions,
        )

        payload = {
            "title": "Test",
            "attributes": [{"id": "COLOR", "value_name": "Red"}],
        }
        suggestions = [
            {"attr_id": "COLOR", "canonical_value": "Azul", "confidence": 0.95},  # already present
            {"attr_id": "BRAND", "canonical_value": "Nike", "confidence": 0.88},  # new
        ]

        result = _apply_attribute_suggestions(payload, suggestions)

        assert len(result["attributes"]) == 2
        assert result["attributes"][0]["id"] == "COLOR"
        assert result["attributes"][0]["value_name"] == "Red"
        assert result["attributes"][1]["id"] == "BRAND"
        assert result["attributes"][1]["value_name"] == "Nike"

    def test_apply_attribute_suggestions_no_existing_attrs(self) -> None:
        """N1: When payload has no attributes, suggestions create the list."""
        from mercadolivre_upload.application.publish_json_use_case import (
            _apply_attribute_suggestions,
        )

        payload: dict = {"title": "Test"}
        suggestions = [
            {"attr_id": "COLOR", "canonical_value": "Azul", "confidence": 0.95},
        ]

        result = _apply_attribute_suggestions(payload, suggestions)

        assert len(result["attributes"]) == 1
        assert result["attributes"][0]["id"] == "COLOR"

    def test_description_retry_success_on_second_attempt(self, tmp_path, monkeypatch):
        """N2: description POST fails once then succeeds → published + warning."""
        from mercadolivre_upload.application.publish_json_use_case import (
            PublishJsonUseCase,
        )

        mock_reader = MagicMock()
        mock_reader.read.return_value = _make_read_result(description="Test description")

        mock_policy = MagicMock()
        mock_policy.apply_overrides.side_effect = lambda p: dict(p)
        mock_policy.validate.return_value = MagicMock(violations=[])

        call_count = {"n": 0}
        warning_logs = []

        def failing_once(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise Exception("first attempt failed")
            return None

        mock_publisher = MagicMock()
        mock_publisher.create_item.return_value = {"id": "MLB123"}
        mock_publisher.create_item_description.side_effect = failing_once

        def warning_logger(message, *args, **kwargs):
            if "Description POST" in message:
                warning_logs.append(message)

        monkeypatch.setattr(
            "mercadolivre_upload.application.publish_json_use_case.logger.warning",
            warning_logger,
        )

        use_case = PublishJsonUseCase(
            reader=mock_reader,
            policy=mock_policy,
            publisher=mock_publisher,
        )

        result = use_case.execute(tmp_path / "p.json")

        assert result.status == "published"
        assert call_count["n"] == 2  # first fails, second succeeds
        assert len(warning_logs) == 1  # one warning (second attempt succeeded)
        assert "retrying" in warning_logs[0] or "attempt" in warning_logs[0]

    def test_description_retry_both_fail(self, tmp_path, monkeypatch):
        """N2: both description attempts fail → published + 2 warnings."""
        from mercadolivre_upload.application.publish_json_use_case import (
            PublishJsonUseCase,
        )

        mock_reader = MagicMock()
        mock_reader.read.return_value = _make_read_result(description="Test description")

        mock_policy = MagicMock()
        mock_policy.apply_overrides.side_effect = lambda p: dict(p)
        mock_policy.validate.return_value = MagicMock(violations=[])

        warning_logs = []

        mock_publisher = MagicMock()
        mock_publisher.create_item.return_value = {"id": "MLB123"}
        mock_publisher.create_item_description.side_effect = Exception("always fails")

        def warning_logger(message, *args, **kwargs):
            if "Description POST" in message:
                warning_logs.append(message)

        monkeypatch.setattr(
            "mercadolivre_upload.application.publish_json_use_case.logger.warning",
            warning_logger,
        )

        use_case = PublishJsonUseCase(
            reader=mock_reader,
            policy=mock_policy,
            publisher=mock_publisher,
        )

        result = use_case.execute(tmp_path / "p.json")

        assert result.status == "published"  # non-blocking
        assert len(warning_logs) == 2  # two warnings (attempt + retry)
