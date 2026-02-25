"""Identifier/GTIN helpers extracted from publish use case orchestration."""

from __future__ import annotations

import re
from typing import Any

from mercadolivre_upload.shared.utils.text_utils import PortugueseTextNormalizer

from .publish_product_constants import IDENTIFIER_EMPTY_TOKENS


def normalize_identifier_text(value: Any) -> str | None:
    """Normalize a generic identifier/fallback value."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    normalized_text = PortugueseTextNormalizer.normalize(text)
    if normalized_text in IDENTIFIER_EMPTY_TOKENS:
        return None
    return text


def normalize_gtin_value(value: Any) -> str | None:
    """Normalize GTIN into digits-only representation."""
    text = normalize_identifier_text(value)
    if text is None:
        return None
    digits_only = re.sub(r"\D", "", text)
    return digits_only or None


def collect_identifier_state(attributes: Any) -> dict[str, Any]:
    """Collect and normalize GTIN/EMPTY_GTIN_REASON state from attribute payload."""
    state: dict[str, Any] = {
        "gtin": None,
        "gtin_attribute_present": False,
        "empty_gtin_reason_attribute_present": False,
        "empty_gtin_reason_value_id": None,
        "empty_gtin_reason_value_name": None,
        "has_identifier_attribute": False,
    }
    if not isinstance(attributes, list):
        return state

    for attribute in attributes:
        if not isinstance(attribute, dict):
            continue
        attribute_id = attribute.get("id")
        if not isinstance(attribute_id, str) or not attribute_id:
            continue
        normalized_id = attribute_id.strip().upper()

        if normalized_id == "GTIN":
            state["gtin_attribute_present"] = True
            candidate_raw = attribute.get("value_name")
            if candidate_raw in (None, ""):
                candidate_raw = attribute.get("value_id")
            normalized_gtin = normalize_gtin_value(candidate_raw)
            if normalized_gtin:
                state["gtin"] = normalized_gtin
                attribute["value_name"] = normalized_gtin
                if "value_id" in attribute:
                    attribute["value_id"] = normalized_gtin
            continue

        if normalized_id != "EMPTY_GTIN_REASON":
            continue

        state["empty_gtin_reason_attribute_present"] = True
        normalized_reason_id = normalize_identifier_text(attribute.get("value_id"))
        normalized_reason_name = normalize_identifier_text(attribute.get("value_name"))
        if normalized_reason_id is not None:
            state["empty_gtin_reason_value_id"] = normalized_reason_id
            attribute["value_id"] = normalized_reason_id
        if normalized_reason_name is not None:
            state["empty_gtin_reason_value_name"] = normalized_reason_name
            attribute["value_name"] = normalized_reason_name

    state["has_identifier_attribute"] = bool(
        state["gtin_attribute_present"] or state["empty_gtin_reason_attribute_present"]
    )
    return state


def select_empty_gtin_reason(
    *,
    default_value_name: str,
    allowed_reason_ids: set[str],
    allowed_reason_names: list[str],
) -> tuple[str | None, str | None, str | None]:
    """Select EMPTY_GTIN_REASON default with deterministic schema-aware fallback."""
    normalized_reason_name_map: dict[str, str] = {}
    for reason_name in sorted(set(allowed_reason_names)):
        normalized_reason_name = PortugueseTextNormalizer.normalize(reason_name)
        if normalized_reason_name:
            normalized_reason_name_map.setdefault(normalized_reason_name, reason_name)

    selected_reason_id: str | None = None
    if len(allowed_reason_ids) == 1:
        selected_reason_id = next(iter(allowed_reason_ids))
    elif allowed_reason_ids and not normalized_reason_name_map:
        selected_reason_id = sorted(allowed_reason_ids)[0]

    selected_reason_name: str | None = default_value_name
    warning_message: str | None = None
    has_allowed_reasons = bool(allowed_reason_ids or normalized_reason_name_map)
    if has_allowed_reasons:
        normalized_default_name = PortugueseTextNormalizer.normalize(default_value_name)
        if normalized_default_name in normalized_reason_name_map:
            selected_reason_name = normalized_reason_name_map[normalized_default_name]
        elif normalized_reason_name_map:
            selected_reason_name = normalized_reason_name_map[sorted(normalized_reason_name_map)[0]]
            warning_message = (
                "Configured EMPTY_GTIN_REASON default is not allowed by schema metadata; "
                "using deterministic allowed fallback."
            )
        else:
            selected_reason_name = None
            warning_message = (
                "Configured EMPTY_GTIN_REASON default cannot be validated against schema "
                "names; using deterministic allowed value_id fallback."
            )

    return selected_reason_id, selected_reason_name, warning_message


def is_valid_empty_gtin_reason(
    *,
    state: dict[str, Any],
    allowed_reason_ids: set[str],
    allowed_reason_names: set[str],
) -> bool:
    """Validate fallback reason against local schema metadata when available."""
    reason_id = state.get("empty_gtin_reason_value_id")
    reason_name = state.get("empty_gtin_reason_value_name")
    has_reason = bool(reason_id or reason_name)
    if not has_reason:
        return False

    if not allowed_reason_ids and not allowed_reason_names:
        return True
    if isinstance(reason_id, str) and reason_id in allowed_reason_ids:
        return True
    if isinstance(reason_name, str):
        normalized_name = PortugueseTextNormalizer.normalize(reason_name)
        if normalized_name in allowed_reason_names:
            return True
    return False


def validate_identifier_state(
    *,
    scope: str,
    state: dict[str, Any],
    gtin_required: bool,
    fallback_reason_available: bool,
    enforce_identifier_coverage: bool,
    allowed_reason_ids: set[str],
    allowed_reason_names: set[str],
) -> list[str]:
    """Validate identifier coherence for item/variation scope."""
    violations: list[str] = []
    gtin = state.get("gtin")
    has_gtin = isinstance(gtin, str) and bool(gtin)
    has_reason = bool(
        state.get("empty_gtin_reason_value_id") or state.get("empty_gtin_reason_value_name")
    )

    if has_gtin and isinstance(gtin, str) and not (8 <= len(gtin) <= 14):
        violations.append(f"{scope} GTIN must contain between 8 and 14 digits")

    if enforce_identifier_coverage and not has_gtin and not has_reason:
        violations.append(f"{scope} missing GTIN/EMPTY_GTIN_REASON identifier coverage")
        return violations

    if gtin_required and not has_gtin:
        if fallback_reason_available:
            if not has_reason:
                violations.append(f"{scope} missing GTIN; EMPTY_GTIN_REASON is required")
                return violations
            if not is_valid_empty_gtin_reason(
                state=state,
                allowed_reason_ids=allowed_reason_ids,
                allowed_reason_names=allowed_reason_names,
            ):
                violations.append(f"{scope} has invalid EMPTY_GTIN_REASON metadata")
        else:
            violations.append(f"{scope} missing GTIN required by schema contract")
        return violations

    if has_reason and not is_valid_empty_gtin_reason(
        state=state,
        allowed_reason_ids=allowed_reason_ids,
        allowed_reason_names=allowed_reason_names,
    ):
        violations.append(f"{scope} has invalid EMPTY_GTIN_REASON metadata")

    return violations
