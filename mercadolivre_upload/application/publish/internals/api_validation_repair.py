"""API-driven attribute pruning and revalidation helpers."""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

API_VALIDATION_REPAIR_ENABLED = True
API_VALIDATION_REPAIR_SCOPE = "all"
API_VALIDATION_REPAIR_MAX_ATTEMPTS = 3
API_VALIDATION_REPAIR_DETECT_MODE = "conservative"
API_VALIDATION_REPAIR_DROP_REQUIRED_ATTRIBUTES = False

_DETECT_MODES = {"conservative", "aggressive", "references_only"}
_ACTIONS = ("prune_attribute", "keep", "block_non_attribute", "ignore")

_ATTRIBUTE_ID_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")
_ATTRIBUTE_BRACKET_PATTERN = re.compile(r"\[([A-Z][A-Z0-9_]{1,63})\]")
_ATTRIBUTE_INDEX_REFERENCE_PATTERN = re.compile(r"item\.attributes\[(\d+)\]", re.IGNORECASE)

_MESSAGE_ATTR_PATTERNS_CONSERVATIVE = (
    re.compile(r"attribute\s*\[([A-Z][A-Z0-9_]{1,63})\]", re.IGNORECASE),
    re.compile(r"attribute\s+([A-Z][A-Z0-9_]{1,63})\b", re.IGNORECASE),
)
_MESSAGE_ATTR_PATTERNS_AGGRESSIVE = (
    re.compile(r"\[([A-Z][A-Z0-9_]{1,63})\]"),
    re.compile(r"\b([A-Z][A-Z0-9_]{2,63})\b"),
)

_KEEP_WARNING_CODES = {
    "normalize.item.attribute.values",
    "create.item.attribute.business_conditional",
}

_PRUNABLE_ERROR_CODE_TOKENS = (
    "invalid",
    "not_valid",
    "non_existent",
    "omitted",
)
_PRUNABLE_ERROR_MESSAGE_TOKENS = (
    "is not valid",
    "not valid",
    "invalid",
)
_NON_PRUNABLE_ERROR_CODE_TOKENS = (
    "missing_required",
    "deleted_required",
)


def _normalize_attribute_id(raw_value: Any) -> str | None:
    text = str(raw_value).strip().upper()
    if not _ATTRIBUTE_ID_PATTERN.fullmatch(text):
        return None
    return text


def _normalize_detect_mode(raw_mode: Any) -> str:
    mode = str(raw_mode).strip().lower()
    if mode not in _DETECT_MODES:
        return API_VALIDATION_REPAIR_DETECT_MODE
    return mode


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


def _resolve_item_attribute_ids(item: dict[str, Any] | None) -> list[str | None]:
    if not isinstance(item, dict):
        return []
    raw_attributes = item.get("attributes")
    if not isinstance(raw_attributes, list):
        return []

    resolved: list[str | None] = []
    for raw_attribute in raw_attributes:
        if not isinstance(raw_attribute, dict):
            resolved.append(None)
            continue
        resolved.append(_normalize_attribute_id(raw_attribute.get("id")))
    return resolved


def _extract_attribute_ids_from_references(
    raw_references: Any,
    *,
    item_attribute_ids: list[str | None],
) -> set[str]:
    candidate_ids: set[str] = set()
    for reference_text in _iter_reference_strings(raw_references):
        direct_id = _normalize_attribute_id(reference_text)
        if direct_id:
            candidate_ids.add(direct_id)
        for match in _ATTRIBUTE_BRACKET_PATTERN.finditer(reference_text.upper()):
            normalized = _normalize_attribute_id(match.group(1))
            if normalized:
                candidate_ids.add(normalized)
        for match in _ATTRIBUTE_INDEX_REFERENCE_PATTERN.finditer(reference_text):
            index = int(match.group(1))
            if index < 0 or index >= len(item_attribute_ids):
                continue
            indexed_attr_id = item_attribute_ids[index]
            if indexed_attr_id:
                candidate_ids.add(indexed_attr_id)
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


