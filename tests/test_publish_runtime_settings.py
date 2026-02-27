"""Tests for publish runtime setting normalization."""

from __future__ import annotations

import logging

from mercadolivre_upload.application.publish.internals.runtime_settings import (
    resolve_runtime_settings,
)


def test_resolve_runtime_settings_defaults() -> None:
    settings = resolve_runtime_settings({}, logger=logging.getLogger(__name__))

    assert settings.strict_warning_gate_mode == "enforce"
    assert settings.strict_attribute_warnings is True
    assert settings.validation_decision_mode == "strict"
    assert settings.flow_user_products_enabled is True
    assert settings.flow_blocked_behavior == "fail"
    assert settings.image_diagnostics_gate_mode == "enforce"
    assert settings.shipping_non_blocking_codes == set()
    assert settings.shipping_mandatory_free_shipping_tags == {"mandatory_free_shipping"}
    assert settings.shipping_enforce_mandatory_free_shipping is True
    assert settings.shipping_allow_runtime_tag_overrides is True
    assert settings.shipping_allow_runtime_free_shipping_override is True
    assert settings.api_validation_repair_enabled is True
    assert settings.api_validation_repair_scope == "all"
    assert settings.api_validation_repair_max_attempts == 3
    assert settings.api_validation_repair_detect_mode == "conservative"
    assert settings.api_validation_repair_drop_required_attributes is False


def test_resolve_runtime_settings_accepts_legacy_aliases() -> None:
    config = {
        "strict_warning_gate_mode": "REPORT_ONLY",
        "validation_decision_mode": "CONTROLLED",
        "flow_routing": {
            "enable_user_products": False,
            "on_blocked": "fallback_legacy",
        },
        "image_diagnostics": {"mode": "observe"},
        "shipping_policy": {
            "non_blocking_codes": ["ITEM.SHIPPING.MANDATORY_FREE_SHIPPING"],
            "mandatory_free_shipping_tags": ["TagOne", "TagTwo"],
            "enforce_mandatory_free_shipping": False,
            "allow_runtime_tag_overrides": False,
            "allow_runtime_free_shipping_override": False,
        },
        "api_validation_repair": {
            "enabled": False,
            "scope": "UPLOAD_ONLY",
            "max_attempts": 4,
            "detect_mode": "AGGRESSIVE",
            "drop_required_attributes": True,
        },
    }

    settings = resolve_runtime_settings(config, logger=logging.getLogger(__name__))

    assert settings.strict_warning_gate_mode == "report_only"
    assert settings.strict_attribute_warnings is False
    assert settings.validation_decision_mode == "controlled"
    assert settings.flow_user_products_enabled is False
    assert settings.flow_blocked_behavior == "fallback_legacy"
    assert settings.image_diagnostics_gate_mode == "report_only"
    assert settings.shipping_non_blocking_codes == {"item.shipping.mandatory_free_shipping"}
    assert settings.shipping_mandatory_free_shipping_tags == {"tagone", "tagtwo"}
    assert settings.shipping_enforce_mandatory_free_shipping is False
    assert settings.shipping_allow_runtime_tag_overrides is False
    assert settings.shipping_allow_runtime_free_shipping_override is False
    assert settings.api_validation_repair_enabled is False
    assert settings.api_validation_repair_scope == "upload_only"
    assert settings.api_validation_repair_max_attempts == 4
    assert settings.api_validation_repair_detect_mode == "aggressive"
    assert settings.api_validation_repair_drop_required_attributes is True


def test_resolve_runtime_settings_invalid_values_fall_back_to_safe_defaults() -> None:
    config = {
        "strict_warning_gate_mode": "unknown",
        "validation_decision_mode": "invalid",
        "flow_routing": {"blocked_behavior": "oops"},
        "image_diagnostics": "skip",
        "api_validation_repair": {
            "scope": "somewhere",
            "max_attempts": 0,
            "detect_mode": "unknown",
        },
    }

    settings = resolve_runtime_settings(config, logger=logging.getLogger(__name__))

    assert settings.strict_warning_gate_mode == "enforce"
    assert settings.strict_attribute_warnings is True
    assert settings.validation_decision_mode == "strict"
    assert settings.flow_blocked_behavior == "fail"
    assert settings.image_diagnostics_gate_mode == "disabled"
    assert settings.api_validation_repair_scope == "all"
    assert settings.api_validation_repair_max_attempts == 3
    assert settings.api_validation_repair_detect_mode == "conservative"
