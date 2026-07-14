"""Public application API used by the mlbot dashboard."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer

from mercadolivre_upload.adapters.json_payload_reader import JsonPayloadReader
from mercadolivre_upload.api.client import MLApiClient
from mercadolivre_upload.application.publish.internals.validation import (
    classify_mercado_livre_validation_response,
)
from mercadolivre_upload.application.publish_payload import publish_payload_file
from mercadolivre_upload.application.validators.seller_policy import (
    SellerPolicyValidator,
    load_seller_config,
)
from mercadolivre_upload.auth.publisher_context import build_publisher_auth_context


def _expand_effective_payloads(payload: dict[str, Any], upload_mode: str) -> list[dict[str, Any]]:
    """Expand dashboard payload envelopes into concrete ML publish/validate payloads."""
    if upload_mode != "user_products":
        return [dict(payload)]

    base_payload = {
        key: value
        for key, value in payload.items()
        if key not in {"items", "payload", "_meta", "fiscal", "description", "description_by_sku"}
    }
    raw_items = payload.get("payload")
    if not isinstance(raw_items, list):
        raw_items = payload.get("items", [])
    if not isinstance(raw_items, list):
        return [base_payload]

    expanded: list[dict[str, Any]] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        merged = dict(base_payload)
        merged.update(item)
        expanded.append(merged)
    return expanded


def _prefix_item_message(message: str, index: int, total: int) -> str:
    return message if total <= 1 else f"item[{index}]: {message}"


def prepare_effective_payload_file(
    payload_path: Path,
    *,
    seller_config_path: Path,
) -> dict[str, Any]:
    """Read a payload and apply local seller policy checks without remote calls."""
    reader = JsonPayloadReader()
    read_result = reader.read(payload_path)
    policy = SellerPolicyValidator(load_seller_config(seller_config_path))
    payloads: list[dict[str, Any]] = []
    warnings: list[str] = []
    errors: list[str] = []
    raw_payloads = _expand_effective_payloads(read_result.payload, read_result.upload_mode)
    total = len(raw_payloads)
    for index, candidate in enumerate(raw_payloads, start=1):
        payload = policy.apply_overrides(candidate)
        policy_result = policy.validate(payload, ai_suggested=read_result.ai_suggested)
        payloads.append(payload)
        warnings.extend(
            _prefix_item_message(violation.message, index, total)
            for violation in policy_result.violations
            if violation.severity == "warning"
        )
        errors.extend(
            _prefix_item_message(violation.message, index, total)
            for violation in policy_result.violations
            if violation.severity == "error"
        )
    return {
        "status": "ok" if not errors else "failed",
        "sku": read_result.sku,
        "category_id": read_result.category_id,
        "upload_mode": read_result.upload_mode,
        "payload": payloads[0] if len(payloads) == 1 else read_result.payload,
        "payloads": payloads,
        "warnings": warnings,
        "errors": errors,
    }


def validate_effective_payload_file(
    payload_path: Path,
    *,
    seller_config_path: Path,
    workspace_root: Path,
) -> dict[str, Any]:
    """Validate a dashboard payload using local checks and Mercado Livre validation."""
    prepared = prepare_effective_payload_file(
        payload_path,
        seller_config_path=seller_config_path,
    )
    if prepared["status"] == "failed":
        return {
            **prepared,
            "validation_status": "local_validation_failed",
            "validation_report": {"errors": prepared["errors"], "warnings": prepared["warnings"]},
            "should_block": True,
        }

    auth_context = build_publisher_auth_context(
        settings_file=seller_config_path,
        workspace_root=workspace_root,
        strict=True,
    )
    client = MLApiClient(auth_context.token_manager)
    payloads = prepared.get("payloads")
    effective_payloads = (
        payloads
        if isinstance(payloads, list) and payloads
        else [prepared["payload"]]
    )
    classifications = []
    reports = []
    for payload in effective_payloads:
        if prepared["upload_mode"] == "user_products":
            validation = client.validate_user_product_item(payload)
        else:
            validation = client.validate_item(payload)
        classified = classify_mercado_livre_validation_response(validation)
        classifications.append(classified)
        reports.append(classified.to_report_dict())
    blocking = [item for item in classifications if item.should_block]
    warning = [item for item in classifications if item.status == "validation_passed_with_warnings"]
    status = (
        "validation_failed"
        if blocking
        else "validation_passed_with_warnings"
        if warning
        else "validation_passed"
    )
    return {
        **prepared,
        "validation_status": status,
        "validation_report": reports[0] if len(reports) == 1 else {"items": reports},
        "should_block": bool(blocking),
    }


def publish_effective_payload_file(
    payload_path: Path,
    *,
    seller_config_path: Path,
    workspace_root: Path,
    report_dir: Path | None = None,
    publish_inactive: bool = False,
) -> dict[str, Any]:
    """Publish a dashboard effective payload through the existing public publisher API."""
    return publish_payload_file(
        payload_path,
        report_dir=report_dir,
        dry_run=False,
        publish_inactive=publish_inactive,
        seller_config_path=seller_config_path,
        workspace_root=workspace_root,
    )


def publish_manifest_file(
    manifest_path: Path,
    *,
    seller_config_path: Path,
    workspace_root: Path,
    report_dir: Path,
    dry_run: bool = True,
    publish_inactive: bool = False,
) -> dict[str, Any]:
    """Publish or dry-run a run manifest and return the structured report.

    This is the dashboard-safe public facade for the manifest publication flow.
    The legacy CLI command still owns the implementation today, but callers no
    longer import CLI modules directly.
    """
    from mercadolivre_upload.cli.commands.publish_manifest import publish_manifest

    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "report.json"
    cli_exit_code: int | None = None
    try:
        publish_manifest(
            manifest_path=manifest_path,
            dry_run=dry_run,
            publish_inactive=publish_inactive,
            workspace_root=workspace_root,
            report_dir=report_dir,
            seller_config=seller_config_path,
        )
    except typer.Exit as exc:
        cli_exit_code = int(exc.exit_code or 0)
        if not report_path.exists():
            raise
    report = (
        json.loads(report_path.read_text(encoding="utf-8"))
        if report_path.exists()
        else {}
    )
    if isinstance(report, dict):
        report.setdefault("report_path", str(report_path))
        if cli_exit_code is not None:
            report.setdefault("cli_exit_code", cli_exit_code)
        return report
    return {"status": "unknown", "report_path": str(report_path), "report": report}


def apply_remote_item_update(
    item_id: str,
    patch: dict[str, Any],
    *,
    operation: str = "update",
    seller_config_path: Path,
    workspace_root: Path,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Apply an allowlisted remote item update for post-publication operations."""
    lifecycle_status = {
        "pause": "paused",
        "activate": "active",
        "finalize": "closed",
        "delete": "closed",
    }
    if operation == "update":
        if "status" in patch:
            return {
                "status": "failed",
                "errors": ["Status changes require pause, activate, finalize, or delete operation."],
            }
        allowed = {"price", "available_quantity", "title", "pictures", "attributes"}
    elif operation in lifecycle_status:
        expected_patch = {"status": lifecycle_status[operation]}
        if patch != expected_patch:
            return {
                "status": "failed",
                "errors": [f"Operation {operation} requires the exact patch {expected_patch}."],
            }
        allowed = {"status"}
    else:
        return {"status": "failed", "errors": [f"Unsupported remote operation: {operation}"]}
    rejected = sorted(key for key in patch if key not in allowed)
    if rejected:
        return {"status": "failed", "errors": [f"Unsupported remote update fields: {rejected}"]}
    if dry_run:
        return {"status": "dry_run", "item_id": item_id, "patch": patch}

    auth_context = build_publisher_auth_context(
        settings_file=seller_config_path,
        workspace_root=workspace_root,
        strict=True,
    )
    client = MLApiClient(auth_context.token_manager)
    return {"status": "updated", "item_id": item_id, "response": client.update_item(item_id, patch)}


