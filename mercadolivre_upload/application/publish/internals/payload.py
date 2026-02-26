"""Payload assembly helpers extracted from publish orchestration."""

from __future__ import annotations

import logging
import re
from typing import Any, cast

from .constants import (
    DEFAULT_NA_SKIP_TAGS,
    DIMENSION_DEFAULT_UNIT,
    DIMENSION_KEYWORDS,
    DIMENSION_NUMERIC_ONLY_PATTERN,
    DIMENSION_UNIT_MARKER_PATTERN,
    NON_FILLABLE_ATTRIBUTE_TAGS,
    PACKAGE_WEIGHT_DEFAULT_UNIT,
    WEIGHT_DEFAULT_UNIT,
    WEIGHT_KEYWORDS,
)
from .constants import normalize_attribute_tag as _normalize_attribute_tag

logger = logging.getLogger(__name__)


def get_available_listing_type_ids(use_case: Any, category_id: str) -> list[str]:
    """Fetch available listing types for current seller and category."""
    cached = use_case._available_listing_types_cache.get(category_id)
    if cached is not None:
        return cast(list[str], cached)

    def _extract_listing_type_ids(payload: Any) -> list[str]:
        listing_type_ids: list[str] = []
        if isinstance(payload, list):
            for listing_type in payload:
                if not isinstance(listing_type, dict):
                    continue
                listing_type_id = listing_type.get("id")
                if isinstance(listing_type_id, str) and listing_type_id:
                    listing_type_ids.append(listing_type_id)
        return list(dict.fromkeys(listing_type_ids))

    listing_types: Any = []
    getter = getattr(use_case.publisher, "get_available_listing_types", None)
    if callable(getter):
        try:
            listing_types = getter(category_id)
        except Exception as e:
            logger.warning(f"Could not fetch available listing types for {category_id}: {e}")
    else:
        logger.warning(
            "Publisher does not expose available listing types for category %s",
            category_id,
        )

    deduped_listing_type_ids = _extract_listing_type_ids(listing_types)

    if not deduped_listing_type_ids:
        site_getter = getattr(use_case.publisher, "get_site_listing_types", None)
        site_id = category_id[:3].upper() if isinstance(category_id, str) else ""
        if callable(site_getter) and site_id:
            try:
                site_listing_types = site_getter(site_id)
            except Exception as e:
                logger.warning(
                    "Could not fetch site listing types for %s (%s): %s",
                    category_id,
                    site_id,
                    e,
                )
            else:
                deduped_listing_type_ids = _extract_listing_type_ids(site_listing_types)
                if deduped_listing_type_ids:
                    logger.info(
                        "Using site-level listing types as fallback for %s "
                        "due empty seller availability.",
                        category_id,
                    )

    use_case._available_listing_types_cache[category_id] = deduped_listing_type_ids
    return deduped_listing_type_ids


def resolve_listing_type_id(
    use_case: Any,
    category_id: str,
    explicit_listing_type: str | None,
    default_listing_type: Any,
    has_pictures: bool,
    available_listing_types: list[str],
) -> str:
    """Resolve listing_type_id constrained by the category available listing types."""
    candidates: list[str] = []
    if explicit_listing_type:
        candidates.append(explicit_listing_type)

    if has_pictures and isinstance(default_listing_type, str) and default_listing_type:
        candidates.append(default_listing_type)
    if not has_pictures:
        candidates.append("free")
    if isinstance(default_listing_type, str) and default_listing_type:
        candidates.append(default_listing_type)

    candidates.extend(["gold_special", "free"])
    candidates = list(dict.fromkeys(candidates))

    if available_listing_types:
        if explicit_listing_type and explicit_listing_type not in available_listing_types:
            logger.warning(
                "Explicit listing_type_id %s is not available for category %s. "
                "Falling back to allowed listing type.",
                explicit_listing_type,
                category_id,
            )

        for candidate in candidates:
            if candidate in available_listing_types:
                return candidate

        logger.warning(
            "No preferred listing_type_id is available for category %s. " "Using first allowed: %s",
            category_id,
            available_listing_types[0],
        )
        return available_listing_types[0]

    return candidates[0] if candidates else "free"


