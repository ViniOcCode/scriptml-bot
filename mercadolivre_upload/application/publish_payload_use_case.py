"""Use case for publishing a single payload.json to Mercado Livre.

Orchestrates: read → apply overrides → validate policy → publish → post description/fiscal.
Fully synchronous — matches the existing codebase patterns.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from mercadolivre_upload.adapters.json_payload_reader import (
    InvalidPayloadError,
    JsonPayloadReader,
    ReadPayloadResult,
)
from mercadolivre_upload.api.client import validate_item_id
from mercadolivre_upload.api.exceptions import MLApiError
from mercadolivre_upload.application.mutation_failure import is_ambiguous_mutation_failure
from mercadolivre_upload.application.ports import ItemPublisherPort
from mercadolivre_upload.application.publish.internals.validation import (
    MercadoLivreValidationResult,
    classify_mercado_livre_validation_response,
)
from mercadolivre_upload.application.user_product_contract import expand_effective_payloads
from mercadolivre_upload.application.validators.seller_policy import SellerPolicyValidator
from mercadolivre_upload.contracts.publication import PublicationOutcome, PublicationPhase
from mercadolivre_upload.domain.fiscal.data import FiscalData
from mercadolivre_upload.domain.fiscal.service import FiscalService
from mercadolivre_upload.infrastructure.logging import log_safe_event

logger = logging.getLogger(__name__)


@dataclass
class _PublicationContext:
    """Mutable state shared by the explicit publication phases."""

    path: Path
    read_result: ReadPayloadResult
    publish_payloads: list[dict[str, Any]]
    warnings: list[str]
    phases: list[PublicationPhase]
    listing_type_evidence: list[dict[str, Any]] = field(default_factory=list)
    validation_status: str = "validation_passed"
    validation_report: dict[str, Any] | None = None

    @property
    def total_payloads(self) -> int:
        """Return the number of concrete item payloads in this publication."""
        return len(self.publish_payloads)


@dataclass
class _CreatedItems:
    """Confirmed item-creation state shared by later grouping and fiscal phases."""

    item_ids: list[str] = field(default_factory=list)
    items: list[dict[str, Any]] = field(default_factory=list)
    endpoints: list[str] = field(default_factory=list)
    first_item_id: str | None = None
    user_product_id: str | None = None
    description_posted: bool = False
    by_sku: dict[str, tuple[str, dict[str, Any]]] = field(default_factory=dict)
    variation_id_by_sku: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class _CreatedItem:
    """A single confirmed create response with the payload and route used."""

    response: dict[str, Any]
    item_id: str
    endpoint: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class _FiscalTarget:
    """Resolved remote target for one fiscal entry."""

    item_id: str
    payload: dict[str, Any]
    variation_id: str | None


def _prefix_message(message: str, index: int, total: int) -> str:
    """Prefix per-item messages only when one file expands to many publishes."""
    if total <= 1:
        return message
    return f"item[{index}]: {message}"


def _is_existing_user_product_selling_condition_payload(payload: dict[str, Any]) -> bool:
    return any(
        payload.get(field) == "existing_user_product_selling_condition"
        for field in ("target", "execution_mode")
    )


def _publish_endpoint_for_payload(payload: dict[str, Any], upload_mode: str) -> str:
    if upload_mode == "user_products" and _is_existing_user_product_selling_condition_payload(
        payload
    ):
        return "/user-products/{user_product_id}/items"
    return "/items"


def _normalize_grouping_id(raw: object) -> str | None:
    if raw is None:
        return None
    if isinstance(raw, str):
        text = raw.strip()
    elif isinstance(raw, (int, float)):
        text = str(raw).strip()
    else:
        return None
    return text or None


def _family_id_from_item(item: dict[str, Any]) -> str | None:
    return _normalize_grouping_id(item.get("family_id"))


def _user_product_id_from_item(item: dict[str, Any]) -> str | None:
    return _normalize_grouping_id(item.get("user_product_id"))


def _resolve_family_ids_for_grouping(
    created_items: list[dict[str, Any]],
    publisher: ItemPublisherPort,
) -> list[str | None]:
    family_ids: list[str | None] = []
    for item in created_items:
        if not isinstance(item, dict):
            family_ids.append(None)
            continue
        family_id = _family_id_from_item(item)
        user_product_id = _user_product_id_from_item(item)
        if family_id is None and user_product_id:
            try:
                up_payload = publisher.get_user_product(user_product_id)
                if isinstance(up_payload, dict):
                    family_id = _family_id_from_item(up_payload)
            except Exception as exc:  # noqa: BLE001
                _log_remote_exception(
                    event="payload_grouping_family_lookup_failed",
                    operation="get_user_product",
                    exc=exc,
                    item_id=user_product_id,
                    status="validation_not_completed",
                )
        family_ids.append(family_id)
    return family_ids


def _verify_user_products_grouping(
    created_items: list[dict[str, Any]],
    *,
    publisher: ItemPublisherPort,
) -> tuple[bool, str | None]:
    """Return whether multi-item UP publishes share a consistent family_id."""
    if len(created_items) <= 1:
        return True, None

    family_ids = _resolve_family_ids_for_grouping(created_items, publisher)
    if any(family_id is None for family_id in family_ids):
        return False, "missing_family_id_for_multi_item_user_products_publish"
    if len(set(family_ids)) > 1:
        return False, "divergent_family_id_across_user_product_items"
    return True, None


def _format_blocking_cause(cause: dict[str, Any]) -> str:
    """Format one blocking API cause with references when present."""
    code = cause.get("code")
    message = cause.get("message")
    references = cause.get("references")
    pieces = [f"[{code}]" if code else "[?]"]
    if isinstance(references, list) and references:
        pieces.append(f"references={','.join(str(ref) for ref in references)}")
    if isinstance(message, str) and message.strip():
        pieces.append(message.strip())
    return " | ".join(pieces)


def _format_response_fragment(exc: MLApiError) -> str | None:
    """Return serialized API response data or a non-empty raw response body."""
    response_fragment: str | None = None
    response_body: Any | None = exc.response_body
    if response_body is None and exc.response is not None:
        try:
            response_body = exc.response.json()
        except (TypeError, ValueError, AttributeError):
            raw_text = getattr(exc.response, "text", "")
            if isinstance(raw_text, str):
                raw_text = raw_text.strip()
            if raw_text:
                response_fragment = raw_text

    if response_body is not None:
        try:
            response_fragment = json.dumps(response_body, sort_keys=True)
        except (TypeError, ValueError):
            response_fragment = str(response_body)

    return response_fragment


def _format_sanitization_fragment(metadata: dict[str, Any] | None) -> str | None:
    """Return removal evidence attached to a sanitized API request, if any."""
    if not isinstance(metadata, dict):
        return None

    removed_fields = metadata.get("removed_fields")
    endpoint = metadata.get("endpoint")
    if not removed_fields and not endpoint:
        return None
    return "sanitized=" + json.dumps(
        {
            "endpoint": endpoint,
            "removed_fields": removed_fields or [],
        },
        sort_keys=True,
    )


def _format_ml_api_error(
    exc: MLApiError,
    *,
    sanitization_metadata: dict[str, Any] | None = None,
) -> str:
    """Format ML API errors, preserving full response payload when available."""
    blocking = [cause for cause in exc.causes if cause.get("type") == "error"]
    blocking_message = "; ".join(
        f"[{cause.get('code', '?')}] {cause.get('message', '')}" for cause in blocking
    )
    cause_fragments = [_format_blocking_cause(cause) for cause in blocking]
    sanitization_fragment = _format_sanitization_fragment(sanitization_metadata)
    if sanitization_fragment:
        cause_fragments.append(sanitization_fragment)

    parts = [
        part
        for part in (
            blocking_message,
            "; ".join(cause_fragments),
            _format_response_fragment(exc),
        )
        if part
    ]
    return " | ".join(parts) if parts else "Mercado Livre API request failed"


def _public_remote_error(exc: Exception, *, operation: str, ambiguous: bool = False) -> str:
    """Return a stable public error without serializing transport exception text."""
    if isinstance(exc, MLApiError):
        return _format_ml_api_error(exc)
    if ambiguous:
        return f"{operation} has an unknown remote state; reconciliation is required"
    return f"{operation} failed unexpectedly"


def _log_remote_exception(
    *,
    event: str,
    operation: str,
    exc: Exception,
    item_id: str | None = None,
    status: str | None = None,
) -> None:
    """Record structural remote-failure evidence without exception or payload contents."""
    log_safe_event(
        logger,
        logging.ERROR,
        event,
        operation=operation,
        item_id=item_id,
        status=status,
        error_type=type(exc).__name__,
    )


def _format_validation_response(validation: Any) -> str:
    """Format full validation response for diagnostics."""
    try:
        return json.dumps(validation, sort_keys=True)
    except (TypeError, ValueError):
        return str(validation)


def _extract_valid_created_item_id(response: Any) -> str | None:
    """Return a valid ML item ID from a successful creation response, if present."""
    if not isinstance(response, dict):
        return None
    raw_item_id = response.get("id")
    if not isinstance(raw_item_id, str):
        return None
    item_id = raw_item_id.strip()
    try:
        validate_item_id(item_id)
    except ValueError:
        return None
    return item_id


def _normalize_optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _extract_payload_seller_sku(payload: dict[str, Any]) -> str | None:
    """Extract SKU from common item payload locations."""
    seller_custom_field = _normalize_optional_text(payload.get("seller_custom_field"))
    if seller_custom_field:
        return seller_custom_field

    attributes = payload.get("attributes")
    if not isinstance(attributes, list):
        return None

    for attribute in attributes:
        if not isinstance(attribute, dict):
            continue
        attr_id = _normalize_optional_text(attribute.get("id"))
        if not attr_id or attr_id.upper() != "SELLER_SKU":
            continue

        for key in ("value_name", "value_id"):
            candidate = _normalize_optional_text(attribute.get(key))
            if candidate:
                return candidate
    return None


def _description_for_publish_item(
    *,
    shared_description: str | None,
    description_by_sku: dict[str, str],
    sku: str | None,
) -> str | None:
    if sku:
        direct = description_by_sku.get(sku)
        if direct:
            return direct
        sku_key = sku.casefold()
        for candidate_sku, description in description_by_sku.items():
            if candidate_sku.casefold() == sku_key and description:
                return description
    return shared_description


def _extract_variation_seller_sku(variation: dict[str, Any]) -> str | None:
    """Extract SELLER_SKU from a variation payload returned by ML."""
    seller_custom_field = _normalize_optional_text(variation.get("seller_custom_field"))
    if seller_custom_field:
        return seller_custom_field

    for key in ("attributes", "attribute_combinations"):
        raw_attributes = variation.get(key)
        if not isinstance(raw_attributes, list):
            continue
        for attribute in raw_attributes:
            if not isinstance(attribute, dict):
                continue
            attr_id = _normalize_optional_text(attribute.get("id"))
            if not attr_id or attr_id.upper() != "SELLER_SKU":
                continue
            for value_key in ("value_name", "value_id"):
                candidate = _normalize_optional_text(attribute.get(value_key))
                if candidate:
                    return candidate
    return None


def _extract_variation_ids_by_sku(created_item: dict[str, Any]) -> dict[str, str]:
    """Build SKU -> variation_id mapping from created item response variations."""
    variations = created_item.get("variations")
    if not isinstance(variations, list):
        return {}

    mapping: dict[str, str] = {}
    for variation in variations:
        if not isinstance(variation, dict):
            continue
        variation_id_raw = variation.get("id")
        variation_id = str(variation_id_raw).strip() if variation_id_raw is not None else ""
        if not variation_id:
            continue
        seller_sku = _extract_variation_seller_sku(variation)
        if not seller_sku:
            continue
        mapping.setdefault(seller_sku.casefold(), variation_id)
    return mapping


def _build_fiscal_data(
    *,
    fiscal_item: dict[str, Any],
    publish_payload: dict[str, Any],
    fallback_sku: str | None,
) -> FiscalData:
    """Convert envelope fiscal payload into FiscalData domain model."""
    tax_info = fiscal_item.get("tax_information")
    if not isinstance(tax_info, dict):
        tax_info = {}

    sku = (
        _normalize_optional_text(fiscal_item.get("sku"))
        or _extract_payload_seller_sku(publish_payload)
        or fallback_sku
        or ""
    )
    title = (
        _normalize_optional_text(fiscal_item.get("title"))
        or _normalize_optional_text(publish_payload.get("title"))
        or sku
    )
    return FiscalData(
        sku=sku,
        title=title,
        type=str(fiscal_item.get("type") or "").strip(),
        measurement_unit=str(fiscal_item.get("measurement_unit") or "").strip(),
        cost=fiscal_item.get("cost"),
        tax_payer_type=str(fiscal_item.get("tax_payer_type") or "").strip() or "company",
        ncm=str(tax_info.get("ncm") or "").strip(),
        origin_type=str(tax_info.get("origin_type") or "").strip(),
        origin_detail=str(tax_info.get("origin_detail") or "").strip(),
        cest=tax_info.get("cest"),
        csosn=tax_info.get("csosn"),
        tax_rule_id=tax_info.get("tax_rule_id"),
        cfop=tax_info.get("cfop"),
        fci=tax_info.get("fci"),
        ex_tipi=tax_info.get("ex_tipi"),
        ean=tax_info.get("ean"),
        med_anvisa_code=tax_info.get("med_anvisa_code"),
        med_exemption_reason=tax_info.get("med_exemption_reason"),
        net_weight=tax_info.get("net_weight"),
        gross_weight=tax_info.get("gross_weight"),
    )


def _fiscal_failure_report(
    *,
    index: int,
    item_id: str | None,
    sku: str | None,
    tax_info: dict[str, Any],
    message: str,
    published_item_exists: bool,
    status: Literal["failed", "unknown"] = "failed",
) -> dict[str, Any]:
    """Keep fiscal failure evidence consistent without leaking exception strings."""
    return {
        "index": index,
        "item_id": item_id,
        "sku": sku,
        "ncm": tax_info.get("ncm"),
        "raw_origin_type": tax_info.get("origin_type"),
        "normalized_origin_type": None,
        "raw_origin_detail": tax_info.get("origin_detail"),
        "normalized_origin_detail": None,
        "missing_fields": [],
        "validation_errors": [message],
        "api_response": None,
        "published_item_exists": published_item_exists,
        "final_fiscal_status": status,
    }


def _fiscal_result_status(result: Any) -> str:
    """Normalize the fiscal workflow status while retaining the historical fallback."""
    raw_status = getattr(result, "status", None)
    raw_value = getattr(raw_status, "value", raw_status)
    if isinstance(raw_value, str) and raw_value.strip():
        status = raw_value.strip().lower()
    else:
        status = "completed" if result.success else "failed"
    return "completed" if status == "verified" else status


def _apply_attribute_suggestions(
    payload: dict[str, Any], suggestions: list[dict[str, Any]]
) -> dict[str, Any]:
    """Merge auto-apply attribute suggestions into payload attributes.

    Only adds attr_ids not already present in the payload's existing attributes.
    Returns a new dict (original is not mutated).
    """
    existing_ids = {
        attr.get("id")
        for attr in payload.get("attributes", [])
        if isinstance(attr, dict) and attr.get("id")
    }
    result: dict[str, Any] = dict(payload)
    for suggestion in suggestions:
        attr_id = suggestion.get("attr_id")
        if not attr_id or attr_id in existing_ids:
            continue
        result.setdefault("attributes", []).append(
            {
                "id": attr_id,
                "value_name": suggestion.get("canonical_value", ""),
            }
        )
        existing_ids.add(attr_id)
        logger.info(
            "Applied attribute suggestion: %s = %s (confidence: %s)",
            attr_id,
            suggestion.get("canonical_value"),
            suggestion.get("confidence"),
        )
    return result


class PublishPayloadUseCase:
    """Publishes a single payload.json to Mercado Livre.

    Does not know about Excel, Drive, image generation, or category resolution.
    Depends on JsonPayloadReader, SellerPolicyValidator, and ItemPublisherPort.
    """

    def __init__(
        self,
        reader: JsonPayloadReader,
        policy: SellerPolicyValidator,
        publisher: ItemPublisherPort,
        *,
        fiscal_service: FiscalService | None = None,
        publish_inactive: bool = False,
    ) -> None:
        """Initialize with reader, policy validator, and publisher port."""
        self._reader = reader
        self._policy = policy
        self._publisher = publisher
        self._fiscal_service = fiscal_service
        self._publish_inactive = publish_inactive

    def execute(
        self,
        path: Path,
        *,
        dry_run: bool = False,
        prepared_payload: ReadPayloadResult | None = None,
    ) -> PublicationOutcome:
        """Publish a single payload.json.

        Pipeline:
        1. Read and validate JSON schema
        2. Expand local envelope into concrete publish payloads
        3. Apply seller overrides (e.g. listing_type_id per category)
        4. Validate seller policy rules
        5. Verify seller/category listing availability and validate remotely
        6. If dry_run → return a remotely validated skipped result
        7. Publish one or more items
        8. Verify user-products family_id grouping (multi-item UP only)
        9. POST /items/{id}/description (when description is present)
        10. Submit fiscal information workflow (when fiscal.items is present)

        Args:
            path: Path to the payload.json file.
            dry_run: When True, run non-mutating remote validation but never create or update items.
            prepared_payload: Payload already validated by the shared publisher runtime.

        Returns:
            PublicationOutcome with status "published", "published_but_not_grouped",
            "skipped", "failed", or fail-closed "unknown".
        """
        read_result = self._read_payload_or_failure(path, prepared_payload)
        if isinstance(read_result, PublicationOutcome):
            return read_result

        context = self._prepare_publication_context(path, read_result)
        if isinstance(context, PublicationOutcome):
            return context

        remote_failure = self._run_remote_preflight(context)
        if remote_failure is not None:
            return remote_failure

        if dry_run:
            return self._dry_run_outcome(context)

        return self._publish_after_remote_preflight(context)

    def _read_payload_or_failure(
        self,
        path: Path,
        prepared_payload: ReadPayloadResult | None,
    ) -> ReadPayloadResult | PublicationOutcome:
        """Read the payload and enforce the publisher-owned readiness gate."""
        try:
            read_result = prepared_payload or self._reader.read(path)
        except (InvalidPayloadError, json.JSONDecodeError, OSError) as exc:
            if isinstance(exc, json.JSONDecodeError):
                message = f"Invalid JSON payload: {exc}"
            elif isinstance(exc, OSError):
                message = f"Could not read payload file: {exc}"
            else:
                message = str(exc)
            logger.warning("Invalid payload %s: %s", path, message)
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

        if read_result.publication_ready is True:
            return read_result

        reasons = (
            "; ".join(read_result.blocking_reasons)
            if read_result.blocking_reasons
            else "_meta.publication.publication_ready deve ser true"
        )
        logger.warning("Publish blocked by publication readiness for %s: %s", path, reasons)
        return PublicationOutcome(
            sku=read_result.sku,
            path=str(path),
            status="failed",
            error=f"Publicação bloqueada: {reasons}",
            phases=[
                PublicationPhase(
                    name="payload_validation",
                    status="failed",
                    detail=reasons,
                )
            ],
        )

    def _prepare_publication_context(
        self,
        path: Path,
        read_result: ReadPayloadResult,
    ) -> _PublicationContext | PublicationOutcome:
        """Expand payloads, apply local policy, and build phase state."""
        raw_publish_payloads = expand_effective_payloads(
            read_result.payload, read_result.upload_mode
        )
        total_payloads = len(raw_publish_payloads)
        warnings: list[str] = []
        if read_result.reviewed_fiscal is not True and read_result.fiscal_items:
            warnings.append(
                "Fiscal não revisado (_meta.reviewed_fiscal=false): publicando com aviso"
            )
            logger.warning(
                "Fiscal not reviewed for %s but publication_ready=True — publishing with warning",
                path,
            )

        errors: list[str] = []
        publish_payloads: list[dict[str, Any]] = []
        for index, candidate in enumerate(raw_publish_payloads, start=1):
            payload = self._policy.apply_overrides(candidate)
            policy_result = self._policy.validate(
                payload,
                ai_suggested=read_result.ai_suggested,
                category_confidence=read_result.category_confidence,
                category_decision=read_result.category_decision,
            )
            warnings.extend(
                _prefix_message(violation.message, index, total_payloads)
                for violation in policy_result.violations
                if violation.severity == "warning"
            )
            errors.extend(
                _prefix_message(violation.message, index, total_payloads)
                for violation in policy_result.violations
                if violation.severity == "error"
            )
            publish_payloads.append(payload)

        phases = [PublicationPhase(name="payload_validation", status="succeeded")]
        if errors:
            error_message = "; ".join(errors)
            logger.warning("Policy errors for %s: %s", path, error_message)
            return PublicationOutcome(
                sku=read_result.sku,
                path=str(path),
                status="failed",
                error=error_message,
                warnings=warnings,
                phases=[
                    *phases,
                    PublicationPhase(
                        name="policy_validation",
                        status="failed",
                        detail=error_message,
                    ),
                ],
            )

        if read_result.attribute_suggestions:
            publish_payloads = [
                _apply_attribute_suggestions(payload, read_result.attribute_suggestions)
                for payload in publish_payloads
            ]
        phases.append(PublicationPhase(name="policy_validation", status="succeeded"))
        return _PublicationContext(
            path=path,
            read_result=read_result,
            publish_payloads=publish_payloads,
            warnings=warnings,
            phases=phases,
        )

    def _run_remote_preflight(self, context: _PublicationContext) -> PublicationOutcome | None:
        """Verify seller availability and validate every payload without mutation."""
        availability_failure = self._validate_listing_type_availability(context)
        if availability_failure is not None:
            return availability_failure
        return self._validate_payloads_remotely(context)

    def _validate_listing_type_availability(
        self,
        context: _PublicationContext,
    ) -> PublicationOutcome | None:
        """Fail closed unless each chosen listing type is seller-available for its category."""
        available_by_category: dict[str, set[str]] = {}
        for index, payload in enumerate(context.publish_payloads, start=1):
            category_id = _normalize_optional_text(payload.get("category_id"))
            listing_type_id = _normalize_optional_text(payload.get("listing_type_id"))
            if category_id is None or listing_type_id is None:
                message = _prefix_message(
                    "listing_type_id e category_id são obrigatórios para validar "
                    "disponibilidade remota",
                    index,
                    context.total_payloads,
                )
                return self._remote_preflight_failure(
                    context,
                    message,
                    status="validation_not_executed",
                )
            if category_id not in available_by_category:
                try:
                    available = self._publisher.get_available_listing_types(category_id)
                except Exception as exc:  # noqa: BLE001
                    _log_remote_exception(
                        event="payload_listing_type_availability_failed",
                        operation="get_available_listing_types",
                        exc=exc,
                        status="validation_not_executed",
                    )
                    message = _prefix_message(
                        "Não foi possível verificar os listing types disponíveis para "
                        f"a categoria {category_id}",
                        index,
                        context.total_payloads,
                    )
                    return self._remote_preflight_failure(
                        context,
                        message,
                        status="validation_not_executed",
                    )
                if not isinstance(available, list):
                    message = _prefix_message(
                        "Resposta inválida ao consultar listing types disponíveis para "
                        f"a categoria {category_id}",
                        index,
                        context.total_payloads,
                    )
                    return self._remote_preflight_failure(
                        context,
                        message,
                        status="validation_not_executed",
                    )
                available_by_category[category_id] = {
                    candidate_id
                    for candidate in available
                    if isinstance(candidate, dict)
                    for candidate_id in [_normalize_optional_text(candidate.get("id"))]
                    if candidate_id is not None
                }

            available_ids = sorted(available_by_category[category_id])
            evidence = {
                "index": index,
                "category_id": category_id,
                "listing_type_id": listing_type_id,
                "available_listing_type_ids": available_ids,
                "available": listing_type_id in available_by_category[category_id],
            }
            context.listing_type_evidence.append(evidence)
            if evidence["available"]:
                continue
            message = _prefix_message(
                f"listing_type_id '{listing_type_id}' não está disponível para este seller "
                f"na categoria '{category_id}'",
                index,
                context.total_payloads,
            )
            return self._remote_preflight_failure(
                context,
                message,
                status="validation_not_executed",
            )
        return None

    def _validate_payloads_remotely(
        self,
        context: _PublicationContext,
    ) -> PublicationOutcome | None:
        """Run the non-mutating Mercado Livre item validator for every payload."""
        reports: list[dict[str, Any]] = []
        for index, publish_payload in enumerate(context.publish_payloads, start=1):
            try:
                if context.read_result.upload_mode == "user_products":
                    validation = self._publisher.validate_user_product_item(publish_payload)
                else:
                    validation = self._publisher.validate_item(publish_payload)
            except MLApiError as exc:
                validation_error = _prefix_message(
                    _format_ml_api_error(exc), index, context.total_payloads
                )
                _log_remote_exception(
                    event="payload_remote_validation_rejected",
                    operation="validate_item",
                    exc=exc,
                    status="validation_not_completed",
                )
                return self._remote_preflight_failure(
                    context,
                    validation_error,
                    status="validation_not_completed",
                    reports=reports,
                )
            except Exception as exc:  # noqa: BLE001
                _log_remote_exception(
                    event="payload_remote_validation_failed",
                    operation="validate_item",
                    exc=exc,
                    status="validation_not_completed",
                )
                validation_error = _prefix_message(
                    _public_remote_error(exc, operation="Remote item validation"),
                    index,
                    context.total_payloads,
                )
                return self._remote_preflight_failure(
                    context,
                    validation_error,
                    status="validation_not_completed",
                    reports=reports,
                )

            if validation is None:
                validation_error = _prefix_message(
                    "Remote item validation returned no response",
                    index,
                    context.total_payloads,
                )
                logger.error("ML API validation returned no response for %s", context.path)
                return self._remote_preflight_failure(
                    context,
                    validation_error,
                    status="validation_not_completed",
                    reports=reports,
                )

            validation_result: MercadoLivreValidationResult = (
                classify_mercado_livre_validation_response(validation)
            )
            report = validation_result.to_report_dict()
            reports.append(report)
            context.validation_report = self._validation_report_with_listing_evidence(
                report,
                context.listing_type_evidence,
                reports,
            )
            if validation_result.status == "validation_passed_with_warnings":
                context.validation_status = "validation_passed_with_warnings"

            validation_warnings = validation_result.warning_messages()
            if validation_warnings:
                context.warnings.extend(
                    _prefix_message(
                        f"ML validation warning: {warning}",
                        index,
                        context.total_payloads,
                    )
                    for warning in validation_warnings
                )
                logger.warning(
                    "Validation passed with warnings for %s; continuing publication: %s",
                    context.path,
                    "; ".join(validation_warnings),
                )
            if not validation_result.should_block:
                continue

            validation_error = _prefix_message(
                "; ".join(validation_result.error_messages()) or "Validation failed",
                index,
                context.total_payloads,
            )
            validation_error = (
                f"{validation_error} | response={_format_validation_response(validation)}"
            )
            log_safe_event(
                logger,
                logging.ERROR,
                "payload_remote_validation_failed",
                operation="validate_item",
                status=validation_result.status,
                error_type="remote_validation",
                response=validation,
            )
            context.validation_status = validation_result.status
            return self._remote_preflight_failure(
                context,
                validation_error,
                status=validation_result.status,
                reports=reports,
            )

        context.phases.append(PublicationPhase(name="remote_validation", status="succeeded"))
        return None

    @staticmethod
    def _validation_report_with_listing_evidence(
        report: dict[str, Any],
        listing_type_evidence: list[dict[str, Any]],
        reports: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Keep the historical single-item report shape and attach preflight evidence."""
        result = dict(report) if len(reports) == 1 else {"items": list(reports)}
        result["listing_type_availability"] = list(listing_type_evidence)
        return result

    def _remote_preflight_failure(
        self,
        context: _PublicationContext,
        message: str,
        *,
        status: str,
        reports: list[dict[str, Any]] | None = None,
    ) -> PublicationOutcome:
        """Return an explicit non-mutating preflight failure with remote evidence."""
        if reports is not None:
            report = self._validation_report_with_listing_evidence(
                reports[-1] if reports else {},
                context.listing_type_evidence,
                reports,
            )
        else:
            report = {"listing_type_availability": list(context.listing_type_evidence)}
        context.validation_status = status
        context.validation_report = report
        return PublicationOutcome(
            sku=context.read_result.sku,
            path=str(context.path),
            status="failed",
            error=message,
            warnings=context.warnings,
            validation_status=context.validation_status,
            validation_report=context.validation_report,
            phases=[
                *context.phases,
                PublicationPhase(name="remote_validation", status="failed", detail=message),
            ],
        )

    @staticmethod
    def _dry_run_outcome(context: _PublicationContext) -> PublicationOutcome:
        """Report a validated simulation after all remote non-mutating checks passed."""
        return PublicationOutcome(
            sku=context.read_result.sku,
            path=str(context.path),
            status="skipped",
            warnings=context.warnings,
            validation_status=context.validation_status,
            validation_report=context.validation_report,
            phases=context.phases,
        )

    @staticmethod
    def _post_mutation_failure(
        context: _PublicationContext,
        *,
        phase_name: Literal["pause", "description"],
        item_id: str,
        first_item_id: str | None,
        created_item_ids: list[str],
        user_product_id: str | None,
        publish_endpoints: list[str],
        exc: Exception,
        ambiguous: bool,
    ) -> PublicationOutcome:
        """Build the reconciliation-required outcome shared by item post-mutations."""
        message = _public_remote_error(
            exc,
            operation=phase_name.capitalize(),
            ambiguous=ambiguous,
        )
        return PublicationOutcome(
            sku=context.read_result.sku,
            path=str(context.path),
            status="unknown" if ambiguous else "failed",
            side_effect_state="partial",
            item_id=first_item_id,
            item_ids=created_item_ids,
            user_product_id=user_product_id,
            publish_endpoints=publish_endpoints,
            error=message,
            warnings=context.warnings,
            validation_status=context.validation_status,
            validation_report=context.validation_report,
            reconciliation_required=True,
            phases=[
                *context.phases,
                PublicationPhase(
                    name=phase_name,
                    status="unknown" if ambiguous else "failed",
                    item_id=item_id,
                    detail=message,
                ),
            ],
        )

    def _pause_published_item(
        self,
        context: _PublicationContext,
        *,
        item_id: str,
        first_item_id: str | None,
        created_item_ids: list[str],
        user_product_id: str | None,
        publish_endpoints: list[str],
    ) -> PublicationOutcome | None:
        """Pause a new item when the explicit paused-publication policy requires it."""
        if not self._publish_inactive:
            return None
        try:
            self._publisher.update_item(item_id, {"status": "paused"})
        except Exception as exc:  # noqa: BLE001
            ambiguous = is_ambiguous_mutation_failure(exc)
            _log_remote_exception(
                event="payload_pause_failed",
                operation="pause_item",
                exc=exc,
                item_id=item_id,
                status="unknown" if ambiguous else "failed",
            )
            return self._post_mutation_failure(
                context,
                phase_name="pause",
                item_id=item_id,
                first_item_id=first_item_id,
                created_item_ids=created_item_ids,
                user_product_id=user_product_id,
                publish_endpoints=publish_endpoints,
                exc=exc,
                ambiguous=ambiguous,
            )
        logger.info("Paused item %s after publish (publish_inactive=True)", item_id)
        context.phases.append(PublicationPhase(name="pause", status="succeeded", item_id=item_id))
        return None

    def _publish_item_description(
        self,
        context: _PublicationContext,
        *,
        item_id: str,
        payload_sku: str | None,
        first_item_id: str | None,
        created_item_ids: list[str],
        user_product_id: str | None,
        publish_endpoints: list[str],
        description_posted: bool,
    ) -> tuple[PublicationOutcome | None, bool]:
        """Post the applicable description once per legacy item or per user-product item."""
        read_result = context.read_result
        if read_result.upload_mode == "user_products":
            description = _description_for_publish_item(
                shared_description=read_result.description,
                description_by_sku=read_result.description_by_sku,
                sku=payload_sku,
            )
        elif read_result.description and not description_posted:
            description = read_result.description
        else:
            description = None
        if not description:
            return None, description_posted

        try:
            self._publisher.create_item_description(item_id, description)
        except Exception as exc:  # noqa: BLE001
            ambiguous = is_ambiguous_mutation_failure(exc)
            _log_remote_exception(
                event="payload_description_failed",
                operation="create_item_description",
                exc=exc,
                item_id=item_id,
                status="unknown" if ambiguous else "failed",
            )
            return (
                self._post_mutation_failure(
                    context,
                    phase_name="description",
                    item_id=item_id,
                    first_item_id=first_item_id,
                    created_item_ids=created_item_ids,
                    user_product_id=user_product_id,
                    publish_endpoints=publish_endpoints,
                    exc=exc,
                    ambiguous=ambiguous,
                ),
                description_posted,
            )

        context.phases.append(
            PublicationPhase(name="description", status="succeeded", item_id=item_id)
        )
        return None, description_posted or read_result.upload_mode != "user_products"

    @staticmethod
    def _item_creation_failure(
        context: _PublicationContext,
        state: _CreatedItems,
        *,
        error_message: str,
        status: Literal["failed", "unknown"],
        reconciliation_required: bool,
        side_effect_state: Literal["none", "unknown", "partial"],
    ) -> PublicationOutcome:
        """Build a consistent outcome for a failed or unconfirmed creation request."""
        return PublicationOutcome(
            sku=context.read_result.sku,
            path=str(context.path),
            status=status,
            side_effect_state=side_effect_state,
            item_id=state.first_item_id,
            item_ids=state.item_ids,
            user_product_id=state.user_product_id,
            publish_endpoints=state.endpoints,
            error=error_message,
            warnings=context.warnings,
            validation_status=context.validation_status,
            validation_report=context.validation_report,
            reconciliation_required=reconciliation_required,
            phases=[
                *context.phases,
                PublicationPhase(
                    name="item_creation",
                    status=status,
                    detail=error_message,
                ),
            ],
        )

    def _create_one_item(
        self,
        context: _PublicationContext,
        state: _CreatedItems,
        *,
        index: int,
        publish_payload: dict[str, Any],
    ) -> _CreatedItem | PublicationOutcome:
        """Create one item and return a reconciliation-safe outcome on any uncertain result."""
        payload = dict(publish_payload)
        read_result = context.read_result
        if (
            read_result.upload_mode == "user_products"
            and _is_existing_user_product_selling_condition_payload(payload)
            and state.user_product_id
            and _normalize_optional_text(payload.get("user_product_id")) is None
        ):
            payload["user_product_id"] = state.user_product_id
        endpoint = _publish_endpoint_for_payload(payload, read_result.upload_mode)
        create_item = (
            self._publisher.create_user_product_item
            if read_result.upload_mode == "user_products"
            else self._publisher.create_item
        )
        try:
            response = create_item(payload)
        except Exception as exc:  # noqa: BLE001
            ambiguous = is_ambiguous_mutation_failure(exc)
            confirmed = bool(state.item_ids)
            if isinstance(exc, MLApiError):
                error = _format_ml_api_error(
                    exc,
                    sanitization_metadata=getattr(
                        self._publisher,
                        "last_user_product_sanitization",
                        None,
                    ),
                )
            else:
                error = _public_remote_error(
                    exc,
                    operation="Item creation",
                    ambiguous=ambiguous,
                )
            error_message = _prefix_message(error, index, context.total_payloads)
            status: Literal["failed", "unknown"] = "unknown" if ambiguous else "failed"
            _log_remote_exception(
                event="payload_item_creation_failed",
                operation="create_item",
                exc=exc,
                status=status,
            )
            return self._item_creation_failure(
                context,
                state,
                error_message=error_message,
                status=status,
                reconciliation_required=ambiguous or confirmed,
                side_effect_state="partial" if confirmed else "unknown" if ambiguous else "none",
            )

        item_id = _extract_valid_created_item_id(response)
        if item_id is None:
            error_message = _prefix_message(
                "Item creation returned a success response without a valid Mercado Livre "
                "item.id"
                f" | endpoint={endpoint} | response={_format_validation_response(response)}",
                index,
                context.total_payloads,
            )
            _log_remote_exception(
                event="payload_item_creation_unconfirmed",
                operation="create_item",
                exc=ValueError("missing_item_id"),
                status="unknown",
            )
            state.endpoints.append(endpoint)
            return self._item_creation_failure(
                context,
                state,
                error_message=error_message,
                status="unknown",
                reconciliation_required=True,
                side_effect_state="partial",
            )
        return _CreatedItem(
            response=response,
            item_id=item_id,
            endpoint=endpoint,
            payload=payload,
        )

    def _create_items_with_post_mutations(
        self,
        context: _PublicationContext,
    ) -> _CreatedItems | PublicationOutcome:
        """Create every remote item and run its required pause/description follow-ups."""
        state = _CreatedItems()
        read_result = context.read_result
        for index, publish_payload in enumerate(context.publish_payloads, start=1):
            created_item = self._create_one_item(
                context,
                state,
                index=index,
                publish_payload=publish_payload,
            )
            if isinstance(created_item, PublicationOutcome):
                return created_item

            state.item_ids.append(created_item.item_id)
            state.items.append(created_item.response)
            state.endpoints.append(created_item.endpoint)
            if state.first_item_id is None:
                state.first_item_id = created_item.item_id
            context.phases.append(
                PublicationPhase(
                    name="item_creation",
                    status="succeeded",
                    item_id=created_item.item_id,
                )
            )
            payload_sku = _extract_payload_seller_sku(created_item.payload)
            if not payload_sku and index <= len(read_result.publish_item_skus):
                payload_sku = _normalize_optional_text(read_result.publish_item_skus[index - 1])
            if payload_sku:
                state.by_sku.setdefault(
                    payload_sku.casefold(),
                    (created_item.item_id, created_item.payload),
                )
            if read_result.upload_mode != "user_products" and not state.variation_id_by_sku:
                state.variation_id_by_sku = _extract_variation_ids_by_sku(created_item.response)
            if state.user_product_id is None:
                state.user_product_id = _normalize_optional_text(
                    created_item.response.get("user_product_id")
                )

            pause_failure = self._pause_published_item(
                context,
                item_id=created_item.item_id,
                first_item_id=state.first_item_id,
                created_item_ids=state.item_ids,
                user_product_id=state.user_product_id,
                publish_endpoints=state.endpoints,
            )
            if pause_failure is not None:
                return pause_failure
            description_failure, state.description_posted = self._publish_item_description(
                context,
                item_id=created_item.item_id,
                payload_sku=payload_sku,
                first_item_id=state.first_item_id,
                created_item_ids=state.item_ids,
                user_product_id=state.user_product_id,
                publish_endpoints=state.endpoints,
                description_posted=state.description_posted,
            )
            if description_failure is not None:
                return description_failure
        return state

    def _publish_after_remote_preflight(self, context: _PublicationContext) -> PublicationOutcome:
        """Run mutation and post-publication phases after remote validation succeeds."""
        read_result = context.read_result
        created_items = self._create_items_with_post_mutations(context)
        if isinstance(created_items, PublicationOutcome):
            return created_items

        publish_status: Literal["published", "published_but_not_grouped"] = "published"
        if read_result.upload_mode == "user_products":
            grouped, grouping_reason = _verify_user_products_grouping(
                created_items.items,
                publisher=self._publisher,
            )
            if not grouped:
                publish_status = "published_but_not_grouped"
                context.warnings.append(grouping_reason or "user_products_items_not_grouped")
                context.phases.append(
                    PublicationPhase(
                        name="grouping",
                        status="failed",
                        detail=grouping_reason,
                    )
                )
                log_safe_event(
                    logger,
                    logging.WARNING,
                    "payload_user_products_grouping_failed",
                    operation="verify_grouping",
                    status="failed",
                )
            else:
                context.phases.append(PublicationPhase(name="grouping", status="succeeded"))

        fiscal_result = self._submit_fiscal_phase(
            context,
            created_item_ids=created_items.item_ids,
            first_item_id=created_items.first_item_id,
            user_product_id=created_items.user_product_id,
            publish_endpoints=created_items.endpoints,
            published_by_sku=created_items.by_sku,
            variation_id_by_sku=created_items.variation_id_by_sku,
        )
        if isinstance(fiscal_result, PublicationOutcome):
            return fiscal_result
        fiscal_report = fiscal_result

        requires_reconciliation = publish_status == "published_but_not_grouped"

        return PublicationOutcome(
            sku=read_result.sku,
            path=str(context.path),
            status=publish_status,
            side_effect_state="partial" if requires_reconciliation else "confirmed",
            item_id=created_items.first_item_id,
            item_ids=created_items.item_ids,
            user_product_id=created_items.user_product_id,
            publish_endpoints=created_items.endpoints,
            warnings=context.warnings,
            validation_status=context.validation_status,
            validation_report=context.validation_report,
            fiscal_status="completed" if read_result.fiscal_items else None,
            fiscal_report=fiscal_report,
            reconciliation_required=requires_reconciliation,
            phases=context.phases,
        )

    @staticmethod
    def _resolve_fiscal_target(
        *,
        fiscal_sku: str | None,
        first_item_id: str | None,
        fallback_payload: dict[str, Any],
        created_item_ids: list[str],
        published_by_sku: dict[str, tuple[str, dict[str, Any]]],
        variation_id_by_sku: dict[str, str],
    ) -> tuple[_FiscalTarget | None, str | None]:
        """Map fiscal SKU evidence to its created item or a legacy variation."""
        target_item_id = first_item_id
        target_payload = fallback_payload
        variation_id: str | None = None
        if fiscal_sku:
            mapped = published_by_sku.get(fiscal_sku.casefold())
            if mapped:
                target_item_id, target_payload = mapped
            elif len(created_item_ids) == 1:
                variation_id = variation_id_by_sku.get(fiscal_sku.casefold())
            elif len(created_item_ids) > 1:
                return None, "sku não mapeado para item publicado"
        elif len(created_item_ids) > 1:
            return None, "item fiscal sem sku em publicação multi-item"
        if not target_item_id:
            return None, "sem item publicado para vincular dados fiscais"
        return _FiscalTarget(target_item_id, target_payload, variation_id), None

    def _submit_fiscal_entry(
        self,
        *,
        index: int,
        fiscal_item: dict[str, Any],
        fiscal_sku: str | None,
        tax_info: dict[str, Any],
        target: _FiscalTarget,
        fallback_sku: str | None,
    ) -> tuple[dict[str, Any], str | None, bool, bool]:
        """Submit one fiscal entry and return its report, error, unknown and pending flags."""
        try:
            fiscal_data = _build_fiscal_data(
                fiscal_item=fiscal_item,
                publish_payload=target.payload,
                fallback_sku=fallback_sku,
            )
            if target.variation_id is None:
                fiscal_result = self._fiscal_service.submit_fiscal_data_workflow(
                    target.item_id,
                    fiscal_data,
                )
            else:
                fiscal_result = self._fiscal_service.submit_fiscal_data_workflow(
                    target.item_id,
                    fiscal_data,
                    variation_id=target.variation_id,
                )
            result_status = _fiscal_result_status(fiscal_result)
            reconciliation_required = (
                getattr(fiscal_result, "reconciliation_required", False) is True
            )
            report = {
                "index": index,
                "item_id": target.item_id,
                "sku": fiscal_data.sku,
                "ncm": fiscal_data.ncm,
                "raw_origin_type": fiscal_data.raw_origin_type,
                "normalized_origin_type": fiscal_data.origin_type,
                "raw_origin_detail": fiscal_data.raw_origin_detail,
                "normalized_origin_detail": fiscal_data.origin_detail,
                "missing_fields": fiscal_data.get_missing_fields(),
                "validation_errors": fiscal_data.get_validation_errors(),
                "api_response": getattr(fiscal_result, "response", None),
                "published_item_exists": True,
                "final_fiscal_status": result_status,
                "side_effect_state": getattr(fiscal_result, "side_effect_state", "confirmed"),
                "reconciliation_required": reconciliation_required,
                "invoice_ready": getattr(fiscal_result, "invoice_ready", None),
            }
            raw_message = getattr(fiscal_result, "error_message", None)
            error = (
                raw_message.strip()
                if (not fiscal_result.success or reconciliation_required)
                and isinstance(raw_message, str)
                and raw_message.strip()
                else (
                    "falha no envio fiscal"
                    if not fiscal_result.success or reconciliation_required
                    else None
                )
            )
            return (
                report,
                error,
                result_status == "unknown",
                result_status in {"pending", "pending_verification"},
            )
        except Exception as exc:  # noqa: BLE001
            ambiguous = is_ambiguous_mutation_failure(exc)
            _log_remote_exception(
                event="payload_fiscal_submission_failed",
                operation="submit_fiscal_data",
                exc=exc,
                item_id=target.item_id,
                status="unknown" if ambiguous else "failed",
            )
            message = _public_remote_error(
                exc,
                operation="Fiscal submission",
                ambiguous=ambiguous,
            )
            return (
                _fiscal_failure_report(
                    index=index,
                    item_id=target.item_id,
                    sku=fiscal_sku,
                    tax_info=tax_info,
                    message=message,
                    published_item_exists=True,
                    status="unknown" if ambiguous else "failed",
                ),
                message,
                ambiguous,
                False,
            )

    def _submit_fiscal_phase(
        self,
        context: _PublicationContext,
        *,
        created_item_ids: list[str],
        first_item_id: str | None,
        user_product_id: str | None,
        publish_endpoints: list[str],
        published_by_sku: dict[str, tuple[str, dict[str, Any]]],
        variation_id_by_sku: dict[str, str],
    ) -> list[dict[str, Any]] | PublicationOutcome:
        """Submit fiscal entries only after all item creation side effects are confirmed."""
        read_result = context.read_result
        if not read_result.fiscal_items:
            return []

        fiscal_report: list[dict[str, Any]] = []
        fiscal_blocking_errors: list[str] = []
        fiscal_unknown = False
        fiscal_pending = False
        if self._fiscal_service is None:
            fiscal_blocking_errors.append(
                "fiscal: dados fiscais presentes no payload, "
                "mas o FiscalService não está configurado"
            )
        else:
            fallback_payload = context.publish_payloads[0] if context.publish_payloads else {}
            for fiscal_index, fiscal_item in enumerate(read_result.fiscal_items, start=1):
                tax_info = fiscal_item.get("tax_information")
                tax_info_raw = tax_info if isinstance(tax_info, dict) else {}
                fiscal_sku = _normalize_optional_text(fiscal_item.get("sku"))
                target, target_error = self._resolve_fiscal_target(
                    fiscal_sku=fiscal_sku,
                    first_item_id=first_item_id,
                    fallback_payload=fallback_payload,
                    created_item_ids=created_item_ids,
                    published_by_sku=published_by_sku,
                    variation_id_by_sku=variation_id_by_sku,
                )
                if target is None:
                    assert target_error is not None
                    prefix = (
                        f"sku '{fiscal_sku}' " if fiscal_sku and len(created_item_ids) > 1 else ""
                    )
                    fiscal_blocking_errors.append(f"fiscal[{fiscal_index}]: {prefix}{target_error}")
                    fiscal_report.append(
                        _fiscal_failure_report(
                            index=fiscal_index,
                            item_id=None,
                            sku=fiscal_sku,
                            tax_info=tax_info_raw,
                            message=target_error,
                            published_item_exists=False,
                        )
                    )
                    continue
                entry_report, entry_error, unknown, pending = self._submit_fiscal_entry(
                    index=fiscal_index,
                    fiscal_item=fiscal_item,
                    fiscal_sku=fiscal_sku,
                    tax_info=tax_info_raw,
                    target=target,
                    fallback_sku=read_result.sku,
                )
                fiscal_report.append(entry_report)
                fiscal_unknown = fiscal_unknown or unknown
                fiscal_pending = fiscal_pending or pending
                if entry_error:
                    fiscal_blocking_errors.append(f"fiscal[{fiscal_index}]: {entry_error}")

        if fiscal_blocking_errors:
            fiscal_error_message = "; ".join(fiscal_blocking_errors)
            log_safe_event(
                logger,
                logging.ERROR,
                "payload_fiscal_submission_failed",
                operation="submit_fiscal_data",
                count=len(fiscal_blocking_errors),
                status="unknown" if fiscal_unknown else "failed",
            )
            return PublicationOutcome(
                sku=read_result.sku,
                path=str(context.path),
                status="unknown" if fiscal_unknown else "failed",
                side_effect_state="partial",
                item_id=first_item_id,
                item_ids=created_item_ids,
                user_product_id=user_product_id,
                publish_endpoints=publish_endpoints,
                error=fiscal_error_message,
                warnings=context.warnings,
                validation_status=context.validation_status,
                validation_report=context.validation_report,
                fiscal_status=(
                    "unknown"
                    if fiscal_unknown
                    else "pending_verification" if fiscal_pending else "failed"
                ),
                fiscal_report=fiscal_report,
                reconciliation_required=True,
                phases=[
                    *context.phases,
                    PublicationPhase(
                        name="fiscal",
                        status="unknown" if fiscal_unknown else "failed",
                        detail=fiscal_error_message,
                    ),
                ],
            )

        context.phases.append(PublicationPhase(name="fiscal", status="succeeded"))
        return fiscal_report