def fetch_remote_item(
    item_id: str,
    *,
    seller_config_path: Path,
    workspace_root: Path,
) -> dict[str, Any]:
    """Fetch a single remote Mercado Livre item for dashboard sync."""
    auth_context = build_publisher_auth_context(
        settings_file=seller_config_path,
        workspace_root=workspace_root,
        strict=True,
    )
    client = MLApiClient(auth_context.token_manager)
    return {"status": "synced", "item_id": item_id, "item": client.get(f"/items/{item_id}")}


def fetch_authenticated_seller_identity(
    *,
    seller_config_path: Path,
    workspace_root: Path,
) -> dict[str, str]:
    """Return the minimal authenticated seller identity needed by safe operations."""
    auth_context = build_publisher_auth_context(
        settings_file=seller_config_path,
        workspace_root=workspace_root,
        strict=True,
    )
    client = MLApiClient(auth_context.token_manager)
    seller = client.get("/users/me")
    if not isinstance(seller, dict):
        raise RuntimeError("GET /users/me returned an invalid response")
    seller_id = str(seller.get("id") or "").strip()
    site_id = str(seller.get("site_id") or "").strip().upper()
    if not seller_id or not site_id:
        raise RuntimeError("GET /users/me did not return seller id and site id")
    return {"status": "authenticated", "seller_id": seller_id, "site_id": site_id}


__all__ = [
    "apply_remote_item_update",
    "fetch_authenticated_seller_identity",
    "fetch_remote_item",
    "prepare_effective_payload_file",
    "publish_effective_payload_file",
    "publish_manifest_file",
    "validate_effective_payload_file",
]
