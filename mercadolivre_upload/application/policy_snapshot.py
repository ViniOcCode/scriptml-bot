"""Helpers to compile deterministic category policy snapshots."""

from __future__ import annotations

import hashlib
import json
from typing import Any

POLICY_TAG_KEYS: tuple[str, ...] = (
    "required",
    "new_required",
    "conditional_required",
    "allow_variations",
    "catalog_listing_required",
)


def _coerce_non_negative_int(value: Any) -> int | None:
    """Coerce supported integer payloads into non-negative integers."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float) and value.is_integer():
        parsed = int(value)
        return parsed if parsed >= 0 else None
    if isinstance(value, str):
        text = value.strip()
        if text.isdigit():
            return int(text)
    return None


def _normalize_tag_flags(raw_tags: Any) -> dict[str, bool]:
    """Normalize tag payloads into a fixed set of boolean flags."""
    normalized = dict.fromkeys(POLICY_TAG_KEYS, False)
    if isinstance(raw_tags, dict):
        for tag_key in POLICY_TAG_KEYS:
            normalized[tag_key] = bool(raw_tags.get(tag_key))
        return normalized

    if isinstance(raw_tags, (list, tuple, set)):
        tags = {str(tag).strip().lower() for tag in raw_tags if str(tag).strip()}
        for tag_key in POLICY_TAG_KEYS:
            normalized[tag_key] = tag_key in tags
    return normalized


def _normalize_tag_names(raw_tags: Any) -> list[str]:
    """Normalize arbitrary tag payloads into a sorted tag-name list."""
    if isinstance(raw_tags, dict):
        tags = {str(key).strip().lower() for key, enabled in raw_tags.items() if bool(enabled)}
        return sorted(tag for tag in tags if tag)
    if isinstance(raw_tags, (list, tuple, set)):
        tags = {str(tag).strip().lower() for tag in raw_tags if str(tag).strip()}
        return sorted(tags)
    return []


def _normalize_category_payload(category_id: str, category_data: dict[str, Any]) -> dict[str, Any]:
    """Normalize category-level policy fields."""
    status = category_data.get("status")
    settings = category_data.get("settings")
    normalized_settings: dict[str, Any] = {"status": None, "listing_allowed": None}
    if isinstance(settings, dict):
        settings_status = settings.get("status")
        if isinstance(settings_status, str) and settings_status:
            normalized_settings["status"] = settings_status

        listing_allowed = settings.get("listing_allowed")
        if isinstance(listing_allowed, bool):
            normalized_settings["listing_allowed"] = listing_allowed

    return {
        "id": category_id,
        "status": status if isinstance(status, str) and status else None,
        "settings": normalized_settings,
    }


def _extract_category_limits(category_data: dict[str, Any]) -> dict[str, int | None]:
    """Extract category limit values from settings when available."""
    settings = category_data.get("settings")
    if not isinstance(settings, dict):
        return {
            "max_pictures": None,
            "max_variations_allowed": None,
        }

    max_pictures = None
    for key in ("max_pictures_per_item", "max_pictures"):
        parsed = _coerce_non_negative_int(settings.get(key))
        if parsed is not None:
            max_pictures = parsed
            break

    max_variations_allowed = _coerce_non_negative_int(settings.get("max_variations_allowed"))
    return {
        "max_pictures": max_pictures,
        "max_variations_allowed": max_variations_allowed,
    }


def _normalize_attributes(
    attributes: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Normalize attributes by id and summarize key policy tags."""
    by_id: dict[str, dict[str, bool]] = {}
    for attribute in attributes:
        attribute_id = attribute.get("id")
        if not isinstance(attribute_id, str) or not attribute_id:
            continue
        tag_flags = _normalize_tag_flags(attribute.get("tags"))
        merged = by_id.setdefault(attribute_id, dict.fromkeys(POLICY_TAG_KEYS, False))
        for tag_key in POLICY_TAG_KEYS:
            merged[tag_key] = merged[tag_key] or tag_flags[tag_key]

    normalized_attributes = [{"id": attr_id, "tags": by_id[attr_id]} for attr_id in sorted(by_id)]
    tag_summary = {
        tag_key: sum(tag_flags[tag_key] for tag_flags in by_id.values())
        for tag_key in POLICY_TAG_KEYS
    }
    return normalized_attributes, tag_summary


