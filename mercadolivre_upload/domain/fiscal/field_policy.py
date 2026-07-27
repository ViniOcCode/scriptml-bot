"""Fiscal field requirement and API-boundary policy (config-driven)."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import yaml

from mercadolivre_upload.shared.utils.config_loader import FISCAL_CONFIG_PATH, load_yaml_config

_APP_FISCAL_CONFIG_FALLBACK_PATH = Path(__file__).resolve().parents[3] / "config/fiscal_config.yaml"


def _load_fiscal_config() -> dict[str, Any]:
    try:
        return load_yaml_config(FISCAL_CONFIG_PATH, fallback=_APP_FISCAL_CONFIG_FALLBACK_PATH)
    except (OSError, yaml.YAMLError):
        return {}


def _is_blank_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip().lower() in {"", "nan", "none", "null"}
    return isinstance(value, float) and math.isnan(value)


def _parse_float(value: Any) -> float | None:
    if _is_blank_value(value):
        return None
    if isinstance(value, (int, float)):
        numeric = float(value)
        return None if math.isnan(numeric) else numeric
    try:
        numeric = float(str(value).strip().replace(",", "."))
    except ValueError:
        return None
    return None if math.isnan(numeric) else numeric


# Top-level fiscal model fields always required for publisher validation.
_ROOT_REQUIRED_FISCAL_FIELDS: frozenset[str] = frozenset({"sku", "title", "type"})

# Tax fields required for submission (also declared in fiscal_fields with required: true).
_ROOT_REQUIRED_TAX_FIELDS: frozenset[str] = frozenset({"ncm", "origin_type", "origin_detail"})


def load_optional_fiscal_fields() -> frozenset[str]:
    """Return fiscal field names marked optional in config/fiscal_config.yaml."""
    config = _load_fiscal_config()
    fields = config.get("fiscal_fields", {})
    optional: set[str] = set()
    if not isinstance(fields, dict):
        return frozenset()
    for name, meta in fields.items():
        if isinstance(meta, dict) and not meta.get("required", False):
            optional.add(str(name))
    return frozenset(optional)


def load_required_fiscal_fields() -> frozenset[str]:
    """Return publisher-required fiscal fields (root + config-required minus optional)."""
    optional = load_optional_fiscal_fields()
    config = _load_fiscal_config()
    fields = config.get("fiscal_fields", {})
    from_config: set[str] = set()
    if isinstance(fields, dict):
        for name, meta in fields.items():
            if isinstance(meta, dict) and meta.get("required", False):
                from_config.add(str(name))
    required = _ROOT_REQUIRED_FISCAL_FIELDS | _ROOT_REQUIRED_TAX_FIELDS | from_config
    return frozenset(required - optional)


def is_fiscal_field_required(field_name: str) -> bool:
    """Return True when *field_name* must be present for fiscal submission."""
    return field_name in load_required_fiscal_fields()


def taxpayer_type_for_document(document_type: str | None) -> str | None:
    """Resolve the allowed fiscal owner type for an authenticated document."""
    normalized = str(document_type or "").strip().upper()
    if not normalized:
        return None
    config = _load_fiscal_config()
    policy = config.get("taxpayer_policy", {})
    mappings = policy.get("document_types", {}) if isinstance(policy, dict) else {}
    if not isinstance(mappings, dict):
        return None
    value = mappings.get(normalized)
    return str(value).strip().lower() if isinstance(value, str) and value.strip() else None


def normalize_fiscal_cost(value: Any) -> float | None:
    """Normalize fiscal cost for validation and API boundary.

    Blank, null, zero, and non-positive values are treated as unset (None).
    Only explicit positive numeric costs are preserved.
    """
    parsed = _parse_float(value)
    if parsed is None or parsed <= 0 or math.isnan(parsed):
        return None
    return parsed


def fiscal_cost_for_api_payload(cost: float | None) -> float | None:
    """Return cost for outbound fiscal_information body, or None to omit the field."""
    return normalize_fiscal_cost(cost)
