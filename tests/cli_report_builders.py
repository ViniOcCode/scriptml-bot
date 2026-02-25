"""Shared test builders for CLI batching/reporting command tests."""

from __future__ import annotations


def _build_rows(count: int) -> list[dict[str, object]]:
    return [
        {
            "sku": f"SKU{i:03d}",
            "titulo": f"Produto {i}",
            "preco": 10.0 + i,
            "quantidade": 1,
            "condicao": "novo",
        }
        for i in range(1, count + 1)
    ]


def _make_item_result(
    index: int,
    sku: str,
    status: str | None = None,
    error: str | None = None,
    *,
    cause_codes: list[str] | None = None,
    cause_taxonomy: list[dict[str, object]] | None = None,
    validation_decision: dict[str, object] | None = None,
    policy_hash: str | None = None,
    policy_summary: dict[str, object] | None = None,
    schema_contract_hash: str | None = None,
    schema_contract_summary: dict[str, object] | None = None,
    identifier_gate: dict[str, object] | None = None,
    flow_routing: dict[str, object] | None = None,
    image_diagnostics: dict[str, object] | None = None,
    shipping_policy: dict[str, object] | None = None,
    rollout_flags: dict[str, object] | None = None,
    category_input: str | None = None,
    category_resolved_id: str | None = None,
    category_path: list[dict[str, object]] | None = None,
    resolution_strategy: str | None = None,
    category_resolution_decision: dict[str, object] | None = None,
) -> dict[str, object]:
    if status is None:
        raise TypeError("status is required")

    result: dict[str, object] = {
        "index": index,
        "sku": sku,
        "title": f"Produto {index + 1}",
        "status": status,
    }
    if error is not None:
        result["error"] = error
    if cause_codes is not None:
        result["cause_codes"] = cause_codes
    if cause_taxonomy is not None:
        result["cause_taxonomy"] = cause_taxonomy
    if validation_decision is not None:
        result["validation_decision"] = validation_decision
    if policy_hash is not None:
        result["policy_hash"] = policy_hash
    if policy_summary is not None:
        result["policy_summary"] = policy_summary
    if schema_contract_hash is not None:
        result["schema_contract_hash"] = schema_contract_hash
    if schema_contract_summary is not None:
        result["schema_contract_summary"] = schema_contract_summary
    if identifier_gate is not None:
        result["identifier_gate"] = identifier_gate
    if flow_routing is not None:
        result["flow_routing"] = flow_routing
    if image_diagnostics is not None:
        result["image_diagnostics"] = image_diagnostics
    if shipping_policy is not None:
        result["shipping_policy"] = shipping_policy
    if rollout_flags is not None:
        result["rollout_flags"] = rollout_flags
    if category_input is not None:
        result["category_input"] = category_input
    if category_resolved_id is not None:
        result["category_resolved_id"] = category_resolved_id
    if category_path is not None:
        result["category_path"] = category_path
    if resolution_strategy is not None:
        result["resolution_strategy"] = resolution_strategy
    if category_resolution_decision is not None:
        result["category_resolution_decision"] = category_resolution_decision
    return result
