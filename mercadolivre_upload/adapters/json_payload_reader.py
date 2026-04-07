"""JSON payload reader adapter.

Reads and validates payload.json files produced by ml-builder.
Extracts _meta fields (description, sku, ai_suggested) BEFORE stripping
so the cleaned payload is ready for publish routing.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

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
_SUPPORTED_UPLOAD_MODES: frozenset[str] = frozenset({"legacy_items", "user_products"})


class InvalidPayloadError(Exception):
    """Raised when a payload.json is missing required fields or is structurally invalid."""


@dataclass
class ReadPayloadResult:
    """Result of reading a single payload.json file."""

    payload: dict[str, Any]  # cleaned payload without _meta — ready for publish routing
    description: str | None  # _meta.description_plain_text
    sku: str | None  # _meta.sku
    category_id: str  # extracted from payload
    ai_suggested: bool  # _meta.category_ai_suggested
    upload_mode: Literal["legacy_items", "user_products"] = "legacy_items"
    # Spec validation fields extracted from _meta (all optional for backward compat)
    publication_ready: bool | None = None  # _meta.publication_ready; None = absent
    blocking_reasons: list[str] = field(default_factory=list)  # _meta.blocking_reasons
    category_confidence: float | None = None  # _meta.category_confidence
    reviewed_fiscal: bool | None = None  # _meta.reviewed_fiscal


def _resolve_upload_mode(meta: dict[str, Any], payload: dict[str, Any], path_name: str) -> str:
    publication = meta.get("publication", {})
    publication_model = publication.get("model") if isinstance(publication, dict) else None
    if publication_model is not None:
        if (
            not isinstance(publication_model, str)
            or publication_model.strip() not in _SUPPORTED_UPLOAD_MODES
        ):
            raise InvalidPayloadError(
                f"Modelo de publicação inválido em {path_name}: {publication_model!r}"
            )
        publication_model = publication_model.strip()

    payload_model = payload.get("model")
    if payload_model is not None:
        if not isinstance(payload_model, str) or payload_model.strip() != "user_products":
            raise InvalidPayloadError(f"Campo 'payload.model' inválido em {path_name}")
        payload_model = payload_model.strip()

    if publication_model == "user_products" or payload_model == "user_products":
        if publication_model == "legacy_items" and payload_model == "user_products":
            raise InvalidPayloadError(
                f"_meta.publication.model e payload.model divergem em {path_name}"
            )
        return "user_products"
    return "legacy_items"


def _validate_picture_sources(pictures: list[Any], path_name: str) -> None:
    r"""Raise InvalidPayloadError if any picture source is a local filesystem path.

    Accepts: https:// URLs (CDN) and entries without a source key (already-uploaded IDs).
    Rejects: /absolute/paths, relative/paths, C:\\Windows\\paths — ML API would reject these.
    """
    for pic in pictures:
        if not isinstance(pic, dict):
            continue
        source = pic.get("source")
        if not isinstance(source, str) or not source:
            continue  # no source key → already-uploaded picture ID → OK
        if source.startswith(("http://", "https://")):
            continue  # valid CDN URL
        raise InvalidPayloadError(
            f"'pictures[].source' parece um caminho local em {path_name}: {source!r}. "
            "Apenas URLs HTTP(S) são aceitos no campo 'source'"
        )


def _validate_legacy_payload(payload: dict[str, Any], path_name: str) -> None:
    """Validate a direct /items payload."""
    # Inject currency_id default when missing (ml-builder omits it for variation items)
    has_variations = bool(payload.get("variations"))
    if "currency_id" not in payload:
        logger.warning("currency_id missing in %s; defaulting to BRL", path_name)
        payload["currency_id"] = _DEFAULT_CURRENCY_ID

    # price and available_quantity are only required at root when no variations present
    excluded = _VARIATION_LEVEL_FIELDS if has_variations else set()
    effective_required = REQUIRED_FIELDS - excluded
    missing = effective_required - payload.keys()
    if missing:
        raise InvalidPayloadError(f"Campos obrigatórios ausentes em {path_name}: {sorted(missing)}")

    if not payload.get("pictures"):
        raise InvalidPayloadError(f"'pictures' não pode ser vazio em {path_name}")
    _validate_picture_sources(payload["pictures"], path_name)


def _validate_user_products_payload(payload: dict[str, Any], path_name: str) -> None:
    """Validate a local user-products upload envelope payload."""
    family_name = payload.get("family_name")
    if not isinstance(family_name, str) or not family_name.strip():
        raise InvalidPayloadError(f"Campo obrigatório 'family_name' ausente em {path_name}")

    items = payload.get("items")
    if not isinstance(items, list) or not items:
        raise InvalidPayloadError(f"Campo obrigatório 'items' ausente ou vazio em {path_name}")

    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict) or not item:
            raise InvalidPayloadError(f"Item inválido em payload.items[{index}] de {path_name}")
        item_pictures = item.get("pictures", [])
        if isinstance(item_pictures, list) and item_pictures:
            _validate_picture_sources(item_pictures, f"{path_name}[item {index}]")


def _extract_category_id(payload: dict[str, Any], upload_mode: str) -> str:
    """Extract a best-effort category ID for reporting."""
    category_id = payload.get("category_id")
    if isinstance(category_id, str) and category_id.strip():
        return category_id.strip()

    if upload_mode != "user_products":
        return ""

    items = payload.get("items")
    if not isinstance(items, list):
        return ""

    for item in items:
        if not isinstance(item, dict):
            continue
        item_category_id = item.get("category_id")
        if isinstance(item_category_id, str) and item_category_id.strip():
            return item_category_id.strip()
    return ""


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
        if not isinstance(raw, dict):
            raise InvalidPayloadError(f"Payload inválido em {path.name}: raiz JSON deve ser objeto")

        # Extract _meta BEFORE removing it — description_plain_text is needed later
        meta: dict[str, Any] = raw.get("_meta", {})
        if not isinstance(meta, dict):
            meta = {}
        description: str | None = meta.get("description_plain_text")
        sku: str | None = meta.get("sku")
        ai_suggested: bool = bool(meta.get("category_ai_suggested", False))
        publication_ready_raw = meta.get("publication_ready")
        publication_ready: bool | None = (
            bool(publication_ready_raw) if publication_ready_raw is not None else None
        )
        blocking_reasons: list[str] = list(meta.get("blocking_reasons") or [])
        category_confidence_raw = meta.get("category_confidence")
        category_confidence: float | None = (
            float(category_confidence_raw)
            if isinstance(category_confidence_raw, (int, float))
            else None
        )
        reviewed_fiscal_raw = meta.get("reviewed_fiscal")
        reviewed_fiscal: bool | None = (
            bool(reviewed_fiscal_raw) if reviewed_fiscal_raw is not None else None
        )

        payload_obj = raw.get("payload")
        if isinstance(payload_obj, dict):
            payload = dict(payload_obj)
        else:
            # Backward-compatible fallback for older root-style payloads.
            payload = {key: value for key, value in raw.items() if key != "_meta"}
        if not payload:
            raise InvalidPayloadError(f"Campo obrigatório 'payload' ausente em {path.name}")
        payload.pop("_meta", None)

        upload_mode = _resolve_upload_mode(meta, payload, path.name)
        payload.pop("model", None)
        if upload_mode == "user_products":
            _validate_user_products_payload(payload, path.name)
        else:
            _validate_legacy_payload(payload, path.name)

        return ReadPayloadResult(
            payload=payload,
            description=description,
            sku=sku,
            category_id=_extract_category_id(payload, upload_mode),
            ai_suggested=ai_suggested,
            upload_mode=upload_mode,  # type: ignore[arg-type]
            publication_ready=publication_ready,
            blocking_reasons=blocking_reasons,
            category_confidence=category_confidence,
            reviewed_fiscal=reviewed_fiscal,
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