def get_category_sale_terms_map(use_case: Any, category_id: str) -> dict[str, dict[str, Any]]:
    """Fetch category sale terms and cache by id."""
    cached = use_case._category_sale_terms_cache.get(category_id)
    if cached is not None:
        return cast(dict[str, dict[str, Any]], cached)

    getter = getattr(use_case.publisher, "get_category_sale_terms", None)
    if not callable(getter):
        logger.warning(
            "Publisher does not expose category sale terms for category %s",
            category_id,
        )
        use_case._category_sale_terms_cache[category_id] = {}
        return {}

    try:
        sale_terms = getter(category_id)
    except Exception as e:
        logger.warning(f"Could not fetch category sale terms for {category_id}: {e}")
        use_case._category_sale_terms_cache[category_id] = {}
        return {}

    mapped_sale_terms: dict[str, dict[str, Any]] = {}
    if isinstance(sale_terms, list):
        for sale_term in sale_terms:
            if not isinstance(sale_term, dict):
                continue
            sale_term_id = sale_term.get("id")
            if isinstance(sale_term_id, str) and sale_term_id:
                mapped_sale_terms[sale_term_id] = sale_term

    use_case._category_sale_terms_cache[category_id] = mapped_sale_terms
    return mapped_sale_terms


def is_required_sale_term(sale_term: dict[str, Any]) -> bool:
    """Return whether a sale term metadata entry is required."""
    tags = sale_term.get("tags", {})
    if isinstance(tags, dict):
        return bool(tags.get("required") or tags.get("new_required"))
    if isinstance(tags, list):
        normalized_tags = {str(tag).lower() for tag in tags}
        return "required" in normalized_tags or "new_required" in normalized_tags
    return False


