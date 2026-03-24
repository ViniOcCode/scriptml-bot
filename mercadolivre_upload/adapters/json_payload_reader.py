"""JSON payload reader adapter.

Reads and validates payload.json files produced by ml-builder.
Extracts _meta fields (description, sku, ai_suggested) BEFORE stripping
so the cleaned payload is ready for POST /items.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

REQUIRED_FIELDS = {
    "title",
    "category_id",
    "price",
    "currency_id",
    "available_quantity",
    "buying_mode",
    "listing_type_id",
    "condition",
    "pictures",
}

# Fields that live inside each variation — not required at root when variations present
_VARIATION_LEVEL_FIELDS: frozenset[str] = frozenset({"price", "available_quantity"})

# currency_id is always required by ML API at root; default to BRL when builder omits it
_DEFAULT_CURRENCY_ID = "BRL"


class InvalidPayloadError(Exception):
    """Raised when a payload.json is missing required fields or is structurally invalid."""


@dataclass
class ReadPayloadResult:
    """Result of reading a single payload.json file."""

    payload: dict[str, Any]  # cleaned payload without _meta — ready for POST /items
    description: str | None  # _meta.description_plain_text
    sku: str | None  # _meta.sku
    category_id: str  # extracted from payload
    ai_suggested: bool  # _meta.category_ai_suggested


class JsonPayloadReader:
    """Reads and validates payload.json files produced by ml-builder.

    Extracts _meta before stripping so description_plain_text is preserved
    for the separate POST /items/{id}/description call.
    """

    def read(self, path: Path) -> ReadPayloadResult:
        """Read and validate a single payload.json.

        Args:
            path: Path to the payload.json file.

        Returns:
            ReadPayloadResult with cleaned payload and extracted metadata.

        Raises:
            FileNotFoundError: If the file does not exist.
            json.JSONDecodeError: If the file contains invalid JSON.
            InvalidPayloadError: If required fields are missing or pictures is empty.
        """
        raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))

        # Extract _meta BEFORE removing it — description_plain_text is needed later
        meta: dict[str, Any] = raw.pop("_meta", {})
        description: str | None = meta.get("description_plain_text")
        sku: str | None = meta.get("sku")
        ai_suggested: bool = bool(meta.get("category_ai_suggested", False))

        # Inject currency_id default when missing (ml-builder omits it for variation items)
        has_variations = bool(raw.get("variations"))
        if "currency_id" not in raw:
            logger.warning("currency_id missing in %s; defaulting to BRL", path.name)
            raw["currency_id"] = _DEFAULT_CURRENCY_ID

        # price and available_quantity are only required at root when no variations present
        effective_required = REQUIRED_FIELDS - (_VARIATION_LEVEL_FIELDS if has_variations else set())
        missing = effective_required - raw.keys()
        if missing:
            raise InvalidPayloadError(
                f"Campos obrigatórios ausentes em {path.name}: {sorted(missing)}"
            )

        if not raw.get("pictures"):
            raise InvalidPayloadError(f"'pictures' não pode ser vazio em {path.name}")

        return ReadPayloadResult(
            payload=raw,
            description=description,
            sku=sku,
            category_id=raw["category_id"],
            ai_suggested=ai_suggested,
        )

    def read_batch(self, batch_dir: Path) -> list[tuple[Path, ReadPayloadResult | Exception]]:
        """Walk batch_dir for payload.json files and read each one.

        Expected structure: {batch_dir}/{category_id}/{sku}/payload.json

        Individual read failures are collected rather than raised so the caller
        decides how to handle them.

        Args:
            batch_dir: Root directory to scan for payload.json files.

        Returns:
            List of (path, result_or_exception) tuples, sorted by path.
        """
        results: list[tuple[Path, ReadPayloadResult | Exception]] = []
        for payload_path in sorted(batch_dir.rglob("payload.json")):
            try:
                result = self.read(payload_path)
                results.append((payload_path, result))
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to read %s: %s", payload_path, exc)
                results.append((payload_path, exc))
        return results
