"""JSON payload reader adapter.

Reads and validates payload.json files produced by ml-builder.
Extracts _meta fields (description, sku, ai_suggested) BEFORE stripping
so the cleaned payload is ready for publish routing.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from math import isfinite
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

# Fields required in each item of a user_products payload (per ML API docs)
UP_ITEM_REQUIRED_FIELDS: frozenset[str] = frozenset(
    {
        "category_id",
        "price",
        "currency_id",
        "available_quantity",
        "buying_mode",
        "listing_type_id",
        "condition",
        "pictures",
    }
)

UP_SELLING_CONDITION_ALLOWED_FIELDS: frozenset[str] = frozenset(
    {
        "user_product_id",
        "price",
        "category_id",
        "currency_id",
        "buying_mode",
        "listing_type_id",
        "shipping",
        "channels",
        "tags",
        "sale_terms",
        "catalog_listing",
        "catalog_product_id",
        "official_store_id",
    }
)

UP_SELLING_CONDITION_REQUIRED_FIELDS: frozenset[str] = frozenset(
    {
        "price",
        "category_id",
        "currency_id",
        "buying_mode",
        "listing_type_id",
    }
)

# When True, also validates the envelope-level family_name field (legacy check).
# Set to False to skip the envelope check (e.g. when family_name is injected externally).
VALIDATE_UP_ENVELOPE: bool = True

_SUPPORTED_UPLOAD_MODES: frozenset[str] = frozenset({"legacy_items", "user_products"})
_CATEGORY_DECISION_SOURCES: frozenset[str] = frozenset({"ai", "operator", "marketplace_metadata"})
_CATEGORY_RESOLUTION_MODES: frozenset[str] = frozenset(
    {
        "marketplace_search_consensus",
        "ml_evidence_fusion",
        "evidence_resolver",
        "llm_authoritative",
        "manual_review_required",
    }
)


class InvalidPayloadError(Exception):
    """Raised when a payload.json is missing required fields or is structurally invalid."""


@dataclass(frozen=True)
class CategoryReviewEvidence:
    """Auditable evidence required to approve a category for publication."""

    reference: str
    reviewer: str
    reviewed_at: str


@dataclass(frozen=True)
class CategoryDecision:
    """Typed provenance for the category bound to every strict publish body."""

    schema_version: Literal[1]
    category_id: str
    source: Literal["ai", "operator", "marketplace_metadata"]
    resolution_mode: Literal[
        "marketplace_search_consensus",
        "ml_evidence_fusion",
        "evidence_resolver",
        "llm_authoritative",
        "manual_review_required",
    ]
    confidence: float | None
    review_status: Literal["unreviewed", "approved"]
    review_evidence: CategoryReviewEvidence | None

    @property
    def is_approved(self) -> bool:
        """Whether the decision carries explicit, auditable approval."""
        return self.review_status == "approved"


@dataclass
class ReadPayloadResult:
    """Result of reading a single payload.json file."""

    payload: dict[str, Any]  # cleaned payload without _meta — ready for publish routing
    description: str | None  # _meta.description_plain_text (fallback root description)
    sku: str | None  # _meta.sku
    category_id: str  # extracted from payload
    ai_suggested: bool  # _meta.category_ai_suggested
    description_by_sku: dict[str, str] = field(default_factory=dict)
    upload_mode: Literal["legacy_items", "user_products"] = "legacy_items"
    # Spec validation fields extracted from _meta (all optional for backward compat)
    publication_ready: bool | None = None  # _meta.publication.publication_ready; None = absent
    blocking_reasons: list[str] = field(default_factory=list)  # _meta.blocking_reasons
    category_confidence: float | None = (
        None  # _meta.category_confidence / _meta.category.confidence
    )
    category_decision: CategoryDecision | None = None
    reviewed_fiscal: bool | None = None  # _meta.reviewed_fiscal / _meta.publication.reviewed_fiscal
    fiscal_items: list[dict[str, Any]] = field(default_factory=list)  # root fiscal.items
    publish_item_skus: list[str] = field(
        default_factory=list
    )  # _meta.traceability.publish_item_skus
    attribute_suggestions: list[dict[str, Any]] = field(
        default_factory=list
    )  # _meta.attribute_suggestions (band=="auto_apply" only)


def _normalize_upload_mode(raw_mode: Any) -> str | None:
    """Normalize external mode hints to internal upload modes."""
    if not isinstance(raw_mode, str):
        return None

    token = raw_mode.strip().lower().replace("-", "_")
    if not token:
        return None

    alias_to_mode = {
        "legacy_items": "legacy_items",
        "items": "legacy_items",
        "item": "legacy_items",
        "user_products": "user_products",
        "user_product": "user_products",
        "userproducts": "user_products",
        "up": "user_products",
    }
    return alias_to_mode.get(token)


def _extract_traceability_publish_item_skus(meta: dict[str, Any]) -> list[str]:
    """Extract traceability SKU hints used by some payload generators."""
    traceability = meta.get("traceability")
    if not isinstance(traceability, dict):
        return []

    raw_publish_item_skus = traceability.get("publish_item_skus")
    if not isinstance(raw_publish_item_skus, list):
        return []

    publish_item_skus: list[str] = []
    for raw_sku in raw_publish_item_skus:
        if not isinstance(raw_sku, str):
            continue
        normalized = raw_sku.strip()
        if normalized:
            publish_item_skus.append(normalized)
    return publish_item_skus


def _require_nonblank_string(value: object, *, field: str, path_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidPayloadError(
            f"Invalid category decision in {path_name}: {field} must be non-empty"
        )
    return value.strip()


def _parse_reviewed_at(value: object, *, path_name: str) -> str:
    reviewed_at = _require_nonblank_string(
        value, field="review.evidence.reviewed_at", path_name=path_name
    )
    try:
        parsed = datetime.fromisoformat(reviewed_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise InvalidPayloadError(
            f"Invalid category decision in {path_name}: "
            "review.evidence.reviewed_at must be ISO-8601"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise InvalidPayloadError(
            f"Invalid category decision in {path_name}: "
            "review.evidence.reviewed_at must include a UTC offset or Z suffix"
        )
    return reviewed_at


def _parse_category_decision(
    raw: object,
    *,
    path_name: str,
    required: bool,
) -> CategoryDecision | None:
    """Parse the versioned category-decision contract without legacy defaults."""
    if raw is None:
        if required:
            raise InvalidPayloadError(
                f"Invalid publisher envelope in {path_name}: _meta.category_decision is required"
            )
        return None
    if not isinstance(raw, dict):
        raise InvalidPayloadError(f"Invalid category decision in {path_name}: must be an object")

    allowed_fields = {
        "schema_version",
        "category_id",
        "source",
        "resolution_mode",
        "confidence",
        "review",
    }
    unknown_fields = sorted(set(raw) - allowed_fields)
    missing_fields = sorted(
        {"schema_version", "category_id", "source", "resolution_mode", "review"} - set(raw)
    )
    if unknown_fields or missing_fields:
        detail = []
        if missing_fields:
            detail.append(f"missing={missing_fields}")
        if unknown_fields:
            detail.append(f"unknown={unknown_fields}")
        raise InvalidPayloadError(f"Invalid category decision in {path_name}: {', '.join(detail)}")
    if raw["schema_version"] != 1:
        raise InvalidPayloadError(
            f"Invalid category decision in {path_name}: schema_version must be 1"
        )

    category_id = _require_nonblank_string(
        raw["category_id"], field="category_id", path_name=path_name
    )
    source = raw["source"]
    if source not in _CATEGORY_DECISION_SOURCES:
        raise InvalidPayloadError(f"Invalid category decision in {path_name}: unsupported source")
    resolution_mode = raw["resolution_mode"]
    if resolution_mode not in _CATEGORY_RESOLUTION_MODES:
        raise InvalidPayloadError(
            f"Invalid category decision in {path_name}: unsupported resolution_mode"
        )

    confidence_raw = raw.get("confidence")
    confidence: float | None
    if confidence_raw is None:
        confidence = None
    elif isinstance(confidence_raw, bool) or not isinstance(confidence_raw, (int, float)):
        raise InvalidPayloadError(
            f"Invalid category decision in {path_name}: confidence must be a number in [0.0, 1.0]"
        )
    else:
        confidence = float(confidence_raw)
        if not isfinite(confidence) or not 0.0 <= confidence <= 1.0:
            raise InvalidPayloadError(
                f"Invalid category decision in {path_name}: "
                "confidence must be a finite value in [0.0, 1.0]"
            )

    review_raw = raw["review"]
    if not isinstance(review_raw, dict) or set(review_raw) != {"status", "evidence"}:
        raise InvalidPayloadError(
            f"Invalid category decision in {path_name}: "
            "review must contain only status and evidence"
        )
    review_status = review_raw["status"]
    if review_status not in {"unreviewed", "approved"}:
        raise InvalidPayloadError(
            f"Invalid category decision in {path_name}: "
            "review.status must be unreviewed or approved"
        )
    evidence_raw = review_raw["evidence"]
    evidence: CategoryReviewEvidence | None = None
    if review_status == "unreviewed":
        if evidence_raw is not None:
            raise InvalidPayloadError(
                f"Invalid category decision in {path_name}: "
                "unreviewed decision must not contain evidence"
            )
    else:
        if not isinstance(evidence_raw, dict) or set(evidence_raw) != {
            "reference",
            "reviewer",
            "reviewed_at",
        }:
            raise InvalidPayloadError(
                f"Invalid category decision in {path_name}: "
                "approved review requires auditable evidence"
            )
        evidence = CategoryReviewEvidence(
            reference=_require_nonblank_string(
                evidence_raw["reference"], field="review.evidence.reference", path_name=path_name
            ),
            reviewer=_require_nonblank_string(
                evidence_raw["reviewer"], field="review.evidence.reviewer", path_name=path_name
            ),
            reviewed_at=_parse_reviewed_at(evidence_raw["reviewed_at"], path_name=path_name),
        )

    return CategoryDecision(
        schema_version=1,
        category_id=category_id,
        source=source,
        resolution_mode=resolution_mode,
        confidence=confidence,
        review_status=review_status,
        review_evidence=evidence,
    )


def _body_category_ids(
    payload: object,
    *,
    seller_model: str,
    path_name: str,
) -> list[str]:
    """Return all body category IDs, rejecting inheritance that cannot be verified."""
    if seller_model == "items":
        if not isinstance(payload, dict):
            raise InvalidPayloadError(
                f"Invalid publisher envelope in {path_name}: items model requires object payload"
            )
        return [
            _require_nonblank_string(
                payload.get("category_id"), field="payload.category_id", path_name=path_name
            )
        ]

    if not isinstance(payload, list) or not payload:
        raise InvalidPayloadError(
            f"Invalid publisher envelope in {path_name}: "
            "user_products model requires non-empty array payload"
        )
    category_ids: list[str] = []
    for index, item in enumerate(payload, start=1):
        if not isinstance(item, dict):
            raise InvalidPayloadError(
                f"Invalid publisher envelope in {path_name}: payload[{index}] must be an object"
            )
        category_ids.append(
            _require_nonblank_string(
                item.get("category_id"),
                field=f"payload[{index}].category_id",
                path_name=path_name,
            )
        )
    return category_ids


def _validate_category_decision_binding(
    meta: dict[str, Any],
    payload: object,
    *,
    seller_model: str,
    path_name: str,
) -> CategoryDecision:
    """Fail closed unless the declared decision binds every outbound body."""
    decision = _parse_category_decision(
        meta.get("category_decision"), path_name=path_name, required=True
    )
    assert decision is not None
    body_category_ids = _body_category_ids(payload, seller_model=seller_model, path_name=path_name)
    mismatched = sorted(
        {category_id for category_id in body_category_ids if category_id != decision.category_id}
    )
    if mismatched:
        raise InvalidPayloadError(
            "Invalid publisher envelope in "
            f"{path_name}: _meta.category_decision.category_id must match every payload category_id"
        )
    return decision


def _extract_root_description(raw: dict[str, Any]) -> str | None:
    """Extract top-level description from payload envelopes when present."""
    raw_description = raw.get("description")
    if isinstance(raw_description, str):
        normalized = raw_description.strip()
        return normalized or None
    if isinstance(raw_description, dict):
        plain_text = raw_description.get("plain_text")
        if isinstance(plain_text, str):
            normalized = plain_text.strip()
            return normalized or None
    return None


def _extract_meta_description_by_sku(meta: dict[str, Any]) -> dict[str, str]:
    """Extract internal per-SKU description metadata."""
    raw_descriptions = meta.get("description_by_sku")
    if not isinstance(raw_descriptions, dict):
        return {}

    descriptions: dict[str, str] = {}
    for raw_sku, raw_description in raw_descriptions.items():
        if not isinstance(raw_sku, str) or not isinstance(raw_description, str):
            continue
        sku = raw_sku.strip()
        description = raw_description.strip()
        if sku and description:
            descriptions[sku] = description
    return descriptions


def _extract_root_fiscal_items(raw: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract top-level fiscal.items rows from payload envelopes when present."""
    fiscal = raw.get("fiscal")
    if not isinstance(fiscal, dict):
        return []

    items = fiscal.get("items")
    if not isinstance(items, list):
        return []

    return [dict(item) for item in items if isinstance(item, dict)]


