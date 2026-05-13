"""Tests for publisher-side run_manifest validation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from mercadolivre_upload.contracts.run_manifest import RUN_MANIFEST_SCHEMA_VERSION, load_run_manifest


def test_load_run_manifest_validates_required_fields(tmp_path: Path) -> None:
    manifest_path = tmp_path / "run_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": RUN_MANIFEST_SCHEMA_VERSION,
                "run_id": "run-1",
                "created_at": "2026-05-12T22:00:00Z",
                "workspace_path": str(tmp_path),
                "artifacts": [],
                "blocking_issues": [],
                "warnings": [],
                "diagnostics": {},
            }
        ),
        encoding="utf-8",
    )
    manifest = load_run_manifest(manifest_path)
    assert manifest.run_id == "run-1"


def test_load_run_manifest_rejects_missing_fields(tmp_path: Path) -> None:
    manifest_path = tmp_path / "run_manifest.json"
    manifest_path.write_text(
        json.dumps({"schema_version": RUN_MANIFEST_SCHEMA_VERSION}),
        encoding="utf-8",
    )
    with pytest.raises(ValidationError):
        load_run_manifest(manifest_path)


def test_load_run_manifest_rejects_schema_mismatch(tmp_path: Path) -> None:
    manifest_path = tmp_path / "run_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "9.9.9",
                "run_id": "run-1",
                "created_at": "2026-05-12T22:00:00Z",
                "workspace_path": str(tmp_path),
                "artifacts": [],
                "blocking_issues": [],
                "warnings": [],
                "diagnostics": {},
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        load_run_manifest(manifest_path)

