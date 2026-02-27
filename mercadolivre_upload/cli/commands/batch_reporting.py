"""Shared batch/result/report helpers for upload and validate commands."""

from collections.abc import Callable
from typing import Any

from mercadolivre_upload.cli.commands.common import merge_category_resolution_fields
from mercadolivre_upload.cli.commands.upload_reporting import (
    _extract_cause_codes,
    _extract_decision_classified_codes,
    _increment_code_counter,
    _is_error_classification,
    _is_warning_classification,
)


def _group_products_by_category(
    batch_products: list[dict[str, Any]],
    *,
    default_category: str,
    extract_category: Callable[[dict[str, Any]], str | None],
) -> dict[str, list[tuple[int, dict[str, Any]]]]:
    grouped_products: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    for index, row in enumerate(batch_products):
        row_category = extract_category(row) or default_category
        grouped_products.setdefault(row_category, []).append((index, row))
    return grouped_products


def _extract_group_flow_routing(results: dict[str, Any]) -> dict[str, Any] | None:
    raw_group_flow_routing = results.get("flow_routing")
    if isinstance(raw_group_flow_routing, dict):
        return dict(raw_group_flow_routing)
    return None


def _resolve_cause_codes(raw_codes: Any, error_text: Any) -> list[str]:
    if isinstance(raw_codes, list):
        normalized_codes = [str(code) for code in raw_codes if str(code).strip()]
        if normalized_codes:
            return normalized_codes
    return _extract_cause_codes(str(error_text) if error_text is not None else None)


def _merge_item_observability_fields(
    target: dict[str, Any],
    source: dict[str, Any],
    *,
    category_input: str | None,
    default_flow_routing: dict[str, Any] | None = None,
) -> None:
    cause_taxonomy = source.get("cause_taxonomy")
    if isinstance(cause_taxonomy, list):
        normalized_taxonomy = [dict(cause) for cause in cause_taxonomy if isinstance(cause, dict)]
        if normalized_taxonomy:
            target["cause_taxonomy"] = normalized_taxonomy

    validation_decision = source.get("validation_decision")
    if isinstance(validation_decision, dict):
        target["validation_decision"] = dict(validation_decision)

    validation_repair = source.get("validation_repair")
    if isinstance(validation_repair, dict):
        target["validation_repair"] = dict(validation_repair)

    merge_category_resolution_fields(target, source, category_input)

    category_resolution_decision = source.get("category_resolution_decision")
    if isinstance(category_resolution_decision, dict):
        target["category_resolution_decision"] = dict(category_resolution_decision)

    policy_hash = source.get("policy_hash")
    if isinstance(policy_hash, str) and policy_hash:
        target["policy_hash"] = policy_hash

    policy_summary = source.get("policy_summary")
    if isinstance(policy_summary, dict):
        target["policy_summary"] = policy_summary

    schema_contract_hash = source.get("schema_contract_hash")
    if isinstance(schema_contract_hash, str) and schema_contract_hash:
        target["schema_contract_hash"] = schema_contract_hash

    schema_contract_summary = source.get("schema_contract_summary")
    if isinstance(schema_contract_summary, dict):
        target["schema_contract_summary"] = schema_contract_summary

    identifier_gate = source.get("identifier_gate")
    if isinstance(identifier_gate, dict):
        target["identifier_gate"] = identifier_gate

    flow_routing = source.get("flow_routing")
    if isinstance(flow_routing, dict):
        target["flow_routing"] = flow_routing
    elif isinstance(default_flow_routing, dict):
        target["flow_routing"] = dict(default_flow_routing)

    image_diagnostics = source.get("image_diagnostics")
    if isinstance(image_diagnostics, dict):
        target["image_diagnostics"] = image_diagnostics

    shipping_policy = source.get("shipping_policy")
    if isinstance(shipping_policy, dict):
        target["shipping_policy"] = shipping_policy

    rollout_flags = source.get("rollout_flags")
    if isinstance(rollout_flags, dict):
        target["rollout_flags"] = rollout_flags


def _update_cause_code_counters(
    item: dict[str, Any],
    *,
    status_bucket: str,
    cause_code_counts: dict[str, int],
    warning_code_counts: dict[str, dict[str, int]],
    error_code_counts: dict[str, dict[str, int]],
) -> None:
    raw_codes = item.get("cause_codes", [])
    cause_codes = (
        [str(code).strip().lower() for code in raw_codes if str(code).strip()]
        if isinstance(raw_codes, list)
        else []
    )

    warning_codes_for_row: set[str] = set()
    error_codes_for_row: set[str] = set()
    all_codes_for_row: set[str] = set(cause_codes)
    taxonomy = item.get("cause_taxonomy")
    if isinstance(taxonomy, list):
        for cause in taxonomy:
            if not isinstance(cause, dict):
                continue
            code = str(cause.get("code", "")).strip().lower()
            if not code:
                continue
            all_codes_for_row.add(code)
            classification = str(cause.get("classification", "")).strip().lower()
            if _is_warning_classification(classification):
                warning_codes_for_row.add(code)
            elif _is_error_classification(classification):
                error_codes_for_row.add(code)
            else:
                cause_type = str(cause.get("type", "")).strip().lower()
                if cause_type == "warning":
                    warning_codes_for_row.add(code)
                elif cause_type == "error":
                    error_codes_for_row.add(code)

    if not warning_codes_for_row and not error_codes_for_row:
        decision_warning_codes, decision_error_codes = _extract_decision_classified_codes(
            item.get("validation_decision")
        )
        warning_codes_for_row.update(decision_warning_codes)
        error_codes_for_row.update(decision_error_codes)
        all_codes_for_row.update(decision_warning_codes)
        all_codes_for_row.update(decision_error_codes)

    if not warning_codes_for_row and not error_codes_for_row:
        if status_bucket in {"success", "valid"}:
            warning_codes_for_row.update(cause_codes)
        else:
            error_codes_for_row.update(cause_codes)

    for code in all_codes_for_row:
        _increment_code_counter(cause_code_counts, code)
    for code in warning_codes_for_row:
        _increment_code_counter(warning_code_counts[status_bucket], code)
    for code in error_codes_for_row:
        _increment_code_counter(error_code_counts[status_bucket], code)


def _extract_rollout_flags_snapshot(all_item_results: list[dict[str, Any]]) -> dict[str, Any]:
    for item in all_item_results:
        raw_rollout_flags = item.get("rollout_flags")
        if isinstance(raw_rollout_flags, dict) and raw_rollout_flags:
            return dict(raw_rollout_flags)
    return {}