def _resolve_upload_mode(meta: dict[str, Any], payload: Any, path_name: str) -> str:
    publication = meta.get("publication")
    if not isinstance(publication, dict):
        publication = {}

    mode_hints: list[tuple[str, str]] = []

    def _add_mode_hint(source: str, value: Any) -> None:
        if value is None:
            return
        normalized_mode = _normalize_upload_mode(value)
        if normalized_mode is None:
            raise InvalidPayloadError(f"Modelo de publicação inválido em {path_name}: {value!r}")
        mode_hints.append((source, normalized_mode))

    _add_mode_hint("_meta.publication.model", publication.get("model"))
    _add_mode_hint("_meta.publication.seller_model", publication.get("seller_model"))
    payload_model = payload.get("model") if isinstance(payload, dict) else None
    _add_mode_hint("payload.model", payload_model)

    if mode_hints:
        first_source, resolved_mode = mode_hints[0]
        for source, mode in mode_hints[1:]:
            if mode != resolved_mode:
                raise InvalidPayloadError(f"{first_source} e {source} divergem em {path_name}")
        return resolved_mode

    # Last-resort inference when explicit model hints are absent.
    if isinstance(payload, list):
        return "user_products"
    items = payload.get("items") if isinstance(payload, dict) else None
    if isinstance(items, list):
        return "user_products"
    return "legacy_items"