def _normalize_listing_types(listing_types: list[Any]) -> list[str]:
    """Normalize available listing types into a stable sorted id list."""
    listing_type_ids: set[str] = set()
    for listing_type in listing_types:
        if isinstance(listing_type, str) and listing_type:
            listing_type_ids.add(listing_type)
            continue
        if not isinstance(listing_type, dict):
            continue
        listing_type_id = listing_type.get("id")
        if isinstance(listing_type_id, str) and listing_type_id:
            listing_type_ids.add(listing_type_id)
    return sorted(listing_type_ids)


def _normalize_sale_terms(
    sale_terms: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    """Normalize sale-terms ids/tags and count required terms."""
    by_id: dict[str, set[str]] = {}
    for sale_term in sale_terms:
        sale_term_id = sale_term.get("id")
        if not isinstance(sale_term_id, str) or not sale_term_id:
            continue
        tags = set(_normalize_tag_names(sale_term.get("tags")))
        by_id.setdefault(sale_term_id, set()).update(tags)

    normalized_sale_terms: list[dict[str, Any]] = []
    required_count = 0
    for sale_term_id in sorted(by_id):
        tag_names = sorted(by_id[sale_term_id])
        if "required" in tag_names or "new_required" in tag_names:
            required_count += 1
        normalized_sale_terms.append({"id": sale_term_id, "tags": tag_names})

    return normalized_sale_terms, required_count


def _extract_identifier_contract(
    attributes: list[dict[str, Any]],
    *,
    required_attribute_ids: set[str],
) -> dict[str, Any]:
    """Extract deterministic GTIN/EMPTY_GTIN_REASON contract metadata."""
    has_gtin = False
    has_empty_gtin_reason = False
    allowed_reason_ids: set[str] = set()
    allowed_reason_names: set[str] = set()

    for attribute in attributes:
        attribute_id = attribute.get("id")
        if not isinstance(attribute_id, str) or not attribute_id:
            continue
        normalized_id = attribute_id.strip().upper()

        if normalized_id == "GTIN":
            has_gtin = True
            continue

        if normalized_id != "EMPTY_GTIN_REASON":
            continue

        has_empty_gtin_reason = True
        raw_values = attribute.get("values")
        if not isinstance(raw_values, list):
            continue

        for raw_value in raw_values:
            if not isinstance(raw_value, dict):
                continue
            value_id = raw_value.get("id")
            value_name = raw_value.get("name")
            if value_id is not None:
                normalized_value_id = str(value_id).strip()
                if normalized_value_id:
                    allowed_reason_ids.add(normalized_value_id)
            if value_name is not None:
                normalized_value_name = str(value_name).strip()
                if normalized_value_name:
                    allowed_reason_names.add(normalized_value_name)

    return {
        "gtin_attribute_id": "GTIN" if has_gtin else None,
        "empty_gtin_reason_attribute_id": ("EMPTY_GTIN_REASON" if has_empty_gtin_reason else None),
        "gtin_required": "GTIN" in required_attribute_ids,
        "empty_gtin_reason_allowed_value_ids": sorted(allowed_reason_ids),
        "empty_gtin_reason_allowed_value_names": sorted(allowed_reason_names),
    }


def compile_policy_snapshot(
    *,
    category_id: str,
    category_data: dict[str, Any],
    attributes: list[dict[str, Any]],
    listing_types: list[Any],
    sale_terms: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compile a stable policy snapshot/hash and a compact summary."""
    normalized_attributes, attribute_tag_summary = _normalize_attributes(attributes)
    normalized_listing_types = _normalize_listing_types(listing_types)
    normalized_sale_terms, required_sale_term_count = _normalize_sale_terms(sale_terms)
    snapshot: dict[str, Any] = {
        "category": _normalize_category_payload(category_id, category_data),
        "attributes": normalized_attributes,
        "attribute_tag_summary": attribute_tag_summary,
        "listing_types": normalized_listing_types,
        "sale_terms": normalized_sale_terms,
    }
    serialized = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    policy_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    policy_summary = {
        "category_id": category_id,
        "listing_allowed": snapshot["category"]["settings"]["listing_allowed"],
        "status": snapshot["category"]["status"] or snapshot["category"]["settings"]["status"],
        "attribute_count": len(normalized_attributes),
        "attribute_tag_summary": attribute_tag_summary,
        "listing_type_count": len(normalized_listing_types),
        "listing_types": normalized_listing_types,
        "sale_term_count": len(normalized_sale_terms),
        "required_sale_term_count": required_sale_term_count,
    }

    return {
        "policy_snapshot": snapshot,
        "policy_hash": policy_hash,
        "policy_summary": policy_summary,
    }


def compile_schema_contract(
    *,
    category_id: str,
    category_data: dict[str, Any],
    attributes: list[dict[str, Any]],
    sale_terms: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compile deterministic schema-contract metadata for preflight validation."""
    normalized_attributes, _ = _normalize_attributes(attributes)
    attribute_ids_by_tag: dict[str, list[str]] = {tag: [] for tag in POLICY_TAG_KEYS}
    for attribute in normalized_attributes:
        attr_id = attribute["id"]
        tags = attribute.get("tags", {})
        for tag_key in POLICY_TAG_KEYS:
            if bool(tags.get(tag_key)):
                attribute_ids_by_tag[tag_key].append(attr_id)

    required_attribute_ids = sorted(
        {
            *attribute_ids_by_tag["required"],
            *attribute_ids_by_tag["new_required"],
            *attribute_ids_by_tag["catalog_listing_required"],
            *attribute_ids_by_tag["conditional_required"],
        }
    )
    required_attribute_ids_set = set(required_attribute_ids)
    identifier_contract = _extract_identifier_contract(
        attributes,
        required_attribute_ids=required_attribute_ids_set,
    )

    normalized_sale_terms, _ = _normalize_sale_terms(sale_terms)
    required_sale_term_ids: list[str] = []
    optional_sale_term_ids: list[str] = []
    normalized_sale_term_rows: list[dict[str, Any]] = []
    for sale_term in normalized_sale_terms:
        sale_term_id = sale_term["id"]
        tags = sale_term.get("tags", [])
        is_required = "required" in tags or "new_required" in tags
        normalized_sale_term_rows.append(
            {"id": sale_term_id, "required": is_required, "tags": tags}
        )
        if is_required:
            required_sale_term_ids.append(sale_term_id)
        else:
            optional_sale_term_ids.append(sale_term_id)

    category_limits = _extract_category_limits(category_data)
    schema_contract = {
        "category_id": category_id,
        "attribute_ids_by_tag": attribute_ids_by_tag,
        "required_attribute_ids": required_attribute_ids,
        "allow_variations_attribute_ids": list(attribute_ids_by_tag["allow_variations"]),
        "sale_terms": {
            "all": normalized_sale_term_rows,
            "required_ids": required_sale_term_ids,
            "optional_ids": optional_sale_term_ids,
        },
        "limits": category_limits,
        "identifier_contract": identifier_contract,
    }

    serialized = json.dumps(
        schema_contract,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    schema_contract_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    schema_contract_summary = {
        "category_id": category_id,
        "required_attribute_count": len(required_attribute_ids),
        "allow_variations_attribute_count": len(attribute_ids_by_tag["allow_variations"]),
        "sale_term_count": len(normalized_sale_term_rows),
        "required_sale_term_count": len(required_sale_term_ids),
        "optional_sale_term_count": len(optional_sale_term_ids),
        "max_pictures": category_limits["max_pictures"],
        "max_variations_allowed": category_limits["max_variations_allowed"],
        "gtin_required": bool(identifier_contract.get("gtin_required")),
        "empty_gtin_reason_allowed_value_count": len(
            identifier_contract.get("empty_gtin_reason_allowed_value_ids", [])
        ),
    }
    return {
        "schema_contract": schema_contract,
        "schema_contract_hash": schema_contract_hash,
        "schema_contract_summary": schema_contract_summary,
    }