def _extract_cause_candidate_ids(
    cause: dict[str, Any],
    *,
    detect_mode: str,
    item_attribute_ids: list[str | None],
) -> set[str]:
    mode = _normalize_detect_mode(detect_mode)
    aggressive = mode == "aggressive"
    references_only = mode == "references_only"

    candidate_ids = _extract_attribute_ids_from_references(
        cause.get("references"),
        item_attribute_ids=item_attribute_ids,
    )
    if references_only:
        return candidate_ids
    if not _is_attribute_related_cause(cause):
        return candidate_ids

    message = str(cause.get("message", "")).strip()
    if not message:
        return candidate_ids
    candidate_ids.update(
        _extract_attribute_ids_from_message(
            message,
            aggressive=aggressive,
        )
    )
    return candidate_ids


def extract_prune_candidate_ids(
    causes: list[dict[str, Any]],
    *,
    detect_mode: str,
    item: dict[str, Any] | None = None,
) -> set[str]:
    """Extract candidate attribute IDs to prune from validation causes."""
    item_attribute_ids = _resolve_item_attribute_ids(item)
    candidate_ids: set[str] = set()
    for cause in causes:
        if not isinstance(cause, dict):
            continue
        candidate_ids.update(
            _extract_cause_candidate_ids(
                cause,
                detect_mode=detect_mode,
                item_attribute_ids=item_attribute_ids,
            )
        )
    return candidate_ids


def _should_prune_attribute_error(*, cause: dict[str, Any], candidate_ids: set[str]) -> bool:
    if not candidate_ids:
        return False

    cause_code = str(cause.get("code", "")).strip().lower()
    cause_message = str(cause.get("message", "")).strip().lower()

    if any(token in cause_code for token in _NON_PRUNABLE_ERROR_CODE_TOKENS):
        return False

    if any(token in cause_code for token in _PRUNABLE_ERROR_CODE_TOKENS):
        return True

    return any(token in cause_message for token in _PRUNABLE_ERROR_MESSAGE_TOKENS)


def _classify_cause_action(*, cause: dict[str, Any], candidate_ids: set[str]) -> str:
    cause_type = str(cause.get("type", "")).strip().lower()
    cause_code = str(cause.get("code", "")).strip().lower()

    if cause_type == "warning":
        if cause_code in _KEEP_WARNING_CODES:
            return "keep"
        return "keep"

    if cause_type != "error":
        return "ignore"

    if _should_prune_attribute_error(cause=cause, candidate_ids=candidate_ids):
        return "prune_attribute"

    if _is_attribute_related_cause(cause):
        return "keep"

    return "block_non_attribute"


def _empty_action_counts() -> dict[str, int]:
    return dict.fromkeys(_ACTIONS, 0)


def _analyze_validation_causes(
    *,
    causes: list[dict[str, Any]],
    detect_mode: str,
    item: dict[str, Any],
) -> dict[str, Any]:
    prune_candidate_ids: set[str] = set()
    non_attribute_blocking_codes: list[str] = []
    non_attribute_blocking_seen: set[str] = set()
    action_counts = _empty_action_counts()
    cause_actions: list[dict[str, Any]] = []

    item_attribute_ids = _resolve_item_attribute_ids(item)

    for cause in causes:
        candidate_ids = _extract_cause_candidate_ids(
            cause,
            detect_mode=detect_mode,
            item_attribute_ids=item_attribute_ids,
        )
        action = _classify_cause_action(cause=cause, candidate_ids=candidate_ids)
        action_counts[action] += 1

        if action == "prune_attribute":
            prune_candidate_ids.update(candidate_ids)
        elif action == "block_non_attribute":
            code = str(cause.get("code", "")).strip().lower()
            if code and code not in non_attribute_blocking_seen:
                non_attribute_blocking_seen.add(code)
                non_attribute_blocking_codes.append(code)

        cause_actions.append(
            {
                "type": str(cause.get("type", "")).strip().lower(),
                "code": str(cause.get("code", "")).strip().lower(),
                "action": action,
                "candidate_ids": sorted(candidate_ids),
            }
        )

    return {
        "prune_candidate_ids": prune_candidate_ids,
        "non_attribute_blocking_codes": non_attribute_blocking_codes,
        "action_counts": action_counts,
        "cause_actions": cause_actions,
    }


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


