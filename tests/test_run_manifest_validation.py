"""Tests for publisher-side run_manifest validation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from mercadolivre_upload.contracts.run_manifest import load_run_manifest


def _current_manifest(tmp_path: Path) -> dict[str, object]:
    return {
        "run_id": "run-1",
        "created_at": "2026-05-12T22:00:00Z",
        "workspace_path": "workspace",
        "status": "success",
        "publication_candidates": [
            {
                "group_id": "17504",
                "family_id": "fam-1",
                "sku_scope": ["SKU-1"],
                "topology": "family_variations",
                "build_status": "success",
                "payloads": [
                    {
                        "variant": "classic",
                        "payload_path": "workspace/payload_classic.json",
                        "listing_type_id": "gold_special",
                        "publishable": True,
                        "artifact_source": "stage70_payload",
                        "created_at": "2026-05-12T22:00:00Z",
                        "block_reason": None,
                        "skip_reason": None,
                    }
                ],
                "errors": [],
            }
        ],
        "build_failures": [],
        "diagnostics": {
            "batch_log_path": "workspace/batch.log",
            "run_diagnostics_path": "workspace/diagnostics.json",
        },
    }


def test_load_run_manifest_accepts_current_contract(tmp_path: Path) -> None:
    manifest_path = tmp_path / "run_manifest.json"
    manifest_path.write_text(json.dumps(_current_manifest(tmp_path)), encoding="utf-8")

    manifest = load_run_manifest(manifest_path)

    assert manifest.run_id == "run-1"
    assert manifest.publication_candidates[0].payloads[0].payload_path == "workspace/payload_classic.json"


def test_load_run_manifest_rejects_legacy_v1_shape(tmp_path: Path) -> None:
    payload_path = tmp_path / "payload.json"
    payload_path.write_text("{}", encoding="utf-8")
    manifest_path = tmp_path / "run_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "run_id": "run-legacy",
                "created_at": "2026-05-12T22:00:00Z",
                "workspace_path": str(tmp_path),
                "artifacts": [
                    {
                        "sku": "SKU-1",
                        "status": "done",
                        "payload_paths": [str(payload_path)],
                    }
                ],
                "diagnostics": {},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError):
        load_run_manifest(manifest_path)


def test_load_run_manifest_rejects_missing_fields(tmp_path: Path) -> None:
    manifest_path = tmp_path / "run_manifest.json"
    manifest_path.write_text(json.dumps({"run_id": "run-1"}), encoding="utf-8")

    with pytest.raises(ValidationError):
        load_run_manifest(manifest_path)


def test_load_run_manifest_requires_current_contract_sections(tmp_path: Path) -> None:
    manifest = _current_manifest(tmp_path)
    manifest.pop("publication_candidates")
    manifest.pop("build_failures")
    manifest.pop("diagnostics")
    manifest_path = tmp_path / "run_manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValidationError):
        load_run_manifest(manifest_path)


def test_load_run_manifest_rejects_old_schema_version_field(tmp_path: Path) -> None:
    manifest = _current_manifest(tmp_path)
    manifest["schema_version"] = "2.0.0"
    manifest_path = tmp_path / "run_manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValidationError):
        load_run_manifest(manifest_path)
