"""API-driven attribute pruning and revalidation helpers."""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

_ATTRIBUTE_ID_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")
_ATTRIBUTE_BRACKET_PATTERN = re.compile(r"\[([A-Z][A-Z0-9_]{1,63})\]")
_MESSAGE_ATTR_PATTERNS_CONSERVATIVE = (
    re.compile(r"attribute\s*\[([A-Z][A-Z0-9_]{1,63})\]", re.IGNORECASE),
    re.compile(r"attribute\s+([A-Z][A-Z0-9_]{1,63})\b", re.IGNORECASE),
)
_MESSAGE_ATTR_PATTERNS_AGGRESSIVE = (
    re.compile(r"\[([A-Z][A-Z0-9_]{1,63})\]"),
    re.compile(r"\b([A-Z][A-Z0-9_]{2,63})\b"),
)


def _normalize_attribute_id(raw_value: Any) -> str | None:
    text = str(raw_value).strip().upper()
    if not _ATTRIBUTE_ID_PATTERN.fullmatch(text):
        return None
    return text


def _iter_reference_strings(raw_references: Any) -> list[str]:
    if isinstance(raw_references, str):
        text = raw_references.strip()
        return [text] if text else []
    if isinstance(raw_references, list):
        texts: list[str] = []
        for value in raw_references:
            texts.extend(_iter_reference_strings(value))
        return texts
    if isinstance(raw_references, tuple):
        texts = []
        for value in raw_references:
            texts.extend(_iter_reference_strings(value))
        return texts
    if isinstance(raw_references, set):
        texts = []
        for value in raw_references:
            texts.extend(_iter_reference_strings(value))
        return texts
    if isinstance(raw_references, dict):
        texts = []
        for value in raw_references.values():
            texts.extend(_iter_reference_strings(value))
        return texts
    return []


def _extract_attribute_ids_from_references(raw_references: Any) -> set[str]:
    candidate_ids: set[str] = set()
    for reference_text in _iter_reference_strings(raw_references):
        direct_id = _normalize_attribute_id(reference_text)
        if direct_id:
            candidate_ids.add(direct_id)
        for match in _ATTRIBUTE_BRACKET_PATTERN.finditer(reference_text.upper()):
            normalized = _normalize_attribute_id(match.group(1))
            if normalized:
                candidate_ids.add(normalized)
    return candidate_ids


def _extract_attribute_ids_from_message(
    message: str,
    *,
    aggressive: bool,
) -> set[str]:
    candidate_ids: set[str] = set()
    for pattern in _MESSAGE_ATTR_PATTERNS_CONSERVATIVE:
        for match in pattern.finditer(message):
            normalized = _normalize_attribute_id(match.group(1))
            if normalized:
                candidate_ids.add(normalized)

    if not aggressive:
        return candidate_ids

    for pattern in _MESSAGE_ATTR_PATTERNS_AGGRESSIVE:
        for match in pattern.finditer(message.upper()):
            normalized = _normalize_attribute_id(match.group(1))
            if normalized:
                candidate_ids.add(normalized)

    return candidate_ids


def _is_attribute_related_cause(cause: dict[str, Any]) -> bool:
    cause_code = str(cause.get("code", "")).strip().lower()
    cause_message = str(cause.get("message", "")).strip().lower()
    if "attribute" in cause_code or "attribute" in cause_message:
        return True

    for reference_text in _iter_reference_strings(cause.get("references")):
        if "attribute" in reference_text.lower():
            return True
    return False


def extract_prune_candidate_ids(
    causes: list[dict[str, Any]],
    *,
    detect_mode: str,
) -> set[str]:
    """Extract candidate attribute IDs to prune from validation causes."""
    mode = str(detect_mode).strip().lower()
    aggressive = mode == "aggressive"
    references_only = mode == "references_only"

    candidate_ids: set[str] = set()
    for cause in causes:
        if not isinstance(cause, dict):
            continue

        candidate_ids.update(_extract_attribute_ids_from_references(cause.get("references")))
        if references_only:
            continue
        if not _is_attribute_related_cause(cause):
            continue

        message = str(cause.get("message", "")).strip()
        if not message:
            continue
        candidate_ids.update(
            _extract_attribute_ids_from_message(
                message,
                aggressive=aggressive,
            )
        )
    return candidate_ids


def prune_item_attributes(
    *,
    item: dict[str, Any],
    prune_candidate_ids: set[str],
    required_attribute_ids: set[str],
    drop_required_attributes: bool,
) -> dict[str, list[str]]:
    """Prune item attributes in-place and report removed/skipped IDs."""
    if not prune_candidate_ids:
        return {"removed_attribute_ids": [], "skipped_required_attribute_ids": []}

    raw_attributes = item.get("attributes")
    if not isinstance(raw_attributes, list):
        return {"removed_attribute_ids": [], "skipped_required_attribute_ids": []}

    removed_ids: list[str] = []
    skipped_required_ids: list[str] = []
    seen_removed: set[str] = set()
    seen_skipped: set[str] = set()
    kept_attributes: list[Any] = []

    for attribute in raw_attributes:
        if not isinstance(attribute, dict):
            kept_attributes.append(attribute)
            continue

        attr_id = _normalize_attribute_id(attribute.get("id"))
        if not attr_id or attr_id not in prune_candidate_ids:
            kept_attributes.append(attribute)
            continue

        if attr_id in required_attribute_ids and not drop_required_attributes:
            if attr_id not in seen_skipped:
                skipped_required_ids.append(attr_id)
                seen_skipped.add(attr_id)
            kept_attributes.append(attribute)
            continue

        if attr_id not in seen_removed:
            removed_ids.append(attr_id)
            seen_removed.add(attr_id)

    item["attributes"] = kept_attributes
    return {
        "removed_attribute_ids": removed_ids,
        "skipped_required_attribute_ids": skipped_required_ids,
    }


