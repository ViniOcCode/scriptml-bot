"""Tests for generated-vs-published reconciliation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mercadolivre_upload.application.reconcile import ReconcileUseCase


class FakeInventory:
    def __init__(self, items: list[dict[str, Any]]) -> None:
        self.items = {str(item["id"]): item for item in items}
        self.search_calls: list[tuple[str, int]] = []
        self.batch_calls: list[list[str]] = []

    def get_users_me(self) -> dict[str, Any]:
        return {"id": "seller-1"}

    def search_user_items(
        self,
        seller_id: str,
        *,
        status: str,
        limit: int,
        offset: int | None = None,
        search_type: str | None = None,
        scroll_id: str | None = None,
    ) -> dict[str, Any]:
        assert seller_id == "seller-1"
        page_offset = int(scroll_id or offset or 0)
        self.search_calls.append((status, page_offset))
        ids = [item_id for item_id, item in self.items.items() if item.get("status") == status]
        return {
            "results": ids[page_offset : page_offset + limit],
            "paging": {"total": len(ids)},
            "scroll_id": str(page_offset + limit) if search_type == "scan" else None,
        }

    def get_items_batch(self, item_ids: list[str]) -> list[Any]:
        self.batch_calls.append(item_ids)
        return [{"code": 200, "body": self.items[item_id]} for item_id in item_ids]


def _payload(
    sku: str,
    listing_type_id: str = "gold_special",
    *,
    publication_ready: bool | None = True,
) -> dict[str, Any]:
    meta_publication: dict[str, Any] = {}
    if publication_ready is not None:
        meta_publication["publication_ready"] = publication_ready
    return {
        "payload": {
            "title": "Produto",
            "category_id": "MLB123",
            "price": 10,
            "currency_id": "BRL",
            "available_quantity": 1,
            "buying_mode": "buy_it_now",
            "listing_type_id": listing_type_id,
            "condition": "new",
            "pictures": [{"id": "PIC1"}],
            "attributes": [{"id": "SELLER_SKU", "value_name": sku}],
        },
        "_meta": {
            "sku": sku,
            "publication": meta_publication,
            "traceability": {"publish_item_skus": [sku], "family_key": f"family-{sku}"},
        },
    }


def _write_payload(
    workspace: Path,
    group_id: str,
    sku: str,
    listing_type_id: str = "gold_special",
    *,
    publication_ready: bool | None = True,
) -> Path:
    path = workspace / "groups" / group_id / "70_payload.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            _payload(
                sku,
                listing_type_id,
                publication_ready=publication_ready,
            )
        ),
        encoding="utf-8",
    )
    return path


def _ml_item(
    item_id: str,
    sku: str,
    listing_type_id: str = "gold_special",
    *,
    status: str = "active",
) -> dict[str, Any]:
    return {
        "id": item_id,
        "status": status,
        "listing_type_id": listing_type_id,
        "seller_custom_field": sku,
    }


def test_artifact_reconcile_reports_published_unpublished_closed_and_ml_only(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write_payload(workspace, "G1", "SKU-A")
    _write_payload(workspace, "G2", "SKU-B")
    _write_payload(workspace, "G3", "SKU-C")
    marker = workspace / "groups" / "INDEX" / "70_payload.json"
    marker.parent.mkdir(parents=True)
    marker.write_text(json.dumps({"type": "independent_listings_index"}), encoding="utf-8")

    inventory = FakeInventory(
        [
            _ml_item("MLB1", "SKU-A", status="active"),
            _ml_item("MLB2", "SKU-C", status="closed"),
            _ml_item("MLB3", "SKU-EXTRA", status="paused"),
        ]
    )

    report = ReconcileUseCase(inventory).execute(workspace_root=workspace)

    assert report.summary["generated_published"] == 1
    assert report.summary["generated_not_published"] == 1
    assert report.summary["closed_on_ml"] == 1
    assert report.summary["ml_without_local_payload"] == 1
    assert report.summary["local_payload_error"] == 0
    assert not any(row.group_id == "INDEX" for row in report.rows)


def test_artifact_reconcile_reports_local_payload_errors(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    bad_json = workspace / "groups" / "BADJSON" / "70_payload.json"
    bad_json.parent.mkdir(parents=True, exist_ok=True)
    bad_json.write_text("{bad", encoding="utf-8")
    inconsistent = workspace / "groups" / "MIXED" / "70_payload.json"
    inconsistent.parent.mkdir(parents=True, exist_ok=True)
    inconsistent.write_text(
        json.dumps(
            {
                "payload": [
                    {"listing_type_id": "gold_special", "seller_custom_field": "SKU-1"},
                    {"listing_type_id": "gold_pro", "seller_custom_field": "SKU-2"},
                ]
            }
        ),
        encoding="utf-8",
    )
    _write_payload(workspace, "NOTREADY", "SKU-3", publication_ready=False)

    report = ReconcileUseCase(FakeInventory([])).execute(workspace_root=workspace)

    reasons = {row.error_reason for row in report.rows}
    assert report.summary["local_payload_error"] == 3
    assert any(str(reason).startswith("invalid_json") for reason in reasons)
    assert "listing_type_id_inconsistent" in reasons
    assert "publication_ready_false" in reasons


def test_reconcile_matches_variation_seller_sku_from_ml(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write_payload(workspace, "G1", "SKU-V")
    inventory = FakeInventory(
        [
            {
                "id": "MLB1",
                "status": "active",
                "listing_type_id": "gold_special",
                "variations": [
                    {
                        "id": 123,
                        "attribute_combinations": [{"id": "SELLER_SKU", "value_name": "SKU-V"}],
                    }
                ],
            }
        ]
    )

    report = ReconcileUseCase(inventory).execute(workspace_root=workspace)

    row = next(row for row in report.rows if row.group_id == "G1")
    assert row.status == "generated_published"
    assert row.ml_item_id == "MLB1"


def test_listing_type_mismatch_does_not_count_as_published(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write_payload(workspace, "G1", "SKU-A", "gold_special")
    inventory = FakeInventory([_ml_item("MLB1", "SKU-A", "gold_pro", status="active")])

    report = ReconcileUseCase(inventory).execute(workspace_root=workspace)

    local_row = next(row for row in report.rows if row.group_id == "G1")
    assert local_row.status == "generated_not_published"
    assert local_row.error_reason == "listing_type_mismatch"
    assert report.summary["ml_without_local_payload"] == 1


def _manifest_payload(workspace: Path, payload_path: str) -> dict[str, Any]:
    return {
        "run_id": "run-1",
        "created_at": "2026-05-12T22:00:00Z",
        "workspace_path": str(workspace),
        "status": "partial_success",
        "publication_candidates": [
            {
                "group_id": "G1",
                "family_id": "FAM-1",
                "sku_scope": ["SKU-A"],
                "topology": "family_variations",
                "build_status": "partial_success",
                "payloads": [
                    {
                        "variant": "classic",
                        "payload_path": payload_path,
                        "listing_type_id": "gold_special",
                        "publishable": True,
                    },
                    {
                        "variant": "premium",
                        "listing_type_id": "gold_pro",
                        "publishable": True,
                    },
                    {
                        "variant": "blocked",
                        "payload_path": payload_path,
                        "listing_type_id": "gold_special",
                        "publishable": False,
                    },
                ],
                "errors": [],
            }
        ],
        "build_failures": [
            {
                "sku": "SKU-BAD",
                "group_id": "GBAD",
                "family_id": "FBAD",
                "stage": "stage70_payload",
                "reason": "payload_failed",
                "publishable": False,
            }
        ],
        "diagnostics": {},
    }


def test_manifest_reconcile_keeps_variants_and_partial_errors(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    payload_path = _write_payload(workspace, "G1", "SKU-A")
    manifest_path = workspace / "runs" / "run-1" / "run_manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(
        json.dumps(_manifest_payload(workspace, str(payload_path))),
        encoding="utf-8",
    )
    inventory = FakeInventory([_ml_item("MLB1", "SKU-A", status="paused")])

    report = ReconcileUseCase(inventory).execute(
        workspace_root=workspace,
        from_manifest=True,
        manifest_path=manifest_path,
    )

    assert report.summary["generated_published"] == 1
    assert report.summary["expected_not_generated"] == 2
    assert report.summary["local_payload_error"] == 1
    assert any(row.variant == "classic" for row in report.rows)
    assert any(row.variant == "premium" for row in report.rows)


def test_invalid_manifest_reports_manifest_error_without_inventory_call(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    manifest_path = workspace / "runs" / "run-1" / "run_manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text("{}", encoding="utf-8")
    inventory = FakeInventory([_ml_item("MLB1", "SKU-A")])

    report = ReconcileUseCase(inventory).execute(
        workspace_root=workspace,
        from_manifest=True,
        manifest_path=manifest_path,
    )

    assert report.summary["manifest_error"] == 1
    assert inventory.search_calls == []


def test_save_report_writes_publication_audit(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write_payload(workspace, "G1", "SKU-A")

    report = ReconcileUseCase(FakeInventory([])).execute(
        workspace_root=workspace,
        save_report=True,
    )

    assert report.report_path is not None
    report_path = Path(report.report_path)
    assert report_path.parent == workspace / "publication_audits"
    saved = json.loads(report_path.read_text(encoding="utf-8"))
    assert saved["summary"]["generated_not_published"] == 1


def test_inventory_uses_scan_pagination_past_offset_limit(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write_payload(workspace, "G1", "SKU-1049")
    inventory = FakeInventory(
        [_ml_item(f"MLB{i}", f"SKU-{i}", status="active") for i in range(1051)]
    )

    report = ReconcileUseCase(inventory).execute(workspace_root=workspace)

    row = next(row for row in report.rows if row.group_id == "G1")
    assert row.status == "generated_published"
    assert row.ml_item_id == "MLB1049"
    assert ("active", 1050) in inventory.search_calls
