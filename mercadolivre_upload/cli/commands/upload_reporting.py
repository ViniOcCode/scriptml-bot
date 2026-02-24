"""Reporting helpers for upload command observability artifacts."""

import re
from typing import Any

_CAUSE_CODE_PATTERN = re.compile(r"\b[a-z]+(?:[._-][a-z0-9]+)+\b")


def _normalize_cause_codes(raw_codes: Any) -> list[str]:
    if not isinstance(raw_codes, list):
        return []
    normalized: list[str] = []
    for code in raw_codes:
        code_text = str(code).strip().lower()
        if code_text and code_text not in normalized:
            normalized.append(code_text)
    return normalized


def _normalize_cause_taxonomy(raw_taxonomy: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_taxonomy, list):
        return []
    return [dict(cause) for cause in raw_taxonomy if isinstance(cause, dict)]


def _extract_cause_codes(error: str | None) -> list[str]:
    if not error:
        return []
    return list(dict.fromkeys(_CAUSE_CODE_PATTERN.findall(error.lower())))


def _extract_decision_classified_codes(validation_decision: Any) -> tuple[set[str], set[str]]:
    warning_codes: set[str] = set()
    error_codes: set[str] = set()
    if not isinstance(validation_decision, dict):
        return warning_codes, error_codes

    classification_codes = validation_decision.get("classification_codes")
    if not isinstance(classification_codes, dict):
        return warning_codes, error_codes

    for classification, raw_codes in classification_codes.items():
        normalized_codes = _normalize_cause_codes(raw_codes)
        normalized_classification = str(classification).strip().lower()
        if _is_warning_classification(normalized_classification):
            warning_codes.update(normalized_codes)
        elif _is_error_classification(normalized_classification):
            error_codes.update(normalized_codes)
    return warning_codes, error_codes


def _default_validation_decision(status: str) -> dict[str, Any]:
    action = "block" if status.strip().lower() == "failed" else "allow"
    return {
        "mode": "unknown",
        "strict_warning_gate_mode": "unknown",
        "strict_attribute_warnings": None,
        "action": action,
        "reason": "missing_validation_decision",
        "classification_counts": {
            "blocking_error": 0,
            "retryable_error": 0,
            "critical_warning": 0,
            "informational_warning": 0,
        },
        "classification_codes": {
            "blocking_error": [],
            "retryable_error": [],
            "critical_warning": [],
            "informational_warning": [],
        },
    }


def _ensure_observability_evidence(
    item: dict[str, Any],
    *,
    row_status: str,
    default_flow_routing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized = dict(item)
    normalized["cause_codes"] = _normalize_cause_codes(normalized.get("cause_codes"))
    normalized["cause_taxonomy"] = _normalize_cause_taxonomy(normalized.get("cause_taxonomy"))

    validation_decision = normalized.get("validation_decision")
    if isinstance(validation_decision, dict):
        normalized["validation_decision"] = dict(validation_decision)
    else:
        normalized["validation_decision"] = _default_validation_decision(row_status)

    policy_hash = normalized.get("policy_hash")
    normalized["policy_hash"] = (
        policy_hash if isinstance(policy_hash, str) and policy_hash else None
    )
    policy_summary = normalized.get("policy_summary")
    normalized["policy_summary"] = dict(policy_summary) if isinstance(policy_summary, dict) else {}

    schema_contract_hash = normalized.get("schema_contract_hash")
    normalized["schema_contract_hash"] = (
        schema_contract_hash
        if isinstance(schema_contract_hash, str) and schema_contract_hash
        else None
    )
    schema_contract_summary = normalized.get("schema_contract_summary")
    normalized["schema_contract_summary"] = (
        dict(schema_contract_summary) if isinstance(schema_contract_summary, dict) else {}
    )

    flow_routing = normalized.get("flow_routing")
    if isinstance(flow_routing, dict):
        normalized["flow_routing"] = dict(flow_routing)
    elif isinstance(default_flow_routing, dict):
        normalized["flow_routing"] = dict(default_flow_routing)
    else:
        normalized["flow_routing"] = {}

    identifier_gate = normalized.get("identifier_gate")
    if isinstance(identifier_gate, dict):
        normalized["identifier_gate"] = dict(identifier_gate)

    image_diagnostics = normalized.get("image_diagnostics")
    if isinstance(image_diagnostics, dict):
        normalized["image_diagnostics"] = dict(image_diagnostics)

    shipping_policy = normalized.get("shipping_policy")
    if isinstance(shipping_policy, dict):
        normalized["shipping_policy"] = dict(shipping_policy)

    rollout_flags = normalized.get("rollout_flags")
    if isinstance(rollout_flags, dict):
        normalized["rollout_flags"] = dict(rollout_flags)
    else:
        normalized["rollout_flags"] = {}

    category_resolution_decision = normalized.get("category_resolution_decision")
    if isinstance(category_resolution_decision, dict):
        normalized["category_resolution_decision"] = dict(category_resolution_decision)
    else:
        normalized["category_resolution_decision"] = {}

    return normalized


def _is_warning_classification(classification: str) -> bool:
    return classification in {"critical_warning", "informational_warning"}


def _is_error_classification(classification: str) -> bool:
    return classification in {"blocking_error", "retryable_error"}


def _increment_code_counter(counter: dict[str, int], code: str) -> None:
    normalized = code.strip().lower()
    if not normalized:
        return
    counter[normalized] = counter.get(normalized, 0) + 1


def _top_code_entries(counter: dict[str, int], limit: int = 5) -> list[dict[str, Any]]:
    return [
        {"code": code, "count": count}
        for code, count in sorted(counter.items(), key=lambda item: (-item[1], item[0]))[:limit]
    ]


def _top_codes_by_status(
    counters: dict[str, dict[str, int]], limit: int = 5
) -> dict[str, list[dict[str, Any]]]:
    return {status: _top_code_entries(counter, limit=limit) for status, counter in counters.items()}


def _empty_category_resolution_summary() -> dict[str, Any]:
    return {
        "strategy_counts": {
            "direct_id": 0,
            "predictor_path_match": 0,
            "name_match": 0,
            "unresolved": 0,
        },
        "fallback_counts": {"attempted": 0, "resolved": 0, "unresolved": 0},
        "predictor_counts": {"attempted": 0, "matched": 0, "unmatched": 0},
        "decisions": [],
    }


def _merge_counter_values(counter: dict[str, int], raw_values: Any) -> None:
    if not isinstance(raw_values, dict):
        return
    for key, raw_count in raw_values.items():
        key_text = str(key).strip()
        if not key_text:
            continue
        try:
            count = int(raw_count)
        except (TypeError, ValueError):
            continue
        counter[key_text] = counter.get(key_text, 0) + count


def _merge_category_resolution_summary(summary: dict[str, Any], raw_resolution: Any) -> None:
    if not isinstance(raw_resolution, dict):
        return

    strategy_counts = summary.get("strategy_counts")
    if isinstance(strategy_counts, dict):
        _merge_counter_values(strategy_counts, raw_resolution.get("strategy_counts"))

    fallback_counts = summary.get("fallback_counts")
    if isinstance(fallback_counts, dict):
        _merge_counter_values(fallback_counts, raw_resolution.get("fallback_counts"))

    predictor_counts = summary.get("predictor_counts")
    if isinstance(predictor_counts, dict):
        _merge_counter_values(predictor_counts, raw_resolution.get("predictor_counts"))

    decision = raw_resolution.get("decision")
    decisions = summary.get("decisions")
    if isinstance(decision, dict) and isinstance(decisions, list):
        decisions.append(dict(decision))
