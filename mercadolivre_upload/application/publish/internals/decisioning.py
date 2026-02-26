"""Decisioning helpers extracted from publish orchestration use case."""

from __future__ import annotations

from typing import Any

from .constants import (
    SHIPPING_BLOCKING_CODE_TOKENS,
    SHIPPING_BLOCKING_MESSAGE_TOKENS,
    SHIPPING_EXPLICIT_NON_BLOCKING_CODES,
    SHIPPING_RETRYABLE_CODE_TOKENS,
    SHIPPING_RETRYABLE_MESSAGE_TOKENS,
)


def build_validation_decision(
    *,
    taxonomy: list[dict[str, str]],
    validation_decision_mode: str,
    strict_warning_gate_mode: str,
    strict_attribute_warnings: bool,
) -> dict[str, Any]:
    """Resolve deterministic strict/controlled decision from taxonomy."""
    classification_counts = {
        "blocking_error": 0,
        "retryable_error": 0,
        "critical_warning": 0,
        "informational_warning": 0,
    }
    classification_codes: dict[str, list[str]] = {
        "blocking_error": [],
        "retryable_error": [],
        "critical_warning": [],
        "informational_warning": [],
    }

    for cause in taxonomy:
        classification = str(cause.get("classification", "")).strip().lower()
        if classification not in classification_counts:
            continue
        classification_counts[classification] += 1
        code = str(cause.get("code", "")).strip().lower()
        if code and code not in classification_codes[classification]:
            classification_codes[classification].append(code)

    action = "allow"
    reason = "no_validation_causes"
    if classification_counts["blocking_error"] > 0:
        action = "block"
        reason = "blocking_error"
    elif classification_counts["retryable_error"] > 0:
        if validation_decision_mode == "controlled":
            action = "retry"
            reason = "retryable_error_controlled"
        else:
            action = "block"
            reason = "retryable_error_strict"
    elif classification_counts["critical_warning"] > 0:
        if validation_decision_mode == "strict" and strict_attribute_warnings:
            action = "block"
            reason = "critical_warning_strict"
        else:
            action = "allow"
            reason = "critical_warning_allowed"
    elif classification_counts["informational_warning"] > 0:
        action = "allow"
        reason = "informational_warning"

    return {
        "mode": validation_decision_mode,
        "strict_warning_gate_mode": strict_warning_gate_mode,
        "strict_attribute_warnings": strict_attribute_warnings,
        "action": action,
        "reason": reason,
        "classification_counts": classification_counts,
        "classification_codes": classification_codes,
    }


def is_shipping_cause(cause_code: str, cause_message: str) -> bool:
    """Check whether a cause row is shipping-related."""
    normalized_code = cause_code.lower()
    normalized_message = cause_message.lower()
    return (
        "shipping" in normalized_code
        or "shipping" in normalized_message
        or "envio" in normalized_message
    )


def classify_shipping_cause(
    *,
    cause_code: str,
    cause_message: str,
    shipping_non_blocking_codes: set[str],
) -> str:
    """Classify shipping causes into blocking/retryable/unknown buckets."""
    normalized_code = cause_code.lower()
    normalized_message = cause_message.lower()

    if (
        normalized_code in SHIPPING_EXPLICIT_NON_BLOCKING_CODES
        or "mandatory free shipping added" in normalized_message
    ):
        return "unknown"

    if any(
        normalized_code == code or normalized_code.startswith(f"{code}.")
        for code in shipping_non_blocking_codes
    ):
        return "unknown"
    if any(token in normalized_code for token in SHIPPING_BLOCKING_CODE_TOKENS):
        return "blocking"
    if any(token in normalized_code for token in SHIPPING_RETRYABLE_CODE_TOKENS):
        return "retryable"
    if any(token in normalized_message for token in SHIPPING_BLOCKING_MESSAGE_TOKENS):
        return "blocking"
    if any(token in normalized_message for token in SHIPPING_RETRYABLE_MESSAGE_TOKENS):
        return "retryable"
    return "unknown"


def register_shipping_causes(
    causes: list[Any],
    *,
    stage: str,
    current_shipping_policy: dict[str, Any] | None,
    shipping_non_blocking_codes: set[str],
) -> list[dict[str, str]]:
    """Extract and store shipping-cause classification metadata for current item."""
    decisions: list[dict[str, str]] = []
    for raw_cause in causes:
        if not isinstance(raw_cause, dict):
            continue
        cause_code = str(raw_cause.get("code", "") or "").strip()
        cause_message = str(raw_cause.get("message", "") or "").strip()
        if not is_shipping_cause(cause_code, cause_message):
            continue
        decision = {
            "stage": stage,
            "type": str(raw_cause.get("type", "") or "").strip().lower(),
            "code": cause_code,
            "message": cause_message,
            "classification": classify_shipping_cause(
                cause_code=cause_code,
                cause_message=cause_message,
                shipping_non_blocking_codes=shipping_non_blocking_codes,
            ),
        }
        decisions.append(decision)

    if decisions and current_shipping_policy is not None:
        existing = current_shipping_policy.setdefault("cause_decisions", [])
        if isinstance(existing, list):
            known = {
                (
                    str(row.get("stage", "")),
                    str(row.get("type", "")),
                    str(row.get("code", "")),
                    str(row.get("message", "")),
                )
                for row in existing
                if isinstance(row, dict)
            }
            for decision in decisions:
                key = (
                    decision["stage"],
                    decision["type"],
                    decision["code"],
                    decision["message"],
                )
                if key in known:
                    continue
                existing.append(decision)
                known.add(key)
            current_shipping_policy["has_blocking_cause"] = any(
                isinstance(row, dict) and row.get("classification") == "blocking"
                for row in existing
            )
    return decisions


def extract_exception_error_detail(error: Exception) -> dict[str, Any] | None:
    """Return parsed API error payload when available."""
    response = getattr(error, "response", None)
    if response is None:
        return None
    response_json = getattr(response, "json", None)
    if not callable(response_json):
        return None
    try:
        payload = response_json()
    except (TypeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def extract_exception_response_excerpt(error: Exception, *, limit: int = 200) -> str | None:
    """Return bounded response text excerpt for non-JSON API failures."""
    response = getattr(error, "response", None)
    if response is None:
        return None
    response_text = getattr(response, "text", None)
    if not isinstance(response_text, str):
        return None
    excerpt = response_text[:limit].strip()
    return excerpt or None
