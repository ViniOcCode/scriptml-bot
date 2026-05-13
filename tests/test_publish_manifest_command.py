"""Tests for publish-manifest command behavior."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import typer

from mercadolivre_upload.cli.commands.publish_manifest import publish_manifest


def _manifest_payload(
    tmp_path: Path,
    *,
    blocking_issues: list[str],
    artifacts: list[dict[str, object]] | None = None,
) -> Path:
    manifest_path = tmp_path / "run_manifest.json"
    payload_path = tmp_path / "payload.json"
    payload_path.write_text(
        json.dumps(
            {
                "payload": {
                    "title": "Produto",
                    "category_id": "MLB123",
                    "price": 10,
                    "currency_id": "BRL",
                    "available_quantity": 1,
                    "buying_mode": "buy_it_now",
                    "listing_type_id": "gold_special",
                    "condition": "new",
                    "pictures": [{"source": "https://example.com/a.jpg"}],
                },
                "_meta": {"sku": "SKU-1", "publication": {"publication_ready": True}},
            }
        ),
        encoding="utf-8",
    )
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "run_id": "run-1",
                "created_at": "2026-05-12T22:00:00Z",
                "workspace_path": str(tmp_path),
                "artifacts": artifacts
                or [
                    {
                        "sku": "SKU-1",
                        "status": "done",
                        "payload_paths": [str(payload_path)],
                        "category_id": "MLB123",
                        "category_name": "Categoria",
                        "error": None,
                    }
                ],
                "blocking_issues": blocking_issues,
                "warnings": [],
                "diagnostics": {},
            }
        ),
        encoding="utf-8",
    )
    return manifest_path


def test_publish_manifest_rejects_blocked_runs(tmp_path: Path) -> None:
    manifest_path = _manifest_payload(tmp_path, blocking_issues=["SKU-1: blocked"])
    with pytest.raises(typer.Exit) as exc:
        publish_manifest(manifest_path, report_dir=tmp_path / "reports")
    assert exc.value.exit_code == 1


def test_publish_manifest_publishes_done_artifacts(tmp_path: Path, monkeypatch) -> None:
    manifest_path = _manifest_payload(tmp_path, blocking_issues=[])
    calls: list[tuple[Path, dict[str, object]]] = []

    def _fake_publish(path: Path, **kwargs: object) -> dict[str, object]:
        calls.append((path, kwargs))
        return {"status": "published", "sku": "SKU-1", "errors": [], "warnings": []}

    monkeypatch.setattr(
        "mercadolivre_upload.cli.commands.publish_manifest.publish_payload_file",
        _fake_publish,
    )

    publish_manifest(
        manifest_path,
        report_dir=tmp_path / "reports",
        seller_config=tmp_path / "publisher.yaml",
    )

    assert len(calls) == 1
    assert calls[0][0].name == "payload.json"
    assert calls[0][1]["seller_config_path"] == tmp_path / "publisher.yaml"
    report_files = list((tmp_path / "reports").glob("publish-manifest-summary-*.json"))
    assert len(report_files) == 1


def test_publish_manifest_rejects_payload_path_escape(tmp_path: Path, monkeypatch) -> None:
    outside_payload = tmp_path.parent / "outside.json"
    outside_payload.write_text("{}", encoding="utf-8")
    manifest_path = _manifest_payload(
        tmp_path,
        blocking_issues=[],
        artifacts=[
            {
                "sku": "SKU-1",
                "status": "done",
                "payload_paths": ["../outside.json"],
                "category_id": "MLB123",
                "category_name": "Categoria",
                "error": None,
            }
        ],
    )
    monkeypatch.setattr(
        "mercadolivre_upload.cli.commands.publish_manifest.publish_payload_file",
        lambda *_args, **_kwargs: {"status": "published", "errors": [], "warnings": []},
    )

    with pytest.raises(typer.Exit) as exc:
        publish_manifest(
            manifest_path,
            report_dir=tmp_path / "reports",
            seller_config=tmp_path / "publisher.yaml",
        )
    assert exc.value.exit_code == 1
    report_file = next((tmp_path / "reports").glob("publish-manifest-summary-*.json"))
    report = json.loads(report_file.read_text(encoding="utf-8"))
    assert report["summary"]["failed"] == 1
    assert "escapes allowed roots" in report["results"][0]["errors"][0]


def test_publish_manifest_reports_skipped_non_done_artifacts(tmp_path: Path, monkeypatch) -> None:
    manifest_path = _manifest_payload(
        tmp_path,
        blocking_issues=[],
        artifacts=[
            {
                "sku": "SKU-1",
                "status": "review_required",
                "payload_paths": [],
                "category_id": "MLB123",
                "category_name": "Categoria",
                "error": "needs review",
            }
        ],
    )
    calls: list[tuple[Path, dict[str, object]]] = []

    def _fake_publish(path: Path, **kwargs: object) -> dict[str, object]:
        calls.append((path, kwargs))
        return {"status": "published", "sku": "SKU-1", "errors": [], "warnings": []}

    monkeypatch.setattr(
        "mercadolivre_upload.cli.commands.publish_manifest.publish_payload_file",
        _fake_publish,
    )

    publish_manifest(
        manifest_path,
        report_dir=tmp_path / "reports",
        seller_config=tmp_path / "publisher.yaml",
    )

    assert not calls
    report_file = next((tmp_path / "reports").glob("publish-manifest-summary-*.json"))
    report = json.loads(report_file.read_text(encoding="utf-8"))
    assert report["summary"]["skipped"] == 1
    assert report["results"][0]["status"] == "skipped"
    assert report["results"][0]["artifact_status"] == "review_required"