def _normalize_payload_shape(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize known envelope variants into publish-ready payload shape."""
    nested_item = payload.get("item")
    if not isinstance(nested_item, dict):
        return payload

    has_root_item_fields = any(
        field in payload
        for field in (
            "title",
            "category_id",
            "price",
            "available_quantity",
            "pictures",
            "items",
            "family_name",
        )
    )
    if has_root_item_fields:
        return payload

    normalized = dict(nested_item)
    root_model = payload.get("model")
    if isinstance(root_model, str) and "model" not in normalized:
        normalized["model"] = root_model
    return normalized


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
    has_variations = bool(payload.get("variations"))

    # price and available_quantity are only required at root when no variations present
    excluded = _VARIATION_LEVEL_FIELDS if has_variations else set()
    effective_required = REQUIRED_FIELDS - excluded
    missing = effective_required - payload.keys()
    if missing:
        raise InvalidPayloadError(f"Campos obrigatórios ausentes em {path_name}: {sorted(missing)}")

    if not payload.get("pictures"):
        raise InvalidPayloadError(f"'pictures' não pode ser vazio em {path_name}")
    _validate_picture_sources(payload["pictures"], path_name)


def _validate_user_products_payload(payload: Any, path_name: str) -> None:
    """Validate a local user-products upload envelope payload."""
    items: Any = None
    family_name: str | None = None
    using_payload_array = False
    envelope_user_product_id: str | None = None
    if isinstance(payload, list):
        items = payload
        using_payload_array = True
    elif isinstance(payload, dict):
        raw_user_product_id = payload.get("user_product_id")
        if isinstance(raw_user_product_id, str) and raw_user_product_id.strip():
            envelope_user_product_id = raw_user_product_id.strip()
        # New builder artifacts use payload[] directly.
        if isinstance(payload.get("payload"), list):
            items = payload.get("payload")
            using_payload_array = True
            family_name_value = payload.get("family_name")
            if isinstance(family_name_value, str):
                family_name = family_name_value
        else:
            # Backward-compatible UP envelope variant.
            items = payload.get("items")
            family_name_value = payload.get("family_name")
            if isinstance(family_name_value, str):
                family_name = family_name_value
    if not isinstance(items, list) or not items:
        missing_field = "payload" if using_payload_array else "items"
        raise InvalidPayloadError(
            f"Campo obrigatório '{missing_field}' ausente ou vazio em {path_name}"
        )

    # Per-item required fields (ML API docs) — validated first, always.
    has_existing_user_product_items = bool(envelope_user_product_id)
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict) or not item:
            raise InvalidPayloadError(f"Item inválido em payload.items[{index}] de {path_name}")
        item_user_product_id = item.get("user_product_id")
        has_existing_user_product_id = (
            isinstance(item_user_product_id, str) and bool(item_user_product_id.strip())
        ) or bool(envelope_user_product_id)
        if has_existing_user_product_id:
            has_existing_user_product_items = True
            # Publish flow merges envelope/base fields into each item before calling ML.
            # Validate required selling-condition fields against the effective merged keys.
            effective_item_keys = set(item.keys())
            if isinstance(payload, dict):
                effective_item_keys.update(payload.keys())
            missing = UP_SELLING_CONDITION_REQUIRED_FIELDS - effective_item_keys
            if missing:
                raise InvalidPayloadError(
                    "Campos obrigatórios ausentes em "
                    f"item[{index}] de {path_name}: {sorted(missing)}"
                )
            invalid_fields = sorted(
                field for field in item if field not in UP_SELLING_CONDITION_ALLOWED_FIELDS
            )
            if invalid_fields:
                logger.warning(
                    "Ignoring inherited/unsupported user-products selling-condition fields "
                    "during local validation for %s item[%s]: %s",
                    path_name,
                    index,
                    invalid_fields,
                )
            continue

        if using_payload_array:
            item_family_name = item.get("family_name")
            if not isinstance(item_family_name, str) or not item_family_name.strip():
                raise InvalidPayloadError(
                    f"Campo obrigatório 'family_name' ausente em item[{index}] de {path_name}"
                )
        missing = UP_ITEM_REQUIRED_FIELDS - item.keys()
        if missing:
            raise InvalidPayloadError(
                f"Campos obrigatórios ausentes em item[{index}] de {path_name}: {sorted(missing)}"
            )
        item_pictures = item.get("pictures", [])
        if isinstance(item_pictures, list) and item_pictures:
            _validate_picture_sources(item_pictures, f"{path_name}[item {index}]")

    # Envelope-level check — behind VALIDATE_UP_ENVELOPE feature flag.
    if (
        VALIDATE_UP_ENVELOPE
        and isinstance(payload, dict)
        and "items" in payload
        and not has_existing_user_product_items
        and (not isinstance(family_name, str) or not family_name.strip())
    ):
        raise InvalidPayloadError(f"Campo obrigatório 'family_name' ausente em {path_name}")


def _extract_category_id(payload: dict[str, Any], upload_mode: str) -> str:
    """Extract a best-effort category ID for reporting."""
    category_id = payload.get("category_id")
    if isinstance(category_id, str) and category_id.strip():
        return category_id.strip()

    if upload_mode != "user_products":
        return ""

    items = payload.get("items")
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                continue
            item_category_id = item.get("category_id")
            if isinstance(item_category_id, str) and item_category_id.strip():
                return item_category_id.strip()
    payload_items = payload.get("payload")
    if not isinstance(payload_items, list):
        return ""
    for item in payload_items:
        if not isinstance(item, dict):
            continue
        item_category_id = item.get("category_id")
        if isinstance(item_category_id, str) and item_category_id.strip():
            return item_category_id.strip()
    return ""


def _validate_publisher_envelope(raw: dict[str, Any], path_name: str) -> None:
    """Validate the public builder-to-publisher payload envelope."""
    required_root_fields = {"payload", "description", "fiscal", "_meta"}
    missing = required_root_fields - raw.keys()
    extra = raw.keys() - required_root_fields
    if missing or extra:
        details: list[str] = []
        if missing:
            details.append(f"missing={sorted(missing)}")
        if extra:
            details.append(f"extra={sorted(extra)}")
        raise InvalidPayloadError(
            f"Invalid publisher envelope in {path_name}: {', '.join(details)}"
        )

    if not isinstance(raw.get("description"), str):
        raise InvalidPayloadError(
            f"Invalid publisher envelope in {path_name}: description must be a string"
        )
    fiscal = raw.get("fiscal")
    if not isinstance(fiscal, dict) or not isinstance(fiscal.get("items"), list):
        raise InvalidPayloadError(
            f"Invalid publisher envelope in {path_name}: fiscal.items must be a list"
        )
    meta = raw.get("_meta")
    if not isinstance(meta, dict):
        raise InvalidPayloadError(
            f"Invalid publisher envelope in {path_name}: _meta must be an object"
        )
    publication = meta.get("publication")
    if not isinstance(publication, dict):
        raise InvalidPayloadError(
            f"Invalid publisher envelope in {path_name}: _meta.publication must be an object"
        )
    if publication.get("publication_ready") is not True:
        raise InvalidPayloadError(
            "Invalid publisher envelope in "
            f"{path_name}: _meta.publication.publication_ready must be true"
        )
    seller_model = publication.get("seller_model")
    payload = raw.get("payload")
    if seller_model == "items" and not isinstance(payload, dict):
        raise InvalidPayloadError(
            f"Invalid publisher envelope in {path_name}: items model requires object payload"
        )
    if seller_model == "user_products" and not isinstance(payload, list):
        raise InvalidPayloadError(
            f"Invalid publisher envelope in {path_name}: user_products model requires list payload"
        )
    if seller_model not in {"items", "user_products"}:
        raise InvalidPayloadError(
            f"Invalid publisher envelope in {path_name}: unsupported seller_model"
        )
    if "category_ai_suggested" in meta:
        raise InvalidPayloadError(
            "Invalid publisher envelope in "
            f"{path_name}: category_ai_suggested is retired; use _meta.category_decision"
        )
    _validate_category_decision_binding(
        meta,
        payload,
        seller_model=seller_model,
        path_name=path_name,
    )
    traceability = meta.get("traceability")
    publish_item_skus = (
        traceability.get("publish_item_skus") if isinstance(traceability, dict) else None
    )
    if (
        not isinstance(publish_item_skus, list)
        or not publish_item_skus
        or any(not isinstance(sku, str) or not sku.strip() for sku in publish_item_skus)
    ):
        raise InvalidPayloadError(
            "Invalid publisher envelope in "
            f"{path_name}: _meta.traceability.publish_item_skus must be a non-empty string list"
        )


class JsonPayloadReader:
    """Reads and validates payload.json files produced by ml-builder.

    Extracts _meta before stripping so description_plain_text is preserved
    for the separate POST /items/{id}/description call.
    """

    def __init__(self, *, strict_publisher_contract: bool = False) -> None:
        """Initialize the reader with an optional strict publisher boundary."""
        self._strict_publisher_contract = strict_publisher_contract

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
        if self._strict_publisher_contract:
            _validate_publisher_envelope(raw, path.name)

        # Extract _meta BEFORE removing it — description_plain_text is needed later
        meta: dict[str, Any] = raw.get("_meta", {})
        if not isinstance(meta, dict):
            raise InvalidPayloadError(f"'_meta' deve ser objeto em {path.name}")
        description_raw = meta.get("description_plain_text")
        description: str | None = (
            description_raw.strip()
            if isinstance(description_raw, str) and description_raw.strip()
            else None
        )
        if description is None:
            description = _extract_root_description(raw)
        description_by_sku = _extract_meta_description_by_sku(meta)
        sku: str | None = meta.get("sku")
        category_decision = _parse_category_decision(
            meta.get("category_decision"),
            path_name=path.name,
            required=self._strict_publisher_contract,
        )
        ai_suggested_raw = meta.get("category_ai_suggested", False)
        if not isinstance(ai_suggested_raw, bool):
            raise InvalidPayloadError(
                f"'_meta.category_ai_suggested' deve ser booleano em {path.name}"
            )
        if category_decision is not None:
            ai_suggested = category_decision.source == "ai"
            if "category_ai_suggested" in meta and ai_suggested_raw != ai_suggested:
                raise InvalidPayloadError(
                    "'_meta.category_ai_suggested' diverge de "
                    f"category_decision.source em {path.name}"
                )
        else:
            ai_suggested = ai_suggested_raw
        publication = meta.get("publication")
        if not isinstance(publication, dict):
            publication = {}

        publication_ready_raw = meta.get("publication_ready", publication.get("publication_ready"))
        if publication_ready_raw is not None and not isinstance(publication_ready_raw, bool):
            raise InvalidPayloadError(
                f"'_meta.publication.publication_ready' deve ser booleano em {path.name}"
            )
        publication_ready = publication_ready_raw
        blocking_reasons_raw = meta.get("blocking_reasons", [])
        if not isinstance(blocking_reasons_raw, list) or any(
            not isinstance(reason, str) for reason in blocking_reasons_raw
        ):
            raise InvalidPayloadError(
                f"'_meta.blocking_reasons' deve ser lista de strings em {path.name}"
            )
        blocking_reasons = list(blocking_reasons_raw)
        category_meta = meta.get("category")
        if not isinstance(category_meta, dict):
            category_meta = {}
        category_confidence_raw = meta.get("category_confidence", category_meta.get("confidence"))
        category_confidence: float | None = (
            category_decision.confidence
            if category_decision is not None
            else float(category_confidence_raw)
            if isinstance(category_confidence_raw, (int, float))
            and not isinstance(category_confidence_raw, bool)
            else None
        )
        reviewed_fiscal_raw = meta.get("reviewed_fiscal", publication.get("reviewed_fiscal"))
        if reviewed_fiscal_raw is not None and not isinstance(reviewed_fiscal_raw, bool):
            raise InvalidPayloadError(
                f"'_meta.publication.reviewed_fiscal' deve ser booleano em {path.name}"
            )
        reviewed_fiscal = reviewed_fiscal_raw
        fiscal_items = _extract_root_fiscal_items(raw)
        publish_item_skus = _extract_traceability_publish_item_skus(meta)

        # F1: fallback to publish_item_skus[0] when _meta.sku is absent
        if not sku and publish_item_skus:
            sku = publish_item_skus[0]

        # N1: extract attribute_suggestions, keeping only auto_apply entries
        attribute_suggestions: list[dict[str, Any]] = []
        raw_suggestions = meta.get("attribute_suggestions", [])
        if isinstance(raw_suggestions, list):
            attribute_suggestions = [
                s for s in raw_suggestions if isinstance(s, dict) and s.get("band") == "auto_apply"
            ]

        payload_obj = raw.get("payload")
        if isinstance(payload_obj, dict):
            payload = dict(payload_obj)
        else:
            # Backward-compatible fallback for older root-style payloads.
            payload = {key: value for key, value in raw.items() if key != "_meta"}
        if not payload:
            raise InvalidPayloadError(f"Campo obrigatório 'payload' ausente em {path.name}")
        payload.pop("_meta", None)
        payload = _normalize_payload_shape(payload)

        upload_mode = _resolve_upload_mode(meta, payload, path.name)
        payload.pop("model", None)
        if upload_mode == "user_products":
            _validate_user_products_payload(payload, path.name)
        else:
            _validate_legacy_payload(payload, path.name)

        return ReadPayloadResult(
            payload=payload,
            description=description,
            description_by_sku=description_by_sku,
            sku=sku,
            category_id=_extract_category_id(payload, upload_mode),
            ai_suggested=ai_suggested,
            upload_mode=upload_mode,  # type: ignore[arg-type]
            publication_ready=publication_ready,
            blocking_reasons=blocking_reasons,
            category_confidence=category_confidence,
            category_decision=category_decision,
            reviewed_fiscal=reviewed_fiscal,
            fiscal_items=fiscal_items,
            publish_item_skus=publish_item_skus,
            attribute_suggestions=attribute_suggestions,
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
