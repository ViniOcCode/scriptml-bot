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
    error: str | None = None
    warnings: list[str] = field(default_factory=list)


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
    ) -> None:
        """Initialize with reader, policy validator, and publisher port."""
        self._reader = reader
        self._policy = policy
        self._publisher = publisher

    def execute(self, path: Path, *, dry_run: bool = False) -> PublishJsonResult:
        """Publish a single payload.json.

        Pipeline:
        1. Read and validate JSON schema
        2. Apply seller overrides (e.g. listing_type_id per category)
        3. Validate seller policy rules
        4. If dry_run → return skipped result
        5. POST /items
        6. POST /items/{id}/description (only when description_plain_text present)

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

        # 2. Apply seller overrides
        payload: dict[str, Any] = self._policy.apply_overrides(read_result.payload)

        # 3. Validate seller policy
        policy_result = self._policy.validate(payload, ai_suggested=read_result.ai_suggested)
        warnings = [v.message for v in policy_result.violations if v.severity == "warning"]

        if policy_result.has_errors:
            errors = "; ".join(
                v.message for v in policy_result.violations if v.severity == "error"
            )
            logger.warning("Policy errors for %s: %s", path, errors)
            return PublishJsonResult(
                sku=read_result.sku,
                path=str(path),
                status="failed",
                error=errors,
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

        # 5. Publish item
        try:
            item = self._publisher.create_item(payload)
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to publish %s: %s", path, exc)
            return PublishJsonResult(
                sku=read_result.sku,
                path=str(path),
                status="failed",
                error=str(exc),
                warnings=warnings,
            )

        item_id = str(item["id"])

        # 6. Post description separately (if available)
        if read_result.description:
            try:
                self._publisher.create_item_description(item_id, read_result.description)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to post description for %s: %s", item_id, exc)

        return PublishJsonResult(
            sku=read_result.sku,
            path=str(path),
            status="published",
            item_id=item_id,
            warnings=warnings,
        )
