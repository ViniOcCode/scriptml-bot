"""Metadata helper logic for category resolver."""

from __future__ import annotations

import logging
from typing import Any

from ..attribute_metadata import AttributeMeta


def get_attribute_metadata(
    resolver: Any,
    category_id: str,
    logger: logging.Logger,
) -> list[AttributeMeta]:
    """Get normalized attribute metadata for a category."""
    raw_attributes: list[dict[str, Any]] | None = None
    if resolver._attribute_cache:
        cached = resolver._attribute_cache.get_attributes(category_id)
        if cached is not None:
            logger.debug(f"Using cached metadata for {category_id}")
            raw_attributes = cached

    if raw_attributes is None:
        raw_attributes = resolver._api.get_category_attributes(category_id)

    technical_specs = {}
    if hasattr(resolver._api, "get_category_technical_specs"):
        try:
            technical_specs = resolver._api.get_category_technical_specs(category_id)
        except Exception:
            technical_specs = {}

    if technical_specs:
        spec_map = resolver._extract_technical_spec_attributes(technical_specs)
        if spec_map:
            for attr in raw_attributes:
                attr_id = attr.get("id")
                if not isinstance(attr_id, str):
                    continue
                spec = spec_map.get(attr_id)
                if spec:
                    resolver._merge_technical_spec(attr, spec)

    metadata = []
    for attr in raw_attributes:
        try:
            meta = AttributeMeta.from_ml_api(attr)
            metadata.append(meta)
        except (KeyError, TypeError) as error:
            logger.warning(f"Failed to parse attribute: {attr.get('id', 'unknown')}: {error}")

    if resolver._attribute_cache and raw_attributes is not None:
        resolver._attribute_cache.save_attributes(category_id, raw_attributes)

    return metadata
