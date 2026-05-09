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
)
from mercadolivre_upload.api.exceptions import MLApiError
from mercadolivre_upload.application.ports import ItemPublisherPort
from mercadolivre_upload.application.validators.seller_policy import SellerPolicyValidator
from mercadolivre_upload.domain.fiscal.data import FiscalData
from mercadolivre_upload.domain.fiscal.service import FiscalService

logger = logging.getLogger(__name__)


@dataclass
class PublishJsonResult:
    """Result of publishing a single payload.json."""

    sku: str | None
    path: str
    status: Literal["published", "skipped", "failed"]
    item_id: str | None = None
    item_ids: list[str] = field(default_factory=list)
    user_product_id: str | None = None
    error: str | None = None
    warnings: list[str] = field(default_factory=list)


def _prefix_message(message: str, index: int, total: int) -> str:
    """Prefix per-item messages only when one file expands to many publishes."""
    if total <= 1:
        return message
    return f"item[{index}]: {message}"


def _expand_publish_payloads(payload: dict[str, Any], upload_mode: str) -> list[dict[str, Any]]:
    """Expand a normalized envelope into concrete publish payloads."""
    if upload_mode != "user_products":
        return [dict(payload)]

    base_payload = {key: value for key, value in payload.items() if key != "items"}
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


