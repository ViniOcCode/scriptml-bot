"""Tests for publish-manifest command behavior."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import typer

from mercadolivre_upload.cli.commands.publish_manifest import _final_status, publish_manifest


def _payload_document(listing_type_id: str = "gold_special", *, wrapper_list: bool = False) -> dict[str, Any]:
    payload = {
        "title": "Produto",
        "category_id": "MLB123",
        "price": 10,
        "currency_id": "BRL",
        "available_quantity": 1,
        "buying_mode": "buy_it_now",
        "listing_type_id": listing_type_id,
        "condition": "new",
        "pictures": [{"source": "https://example.com/a.jpg"}],
    }
    return {
        "payload": [payload] if wrapper_list else payload,
        "description": "desc",
        "fiscal": {},
        "_meta": {"sku": "SKU-1", "publication": {"publication_ready": True}},
    }


def _write_payload(path: Path, listing_type_id: str = "gold_special", *, wrapper_list: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_payload_document(listing_type_id, wrapper_list=wrapper_list)), encoding="utf-8")


def _payload_entry(
    variant: str,
    payload_path: str | None,
    listing_type_id: str,
    *,
    publishable: bool = True,
    block_reason: str | None = None,
    skip_reason: str | None = None,
) -> dict[str, object]:
    row: dict[str, object] = {
        "variant": variant,
        "payload_path": payload_path,
        "listing_type_id": listing_type_id,
        "publishable": publishable,
        "artifact_source": "stage70_payload",
        "created_at": "2026-05-12T22:00:00Z",
        "block_reason": block_reason,
        "skip_reason": skip_reason,
    }
    if payload_path is None:
        row.pop("payload_path")
    return row


def _manifest_payload(
    tmp_path: Path,
    *,
    status: str = "success",
    publication_candidates: list[dict[str, object]] | None = None,
    build_failures: list[dict[str, object]] | None = None,
) -> Path:
    workspace = tmp_path / "workspace"
    classic_path = workspace / "batches" / "outros" / "17506" / "payload_classic.json"
    premium_path = workspace / "batches" / "outros" / "17506" / "payload_premium.json"
    _write_payload(classic_path, "gold_special")
    _write_payload(premium_path, "gold_pro")

    manifest_path = tmp_path / "run_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "run_id": "run-1",
                "created_at": "2026-05-12T22:00:00Z",
                "workspace_path": "workspace",
                "status": status,
                "publication_candidates": publication_candidates
                or [
                    {
                        "group_id": "17506",
                        "family_id": "family-17506",
                        "sku_scope": ["17506TRANSPARENTEU"],
                        "topology": "family_variations",
                        "build_status": "success",
                        "payloads": [
                            _payload_entry(
                                "classic",
                                "workspace/batches/outros/17506/payload_classic.json",
                                "gold_special",
                            ),
                            _payload_entry(
                                "premium",
                                "workspace/batches/outros/17506/payload_premium.json",
                                "gold_pro",
                            ),
                        ],
                        "errors": [],
                    }
                ],
                "build_failures": build_failures or [],
                "diagnostics": {
                    "batch_log_path": "workspace/batch.log",
                    "run_diagnostics_path": "workspace/diagnostics.json",
                },
            }
        ),
        encoding="utf-8",
    )
    return manifest_path


def _candidate(payloads: list[dict[str, object]], *, build_status: str = "success") -> dict[str, object]:
    return {
        "group_id": "17506",
        "family_id": "family-17506",
        "sku_scope": ["SKU-1"],
        "topology": "family_variations",
        "build_status": build_status,
        "payloads": payloads,
        "errors": [],
    }


def _report(tmp_path: Path) -> dict[str, Any]:
    return json.loads((tmp_path / "reports" / "report.json").read_text(encoding="utf-8"))


def _patch_publish(monkeypatch: pytest.MonkeyPatch, calls: list[Path], statuses: dict[str, str] | None = None) -> None:
    def _fake_publish(path: Path, **_kwargs: object) -> dict[str, object]:
        calls.append(path)
        status = (statuses or {}).get(path.name, "published")
        return {
            "status": status,
            "item_id": f"MLB-{path.stem}",
            "user_product_id": f"UP-{path.stem}",
            "errors": ["api error"] if status == "failed" else [],
            "warnings": [],
            "validation_status": "validation_passed",
            "validation_report": {"status": "validation_passed", "warnings": [], "errors": []},
            "fiscal_status": "skipped",
        }

    monkeypatch.setattr("mercadolivre_upload.cli.commands.publish_manifest.publish_payload_file", _fake_publish)


def test_current_manifest_shape_with_classic_and_premium_selects_both(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manifest_path = _manifest_payload(tmp_path)
    calls: list[Path] = []
    _patch_publish(monkeypatch, calls)

    publish_manifest(manifest_path, workspace_root=tmp_path / "workspace", report_dir=tmp_path / "reports")

    assert [p.name for p in calls] == ["payload_classic.json", "payload_premium.json"]
    assert _report(tmp_path)["summary"]["selected_payload_variants"] == 2


def test_manifest_under_runs_resolves_workspace_prefixed_payloads_from_workspace_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest_path = _manifest_payload(tmp_path)
    run_manifest_path = tmp_path / "workspace" / "runs" / "run-1" / "run_manifest.json"
    run_manifest_path.parent.mkdir(parents=True)
    run_manifest_path.write_text(manifest_path.read_text(encoding="utf-8"), encoding="utf-8")
    calls: list[Path] = []
    _patch_publish(monkeypatch, calls)

    publish_manifest(run_manifest_path, workspace_root=tmp_path / "workspace", report_dir=tmp_path / "reports")

    assert calls == [
        tmp_path / "workspace" / "batches" / "outros" / "17506" / "payload_classic.json",
        tmp_path / "workspace" / "batches" / "outros" / "17506" / "payload_premium.json",
    ]
    assert all(
        "/workspace/runs/run-1/workspace/" not in row["resolved_payload_path"]
        for row in _report(tmp_path)["results"]
        if row["resolved_payload_path"]
    )


def test_partial_success_manifest_with_build_failures_still_publishes_selected_payloads(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manifest_path = _manifest_payload(
        tmp_path,
        status="partial_success",
        build_failures=[
            {
                "sku": "SKU-BAD",
                "group_id": "10008",
                "stage": "stage70_payload",
                "reason": "payload_failed",
                "publishable": False,
            }
        ],
    )
    calls: list[Path] = []
    _patch_publish(monkeypatch, calls)

    with pytest.raises(typer.Exit) as exc:
        publish_manifest(
            manifest_path,
            workspace_root=tmp_path / "workspace",
            report_dir=tmp_path / "reports",
        )

    assert exc.value.exit_code == 1
    report = _report(tmp_path)
    assert len(calls) == 2
    assert report["summary"]["build_failures"] == 1
    assert any(row["skipped_build_failure"] for row in report["results"])


def test_failed_manifest_with_zero_publishable_payloads_fails_clearly(tmp_path: Path) -> None:
    manifest_path = _manifest_payload(
        tmp_path,
        status="failed",
        publication_candidates=[
            _candidate([
                _payload_entry("classic", "workspace/missing.json", "gold_special", publishable=False)
            ], build_status="failed")
        ],
    )

    with pytest.raises(typer.Exit) as exc:
        publish_manifest(manifest_path, workspace_root=tmp_path / "workspace", report_dir=tmp_path / "reports")

    assert exc.value.exit_code == 1
    assert _report(tmp_path)["summary"]["final_status"] == "partial_success"


def test_failed_manifest_with_publishable_payloads_fails_as_manifest_inconsistency(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manifest_path = _manifest_payload(tmp_path, status="failed")
    calls: list[Path] = []
    _patch_publish(monkeypatch, calls)

    with pytest.raises(typer.Exit) as exc:
        publish_manifest(manifest_path, workspace_root=tmp_path / "workspace", report_dir=tmp_path / "reports")

    assert exc.value.exit_code == 1
    assert calls == []


def test_publishable_false_payload_is_skipped_and_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manifest_path = _manifest_payload(
        tmp_path,
        publication_candidates=[
            _candidate([_payload_entry("classic", "workspace/batches/outros/17506/payload_classic.json", "gold_special", publishable=False)])
        ],
    )
    calls: list[Path] = []
    _patch_publish(monkeypatch, calls)

    with pytest.raises(typer.Exit):
        publish_manifest(manifest_path, workspace_root=tmp_path / "workspace", report_dir=tmp_path / "reports")

    assert calls == []
    assert _report(tmp_path)["results"][0]["publish_result"] == "skipped"


def test_payload_with_block_reason_is_skipped_and_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manifest_path = _manifest_payload(
        tmp_path,
        publication_candidates=[
            _candidate([_payload_entry("classic", "workspace/batches/outros/17506/payload_classic.json", "gold_special", block_reason="family_incomplete")])
        ],
    )
    calls: list[Path] = []
    _patch_publish(monkeypatch, calls)

    with pytest.raises(typer.Exit):
        publish_manifest(manifest_path, workspace_root=tmp_path / "workspace", report_dir=tmp_path / "reports")

    assert calls == []
    assert _report(tmp_path)["results"][0]["block_reason"] == "family_incomplete"


def test_payload_with_skip_reason_is_skipped_and_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manifest_path = _manifest_payload(
        tmp_path,
        publication_candidates=[
            _candidate([_payload_entry("premium", "workspace/batches/outros/17506/payload_premium.json", "gold_pro", skip_reason="manual_skip")])
        ],
    )
    calls: list[Path] = []
    _patch_publish(monkeypatch, calls)

    with pytest.raises(typer.Exit):
        publish_manifest(manifest_path, workspace_root=tmp_path / "workspace", report_dir=tmp_path / "reports")

    assert calls == []
    assert _report(tmp_path)["results"][0]["skip_reason"] == "manual_skip"


def test_build_failures_are_included_in_report_but_do_not_block_selected_payloads(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    test_partial_success_manifest_with_build_failures_still_publishes_selected_payloads(tmp_path, monkeypatch)


def test_classic_and_premium_are_attempted_independently(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manifest_path = _manifest_payload(tmp_path)
    calls: list[Path] = []
    _patch_publish(monkeypatch, calls, {"payload_classic.json": "failed", "payload_premium.json": "published"})

    with pytest.raises(typer.Exit) as exc:
        publish_manifest(
            manifest_path,
            workspace_root=tmp_path / "workspace",
            report_dir=tmp_path / "reports",
        )

    assert exc.value.exit_code == 1
    assert [p.name for p in calls] == ["payload_classic.json", "payload_premium.json"]


def test_classic_success_and_premium_failure_produces_partial_success_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manifest_path = _manifest_payload(tmp_path)
    calls: list[Path] = []
    _patch_publish(monkeypatch, calls, {"payload_premium.json": "failed"})

    with pytest.raises(typer.Exit) as exc:
        publish_manifest(
            manifest_path,
            workspace_root=tmp_path / "workspace",
            report_dir=tmp_path / "reports",
        )

    assert exc.value.exit_code == 1
    assert _report(tmp_path)["summary"]["final_status"] == "partial_success"


def test_premium_success_and_classic_failure_produces_partial_success_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manifest_path = _manifest_payload(tmp_path)
    calls: list[Path] = []
    _patch_publish(monkeypatch, calls, {"payload_classic.json": "failed"})

    with pytest.raises(typer.Exit) as exc:
        publish_manifest(
            manifest_path,
            workspace_root=tmp_path / "workspace",
            report_dir=tmp_path / "reports",
        )

    assert exc.value.exit_code == 1
    assert _report(tmp_path)["summary"]["final_status"] == "partial_success"


def test_wrapper_payload_with_payload_zero_listing_type_id_is_supported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_payload(tmp_path / "workspace" / "wrapped.json", "gold_special", wrapper_list=True)
    manifest_path = _manifest_payload(
        tmp_path,
        publication_candidates=[_candidate([_payload_entry("classic", "workspace/wrapped.json", "gold_special")])],
    )
    calls: list[Path] = []
    _patch_publish(monkeypatch, calls)

    publish_manifest(manifest_path, workspace_root=tmp_path / "workspace", report_dir=tmp_path / "reports")

    assert calls[0].name == "wrapped.json"
    assert _report(tmp_path)["results"][0]["actual_payload_listing_type_id"] == "gold_special"


def test_manifest_listing_type_id_mismatch_blocks_only_that_variant(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manifest_path = _manifest_payload(
        tmp_path,
        publication_candidates=[
            _candidate([
                _payload_entry("classic", "workspace/batches/outros/17506/payload_classic.json", "gold_pro"),
                _payload_entry("premium", "workspace/batches/outros/17506/payload_premium.json", "gold_pro"),
            ])
        ],
    )
    calls: list[Path] = []
    _patch_publish(monkeypatch, calls)

    with pytest.raises(typer.Exit) as exc:
        publish_manifest(
            manifest_path,
            workspace_root=tmp_path / "workspace",
            report_dir=tmp_path / "reports",
        )

    assert exc.value.exit_code == 1
    assert [p.name for p in calls] == ["payload_premium.json"]
    assert any("listing_type_id_mismatch" in str(row["block_reason"]) for row in _report(tmp_path)["results"])


def test_missing_payload_file_blocks_only_that_variant(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manifest_path = _manifest_payload(
        tmp_path,
        publication_candidates=[
            _candidate([
                _payload_entry("classic", "workspace/missing.json", "gold_special"),
                _payload_entry("premium", "workspace/batches/outros/17506/payload_premium.json", "gold_pro"),
            ])
        ],
    )
    calls: list[Path] = []
    _patch_publish(monkeypatch, calls)

    with pytest.raises(typer.Exit) as exc:
        publish_manifest(
            manifest_path,
            workspace_root=tmp_path / "workspace",
            report_dir=tmp_path / "reports",
        )

    assert exc.value.exit_code == 1
    assert [p.name for p in calls] == ["payload_premium.json"]
    assert any(row["block_reason"] == "payload_missing" for row in _report(tmp_path)["results"])


def test_malformed_json_blocks_only_that_variant(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bad_path = tmp_path / "workspace" / "bad.json"
    bad_path.parent.mkdir(parents=True, exist_ok=True)
    bad_path.write_text("{bad", encoding="utf-8")
    manifest_path = _manifest_payload(
        tmp_path,
        publication_candidates=[
            _candidate([
                _payload_entry("classic", "workspace/bad.json", "gold_special"),
                _payload_entry("premium", "workspace/batches/outros/17506/payload_premium.json", "gold_pro"),
            ])
        ],
    )
    calls: list[Path] = []
    _patch_publish(monkeypatch, calls)

    with pytest.raises(typer.Exit) as exc:
        publish_manifest(
            manifest_path,
            workspace_root=tmp_path / "workspace",
            report_dir=tmp_path / "reports",
        )

    assert exc.value.exit_code == 1
    assert [p.name for p in calls] == ["payload_premium.json"]
    assert any(row["block_reason"] == "payload_invalid" for row in _report(tmp_path)["results"])


def test_payload_files_not_listed_in_manifest_are_never_published(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_payload(tmp_path / "workspace" / "unlisted.json", "gold_special")
    manifest_path = _manifest_payload(
        tmp_path,
        publication_candidates=[_candidate([_payload_entry("classic", "workspace/batches/outros/17506/payload_classic.json", "gold_special")])],
    )
    calls: list[Path] = []
    _patch_publish(monkeypatch, calls)

    publish_manifest(manifest_path, workspace_root=tmp_path / "workspace", report_dir=tmp_path / "reports")

    assert [p.name for p in calls] == ["payload_classic.json"]


def test_report_is_per_payload_variant(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manifest_path = _manifest_payload(tmp_path)
    calls: list[Path] = []
    _patch_publish(monkeypatch, calls)

    publish_manifest(manifest_path, workspace_root=tmp_path / "workspace", report_dir=tmp_path / "reports")

    rows = [row for row in _report(tmp_path)["results"] if row["variant"]]
    assert [row["variant"] for row in rows] == ["classic", "premium"]
    assert all(row["run_id"] == "run-1" for row in rows)


def test_cli_output_shows_run_id_counts_skips_and_report_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    manifest_path = _manifest_payload(
        tmp_path,
        status="partial_success",
        build_failures=[
            {
                "sku": "SKU-BAD",
                "group_id": "10008",
                "stage": "stage70_payload",
                "reason": "payload_failed",
                "publishable": False,
            }
        ],
    )
    calls: list[Path] = []
    _patch_publish(monkeypatch, calls)

    with pytest.raises(typer.Exit) as exc:
        publish_manifest(
            manifest_path,
            workspace_root=tmp_path / "workspace",
            report_dir=tmp_path / "reports",
        )

    assert exc.value.exit_code == 1
    output = capsys.readouterr().out
    assert "Run ID:" in output
    assert "run-1" in output
    assert "Selected classic:" in output
    assert "Selected premium:" in output
    assert "Skipped/build-failed entries:" in output
    assert "Report path:" in output


def test_warning_only_ml_validation_continues_publication(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manifest_path = _manifest_payload(tmp_path)
    calls: list[Path] = []

    def _fake_publish(path: Path, **_kwargs: object) -> dict[str, object]:
        calls.append(path)
        return {
            "status": "published",
            "errors": [],
            "warnings": ["ML validation warning: shipping.lost_me1_by_user"],
            "validation_status": "validation_passed_with_warnings",
            "validation_report": {
                "status": "validation_passed_with_warnings",
                "warnings": [{"type": "warning", "code": "shipping.lost_me1_by_user", "message": "warn"}],
                "errors": [],
            },
        }

    monkeypatch.setattr("mercadolivre_upload.cli.commands.publish_manifest.publish_payload_file", _fake_publish)

    publish_manifest(manifest_path, workspace_root=tmp_path / "workspace", report_dir=tmp_path / "reports")

    assert len(calls) == 2
    assert _report(tmp_path)["summary"]["final_status"] == "success"


def test_mixed_warning_and_error_ml_validation_blocks_only_that_payload_variant(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manifest_path = _manifest_payload(tmp_path)
    calls: list[Path] = []

    def _fake_publish(path: Path, **_kwargs: object) -> dict[str, object]:
        calls.append(path)
        if path.name == "payload_classic.json":
            return {
                "status": "failed",
                "errors": ["validation error"],
                "warnings": ["ML validation warning: warn"],
                "validation_status": "validation_failed",
                "validation_report": {
                    "status": "validation_failed",
                    "warnings": [{"type": "warning", "code": "warn", "message": "warn"}],
                    "errors": [{"type": "error", "code": "err", "message": "err"}],
                },
            }
        return {"status": "published", "errors": [], "warnings": [], "validation_status": "validation_passed"}

    monkeypatch.setattr("mercadolivre_upload.cli.commands.publish_manifest.publish_payload_file", _fake_publish)

    with pytest.raises(typer.Exit) as exc:
        publish_manifest(
            manifest_path,
            workspace_root=tmp_path / "workspace",
            report_dir=tmp_path / "reports",
        )

    assert exc.value.exit_code == 1
    assert [p.name for p in calls] == ["payload_classic.json", "payload_premium.json"]
    report = _report(tmp_path)
    assert report["summary"]["final_status"] == "partial_success"
    assert report["summary"]["premium"]["published"] == 1


def test_dry_run_with_selected_payloads_does_not_exit_nonzero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest_path = _manifest_payload(tmp_path)
    calls: list[Path] = []
    _patch_publish(monkeypatch, calls)

    publish_manifest(
        manifest_path,
        workspace_root=tmp_path / "workspace",
        report_dir=tmp_path / "reports",
        dry_run=True,
    )

    assert [p.name for p in calls] == ["payload_classic.json", "payload_premium.json"]
    assert _report(tmp_path)["summary"]["final_status"] == "success"


def test_no_test_depends_on_old_manifest_format(tmp_path: Path) -> None:
    legacy_manifest = {
        "schema_version": "2.0.0",
        "run_id": "legacy",
        "created_at": "2026-05-12T22:00:00Z",
        "workspace_path": "workspace",
        "status": "success",
        "publication_candidates": [],
        "build_failures": [],
        "blocking_issues": [],
        "warnings": [],
        "diagnostics": {},
    }
    manifest_path = tmp_path / "run_manifest.json"
    manifest_path.write_text(json.dumps(legacy_manifest), encoding="utf-8")

    with pytest.raises(Exception):
        publish_manifest(manifest_path, workspace_root=tmp_path / "workspace", report_dir=tmp_path / "reports")


def test_final_status_marks_published_but_not_grouped_as_partial_success() -> None:
    results = [{"selected": True, "publish_result": "published_but_not_grouped"}]

    assert _final_status(results, selected_count=1, build_failure_count=0) == "partial_success"
