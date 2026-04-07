"""Use case for publishing a single payload.json to Mercado Livre.

Orchestrates: read → apply overrides → validate policy → publish → post description.
Fully synchronous — matches the existing codebase patterns.
"""

from __future__ import annotations

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
    """Format ML cause codes into a readable string."""
    blocking = [c for c in exc.causes if c.get("type") == "error"]
    return "; ".join(f"[{c.get('code', '?')}] {c.get('message', '')}" for c in blocking) or str(exc)


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
        publish_inactive: bool = False,
    ) -> None:
        """Initialize with reader, policy validator, and publisher port."""
        self._reader = reader
        self._policy = policy
        self._publisher = publisher
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
        7. POST /items/{id}/description (only when description_plain_text present)

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
        if read_result.publication_ready is True and read_result.reviewed_fiscal is False:
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

        # 5. Publish one or more items.
        created_item_ids: list[str] = []
        first_item_id: str | None = None
        user_product_id: str | None = None
        description_posted = False
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
                try:
                    self._publisher.create_item_description(item_id, read_result.description)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Failed to post description for %s: %s", item_id, exc)
                description_posted = True

        return PublishJsonResult(
            sku=read_result.sku,
            path=str(path),
            status="published",
            item_id=first_item_id,
            item_ids=created_item_ids,
            user_product_id=user_product_id,
            warnings=warnings,
        )
