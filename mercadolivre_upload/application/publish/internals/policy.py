"""Policy snapshot helper functions extracted from publish orchestration."""

from __future__ import annotations

import logging
from typing import Any, cast

from mercadolivre_upload.application.policy_snapshot import compile_policy_snapshot

logger = logging.getLogger(__name__)


def get_policy_category_data(use_case: Any, category_id: str) -> dict[str, Any]:
    """Fetch category metadata for policy compilation."""
    getter = getattr(use_case.category_resolver, "get_category_data", None)
    if callable(getter):
        try:
            result = getter(category_id)
        except Exception as error:
            logger.warning(
                "Could not fetch category metadata for policy snapshot %s: %s",
                category_id,
                error,
            )
            return {}
        if isinstance(result, dict):
            return result
        logger.warning(
            "Unexpected category metadata payload for policy snapshot %s: %s",
            category_id,
            type(result).__name__,
        )
        return {}

    cached_getter = getattr(use_case.category_resolver, "_get_category_cached", None)
    if callable(cached_getter):
        try:
            result = cached_getter(category_id)
        except Exception as error:
            logger.warning(
                "Could not fetch cached category metadata for policy snapshot %s: %s",
                category_id,
                error,
            )
            return {}
        if isinstance(result, dict):
            return result

    logger.warning(
        "Category resolver does not expose category metadata for policy snapshot %s",
        category_id,
    )
    return {}


def build_policy_attribute_rows(attributes: list[Any]) -> list[dict[str, Any]]:
    """Normalize arbitrary attribute metadata payloads into dict rows."""
    normalized_rows: list[dict[str, Any]] = []
    for attribute in attributes:
        if isinstance(attribute, dict):
            attr_id = attribute.get("id")
            if isinstance(attr_id, str) and attr_id:
                row: dict[str, Any] = {"id": attr_id, "tags": attribute.get("tags", {})}
                raw_values = attribute.get("values")
                normalized_values: list[dict[str, str]] = []
                if isinstance(raw_values, list):
                    for raw_value in raw_values:
                        if not isinstance(raw_value, dict):
                            continue
                        value_row: dict[str, str] = {}
                        value_id = raw_value.get("id")
                        value_name = raw_value.get("name")
                        if value_id is not None:
                            normalized_value_id = str(value_id).strip()
                            if normalized_value_id:
                                value_row["id"] = normalized_value_id
                        if value_name is not None:
                            normalized_value_name = str(value_name).strip()
                            if normalized_value_name:
                                value_row["name"] = normalized_value_name
                        if value_row:
                            normalized_values.append(value_row)
                if normalized_values:
                    row["values"] = normalized_values
                normalized_rows.append(row)
            continue

        attr_id = getattr(attribute, "id", None)
        if not isinstance(attr_id, str) or not attr_id:
            continue
        raw_tags = getattr(attribute, "tags", {})
        if isinstance(raw_tags, set):
            tags_payload: Any = sorted(raw_tags)
        else:
            tags_payload = raw_tags
        row = {"id": attr_id, "tags": tags_payload}

        raw_values = getattr(attribute, "values", None)
        normalized_values = []
        if isinstance(raw_values, list):
            for raw_value in raw_values:
                if not isinstance(raw_value, dict):
                    continue
                fallback_value_row: dict[str, str] = {}
                value_id = raw_value.get("id")
                value_name = raw_value.get("name")
                if value_id is not None:
                    normalized_value_id = str(value_id).strip()
                    if normalized_value_id:
                        fallback_value_row["id"] = normalized_value_id
                if value_name is not None:
                    normalized_value_name = str(value_name).strip()
                    if normalized_value_name:
                        fallback_value_row["name"] = normalized_value_name
                if fallback_value_row:
                    normalized_values.append(fallback_value_row)
        else:
            allowed_values = getattr(attribute, "allowed_values", None)
            if isinstance(allowed_values, set):
                normalized_values = [
                    {"name": str(value).strip()}
                    for value in sorted(allowed_values)
                    if str(value).strip()
                ]

        if normalized_values:
            row["values"] = normalized_values
        normalized_rows.append(row)

    return normalized_rows


def get_policy_attributes(use_case: Any, category_id: str) -> list[dict[str, Any]]:
    """Fetch category attributes for policy compilation."""
    getter = getattr(use_case.category_resolver, "get_all_attributes", None)
    if callable(getter):
        try:
            result = getter(category_id)
        except Exception as error:
            logger.warning(
                "Could not fetch category attributes for policy snapshot %s: %s",
                category_id,
                error,
            )
        else:
            if isinstance(result, list):
                return cast(list[dict[str, Any]], use_case._build_policy_attribute_rows(result))
            logger.warning(
                "Unexpected category attributes payload for policy snapshot %s: %s",
                category_id,
                type(result).__name__,
            )
            return []

    metadata_getter = getattr(use_case.category_resolver, "get_attribute_metadata", None)
    if callable(metadata_getter):
        try:
            result = metadata_getter(category_id)
        except Exception as error:
            logger.warning(
                "Could not fetch attribute metadata for policy snapshot %s: %s",
                category_id,
                error,
            )
            return []
        if isinstance(result, list):
            return cast(list[dict[str, Any]], use_case._build_policy_attribute_rows(result))
        logger.warning(
            "Unexpected attribute metadata payload for policy snapshot %s: %s",
            category_id,
            type(result).__name__,
        )
        return []

    logger.warning(
        "Category resolver does not expose attributes for policy snapshot %s",
        category_id,
    )
    return []


def get_policy_artifact(use_case: Any, category_id: str) -> dict[str, Any]:
    """Compile and cache policy hash/summary for a category."""
    cached = use_case._category_policy_cache.get(category_id)
    if cached is not None:
        return cast(dict[str, Any], cached)

    category_data = use_case._get_policy_category_data(category_id)
    attributes = use_case._get_policy_attributes(category_id)
    listing_types = use_case._get_available_listing_type_ids(category_id)
    sale_terms = list(use_case._get_category_sale_terms_map(category_id).values())
    try:
        compiled = compile_policy_snapshot(
            category_id=category_id,
            category_data=category_data,
            attributes=attributes,
            listing_types=listing_types,
            sale_terms=sale_terms,
        )
    except Exception as error:
        logger.error("Failed to compile policy snapshot for %s: %s", category_id, error)
        compiled = compile_policy_snapshot(
            category_id=category_id,
            category_data={},
            attributes=[],
            listing_types=[],
            sale_terms=[],
        )

    artifact = {
        "policy_hash": compiled["policy_hash"],
        "policy_summary": compiled["policy_summary"],
    }
    use_case._category_policy_cache[category_id] = artifact
    return artifact


__all__ = [
    "build_policy_attribute_rows",
    "get_policy_artifact",
    "get_policy_attributes",
    "get_policy_category_data",
]
