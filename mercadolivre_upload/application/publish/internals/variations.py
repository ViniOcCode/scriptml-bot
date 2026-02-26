"""Legacy variation helper functions extracted from publish orchestration."""

from __future__ import annotations

import logging
import re
from itertools import product as cartesian_product
from typing import Any

from mercadolivre_upload.shared.utils.text_utils import PortugueseTextNormalizer

logger = logging.getLogger(__name__)


def get_legacy_variation_contract(use_case: Any) -> tuple[list[str], dict[str, Any]]:
    """Return allow_variations IDs and limits for the current category."""
    category_id = use_case._current_publish_category_id
    if not category_id:
        return [], {}

    compiled = use_case._get_schema_contract_compiled(category_id)
    schema_contract = compiled.get("schema_contract", {})
    if not isinstance(schema_contract, dict):
        return [], {}

    allow_variations_raw = schema_contract.get("allow_variations_attribute_ids", [])
    allow_variations_attribute_ids = []
    if isinstance(allow_variations_raw, list):
        allow_variations_attribute_ids = [
            attr_id.strip()
            for attr_id in allow_variations_raw
            if isinstance(attr_id, str) and attr_id.strip()
        ]

    limits = schema_contract.get("limits", {})
    if not isinstance(limits, dict):
        limits = {}

    return allow_variations_attribute_ids, limits


def get_mapped_variation_candidate(use_case: Any, attr_id: str) -> dict[str, Any] | None:
    """Resolve mapped attribute payload as preferred variation candidate."""
    for attribute in use_case._current_variation_reference_attributes:
        if not isinstance(attribute, dict):
            continue
        raw_attr_id = attribute.get("id")
        if not isinstance(raw_attr_id, str) or raw_attr_id != attr_id:
            continue

        value_name = attribute.get("value_name")
        value_id = attribute.get("value_id")
        if isinstance(value_name, str) and value_name.strip():
            return {"id": value_id, "name": value_name.strip()}
        if value_id is not None and str(value_id).strip():
            normalized_value_id = str(value_id).strip()
            return {"id": value_id, "name": normalized_value_id}
    return None


def build_legacy_variation_seller_sku(use_case: Any, index: int) -> str | None:
    """Build deterministic SELLER_SKU value for legacy variation attributes."""
    base_sku = use_case._current_publish_sku
    if not isinstance(base_sku, str) or not base_sku.strip():
        return None
    normalized_sku = re.sub(r"\s+", "-", base_sku.strip())
    if not normalized_sku:
        return None
    return f"{normalized_sku}-{index:03d}"


def build_variations_from_candidates(
    use_case: Any,
    variation_candidates: dict[str, list[dict[str, Any]]],
    quantity: int,
    price: float,
    picture_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Build variations payload from candidate values extracted during mapping."""
    normalized_candidates = use_case._normalize_variation_candidates(variation_candidates)
    if not normalized_candidates:
        return []

    allow_variations_attribute_ids, limits = use_case._get_legacy_variation_contract()
    candidates_by_id = dict(normalized_candidates)
    preferred_attr_ids = [
        attr_id for attr_id in allow_variations_attribute_ids if attr_id in candidates_by_id
    ]
    variation_attr_ids = preferred_attr_ids or [
        attr_id for attr_id, _values in normalized_candidates
    ]

    grouped_candidates: list[tuple[str, list[dict[str, Any]]]] = []
    for attr_id in variation_attr_ids:
        values = list(candidates_by_id.get(attr_id, []))
        if not values:
            continue
        values = sorted(values, key=use_case._variation_value_sort_key)
        mapped_candidate = use_case._get_mapped_variation_candidate(attr_id)
        if mapped_candidate is not None:
            normalized_mapped_name = PortugueseTextNormalizer.normalize(mapped_candidate["name"])
            preferred_index = next(
                (
                    index
                    for index, candidate in enumerate(values)
                    if PortugueseTextNormalizer.normalize(str(candidate.get("name", "")))
                    == normalized_mapped_name
                ),
                None,
            )
            if preferred_index is not None:
                preferred_candidate = values.pop(preferred_index)
                if preferred_candidate.get("id") is None and mapped_candidate.get("id") is not None:
                    preferred_candidate["id"] = mapped_candidate.get("id")
                values.insert(0, preferred_candidate)
            else:
                values.insert(0, mapped_candidate)
        grouped_candidates.append((attr_id, values))

    if not grouped_candidates:
        return []

    max_pictures = limits.get("max_pictures")
    max_picture_count = 10
    if isinstance(max_pictures, int) and max_pictures >= 0:
        max_picture_count = min(max_picture_count, max_pictures)

    unique_picture_ids = list(dict.fromkeys(picture_ids or []))
    scoped_picture_ids = unique_picture_ids[:max_picture_count]
    if not scoped_picture_ids:
        logger.warning(
            "Variation candidates detected but no scoped picture IDs are available; "
            "skipping variations payload."
        )
        return []

    max_variations_allowed = limits.get("max_variations_allowed")
    if (
        isinstance(max_variations_allowed, int)
        and max_variations_allowed >= 0
        and max_variations_allowed < 2
    ):
        logger.info(
            "Category variation limit %s prevents legacy variation payload generation.",
            max_variations_allowed,
        )
        return []

    combinations = list(cartesian_product(*(values for _attr_id, values in grouped_candidates)))
    if len(combinations) <= 1:
        return []
    if isinstance(max_variations_allowed, int) and max_variations_allowed >= 2:
        combinations = combinations[:max_variations_allowed]
        if len(combinations) <= 1:
            return []

    variations: list[dict[str, Any]] = []
    for index, combination in enumerate(combinations, start=1):
        attribute_combinations = []
        for (attr_id, _values), value in zip(grouped_candidates, combination, strict=True):
            mapped = {"id": attr_id, "value_name": value["name"]}
            value_id = value.get("id")
            if value_id is not None:
                mapped["value_id"] = value_id
            attribute_combinations.append(mapped)

        variation: dict[str, Any] = {
            "attribute_combinations": attribute_combinations,
            "available_quantity": max(1, quantity),
            "price": price,
            "picture_ids": scoped_picture_ids,
        }
        seller_sku = use_case._build_legacy_variation_seller_sku(index)
        if seller_sku:
            variation["attributes"] = [{"id": "SELLER_SKU", "value_name": seller_sku}]

        variations.append(variation)

    return variations


def resolve_picture_ids(use_case: Any, picture_urls: list[str]) -> list[str]:
    """Resolve ML picture IDs for current picture URLs from uploader history."""
    getter = getattr(use_case.image_uploader, "get_uploaded_images", None)
    if not callable(getter):
        return []

    try:
        uploaded_images = getter()
    except Exception as error:
        logger.warning("Could not read uploaded image IDs: %s", error)
        return []

    if not isinstance(uploaded_images, list):
        return []

    url_to_id: dict[str, str] = {}
    for image in uploaded_images:
        if not isinstance(image, dict):
            continue
        url = image.get("url")
        image_id = image.get("id")
        if isinstance(url, str) and isinstance(image_id, str) and url and image_id:
            url_to_id[url] = image_id

    return [url_to_id[url] for url in picture_urls if url in url_to_id]


__all__ = [
    "build_legacy_variation_seller_sku",
    "build_variations_from_candidates",
    "get_legacy_variation_contract",
    "get_mapped_variation_candidate",
    "resolve_picture_ids",
]
