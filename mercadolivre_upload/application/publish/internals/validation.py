"""Validation helper functions for publish_product use case."""

from typing import Any

from .constants import (
    CRITICAL_ATTRIBUTE_WARNING_TOKENS,
    CRITICAL_VALIDATION_WARNING_TOKENS,
    RETRYABLE_VALIDATION_ERROR_TOKENS,
)


def get_critical_attribute_warnings(warnings: list[str]) -> list[str]:
    """Return attribute-processing warnings that should block publication."""
    critical: list[str] = []
    for warning in warnings:
        normalized = str(warning).lower()
        if any(token in normalized for token in CRITICAL_ATTRIBUTE_WARNING_TOKENS):
            critical.append(str(warning))
    return critical


def get_critical_validation_warnings(warnings: list[str]) -> list[str]:
    """Return API validation warnings that indicate payload/data loss."""
    critical: list[str] = []
    for warning in warnings:
        normalized = str(warning).lower()
        if any(token in normalized for token in CRITICAL_VALIDATION_WARNING_TOKENS):
            critical.append(str(warning))
    return critical


def classify_validation_cause(cause: dict[str, Any]) -> str:
    """Classify validation causes for deterministic decisioning."""
    cause_type = str(cause.get("type", "")).strip().lower()
    cause_code = str(cause.get("code", "")).strip().lower()
    cause_message = str(cause.get("message", "")).strip().lower()
    normalized_payload = f"{cause_code} {cause_message}"

    if cause_type == "warning":
        if any(token in normalized_payload for token in CRITICAL_VALIDATION_WARNING_TOKENS):
            return "critical_warning"
        return "informational_warning"

    if any(token in normalized_payload for token in RETRYABLE_VALIDATION_ERROR_TOKENS):
        return "retryable_error"
    return "blocking_error"


def build_validation_cause_taxonomy(causes: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Normalize raw validation causes into a persisted taxonomy."""
    taxonomy: list[dict[str, str]] = []
    for cause in causes:
        if not isinstance(cause, dict):
            continue
        raw_code = str(cause.get("code", "")).strip()
        taxonomy.append(
            {
                "type": str(cause.get("type", "")).strip().lower(),
                "code": raw_code.lower(),
                "message": str(cause.get("message", "")).strip(),
                "classification": classify_validation_cause(cause),
            }
        )
    return taxonomy