def resolve_sale_terms(
    use_case: Any,
    category_id: str,
    sale_terms_from_mapping: list[dict[str, Any]],
    default_sale_terms: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Resolve sale terms constrained to category-allowed definitions."""
    candidate_sale_terms = sale_terms_from_mapping or default_sale_terms
    candidate_sale_terms = [
        sale_term
        for sale_term in candidate_sale_terms
        if isinstance(sale_term, dict) and isinstance(sale_term.get("id"), str)
    ]

    category_sale_terms = use_case._get_category_sale_terms_map(category_id)
    if not category_sale_terms:
        return candidate_sale_terms

    filtered_sale_terms: list[dict[str, Any]] = []
    dropped_sale_term_ids: list[str] = []
    for sale_term in candidate_sale_terms:
        sale_term_id = sale_term.get("id")
        if sale_term_id in category_sale_terms:
            filtered_sale_terms.append(sale_term)
        else:
            dropped_sale_term_ids.append(str(sale_term_id))

    if dropped_sale_term_ids:
        logger.warning(
            "Ignoring unsupported sale_terms for category %s: %s",
            category_id,
            dropped_sale_term_ids,
        )

    required_sale_term_ids = [
        sale_term_id
        for sale_term_id, sale_term_meta in category_sale_terms.items()
        if use_case._is_required_sale_term(sale_term_meta)
    ]
    if not required_sale_term_ids:
        return filtered_sale_terms

    default_by_id = {
        sale_term["id"]: sale_term
        for sale_term in default_sale_terms
        if isinstance(sale_term, dict) and isinstance(sale_term.get("id"), str)
    }
    existing_ids = {
        sale_term["id"] for sale_term in filtered_sale_terms if isinstance(sale_term.get("id"), str)
    }

    for required_sale_term_id in required_sale_term_ids:
        if required_sale_term_id in existing_ids:
            continue
        fallback_sale_term = default_by_id.get(required_sale_term_id)
        if fallback_sale_term:
            filtered_sale_terms.append(fallback_sale_term)
            existing_ids.add(required_sale_term_id)
        else:
            logger.warning(
                "Required sale term %s is missing for category %s and " "no default is configured.",
                required_sale_term_id,
                category_id,
            )

    return filtered_sale_terms


def get_non_fillable_attribute_ids(use_case: Any, category_id: str) -> set[str]:
    """Return attribute IDs that should not be auto-filled or hard-required."""
    cache = getattr(use_case, "_category_non_fillable_attribute_ids_cache", None)
    if not isinstance(cache, dict):
        cache = {}
        use_case._category_non_fillable_attribute_ids_cache = cache

    cached = cache.get(category_id)
    if isinstance(cached, set):
        return {attr_id for attr_id in cached if isinstance(attr_id, str)}

    try:
        metadata = use_case.category_resolver.get_attribute_metadata(category_id)
    except Exception as e:
        logger.warning(
            "Could not fetch attribute metadata for non-fillable filtering in %s: %s",
            category_id,
            e,
        )
        cache[category_id] = set()
        return set()

    non_fillable_attribute_ids: set[str] = set()
    for meta in metadata:
        attr_id = getattr(meta, "id", None)
        if not isinstance(attr_id, str) or not attr_id:
            continue
        tags = {
            _normalize_attribute_tag(tag)
            for tag in getattr(meta, "tags", set())
            if str(tag).strip()
        }
        if tags.intersection(NON_FILLABLE_ATTRIBUTE_TAGS):
            non_fillable_attribute_ids.add(attr_id)

    cache[category_id] = non_fillable_attribute_ids
    return non_fillable_attribute_ids


def get_missing_conditional_attributes(
    use_case: Any,
    category_id: str,
    item: dict[str, Any],
    description: str,
    conditional_required_ids: set[str] | None = None,
) -> list[str]:
    """Validate conditional required attributes using full item context payload."""
    required_ids = conditional_required_ids
    if required_ids is None:
        required_ids = use_case._get_conditional_required_attribute_ids(
            category_id=category_id,
            item=item,
            description=description,
        )

    if not required_ids:
        return []

    existing_ids = {
        attr.get("id")
        for attr in item.get("attributes", [])
        if isinstance(attr, dict) and isinstance(attr.get("id"), str)
    }
    return sorted(attr_id for attr_id in required_ids if attr_id not in existing_ids)


def get_conditional_required_attribute_ids(
    use_case: Any,
    category_id: str,
    item: dict[str, Any],
    description: str,
) -> set[str]:
    """Get conditional required attribute IDs for the current item context."""
    conditional_payload = dict(item)
    if description:
        conditional_payload["description"] = {"plain_text": description}

    try:
        conditional_attrs = use_case.category_resolver.get_conditional_attributes(
            category_id, conditional_payload
        )
    except Exception as e:
        logger.warning(f"Could not get conditional attributes for {category_id}: {e}")
        return set()

    if isinstance(conditional_attrs, dict):
        required_attributes = conditional_attrs.get("required_attributes", [])
        conditional_attrs = required_attributes if isinstance(required_attributes, list) else []

    if not isinstance(conditional_attrs, list):
        return set()

    required_ids = {
        attr_id
        for attr in conditional_attrs
        if isinstance(attr, dict)
        for attr_id in [attr.get("id")]
        if isinstance(attr_id, str) and attr_id
    }
    if not required_ids:
        return set()

    non_fillable_attribute_ids = use_case._get_non_fillable_attribute_ids(category_id)
    if non_fillable_attribute_ids:
        required_ids.difference_update(non_fillable_attribute_ids)
    return required_ids


def inject_optional_na_attributes(
    use_case: Any,
    category_id: str,
    item: dict[str, Any],
    sku: str,
    description: str,
) -> set[str] | None:
    """Auto-fill missing optional attributes with N/A payload when enabled."""
    na_policy = use_case.config.get("na_policy")
    if not isinstance(na_policy, dict) or not na_policy.get("enabled", False):
        return None

    attrs = item.get("attributes")
    if not isinstance(attrs, list):
        return None

    value_id = str(na_policy.get("value_id", "-1"))
    value_name = na_policy.get("value_name")
    configured_skip_tags = na_policy.get("skip_tags", [])
    skip_tags = DEFAULT_NA_SKIP_TAGS.copy()
    if isinstance(configured_skip_tags, list):
        configured = {
            _normalize_attribute_tag(tag) for tag in configured_skip_tags if str(tag).strip()
        }
        if configured:
            skip_tags = skip_tags.union(configured)

    conditional_required_ids = cast(
        set[str] | None,
        use_case._get_conditional_required_attribute_ids(
            category_id=category_id,
            item=item,
            description=description,
        ),
    )

    try:
        metadata = use_case.category_resolver.get_attribute_metadata(category_id)
    except Exception as e:
        logger.warning(
            "Could not fetch attribute metadata for N/A policy in %s: %s",
            category_id,
            e,
        )
        return conditional_required_ids

    existing_ids = {
        attr.get("id")
        for attr in attrs
        if isinstance(attr, dict) and isinstance(attr.get("id"), str)
    }
    auto_filled_count = 0
    skipped: list[str] = []

    for meta in metadata:
        attr_id = getattr(meta, "id", None)
        if not isinstance(attr_id, str) or not attr_id or attr_id in existing_ids:
            continue

        tags = {
            _normalize_attribute_tag(tag)
            for tag in getattr(meta, "tags", set())
            if str(tag).strip()
        }
        if bool(getattr(meta, "required", False)):
            tags.add("required")
        if conditional_required_ids and attr_id in conditional_required_ids:
            tags.add("conditional_required")

        if tags.intersection(skip_tags):
            skipped.append(attr_id)
            continue

        attrs.append({"id": attr_id, "value_id": value_id, "value_name": value_name})
        existing_ids.add(attr_id)
        auto_filled_count += 1

    if auto_filled_count:
        logger.info(
            "Auto-filled N/A for %s optional attributes on %s",
            auto_filled_count,
            sku,
        )
        conditional_required_ids = cast(
            set[str] | None,
            use_case._get_conditional_required_attribute_ids(
                category_id=category_id,
                item=item,
                description=description,
            ),
        )

    if skipped:
        logger.warning(
            "Skipped N/A auto-fill for %s attributes on %s due non-eligible tags",
            len(skipped),
            sku,
        )

    return conditional_required_ids


def normalize_item_attributes(use_case: Any, item: dict[str, Any]) -> None:
    """Ensure numeric dimensions have units.

    Appends default unit to pure-numeric dimension attributes.
    Uses dimension patterns from config.
    Operates in-place on `item['attributes']`.
    """
    attrs = item.get("attributes")
    if not isinstance(attrs, list):
        return

    dim_config = use_case.config.get("dimension_patterns") or {}
    keywords = dim_config.get("keywords", DIMENSION_KEYWORDS)
    weight_keywords = dim_config.get("weight_keywords", WEIGHT_KEYWORDS)
    default_unit = dim_config.get("default_unit", DIMENSION_DEFAULT_UNIT)
    weight_default_unit = dim_config.get("weight_default_unit", WEIGHT_DEFAULT_UNIT)
    package_weight_default_unit = dim_config.get(
        "package_weight_default_unit", PACKAGE_WEIGHT_DEFAULT_UNIT
    )
    numeric_pattern = dim_config.get("numeric_only", DIMENSION_NUMERIC_ONLY_PATTERN)
    unit_pattern = dim_config.get("unit_marker", DIMENSION_UNIT_MARKER_PATTERN)

    numeric_only = re.compile(numeric_pattern)
    unit_marker = re.compile(unit_pattern, re.IGNORECASE)

    for attr in attrs:
        if not isinstance(attr, dict):
            logger.debug("Skipping non-dict attribute during normalization: %r", attr)
            continue

        name_raw = attr.get("name")
        attr_id_raw = attr.get("id")
        name = str(name_raw).lower() if name_raw is not None else ""
        attr_id = str(attr_id_raw).upper() if attr_id_raw is not None else ""

        source_text = f"{name} {attr_id.lower()}".strip()
        is_weight = (
            any(keyword in source_text for keyword in weight_keywords)
            or attr_id == "WEIGHT"
            or attr_id == "SELLER_PACKAGE_WEIGHT"
        )
        is_dimension = (
            any(keyword in source_text for keyword in keywords)
            or attr_id in {"WIDTH", "HEIGHT", "LENGTH", "DEPTH"}
            or attr_id in {"SELLER_PACKAGE_WIDTH", "SELLER_PACKAGE_HEIGHT", "SELLER_PACKAGE_LENGTH"}
        )

        if not (is_weight or is_dimension):
            continue

        target_unit = default_unit
        if is_weight:
            target_unit = (
                package_weight_default_unit
                if attr_id == "SELLER_PACKAGE_WEIGHT"
                else weight_default_unit
            )

        val = attr.get("value_name")
        if isinstance(val, (int, float)):
            attr["value_name"] = f"{val} {target_unit}"
        elif isinstance(val, str) and numeric_only.match(val) and not unit_marker.search(val):
            normalized = val.strip().replace(",", ".")
            attr["value_name"] = f"{normalized} {target_unit}"


__all__ = [
    "get_available_listing_type_ids",
    "get_category_sale_terms_map",
    "get_conditional_required_attribute_ids",
    "get_missing_conditional_attributes",
    "get_non_fillable_attribute_ids",
    "inject_optional_na_attributes",
    "is_required_sale_term",
    "normalize_item_attributes",
    "resolve_listing_type_id",
    "resolve_sale_terms",
]