def _format_ml_api_error(exc: MLApiError) -> str:
    """Format ML API errors, preserving full response payload when available."""
    blocking = [c for c in exc.causes if c.get("type") == "error"]
    blocking_message = "; ".join(f"[{c.get('code', '?')}] {c.get('message', '')}" for c in blocking)

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

    parts = [part for part in (blocking_message, response_fragment) if part]
    return " | ".join(parts) if parts else str(exc)


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
    cost = fiscal_item.get("cost")
    if cost is None:
        cost = publish_payload.get("price")

    return FiscalData(
        sku=sku,
        title=title,
        type=str(fiscal_item.get("type") or "").strip(),
        measurement_unit=str(fiscal_item.get("measurement_unit") or "").strip(),
        cost=cost,
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


class PublishJsonUseCase:
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

    def execute(self, path: Path, *, dry_run: bool = False) -> PublishJsonResult:
        """Publish a single payload.json.

        Pipeline:
        1. Read and validate JSON schema
        2. Expand local envelope into concrete publish payloads
        3. Apply seller overrides (e.g. listing_type_id per category)
        4. Validate seller policy rules
        5. If dry_run → return skipped result
        6. Publish one or more items
        7. POST /items/{id}/description (when description is present)
        8. Submit fiscal information workflow (when fiscal.items is present)

        Args:
            path: Path to the payload.json file.
            dry_run: When True, validates only — does not call the API.

        Returns:
            PublishJsonResult with status "published", "skipped", or "failed".
        """
        # 1. Read and validate schema
        try:
            read_result = self._reader.read(path)
        except InvalidPayloadError as exc:
            logger.warning("Invalid payload %s: %s", path, exc)
            return PublishJsonResult(
                sku=None,
                path=str(path),
                status="failed",
                error=str(exc),
            )

        # 1b. Publication readiness gate — block publish when explicitly marked not ready
        if read_result.publication_ready is False:
            reasons = (
                "; ".join(read_result.blocking_reasons)
                if read_result.blocking_reasons
                else "sem detalhes"
            )
            logger.warning("Publish blocked by publication_ready=False for %s: %s", path, reasons)
            return PublishJsonResult(
                sku=read_result.sku,
                path=str(path),
                status="failed",
                error=f"Publicação bloqueada: {reasons}",
            )
        elif read_result.publication_ready is None:
            logger.debug(
                "publication_ready absent in _meta for %s — proceeding (backward compat)", path
            )

        # 2. Expand one file into one or more publish payloads.
        raw_publish_payloads = _expand_publish_payloads(
            read_result.payload, read_result.upload_mode
        )
        total_payloads = len(raw_publish_payloads)

        # 3. Apply seller overrides + validate seller policy.
        publish_payloads: list[dict[str, Any]] = []
        # 1c. Fiscal reviewed gate (warning-only — full FiscalService integration is separate)
        warnings: list[str] = []
        has_fiscal = bool(read_result.fiscal_items)
        if (
            read_result.publication_ready is True
            and read_result.reviewed_fiscal is not True
            and has_fiscal
        ):
            warnings.append(
                "Fiscal não revisado (_meta.reviewed_fiscal=false): publicando com aviso"
            )
            logger.warning(
                "Fiscal not reviewed for %s but publication_ready=True — "
                "publishing with warning",
                path,
            )
        errors: list[str] = []
        for index, candidate in enumerate(raw_publish_payloads, start=1):
            payload = self._policy.apply_overrides(candidate)
            policy_result = self._policy.validate(
                payload,
                ai_suggested=read_result.ai_suggested,
                category_confidence=read_result.category_confidence,
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

        if errors:
            error_message = "; ".join(errors)
            logger.warning("Policy errors for %s: %s", path, error_message)
            return PublishJsonResult(
                sku=read_result.sku,
                path=str(path),
                status="failed",
                error=error_message,
                warnings=warnings,
            )

        # 4. Dry run — skip actual publish
        if dry_run:
            return PublishJsonResult(
                sku=read_result.sku,
                path=str(path),
                status="skipped",
                warnings=warnings,
            )

        # 4b. Auto-apply attribute suggestions into each publish payload
        if read_result.attribute_suggestions:
            publish_payloads = [
                _apply_attribute_suggestions(p, read_result.attribute_suggestions)
                for p in publish_payloads
            ]

        # 5. Publish one or more items.
        created_item_ids: list[str] = []
        first_item_id: str | None = None
        user_product_id: str | None = None
        description_posted = False
        published_by_sku: dict[str, tuple[str, dict[str, Any]]] = {}
        variation_id_by_sku: dict[str, str] = {}
        for index, publish_payload in enumerate(publish_payloads, start=1):
            payload = dict(publish_payload)
            if read_result.upload_mode == "user_products":
                if user_product_id:
                    payload["user_product_id"] = user_product_id
                create_item = self._publisher.create_user_product_item
            else:
                create_item = self._publisher.create_item

            try:
                item = create_item(payload)
            except MLApiError as exc:
                causes_str = _prefix_message(_format_ml_api_error(exc), index, total_payloads)
                logger.error("ML API rejected %s: %s", path, causes_str)
                return PublishJsonResult(
                    sku=read_result.sku,
                    path=str(path),
                    status="failed",
                    item_id=first_item_id,
                    item_ids=created_item_ids,
                    user_product_id=user_product_id,
                    error=causes_str,
                    warnings=warnings,
                )
            except Exception as exc:  # noqa: BLE001
                error_message = _prefix_message(str(exc), index, total_payloads)
                logger.error("Failed to publish %s: %s", path, error_message)
                return PublishJsonResult(
                    sku=read_result.sku,
                    path=str(path),
                    status="failed",
                    item_id=first_item_id,
                    item_ids=created_item_ids,
                    user_product_id=user_product_id,
                    error=error_message,
                    warnings=warnings,
                )

            item_id = str(item["id"])
            created_item_ids.append(item_id)
            if first_item_id is None:
                first_item_id = item_id
            payload_sku = _extract_payload_seller_sku(payload)
            if not payload_sku and index <= len(read_result.publish_item_skus):
                payload_sku = _normalize_optional_text(read_result.publish_item_skus[index - 1])
            if payload_sku:
                published_by_sku.setdefault(payload_sku.casefold(), (item_id, payload))
            if read_result.upload_mode != "user_products" and not variation_id_by_sku:
                variation_id_by_sku = _extract_variation_ids_by_sku(item)

            if self._publish_inactive:
                try:
                    self._publisher.update_item(item_id, {"status": "paused"})
                    logger.info("Paused item %s after publish (publish_inactive=True)", item_id)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "Failed to pause item %s after publish: %s — "
                        "item was published but status was NOT set to paused.",
                        item_id,
                        exc,
                    )

            if user_product_id is None:
                raw_user_product_id = item.get("user_product_id")
                if isinstance(raw_user_product_id, str) and raw_user_product_id.strip():
                    user_product_id = raw_user_product_id.strip()

            if (
                read_result.upload_mode == "user_products"
                and total_payloads > 1
                and index == 1
                and user_product_id is None
            ):
                error_message = (
                    "item[1]: first user-products publish did not return user_product_id"
                )
                logger.error("Failed to continue UP publish for %s: %s", path, error_message)
                return PublishJsonResult(
                    sku=read_result.sku,
                    path=str(path),
                    status="failed",
                    item_id=first_item_id,
                    item_ids=created_item_ids,
                    user_product_id=user_product_id,
                    error=error_message,
                    warnings=warnings,
                )

            # 6. Post description separately after the first successful item creation.
            if read_result.description and not description_posted:
                for attempt in range(2):
                    try:
                        self._publisher.create_item_description(item_id, read_result.description)
                        break
                    except Exception as exc:  # noqa: BLE001
                        if attempt == 0:
                            logger.warning(
                                "Description POST failed for %s (attempt 1), retrying: %s",
                                item_id,
                                exc,
                            )
                        else:
                            logger.warning(
                                "Description POST failed for %s after retry: %s",
                                item_id,
                                exc,
                            )
                description_posted = True

        # 7. Submit fiscal workflow for each fiscal.items entry.
        fiscal_blocking_errors: list[str] = []
        if read_result.fiscal_items:
            if self._fiscal_service is None:
                fiscal_blocking_errors.append(
                    "fiscal: dados fiscais presentes no payload, "
                    "mas o FiscalService não está configurado"
                )
            else:
                fallback_payload = publish_payloads[0] if publish_payloads else {}
                for fiscal_index, fiscal_item in enumerate(read_result.fiscal_items, start=1):
                    fiscal_sku = _normalize_optional_text(fiscal_item.get("sku"))
                    target_item_id = first_item_id
                    target_payload = fallback_payload
                    target_variation_id: str | None = None

                    if fiscal_sku:
                        mapped = published_by_sku.get(fiscal_sku.casefold())
                        if mapped:
                            target_item_id, target_payload = mapped
                        elif len(created_item_ids) == 1:
                            target_variation_id = variation_id_by_sku.get(fiscal_sku.casefold())
                        elif len(created_item_ids) > 1:
                            fiscal_blocking_errors.append(
                                "fiscal["
                                f"{fiscal_index}"
                                f"]: sku '{fiscal_sku}' não mapeado para item publicado"
                            )
                            continue
                    elif len(created_item_ids) > 1:
                        fiscal_blocking_errors.append(
                            f"fiscal[{fiscal_index}]: item fiscal sem sku em publicação multi-item"
                        )
                        continue

                    if not target_item_id:
                        fiscal_blocking_errors.append(
                            "fiscal["
                            f"{fiscal_index}"
                            "]: sem item publicado para vincular dados fiscais"
                        )
                        continue

                    try:
                        fiscal_data = _build_fiscal_data(
                            fiscal_item=fiscal_item,
                            publish_payload=target_payload,
                            fallback_sku=read_result.sku,
                        )
                        if target_variation_id is None:
                            fiscal_result = self._fiscal_service.submit_fiscal_data_workflow(
                                target_item_id,
                                fiscal_data,
                            )
                        else:
                            fiscal_result = self._fiscal_service.submit_fiscal_data_workflow(
                                target_item_id,
                                fiscal_data,
                                variation_id=target_variation_id,
                            )
                        if not fiscal_result.success:
                            message = fiscal_result.error_message or "falha no envio fiscal"
                            fiscal_blocking_errors.append(f"fiscal[{fiscal_index}]: {message}")
                    except Exception as exc:  # noqa: BLE001
                        logger.warning(
                            "Failed fiscal submission for %s (fiscal index %s): %s",
                            target_item_id,
                            fiscal_index,
                            exc,
                        )
                        fiscal_blocking_errors.append(
                            f"fiscal[{fiscal_index}]: erro inesperado ao enviar dados ({exc})"
                        )

        if fiscal_blocking_errors:
            fiscal_error_message = "; ".join(fiscal_blocking_errors)
            logger.error("Fiscal submission failed for %s: %s", path, fiscal_error_message)
            return PublishJsonResult(
                sku=read_result.sku,
                path=str(path),
                status="failed",
                item_id=first_item_id,
                item_ids=created_item_ids,
                user_product_id=user_product_id,
                error=fiscal_error_message,
                warnings=warnings,
            )

        return PublishJsonResult(
            sku=read_result.sku,
            path=str(path),
            status="published",
            item_id=first_item_id,
            item_ids=created_item_ids,
            user_product_id=user_product_id,
            warnings=warnings,
        )
