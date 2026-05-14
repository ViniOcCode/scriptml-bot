"""Validation helper functions for publish flows."""

from dataclasses import dataclass, field
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


@dataclass(frozen=True)
class MercadoLivreValidationCause:
    """Normalized Mercado Livre validation cause."""

    type: str
    code: str
    message: str
    department: str = ""
    references: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    def to_report_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "type": self.type,
            "code": self.code,
            "message": self.message,
        }
        if self.department:
            payload["department"] = self.department
        if self.references:
            payload["references"] = list(self.references)
        return payload


@dataclass(frozen=True)
class MercadoLivreValidationResult:
    """Shared validation classification for Mercado Livre item validation."""

    status: str
    should_block: bool
    warning_causes: list[MercadoLivreValidationCause] = field(default_factory=list)
    error_causes: list[MercadoLivreValidationCause] = field(default_factory=list)
    raw_response: Any | None = None
    message: str | None = None

    @property
    def all_causes(self) -> list[MercadoLivreValidationCause]:
        return [*self.warning_causes, *self.error_causes]

    def warning_messages(self) -> list[str]:
        return [format_validation_cause_for_message(cause) for cause in self.warning_causes]

    def error_messages(self) -> list[str]:
        if self.error_causes:
            return [format_validation_cause_for_message(cause) for cause in self.error_causes]
        return [self.message] if self.message else []

    def to_report_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "status": self.status,
            "should_block": self.should_block,
            "warnings": [cause.to_report_dict() for cause in self.warning_causes],
            "errors": [cause.to_report_dict() for cause in self.error_causes],
        }
        if self.message:
            payload["message"] = self.message
        if self.raw_response is not None:
            payload["raw_response"] = self.raw_response
        return payload


def _normalize_references(raw_references: Any) -> list[str]:
    if isinstance(raw_references, str):
        value = raw_references.strip()
        return [value] if value else []
    if not isinstance(raw_references, list):
        return []
    return [str(reference).strip() for reference in raw_references if str(reference).strip()]


def normalize_validation_cause(cause: dict[str, Any]) -> MercadoLivreValidationCause:
    """Normalize a raw Mercado Livre cause row while preserving report details."""
    cause_type = str(cause.get("type", "") or "").strip().lower()
    return MercadoLivreValidationCause(
        type=cause_type,
        code=str(cause.get("code", "") or "").strip(),
        message=str(cause.get("message", "") or "").strip(),
        department=str(cause.get("department", "") or "").strip(),
        references=_normalize_references(cause.get("references")),
        raw=dict(cause),
    )


def _extract_raw_causes(validation: Any) -> tuple[list[dict[str, Any]], bool]:
    if not isinstance(validation, dict):
        return [], False
    raw_causes = validation.get("cause", validation.get("causes", []))
    if isinstance(raw_causes, dict):
        return [raw_causes], True
    if isinstance(raw_causes, list):
        return [cause for cause in raw_causes if isinstance(cause, dict)], True
    return [], False


def classify_mercado_livre_validation_response(
    validation: Any,
) -> MercadoLivreValidationResult:
    """Classify Mercado Livre validation response using cause.type as authority.

    Empty success responses represent /items/validate 204 No Content. Validation
    errors without a clear cause list remain blocking conservatively.
    """
    if validation is None or validation == {}:
        return MercadoLivreValidationResult(
            status="validation_passed",
            should_block=False,
            raw_response=validation,
        )

    if not isinstance(validation, dict):
        return MercadoLivreValidationResult(
            status="validation_failed",
            should_block=True,
            raw_response=validation,
            message=str(validation),
        )

    raw_causes, has_cause_shape = _extract_raw_causes(validation)
    causes = [normalize_validation_cause(cause) for cause in raw_causes]
    warning_causes = [cause for cause in causes if cause.type == "warning"]
    error_causes = [cause for cause in causes if cause.type == "error"]
    unknown_causes = [cause for cause in causes if cause.type not in {"warning", "error"}]

    if error_causes:
        return MercadoLivreValidationResult(
            status="validation_failed",
            should_block=True,
            warning_causes=warning_causes,
            error_causes=[*error_causes, *unknown_causes],
            raw_response=validation,
        )

    if unknown_causes:
        return MercadoLivreValidationResult(
            status="validation_failed",
            should_block=True,
            warning_causes=warning_causes,
            error_causes=unknown_causes,
            raw_response=validation,
            message="Validation response contained causes without a clear type.",
        )

    if warning_causes:
        return MercadoLivreValidationResult(
            status="validation_passed_with_warnings",
            should_block=False,
            warning_causes=warning_causes,
            raw_response=validation,
        )

    error_value = validation.get("error")
    message_value = validation.get("message")
    status_value = validation.get("status")
    looks_like_validation_error = bool(error_value or message_value or status_value)
    if looks_like_validation_error or has_cause_shape:
        return MercadoLivreValidationResult(
            status="validation_failed",
            should_block=True,
            raw_response=validation,
            message=str(message_value or error_value or "Validation failed without causes."),
        )

    return MercadoLivreValidationResult(
        status="validation_passed",
        should_block=False,
        raw_response=validation,
    )


def format_validation_cause_for_message(cause: MercadoLivreValidationCause) -> str:
    """Format a normalized cause for CLI/report warning and error text."""
    parts = [f"[{cause.code or '?'}]"]
    if cause.department:
        parts.append(f"department={cause.department}")
    parts.append(cause.message or str(cause.raw))
    if cause.references:
        parts.append(f"references={', '.join(cause.references)}")
    return " | ".join(parts)


def classify_validation_cause(cause: dict[str, Any]) -> str:
    """Classify validation causes for deterministic decisioning."""
    cause_type = str(cause.get("type", "")).strip().lower()
    cause_code = str(cause.get("code", "")).strip().lower()
    cause_message = str(cause.get("message", "")).strip().lower()
    normalized_payload = f"{cause_code} {cause_message}"

    if cause_type == "warning":
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
