"""Strict expansion contract for Mercado Livre user-product payload envelopes."""

from __future__ import annotations

from typing import Any

_LOCAL_ENVELOPE_FIELDS = frozenset(
    {
        "_meta",
        "description",
        "description_by_sku",
        "fiscal",
        "items",
        "model",
        "payload",
    }
)


def expand_effective_payloads(
    payload: dict[str, Any],
    upload_mode: str,
) -> list[dict[str, Any]]:
    """Return concrete provider payloads without leaking local envelope fields."""
    if upload_mode != "user_products":
        return [dict(payload)]

    base_payload = {
        key: value for key, value in payload.items() if key not in _LOCAL_ENVELOPE_FIELDS
    }
    raw_items = payload.get("payload")
    if not isinstance(raw_items, list):
        raw_items = payload.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        raise ValueError("user_products payload requires a non-empty items or payload array")

    expanded: list[dict[str, Any]] = []
    inherited_family_name = base_payload.get("family_name")
    for index, raw_item in enumerate(raw_items, start=1):
        if not isinstance(raw_item, dict):
            raise ValueError(f"user_products item[{index}] must be an object")
        item = {key: value for key, value in raw_item.items() if key not in _LOCAL_ENVELOPE_FIELDS}
        item_family_name = item.get("family_name")
        if (
            inherited_family_name is not None
            and item_family_name is not None
            and item_family_name != inherited_family_name
        ):
            raise ValueError(f"user_products item[{index}] family_name conflicts with its envelope")
        merged = dict(base_payload)
        merged.update(item)
        expanded.append(merged)
    return expanded


__all__ = ["expand_effective_payloads"]
