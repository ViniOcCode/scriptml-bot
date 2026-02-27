"""Runtime setting normalization for publish use-case wiring."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from ...shipping_policy import resolve_shipping_policy_settings
from .constants import (
    API_VALIDATION_REPAIR_DETECT_MODES,
    API_VALIDATION_REPAIR_SCOPES,
    DEFAULT_MANDATORY_FREE_SHIPPING_TAGS,
    FLOW_BLOCKED_BEHAVIORS,
    IMAGE_DIAGNOSTIC_GATE_MODES,
    STRICT_WARNING_GATE_MODES,
    VALIDATION_DECISION_MODES,
)


@dataclass(frozen=True)
class PublishRuntimeSettings:
    """Normalized runtime flags consumed by PublishProductUseCase."""

    strict_warning_gate_mode: str
    strict_attribute_warnings: bool
    validation_decision_mode: str
    flow_user_products_enabled: bool
    flow_blocked_behavior: str
    image_diagnostics_gate_mode: str
    shipping_non_blocking_codes: set[str]
    shipping_mandatory_free_shipping_tags: set[str]
    shipping_enforce_mandatory_free_shipping: bool
    shipping_allow_runtime_tag_overrides: bool
    shipping_allow_runtime_free_shipping_override: bool
    api_validation_repair_enabled: bool
    api_validation_repair_scope: str
    api_validation_repair_max_attempts: int
    api_validation_repair_detect_mode: str
    api_validation_repair_drop_required_attributes: bool


def resolve_runtime_settings(
    config: dict[str, Any] | None,
    *,
    logger: logging.Logger,
) -> PublishRuntimeSettings:
    """Resolve publish runtime settings from config with normalized defaults."""
    normalized_config = config or {}

    strict_warning_gate_mode = normalized_config.get("strict_warning_gate_mode")
    normalized_strict_mode: str | None = None
    if isinstance(strict_warning_gate_mode, str) and strict_warning_gate_mode.strip():
        normalized_strict_mode = strict_warning_gate_mode.strip().lower()
        if normalized_strict_mode not in STRICT_WARNING_GATE_MODES:
            logger.warning(
                "Invalid strict warning gate mode '%s'; falling back to enforce.",
                normalized_strict_mode,
            )
            normalized_strict_mode = "enforce"

    strict_warnings = normalized_config.get("strict_attribute_warnings")
    if normalized_strict_mode is not None:
        strict_warning_mode = normalized_strict_mode
        strict_attribute_warnings = normalized_strict_mode == "enforce"
    else:
        strict_attribute_warnings = True if strict_warnings is None else bool(strict_warnings)
        strict_warning_mode = "enforce" if strict_attribute_warnings else "report_only"

    raw_validation_mode = normalized_config.get("validation_decision_mode", "strict")
    if isinstance(raw_validation_mode, str) and raw_validation_mode.strip():
        validation_mode = raw_validation_mode.strip().lower()
    else:
        validation_mode = "strict"
    if validation_mode not in VALIDATION_DECISION_MODES:
        logger.warning(
            "Invalid validation decision mode '%s'; falling back to strict.",
            validation_mode,
        )
        validation_mode = "strict"

    flow_user_products_enabled = True
    flow_blocked_behavior = "fail"
    flow_config = normalized_config.get("flow_routing", {})
    if isinstance(flow_config, dict):
        raw_user_products_enabled = flow_config.get(
            "user_products_enabled",
            flow_config.get("enable_user_products"),
        )
        if raw_user_products_enabled is not None:
            flow_user_products_enabled = bool(raw_user_products_enabled)
        raw_blocked_behavior = flow_config.get(
            "blocked_behavior",
            flow_config.get("on_blocked"),
        )
        if isinstance(raw_blocked_behavior, str) and raw_blocked_behavior.strip():
            normalized_behavior = raw_blocked_behavior.strip().lower()
            if normalized_behavior in FLOW_BLOCKED_BEHAVIORS:
                flow_blocked_behavior = normalized_behavior
            else:
                logger.warning(
                    "Invalid flow blocked behavior '%s'; falling back to fail.",
                    normalized_behavior,
                )

    image_diagnostics_gate_mode = "enforce"
    image_diagnostics_config = normalized_config.get("image_diagnostics")
    normalized_diag_mode: str | None = None
    if isinstance(image_diagnostics_config, dict):
        raw_diag_mode = image_diagnostics_config.get("gate_mode")
        if raw_diag_mode is None and "enabled" in image_diagnostics_config:
            raw_diag_mode = (
                "enforce" if bool(image_diagnostics_config.get("enabled")) else "disabled"
            )
        if raw_diag_mode is None:
            raw_diag_mode = image_diagnostics_config.get("mode")
        if isinstance(raw_diag_mode, str) and raw_diag_mode.strip():
            normalized_diag_mode = raw_diag_mode.strip().lower()
    elif isinstance(image_diagnostics_config, str) and image_diagnostics_config.strip():
        normalized_diag_mode = image_diagnostics_config.strip().lower()

    if normalized_diag_mode in {"off", "skip"}:
        normalized_diag_mode = "disabled"
    elif normalized_diag_mode in {"report", "observe"}:
        normalized_diag_mode = "report_only"
    elif normalized_diag_mode in {"strict", "enabled", "on"}:
        normalized_diag_mode = "enforce"

    if normalized_diag_mode:
        if normalized_diag_mode in IMAGE_DIAGNOSTIC_GATE_MODES:
            image_diagnostics_gate_mode = normalized_diag_mode
        else:
            logger.warning(
                "Invalid image diagnostics gate mode '%s'; falling back to enforce.",
                normalized_diag_mode,
            )

    shipping_policy_settings = resolve_shipping_policy_settings(
        normalized_config,
        default_mandatory_free_shipping_tags=DEFAULT_MANDATORY_FREE_SHIPPING_TAGS,
    )

    repair_config = normalized_config.get("api_validation_repair", {})
    if not isinstance(repair_config, dict):
        repair_config = {}

    api_validation_repair_enabled = bool(repair_config.get("enabled", True))

    raw_repair_scope = repair_config.get("scope", "all")
    if isinstance(raw_repair_scope, str) and raw_repair_scope.strip():
        api_validation_repair_scope = raw_repair_scope.strip().lower()
    else:
        api_validation_repair_scope = "all"
    if api_validation_repair_scope not in API_VALIDATION_REPAIR_SCOPES:
        logger.warning(
            "Invalid api_validation_repair scope '%s'; falling back to all.",
            api_validation_repair_scope,
        )
        api_validation_repair_scope = "all"

    raw_max_attempts = repair_config.get("max_attempts", 3)
    try:
        api_validation_repair_max_attempts = int(raw_max_attempts)
    except (TypeError, ValueError):
        logger.warning(
            "Invalid api_validation_repair max_attempts '%s'; falling back to 3.",
            raw_max_attempts,
        )
        api_validation_repair_max_attempts = 3
    if api_validation_repair_max_attempts < 1:
        logger.warning(
            "api_validation_repair max_attempts must be >= 1; falling back to 3.",
        )
        api_validation_repair_max_attempts = 3

    raw_detect_mode = repair_config.get("detect_mode", "conservative")
    if isinstance(raw_detect_mode, str) and raw_detect_mode.strip():
        api_validation_repair_detect_mode = raw_detect_mode.strip().lower()
    else:
        api_validation_repair_detect_mode = "conservative"
    if api_validation_repair_detect_mode not in API_VALIDATION_REPAIR_DETECT_MODES:
        logger.warning(
            "Invalid api_validation_repair detect_mode '%s'; falling back to conservative.",
            api_validation_repair_detect_mode,
        )
        api_validation_repair_detect_mode = "conservative"

    api_validation_repair_drop_required_attributes = bool(
        repair_config.get("drop_required_attributes", False)
    )

    return PublishRuntimeSettings(
        strict_warning_gate_mode=strict_warning_mode,
        strict_attribute_warnings=strict_attribute_warnings,
        validation_decision_mode=validation_mode,
        flow_user_products_enabled=flow_user_products_enabled,
        flow_blocked_behavior=flow_blocked_behavior,
        image_diagnostics_gate_mode=image_diagnostics_gate_mode,
        shipping_non_blocking_codes=set(shipping_policy_settings.non_blocking_codes),
        shipping_mandatory_free_shipping_tags=set(
            shipping_policy_settings.mandatory_free_shipping_tags
        ),
        shipping_enforce_mandatory_free_shipping=(
            shipping_policy_settings.enforce_mandatory_free_shipping
        ),
        shipping_allow_runtime_tag_overrides=shipping_policy_settings.allow_runtime_tag_overrides,
        shipping_allow_runtime_free_shipping_override=(
            shipping_policy_settings.allow_runtime_free_shipping_override
        ),
        api_validation_repair_enabled=api_validation_repair_enabled,
        api_validation_repair_scope=api_validation_repair_scope,
        api_validation_repair_max_attempts=api_validation_repair_max_attempts,
        api_validation_repair_detect_mode=api_validation_repair_detect_mode,
        api_validation_repair_drop_required_attributes=(
            api_validation_repair_drop_required_attributes
        ),
    )
