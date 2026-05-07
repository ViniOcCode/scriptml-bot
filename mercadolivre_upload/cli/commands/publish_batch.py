"""Publish builder-generated payload artifacts."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import typer
from rich.console import Console

from mercadolivre_upload.api.client import MLApiClient
from mercadolivre_upload.auth import TokenManager
from mercadolivre_upload.cli.commands.common import resolve_scriptml_cache_root, resolve_scriptml_workspace

console = Console()
err_console = Console(stderr=True)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _payload_paths(source: Path) -> list[Path]:
    if source.is_file():
        data = _read_json(source)
        if source.name == "batch_manifest.json" or "items" in data:
            paths: list[Path] = []
            for item in data.get("items", []):
                if isinstance(item, dict) and item.get("payload_path"):
                    paths.append(Path(str(item["payload_path"])).expanduser())
            return paths
        return [source]
    if source.is_dir():
        return sorted(source.rglob("payload.json"))
    return []


def _iter_payload_items(envelope: dict[str, Any]) -> list[dict[str, Any]]:
    payload = envelope.get("payload")
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        return [payload]
    return []


def _sku_for(envelope: dict[str, Any], item: dict[str, Any], path: Path) -> str:
    meta = envelope.get("_meta") if isinstance(envelope.get("_meta"), dict) else {}
    for value in (item.get("seller_custom_field"), item.get("sku"), meta.get("sku"), path.parent.name):
        if value:
            return str(value)
    return path.stem


def publish_batch(
    source: Path,
    *,
    workspace: Path | None = None,
    cache_root: Path | None = None,
    report_dir: Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Publish or validate builder payload artifacts and write publication_report.json."""
    resolved_workspace = resolve_scriptml_workspace(workspace)
    resolved_cache_root = resolve_scriptml_cache_root(cache_root)
    resolved_report_dir = report_dir or (resolved_workspace / "publish")
    resolved_report_dir.mkdir(parents=True, exist_ok=True)
    del resolved_cache_root  # cache root is accepted for CLI compatibility; publishing owns cache use.

    paths = _payload_paths(source.expanduser())
    if not paths:
        raise typer.BadParameter(f"No payload artifacts found at {source}")

    client = MLApiClient(TokenManager())
    items: list[dict[str, Any]] = []
    exit_failed = False
    for path in paths:
        try:
            envelope = _read_json(path)
            payload_items = _iter_payload_items(envelope)
            if not payload_items:
                raise ValueError("payload artifact has no publishable payload object")
            for payload_item in payload_items:
                sku = _sku_for(envelope, payload_item, path)
                if dry_run:
                    response = client.validate_item(payload_item)
                    status = "publish_skipped"
                    item_id = None
                else:
                    response = client.create_item(payload_item)
                    status = "published"
                    item_id = response.get("id") or response.get("item_id")
                items.append(
                    {
                        "sku": sku,
                        "payload_path": str(path),
                        "status": status,
                        "item_id": item_id,
                        "response": response,
                        "error": None,
                    }
                )
        except Exception as exc:  # noqa: BLE001 - CLI report must capture per-item failures.
            exit_failed = True
            items.append(
                {
                    "sku": path.parent.name,
                    "payload_path": str(path),
                    "status": "publish_failed",
                    "item_id": None,
                    "response": None,
                    "error": str(exc),
                }
            )

    totals: dict[str, int] = {"items": len(items)}
    for item in items:
        status = str(item["status"])
        totals[status] = totals.get(status, 0) + 1
    report = {
        "created_at": _utc_now(),
        "workspace": str(resolved_workspace),
        "source": str(source),
        "dry_run": dry_run,
        "items": items,
        "totals": totals,
    }
    report_path = resolved_report_dir / "publication_report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    console.print(f"publication_report: {report_path}")
    if exit_failed:
        raise typer.Exit(1)
    return report
