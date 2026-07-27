"""Public API for publishing ready-made ml-builder JSON payloads."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mercadolivre_upload.adapters.json_payload_reader import (
    InvalidPayloadError,
    JsonPayloadReader,
    ReadPayloadResult,
)
from mercadolivre_upload.api.client import MLApiClient
from mercadolivre_upload.application.publish_payload_use_case import (
    PublishPayloadUseCase,
)
from mercadolivre_upload.application.validators.seller_policy import (
    load_seller_config,
)
from mercadolivre_upload.auth.publisher_context import build_publisher_auth_context
from mercadolivre_upload.contracts.publication import PublicationOutcome, PublicationPhase
from mercadolivre_upload.domain.fiscal.field_policy import taxpayer_type_for_document
from mercadolivre_upload.domain.fiscal.service import FiscalService


def _build_use_case(
    *,
    publish_inactive: bool = False,
    seller_config_path: Path,
    workspace_root: Path,
    reader: JsonPayloadReader | None = None,
    ml_client_id: str | None = None,
    expected_seller_id: str | None = None,
    expected_document_type: str | None = None,
) -> PublishPayloadUseCase:
    """Wire the JSON publish use case with the normal scriptml-bot infrastructure."""
    from mercadolivre_upload.application.validators.seller_policy import SellerPolicyValidator

    config_path = Path(seller_config_path).expanduser().resolve()
    seller_config = load_seller_config(config_path)

    payload_reader = reader or JsonPayloadReader(strict_publisher_contract=True)
    auth_context = build_publisher_auth_context(
        settings_file=config_path,
        workspace_root=workspace_root,
        strict=True,
        ml_client_id=ml_client_id,
        expected_seller_id=expected_seller_id,
        expected_document_type=expected_document_type,
    )
    auth_manager = auth_context.token_manager
    api_client = MLApiClient(auth_manager)
    authenticated_document_type = (
        auth_context.expected_document_type
        if isinstance(auth_context.expected_document_type, str)
        else expected_document_type
    )
    expected_tax_payer_type = taxpayer_type_for_document(authenticated_document_type)
    if authenticated_document_type and expected_tax_payer_type is None:
        raise ValueError("Authenticated taxpayer document type has no fiscal policy mapping")
    fiscal_service = FiscalService(
        api_client,
        expected_tax_payer_type=expected_tax_payer_type,
    )
    policy = SellerPolicyValidator(seller_config)
    return PublishPayloadUseCase(
        reader=payload_reader,
        policy=policy,
        publisher=api_client,
        fiscal_service=fiscal_service,
        publish_inactive=publish_inactive or policy.requires_inactive_publication,
    )


@dataclass
class PublisherRuntime:
    """Reusable publisher infrastructure and payload cache for one invocation."""

    reader: JsonPayloadReader
    use_case: PublishPayloadUseCase
    _prepared_payloads: dict[Path, ReadPayloadResult] = field(default_factory=dict)

    @classmethod
    def build(
        cls,
        *,
        publish_inactive: bool,
        seller_config_path: Path,
        workspace_root: Path,
        reader: JsonPayloadReader | None = None,
        ml_client_id: str | None = None,
        expected_seller_id: str | None = None,
        expected_document_type: str | None = None,
    ) -> PublisherRuntime:
        """Build auth, API client, policy and fiscal service exactly once."""
        payload_reader = reader or JsonPayloadReader(strict_publisher_contract=True)
        return cls(
            reader=payload_reader,
            use_case=_build_use_case(
                publish_inactive=publish_inactive,
                seller_config_path=seller_config_path,
                workspace_root=workspace_root,
                reader=payload_reader,
                ml_client_id=ml_client_id,
                expected_seller_id=expected_seller_id,
                expected_document_type=expected_document_type,
            ),
        )

    def remember(self, payload_path: Path, prepared: ReadPayloadResult) -> None:
        """Seed the invocation cache with an already validated payload."""
        cache_key = Path(payload_path).expanduser().resolve()
        self._prepared_payloads[cache_key] = prepared

    def prepare(self, payload_path: Path) -> ReadPayloadResult:
        """Read and validate a payload once for this runtime."""
        path = Path(payload_path)
        cache_key = path.expanduser().resolve()
        prepared = self._prepared_payloads.get(cache_key)
        if prepared is None:
            prepared = self.reader.read(path)
            self._prepared_payloads[cache_key] = prepared
        return prepared

    def publish(self, payload_path: Path, *, dry_run: bool = False) -> PublicationOutcome:
        """Publish using the invocation-owned prepared payload."""
        path = Path(payload_path)
        try:
            prepared = self.prepare(path)
        except json.JSONDecodeError as exc:
            message = f"Invalid JSON payload: {exc}"
            return PublicationOutcome(
                sku=None,
                path=str(path),
                status="failed",
                error=message,
                phases=[
                    PublicationPhase(
                        name="payload_validation",
                        status="failed",
                        detail=message,
                    )
                ],
            )
        except InvalidPayloadError as exc:
            return PublicationOutcome(
                sku=None,
                path=str(path),
                status="failed",
                error=str(exc),
                phases=[
                    PublicationPhase(
                        name="payload_validation",
                        status="failed",
                        detail=str(exc),
                    )
                ],
            )
        except OSError as exc:
            message = f"Could not read payload file: {exc}"
            return PublicationOutcome(
                sku=None,
                path=str(path),
                status="failed",
                error=message,
                phases=[
                    PublicationPhase(
                        name="payload_validation",
                        status="failed",
                        detail=message,
                    )
                ],
            )
        return self.use_case.execute(
            path,
            dry_run=dry_run,
            prepared_payload=prepared,
        )


def serialize_publication_outcome(result: PublicationOutcome) -> dict[str, Any]:
    """Serialize the typed outcome for JSON/IPC compatibility boundaries."""
    errors = [result.error] if result.error else []
    return {
        "status": result.status,
        "side_effect_state": result.side_effect_state,
        "phases": [phase.model_dump(mode="json") for phase in result.phases],
        "sku": result.sku,
        "item_id": result.item_id,
        "item_ids": result.item_ids,
        "user_product_id": result.user_product_id,
        "publish_endpoints": result.publish_endpoints,
        "errors": errors,
        "warnings": result.warnings,
        "validation_status": result.validation_status,
        "validation_report": result.validation_report,
        "fiscal_status": result.fiscal_status,
        "fiscal_report": result.fiscal_report,
        "reconciliation_required": result.reconciliation_required,
        "report_path": result.report_path,
    }


def _with_report(
    result: PublicationOutcome,
    report_dir: Path | None,
) -> PublicationOutcome:
    """Attach the serialized report path without weakening the typed outcome."""
    if report_dir is None:
        return result
    report_path = _write_report([result], report_dir)
    return result.model_copy(update={"report_path": str(report_path)})


def _failure_outcome(
    *,
    payload_path: Path,
    message: str,
    report_dir: Path | None = None,
) -> PublicationOutcome:
    """Return a typed failure, optionally writing its report."""
    result = PublicationOutcome(
        sku=None,
        path=str(payload_path),
        status="failed",
        error=message,
        phases=[
            PublicationPhase(
                name="payload_validation",
                status="failed",
                detail=message,
            )
        ],
    )
    return _with_report(result, report_dir)


def _write_report(results: list[PublicationOutcome], report_dir: Path) -> Path:
    """Write a JSON payload publish report and return the created path."""
    report_dir.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    report_path = report_dir / "report.json"

    published = [r for r in results if r.status == "published"]
    published_but_not_grouped = [r for r in results if r.status == "published_but_not_grouped"]
    failed = [r for r in results if r.status == "failed"]
    skipped = [r for r in results if r.status == "skipped"]
    report: dict[str, Any] = {
        "run_id": run_id,
        "published_at": datetime.now(UTC).isoformat(),
        "summary": {
            "total": len(results),
            "published": len(published),
            "published_but_not_grouped": len(published_but_not_grouped),
            "failed": len(failed),
            "skipped": len(skipped),
        },
        "results": [
            {
                "sku": result.sku,
                "path": result.path,
                "status": result.status,
                "side_effect_state": result.side_effect_state,
                "phases": [phase.model_dump(mode="json") for phase in result.phases],
                "item_id": result.item_id,
                "item_ids": result.item_ids,
                "user_product_id": result.user_product_id,
                "publish_endpoints": result.publish_endpoints,
                "error": result.error,
                "warnings": result.warnings,
                "validation_status": result.validation_status,
                "validation_report": result.validation_report,
                "fiscal_status": result.fiscal_status,
                "fiscal_report": result.fiscal_report,
                "reconciliation_required": result.reconciliation_required,
            }
            for result in results
        ],
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report_path


def publish_payload_outcome(
    payload_path: Path,
    *,
    report_dir: Path | None = None,
    dry_run: bool = False,
    publish_inactive: bool = False,
    seller_config_path: Path,
    workspace_root: Path,
    runtime: PublisherRuntime | None = None,
    ml_client_id: str | None = None,
    expected_seller_id: str | None = None,
    expected_document_type: str | None = None,
) -> PublicationOutcome:
    """Publish a canonical payload variant produced by ml-builder.

    The input must use the public envelope ``payload``, ``description``,
    ``fiscal``, and ``_meta``. Publication reuses the same auth, token storage,
    Mercado Livre client, policy, and fiscal infrastructure for the invocation.
    """
    path = Path(payload_path)
    if not path.exists():
        return _failure_outcome(
            payload_path=path,
            message=f"Payload file not found: {path}",
            report_dir=report_dir,
        )
    if not path.is_file():
        return _failure_outcome(
            payload_path=path,
            message=f"Payload path is not a file: {path}",
            report_dir=report_dir,
        )

    if runtime is None:
        reader = JsonPayloadReader(strict_publisher_contract=True)
        try:
            prepared = reader.read(path)
        except json.JSONDecodeError as exc:
            return _failure_outcome(
                payload_path=path,
                message=f"Invalid JSON payload: {exc}",
                report_dir=report_dir,
            )
        except InvalidPayloadError as exc:
            return _failure_outcome(
                payload_path=path,
                message=str(exc),
                report_dir=report_dir,
            )
        except OSError as exc:
            return _failure_outcome(
                payload_path=path,
                message=f"Could not read payload file: {exc}",
                report_dir=report_dir,
            )
        effective_runtime = PublisherRuntime.build(
            publish_inactive=publish_inactive,
            seller_config_path=seller_config_path,
            workspace_root=workspace_root,
            reader=reader,
            ml_client_id=ml_client_id,
            expected_seller_id=expected_seller_id,
            expected_document_type=expected_document_type,
        )
        effective_runtime.remember(path, prepared)
    else:
        effective_runtime = runtime
    result = effective_runtime.publish(path, dry_run=dry_run)
    return _with_report(result, report_dir)


def publish_payload_file(
    payload_path: Path,
    *,
    report_dir: Path | None = None,
    dry_run: bool = False,
    publish_inactive: bool = False,
    seller_config_path: Path,
    workspace_root: Path,
    runtime: PublisherRuntime | None = None,
    ml_client_id: str | None = None,
    expected_seller_id: str | None = None,
    expected_document_type: str | None = None,
) -> dict[str, Any]:
    """Serialize a publication outcome for the CLI/dashboard IPC boundary.

    The dict return is retained because the current CLI and dashboard worker
    persist and transmit this response as JSON. Publisher internals must call
    :func:`publish_payload_outcome` instead.
    """
    outcome = publish_payload_outcome(
        payload_path,
        report_dir=report_dir,
        dry_run=dry_run,
        publish_inactive=publish_inactive,
        seller_config_path=seller_config_path,
        workspace_root=workspace_root,
        runtime=runtime,
        ml_client_id=ml_client_id,
        expected_seller_id=expected_seller_id,
        expected_document_type=expected_document_type,
    )
    return serialize_publication_outcome(outcome)


__all__ = [
    "PublisherRuntime",
    "publish_payload_file",
    "publish_payload_outcome",
    "serialize_publication_outcome",
]