def _build_action_summary(attempts: list[dict[str, Any]]) -> dict[str, int]:
    summary = _empty_action_counts()
    for attempt in attempts:
        counts = attempt.get("action_counts", {})
        if not isinstance(counts, dict):
            continue
        for action in _ACTIONS:
            summary[action] += int(counts.get(action, 0))
    return summary


def validate_item_with_api_repair(
    *,
    use_case: Any,
    item: dict[str, Any],
    selected_flow: str,
    required_attribute_ids: set[str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate payload with deterministic API-driven pruning retries."""
    max_attempts = max(1, API_VALIDATION_REPAIR_MAX_ATTEMPTS)
    detect_mode = API_VALIDATION_REPAIR_DETECT_MODE
    drop_required_attributes = API_VALIDATION_REPAIR_DROP_REQUIRED_ATTRIBUTES

    attempts: list[dict[str, Any]] = []
    pruned_ids_total: list[str] = []
    skipped_required_ids_total: list[str] = []
    non_attribute_blocking_codes_total: list[str] = []
    pruned_seen: set[str] = set()
    skipped_seen: set[str] = set()
    non_attribute_seen: set[str] = set()
    stop_reason = "max_attempts_reached"
    final_validation: dict[str, Any] = {}

    for attempt_number in range(1, max_attempts + 1):
        validation = use_case._validate_item_for_flow(item=item, selected_flow=selected_flow)
        final_validation = validation
        causes = _get_validation_causes(validation)
        analysis = _analyze_validation_causes(
            causes=causes,
            detect_mode=detect_mode,
            item=item,
        )
        prune_candidate_ids: set[str] = analysis["prune_candidate_ids"]
        non_attribute_blocking_codes: list[str] = analysis["non_attribute_blocking_codes"]
        removed_attribute_ids: list[str] = []
        skipped_required_ids: list[str] = []

        if (
            causes
            and not non_attribute_blocking_codes
            and prune_candidate_ids
            and attempt_number < max_attempts
        ):
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

        for code in non_attribute_blocking_codes:
            if code in non_attribute_seen:
                continue
            non_attribute_seen.add(code)
            non_attribute_blocking_codes_total.append(code)

        attempts.append(
            {
                "attempt": attempt_number,
                "cause_count": len(causes),
                "cause_codes": _extract_cause_codes(causes),
                "prune_candidates": sorted(prune_candidate_ids),
                "pruned_attribute_ids": removed_attribute_ids,
                "skipped_required_attribute_ids": skipped_required_ids,
                "non_attribute_blocking_codes": non_attribute_blocking_codes,
                "action_counts": dict(analysis["action_counts"]),
                "cause_actions": list(analysis["cause_actions"]),
            }
        )

        if not causes:
            stop_reason = "validation_passed"
            break
        if non_attribute_blocking_codes:
            stop_reason = "non_attribute_blocking_errors"
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
        "enabled": API_VALIDATION_REPAIR_ENABLED,
        "scope": API_VALIDATION_REPAIR_SCOPE,
        "detect_mode": detect_mode,
        "max_attempts": max_attempts,
        "attempt_count": len(attempts),
        "stop_reason": stop_reason,
        "pruned_attribute_ids": pruned_ids_total,
        "skipped_required_attribute_ids": skipped_required_ids_total,
        "non_attribute_blocking_codes": non_attribute_blocking_codes_total,
        "action_summary": _build_action_summary(attempts),
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
    "API_VALIDATION_REPAIR_DETECT_MODE",
    "API_VALIDATION_REPAIR_DROP_REQUIRED_ATTRIBUTES",
    "API_VALIDATION_REPAIR_ENABLED",
    "API_VALIDATION_REPAIR_MAX_ATTEMPTS",
    "API_VALIDATION_REPAIR_SCOPE",
    "extract_prune_candidate_ids",
    "prune_item_attributes",
    "validate_item_with_api_repair",
]
