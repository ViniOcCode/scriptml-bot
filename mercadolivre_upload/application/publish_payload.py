"""Public API for publishing ready-made ml-builder JSON payloads."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mercadolivre_upload.adapters.json_payload_reader import JsonPayloadReader
from mercadolivre_upload.api.client import MLApiClient
from mercadolivre_upload.application.publish_payload_use_case import (
    PublishPayloadUseCase,
    PublishPayloadResult,
)
from mercadolivre_upload.application.validators.seller_policy import (
    load_seller_config,
)
from mercadolivre_upload.auth.publisher_context import build_publisher_auth_context
from mercadolivre_upload.domain.fiscal.service import FiscalService


def _build_use_case(
    *,
    publish_inactive: bool = False,
    seller_config_path: Path,
    workspace_root: Path,
) -> PublishPayloadUseCase:
    """Wire the JSON publish use case with the normal scriptml-bot infrastructure."""
    from mercadolivre_upload.application.validators.seller_policy import SellerPolicyValidator

    config_path = Path(seller_config_path).expanduser().resolve()
    seller_config = load_seller_config(config_path)

    reader = JsonPayloadReader()
    auth_context = build_publisher_auth_context(
        settings_file=config_path,
        workspace_root=workspace_root,
        strict=True,
    )
    auth_manager = auth_context.token_manager
    api_client = MLApiClient(auth_manager)
    fiscal_service = FiscalService(api_client)
    return PublishPayloadUseCase(
        reader=reader,
        policy=SellerPolicyValidator(seller_config),
        publisher=api_client,
        fiscal_service=fiscal_service,
        publish_inactive=publish_inactive,
    )


def _result_to_dict(result: PublishPayloadResult, *, report_path: Path | None = None) -> dict[str, Any]:
    """Convert the existing result dataclass into the public structured response."""
    errors = [result.error] if result.error else []
    return {
        "status": result.status,
        "sku": result.sku,
        "item_id": result.item_id,
        "item_ids": result.item_ids,
        "user_product_id": result.user_product_id,
        "errors": errors,
        "warnings": result.warnings,
        "validation_status": result.validation_status,
        "validation_report": result.validation_report,
        "fiscal_status": result.fiscal_status,
        "fiscal_report": result.fiscal_report,
        "report_path": str(report_path) if report_path is not None else None,
    }


def _failure(
    *,
    payload_path: Path,
    message: str,
    report_dir: Path | None = None,
) -> dict[str, Any]:
    """Return a structured failure, optionally writing it to the report directory."""
    result = PublishPayloadResult(
        sku=None,
        path=str(payload_path),
        status="failed",
        error=message,
    )
    report_path = _write_report([result], report_dir) if report_dir is not None else None
    return _result_to_dict(result, report_path=report_path)


def _write_report(results: list[PublishPayloadResult], report_dir: Path) -> Path:
    """Write a JSON payload publish report and return the created path."""
    report_dir.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    report_path = report_dir / "report.json"

    published = [r for r in results if r.status == "published"]
    failed = [r for r in results if r.status == "failed"]
    skipped = [r for r in results if r.status == "skipped"]
    report: dict[str, Any] = {
        "run_id": run_id,
        "published_at": datetime.now(UTC).isoformat(),
        "summary": {
            "total": len(results),
            "published": len(published),
            "failed": len(failed),
            "skipped": len(skipped),
        },
        "results": [
            {
                "sku": result.sku,
                "path": result.path,
                "status": result.status,
                "item_id": result.item_id,
                "item_ids": result.item_ids,
                "user_product_id": result.user_product_id,
                "error": result.error,
                "warnings": result.warnings,
                "validation_status": result.validation_status,
                "validation_report": result.validation_report,
                "fiscal_status": result.fiscal_status,
                "fiscal_report": result.fiscal_report,
            }
            for result in results
        ],
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report_path


def publish_payload_file(
    payload_path: Path,
    *,
    report_dir: Path | None = None,
    dry_run: bool = False,
    publish_inactive: bool = False,
    seller_config_path: Path,
    workspace_root: Path,
) -> dict[str, Any]:
    """Publish a ready-made payload JSON file produced by ml-builder.

    The path may point at either the artifact-store ``70_payload.json`` or the
    workspace ``payload.json`` copy. The JSON contract is validated by
    ``JsonPayloadReader`` and publication reuses the same auth, token storage,
    Mercado Livre client, policy, and fiscal infrastructure as the existing
    scriptml-bot publish flow.
    """
    path = Path(payload_path)
    if not path.exists():
        return _failure(
            payload_path=path,
            message=f"Payload file not found: {path}",
            report_dir=report_dir,
        )
    if not path.is_file():
        return _failure(
            payload_path=path,
            message=f"Payload path is not a file: {path}",
            report_dir=report_dir,
        )

    try:
        raw_payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return _failure(
            payload_path=path,
            message=f"Invalid JSON payload: {exc}",
            report_dir=report_dir,
        )
    except OSError as exc:
        return _failure(
            payload_path=path,
            message=f"Could not read payload file: {exc}",
            report_dir=report_dir,
        )
    if not isinstance(raw_payload, dict):
        return _failure(
            payload_path=path,
            message="Invalid payload: root JSON value must be an object",
            report_dir=report_dir,
        )

    use_case = _build_use_case(
        publish_inactive=publish_inactive,
        seller_config_path=seller_config_path,
        workspace_root=workspace_root,
    )
    result = use_case.execute(path, dry_run=dry_run)
    report_path = _write_report([result], report_dir) if report_dir is not None else None
    return _result_to_dict(result, report_path=report_path)


__all__ = ["publish_payload_file"]
