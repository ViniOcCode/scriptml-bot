"""Attribute helper logic for category resolver."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, Protocol


class AttributeCachePort(Protocol):
    """Protocol for attribute cache operations used by resolver helpers."""

    def get_attributes(self, category_id: str) -> list[dict[str, Any]] | None:
        """Return cached attributes when available."""
        ...

    def save_attributes(self, category_id: str, attributes: list[dict[str, Any]]) -> None:
        """Persist attributes in cache."""
        ...


def get_mandatory_attributes(attributes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Filter mandatory attributes."""
    return [attr for attr in attributes if attr.get("tags", {}).get("required")]


def get_all_attributes(
    category_id: str,
    get_category_attributes: Callable[[str], list[dict[str, Any]]],
    attribute_cache: AttributeCachePort | None = None,
    logger: logging.Logger | None = None,
) -> list[dict[str, Any]]:
    """Get all attributes for a category (cached)."""
    if attribute_cache:
        cached = attribute_cache.get_attributes(category_id)
        if cached is not None:
            if logger is not None:
                logger.debug(f"Using cached attributes for {category_id}")
            return cached

    attributes = get_category_attributes(category_id)

    if attribute_cache:
        attribute_cache.save_attributes(category_id, attributes)

    return attributes


def build_attribute_map(attributes: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Build name -> attribute mapping."""
    mapping = {}

    for attr in attributes:
        name = attr["name"].lower()
        mapping[name] = attr
        mapping[attr["id"].lower()] = attr

    return mapping


def get_conditional_attributes(
    category_id: str,
    item_context: dict[str, Any],
    get_category_conditional_attributes: Callable[[str, dict[str, Any]], Any],
) -> list[dict[str, Any]]:
    """Get conditional attributes for full item context."""
    try:
        result = get_category_conditional_attributes(category_id, item_context)
        if isinstance(result, dict) and "error" in result:
            return []
        if isinstance(result, str):
            return []
        if not isinstance(result, list):
            return []
        return result
    except Exception:
        return []


def get_all_attributes_with_conditionals(
    base_attributes: list[dict[str, Any]],
    conditional_attributes: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return base and conditional attributes together."""
    return base_attributes, conditional_attributes


def get_required_attributes(
    base_attributes: list[dict[str, Any]],
    conditional_attributes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return required base + conditional attributes."""
    required = [attr for attr in base_attributes if attr.get("tags", {}).get("required")]
    required_conditional = [
        attr for attr in conditional_attributes if attr.get("tags", {}).get("required")
    ]
    return required + required_conditional
