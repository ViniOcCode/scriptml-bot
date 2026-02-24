"""Shipping policy helpers for publish flow composition."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ShippingPolicySettings:
    """Normalized shipping policy rollout configuration."""

    non_blocking_codes: set[str]
    mandatory_free_shipping_tags: set[str]
    enforce_mandatory_free_shipping: bool
    allow_runtime_tag_overrides: bool
    allow_runtime_free_shipping_override: bool


def resolve_shipping_policy_settings(
    config: Mapping[str, Any],
    *,
    default_mandatory_free_shipping_tags: set[str],
) -> ShippingPolicySettings:
    """Resolve shipping policy configuration from root/nested config layouts."""
    shipping_policy_config = config.get("shipping_policy")
    if not isinstance(shipping_policy_config, dict):
        shipping_config = config.get("shipping")
        if isinstance(shipping_config, dict):
            nested_policy = shipping_config.get("policy")
            if isinstance(nested_policy, dict):
                shipping_policy_config = nested_policy

    non_blocking_codes: set[str] = set()
    mandatory_free_shipping_tags = set(default_mandatory_free_shipping_tags)
    enforce_mandatory_free_shipping = True
    allow_runtime_tag_overrides = True
    allow_runtime_free_shipping_override = True

    if isinstance(shipping_policy_config, dict):
        raw_non_blocking_codes = shipping_policy_config.get("non_blocking_codes", [])
        if isinstance(raw_non_blocking_codes, str):
            raw_non_blocking_codes = [raw_non_blocking_codes]
        if isinstance(raw_non_blocking_codes, list):
            non_blocking_codes = {
                str(code).strip().lower() for code in raw_non_blocking_codes if str(code).strip()
            }

        raw_mandatory_tags = shipping_policy_config.get(
            "mandatory_free_shipping_tags",
            sorted(default_mandatory_free_shipping_tags),
        )
        if isinstance(raw_mandatory_tags, str):
            raw_mandatory_tags = [raw_mandatory_tags]
        if isinstance(raw_mandatory_tags, list):
            normalized_tags = {
                str(tag).strip().lower() for tag in raw_mandatory_tags if str(tag).strip()
            }
            if normalized_tags:
                mandatory_free_shipping_tags = normalized_tags

        raw_enforce_mandatory = shipping_policy_config.get("enforce_mandatory_free_shipping")
        if isinstance(raw_enforce_mandatory, bool):
            enforce_mandatory_free_shipping = raw_enforce_mandatory

        raw_allow_tag_overrides = shipping_policy_config.get("allow_runtime_tag_overrides")
        if isinstance(raw_allow_tag_overrides, bool):
            allow_runtime_tag_overrides = raw_allow_tag_overrides

        raw_allow_free_shipping_override = shipping_policy_config.get(
            "allow_runtime_free_shipping_override"
        )
        if isinstance(raw_allow_free_shipping_override, bool):
            allow_runtime_free_shipping_override = raw_allow_free_shipping_override

    return ShippingPolicySettings(
        non_blocking_codes=non_blocking_codes,
        mandatory_free_shipping_tags=mandatory_free_shipping_tags,
        enforce_mandatory_free_shipping=enforce_mandatory_free_shipping,
        allow_runtime_tag_overrides=allow_runtime_tag_overrides,
        allow_runtime_free_shipping_override=allow_runtime_free_shipping_override,
    )


def normalize_seller_tags(raw_tags: Any) -> list[str]:
    """Normalize seller tag payload from users/me style responses."""
    normalized_tags: list[str] = []
    if isinstance(raw_tags, list):
        for tag in raw_tags:
            tag_name = str(tag).strip().lower()
            if tag_name:
                normalized_tags.append(tag_name)
    elif isinstance(raw_tags, dict):
        for tag, enabled in raw_tags.items():
            if not enabled:
                continue
            tag_name = str(tag).strip().lower()
            if tag_name:
                normalized_tags.append(tag_name)
    return list(dict.fromkeys(normalized_tags))


def normalize_shipping_constraints(raw_constraints: Any) -> dict[str, Any]:
    """Normalize shipping constraints payload into a deterministic mapping."""
    if not isinstance(raw_constraints, dict):
        return {}
    return {str(key).strip(): value for key, value in raw_constraints.items() if str(key).strip()}


def coerce_shipping_bool(value: Any) -> bool | None:
    """Coerce supported shipping booleans into strict bool values."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y", "on"}:
            return True
        if normalized in {"false", "0", "no", "n", "off"}:
            return False
    return None
