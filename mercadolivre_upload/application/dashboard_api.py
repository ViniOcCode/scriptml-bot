"""Public application API used by the mlbot dashboard."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import requests
import typer

from mercadolivre_upload.adapters.json_payload_reader import JsonPayloadReader
from mercadolivre_upload.api.client import MLApiClient, validate_item_id
from mercadolivre_upload.application.mutation_failure import is_ambiguous_mutation_failure
from mercadolivre_upload.application.publish.internals.validation import (
    classify_mercado_livre_validation_response,
)
from mercadolivre_upload.application.publish_payload import (
    publish_payload_outcome,
    serialize_publication_outcome,
)
from mercadolivre_upload.application.user_product_contract import (
    expand_effective_payloads,
)
from mercadolivre_upload.application.validators.seller_policy import (
    SellerPolicyValidator,
    load_seller_config,
)
from mercadolivre_upload.auth.exceptions import AuthError
from mercadolivre_upload.auth.publisher_context import build_publisher_auth_context
from mercadolivre_upload.contracts.publication import PublicationOutcome


def _prefix_item_message(message: str, index: int, total: int) -> str:
    return message if total <= 1 else f"item[{index}]: {message}"


def _authenticated_seller(
    client: MLApiClient,
    *,
    expected_seller_id: str | None,
    expected_document_type: str | None,
) -> dict[str, str]:
    seller = client.get("/users/me")
    if not isinstance(seller, dict):
        raise AuthError("Mercado Livre authenticated identity is invalid")
    seller_id = str(seller.get("id") or seller.get("user_id") or "").strip()
    site_id = str(seller.get("site_id") or "").strip().upper()
    identification = seller.get("identification")
    identification = identification if isinstance(identification, dict) else {}
    document_type = str(identification.get("type") or "").strip().upper()
    if not seller_id or not site_id:
        raise AuthError("Mercado Livre authenticated identity is incomplete")
    if expected_seller_id and seller_id != expected_seller_id.strip():
        raise AuthError("Authenticated Mercado Livre seller does not match the expected seller")
    if expected_document_type and document_type != expected_document_type.strip().upper():
        raise AuthError(
            "Authenticated Mercado Livre taxpayer document does not match the expected document"
        )
    return {
        "seller_id": seller_id,
        "site_id": site_id,
        "document_type": document_type,
    }


def _build_authenticated_client(
    *,
    seller_config_path: Path,
    workspace_root: Path,
    ml_client_id: str | None,
    expected_seller_id: str | None,
    expected_document_type: str | None,
) -> tuple[MLApiClient, dict[str, str]]:
    auth_context = build_publisher_auth_context(
        settings_file=seller_config_path,
        workspace_root=workspace_root,
        strict=True,
        ml_client_id=ml_client_id,
        expected_seller_id=expected_seller_id,
        expected_document_type=expected_document_type,
    )
    client = MLApiClient(auth_context.token_manager)
    identity = _authenticated_seller(
        client,
        expected_seller_id=expected_seller_id,
        expected_document_type=expected_document_type,
    )
    return client, identity


def prepare_effective_payload_file(
    payload_path: Path,
    *,
    seller_config_path: Path,
) -> dict[str, Any]:
    """Read a payload and apply local seller policy checks without remote calls."""
    reader = JsonPayloadReader(strict_publisher_contract=True)
    read_result = reader.read(payload_path)
    policy = SellerPolicyValidator(load_seller_config(seller_config_path))
    payloads: list[dict[str, Any]] = []
    warnings: list[str] = []
    errors: list[str] = []
    raw_payloads = expand_effective_payloads(read_result.payload, read_result.upload_mode)
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
    ml_client_id: str | None = None,
    expected_seller_id: str | None = None,
    expected_document_type: str | None = None,
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

    client, _identity = _build_authenticated_client(
        seller_config_path=seller_config_path,
        workspace_root=workspace_root,
        ml_client_id=ml_client_id,
        expected_seller_id=expected_seller_id,
        expected_document_type=expected_document_type,
    )
    payloads = prepared.get("payloads")
    effective_payloads = (
        payloads if isinstance(payloads, list) and payloads else [prepared["payload"]]
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
        else "validation_passed_with_warnings" if warning else "validation_passed"
    )
    return {
        **prepared,
        "validation_status": status,
        "validation_report": reports[0] if len(reports) == 1 else {"items": reports},
        "should_block": bool(blocking),
    }


def publish_effective_payload_outcome(
    payload_path: Path,
    *,
    seller_config_path: Path,
    workspace_root: Path,
    report_dir: Path | None = None,
    publish_inactive: bool = False,
    ml_client_id: str | None = None,
    expected_seller_id: str | None = None,
    expected_document_type: str | None = None,
) -> PublicationOutcome:
    """Publish a dashboard effective payload while preserving the typed outcome."""
    _build_authenticated_client(
        seller_config_path=seller_config_path,
        workspace_root=workspace_root,
        ml_client_id=ml_client_id,
        expected_seller_id=expected_seller_id,
        expected_document_type=expected_document_type,
    )
    return publish_payload_outcome(
        payload_path,
        report_dir=report_dir,
        dry_run=False,
        publish_inactive=publish_inactive,
        ml_client_id=ml_client_id,
        expected_seller_id=expected_seller_id,
        expected_document_type=expected_document_type,
        seller_config_path=seller_config_path,
        workspace_root=workspace_root,
    )


def publish_effective_payload_file(
    payload_path: Path,
    *,
    seller_config_path: Path,
    workspace_root: Path,
    report_dir: Path | None = None,
    publish_inactive: bool = False,
    ml_client_id: str | None = None,
    expected_seller_id: str | None = None,
    expected_document_type: str | None = None,
) -> dict[str, Any]:
    """Serialize an effective-payload outcome for dashboard worker IPC.

    The dashboard worker currently persists this mapping as JSON and sends it
    across a process queue, so serialization is intentional at this boundary.
    """
    outcome = publish_effective_payload_outcome(
        payload_path,
        seller_config_path=seller_config_path,
        workspace_root=workspace_root,
        report_dir=report_dir,
        publish_inactive=publish_inactive,
        ml_client_id=ml_client_id,
        expected_seller_id=expected_seller_id,
        expected_document_type=expected_document_type,
    )
    return serialize_publication_outcome(outcome)


def publish_manifest_file(
    manifest_path: Path,
    *,
    seller_config_path: Path,
    workspace_root: Path,
    report_dir: Path,
    dry_run: bool = True,
    publish_inactive: bool = False,
    ml_client_id: str | None = None,
) -> dict[str, Any]:
    """Publish or dry-run a manifest and serialize its aggregate report.

    A manifest can contain multiple ``PublicationOutcome`` values, so this
    dashboard IPC boundary returns the JSON report rather than pretending the
    aggregate is a single payload outcome. The CLI command keeps each payload
    typed until report construction.
    """
    from mercadolivre_upload.cli.commands.publish_manifest import publish_manifest

    expected_seller_id = os.getenv("MLBOT_EXPECTED_SELLER_ID", "").strip() or None
    expected_document_type = os.getenv("MLBOT_EXPECTED_DOCUMENT_TYPE", "").strip() or None
    _build_authenticated_client(
        seller_config_path=seller_config_path,
        workspace_root=workspace_root,
        ml_client_id=ml_client_id,
        expected_seller_id=expected_seller_id,
        expected_document_type=expected_document_type,
    )
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
            ml_client_id=ml_client_id,
            expected_seller_id=expected_seller_id,
            expected_document_type=expected_document_type,
        )
    except typer.Exit as exc:
        cli_exit_code = int(exc.exit_code or 0)
        if not report_path.exists():
            return {
                "status": "failed",
                "result_code": "publication_unavailable",
                "errors": ["Este lote não está disponível para publicação."],
                "report_path": str(report_path),
                "cli_exit_code": cli_exit_code,
            }
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
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
    ml_client_id: str | None = None,
    expected_seller_id: str | None = None,
    expected_document_type: str | None = None,
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
                "side_effect_state": "none",
                "reconciliation_required": False,
                "errors": [
                    "Status changes require pause, activate, finalize, or delete operation."
                ],
            }
        allowed = {"price", "available_quantity", "title", "pictures", "attributes"}
    elif operation in lifecycle_status:
        expected_patch = {"status": lifecycle_status[operation]}
        if patch != expected_patch:
            return {
                "status": "failed",
                "side_effect_state": "none",
                "reconciliation_required": False,
                "errors": [f"Operation {operation} requires the exact patch {expected_patch}."],
            }
        allowed = {"status"}
    else:
        return {
            "status": "failed",
            "side_effect_state": "none",
            "reconciliation_required": False,
            "errors": [f"Unsupported remote operation: {operation}"],
        }
    rejected = sorted(key for key in patch if key not in allowed)
    if rejected:
        return {
            "status": "failed",
            "side_effect_state": "none",
            "reconciliation_required": False,
            "errors": [f"Unsupported remote update fields: {rejected}"],
        }
    if dry_run:
        return {
            "status": "dry_run",
            "side_effect_state": "none",
            "reconciliation_required": False,
            "item_id": item_id,
            "operation": operation,
            "patch": patch,
        }

    validate_item_id(item_id)
    client, identity = _build_authenticated_client(
        seller_config_path=seller_config_path,
        workspace_root=workspace_root,
        ml_client_id=ml_client_id,
        expected_seller_id=expected_seller_id,
        expected_document_type=expected_document_type,
    )
    if not item_id.startswith(identity["site_id"]):
        raise AuthError("Remote item site does not match the authenticated seller site")
    try:
        response = client.update_item(item_id, patch)
    except requests.RequestException as exc:
        if not is_ambiguous_mutation_failure(exc):
            return {
                "status": "failed",
                "side_effect_state": "none",
                "reconciliation_required": False,
                "item_id": item_id,
                "errors": ["A atualização foi rejeitada pelo provedor."],
            }
        return {
            "status": "unknown",
            "side_effect_state": "unknown",
            "reconciliation_required": True,
            "item_id": item_id,
            "errors": [
                "Não foi possível confirmar a atualização. "
                "Verifique o anúncio antes de tentar novamente."
            ],
        }
    return {
        "status": "updated",
        "side_effect_state": "confirmed",
        "reconciliation_required": False,
        "item_id": item_id,
        "operation": operation,
        "patch": patch,
        "response": response,
    }


def fetch_remote_item(
    item_id: str,
    *,
    seller_config_path: Path,
    workspace_root: Path,
    ml_client_id: str | None = None,
    expected_seller_id: str | None = None,
    expected_document_type: str | None = None,
) -> dict[str, Any]:
    """Fetch a single remote Mercado Livre item for dashboard sync."""
    validate_item_id(item_id)
    client, identity = _build_authenticated_client(
        seller_config_path=seller_config_path,
        workspace_root=workspace_root,
        ml_client_id=ml_client_id,
        expected_seller_id=expected_seller_id,
        expected_document_type=expected_document_type,
    )
    if not item_id.startswith(identity["site_id"]):
        raise AuthError("Remote item site does not match the authenticated seller site")
    return {"status": "synced", "item_id": item_id, "item": client.get(f"/items/{item_id}")}


def fetch_authenticated_seller_identity(
    *,
    seller_config_path: Path,
    workspace_root: Path,
    ml_client_id: str | None = None,
    expected_seller_id: str | None = None,
) -> dict[str, str]:
    """Return the minimal authenticated seller identity needed by safe operations."""
    auth_context = build_publisher_auth_context(
        settings_file=seller_config_path,
        workspace_root=workspace_root,
        strict=True,
        ml_client_id=ml_client_id,
        expected_seller_id=expected_seller_id,
    )
    client = MLApiClient(auth_context.token_manager)
    identity = _authenticated_seller(
        client,
        expected_seller_id=expected_seller_id,
        expected_document_type=None,
    )
    return {
        "status": "authenticated",
        "seller_id": identity["seller_id"],
        "site_id": identity["site_id"],
    }


__all__ = [
    "apply_remote_item_update",
    "fetch_authenticated_seller_identity",
    "fetch_remote_item",
    "prepare_effective_payload_file",
    "publish_effective_payload_file",
    "publish_effective_payload_outcome",
    "publish_manifest_file",
    "validate_effective_payload_file",
]