def is_api_validation_repair_active_for_operation(
    *,
    enabled: bool,
    scope: str,
    validation_only: bool,
) -> bool:
    """Return whether API-driven repair is active for current operation."""
    if not enabled:
        return False
    normalized_scope = str(scope).strip().lower()
    if normalized_scope == "all":
        return True
    if normalized_scope == "validate_only":
        return validation_only
    if normalized_scope == "upload_only":
        return not validation_only
    return False


def _extract_cause_codes(causes: list[dict[str, Any]]) -> list[str]:
    codes: list[str] = []
    seen_codes: set[str] = set()
    for cause in causes:
        code = str(cause.get("code", "")).strip().lower()
        if not code or code in seen_codes:
            continue
        seen_codes.add(code)
        codes.append(code)
    return codes


def _get_validation_causes(validation: dict[str, Any]) -> list[dict[str, Any]]:
    raw_causes = validation.get("cause", [])
    if not isinstance(raw_causes, list):
        return []
    return [cause for cause in raw_causes if isinstance(cause, dict)]


def validate_item_with_api_repair(
    *,
    use_case: Any,
    item: dict[str, Any],
    selected_flow: str,
    required_attribute_ids: set[str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate payload with deterministic API-driven pruning retries."""
    max_attempts = max(1, int(use_case.api_validation_repair_max_attempts))
    detect_mode = str(use_case.api_validation_repair_detect_mode).strip().lower()
    drop_required_attributes = bool(use_case.api_validation_repair_drop_required_attributes)

    attempts: list[dict[str, Any]] = []
    pruned_ids_total: list[str] = []
    skipped_required_ids_total: list[str] = []
    pruned_seen: set[str] = set()
    skipped_seen: set[str] = set()
    stop_reason = "max_attempts_reached"
    final_validation: dict[str, Any] = {}

    for attempt_number in range(1, max_attempts + 1):
        validation = use_case._validate_item_for_flow(item=item, selected_flow=selected_flow)
        final_validation = validation
        causes = _get_validation_causes(validation)
        prune_candidate_ids = extract_prune_candidate_ids(causes, detect_mode=detect_mode)
        removed_attribute_ids: list[str] = []
        skipped_required_ids: list[str] = []

        if causes and prune_candidate_ids and attempt_number < max_attempts:
            prune_result = prune_item_attributes(
                item=item,
                prune_candidate_ids=prune_candidate_ids,
                required_attribute_ids=required_attribute_ids,
                drop_required_attributes=drop_required_attributes,
            )
            removed_attribute_ids = prune_result["removed_attribute_ids"]
            skipped_required_ids = prune_result["skipped_required_attribute_ids"]

            for attr_id in removed_attribute_ids:
                if attr_id not in pruned_seen:
                    pruned_seen.add(attr_id)
                    pruned_ids_total.append(attr_id)
            for attr_id in skipped_required_ids:
                if attr_id not in skipped_seen:
                    skipped_seen.add(attr_id)
                    skipped_required_ids_total.append(attr_id)

        attempts.append(
            {
                "attempt": attempt_number,
                "cause_count": len(causes),
                "cause_codes": _extract_cause_codes(causes),
                "prune_candidates": sorted(prune_candidate_ids),
                "pruned_attribute_ids": removed_attribute_ids,
                "skipped_required_attribute_ids": skipped_required_ids,
            }
        )

        if not causes:
            stop_reason = "validation_passed"
            break
        if not prune_candidate_ids:
            stop_reason = "no_prune_candidates"
            break
        if attempt_number >= max_attempts:
            stop_reason = "max_attempts_reached"
            break
        if not removed_attribute_ids:
            if skipped_required_ids:
                stop_reason = "required_attributes_retained"
            else:
                stop_reason = "no_attributes_removed"
            break

    repair_artifact = {
        "enabled": True,
        "scope": str(use_case.api_validation_repair_scope),
        "detect_mode": detect_mode,
        "max_attempts": max_attempts,
        "attempt_count": len(attempts),
        "stop_reason": stop_reason,
        "pruned_attribute_ids": pruned_ids_total,
        "skipped_required_attribute_ids": skipped_required_ids_total,
        "attempts": attempts,
    }

    logger.info(
        "API validation repair finished: attempts=%s stop_reason=%s pruned=%s skipped_required=%s",
        len(attempts),
        stop_reason,
        pruned_ids_total,
        skipped_required_ids_total,
    )
    return final_validation, repair_artifact


__all__ = [
    "extract_prune_candidate_ids",
    "is_api_validation_repair_active_for_operation",
    "prune_item_attributes",
    "validate_item_with_api_repair",
]
