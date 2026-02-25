"""Shipping helpers extracted from publish orchestration."""

from __future__ import annotations

import logging
from typing import Any

from mercadolivre_upload.shared.utils.text_utils import PortugueseTextNormalizer

from .publish_product_constants import (
    ROW_SHIPPING_COST_HEADERS,
    ROW_SHIPPING_CUSTOM_TOKENS,
    ROW_SHIPPING_FALSE_TOKENS,
    ROW_SHIPPING_FREE_FALSE_TOKENS,
    ROW_SHIPPING_FREE_TRUE_TOKENS,
    ROW_SHIPPING_MARKETPLACE_TOKENS,
    ROW_SHIPPING_MODE_HEADERS,
    ROW_SHIPPING_NOT_SPECIFIED_TOKENS,
    ROW_SHIPPING_PICKUP_HEADERS,
    ROW_SHIPPING_TRUE_TOKENS,
)

logger = logging.getLogger(__name__)


def normalize_shipping_header_name(raw_key: Any) -> str:
    """Normalize spreadsheet header names for shipping extraction."""
    text = str(raw_key).replace("_", " ").strip()
    if not text:
        return ""
    return PortugueseTextNormalizer.normalize(text)


def normalize_shipping_value(raw_value: Any) -> str:
    """Normalize spreadsheet shipping values for deterministic matching."""
    text = str(raw_value).strip()
    if not text:
        return ""
    return PortugueseTextNormalizer.normalize(text)


def extract_row_shipping_input(
    use_case: Any,
    row_attributes: dict[str, Any] | None,
) -> dict[str, Any]:
    """Extract shipping intent from row attributes using header names."""
    if not isinstance(row_attributes, dict) or not row_attributes:
        return {
            "mode_intent": None,
            "free_shipping": None,
            "local_pick_up": None,
            "source_headers": {},
            "raw_values": {},
        }

    normalized_row: dict[str, Any] = {}
    for raw_key, raw_value in row_attributes.items():
        normalized_key = normalize_shipping_header_name(raw_key)
        if normalized_key and normalized_key not in normalized_row:
            normalized_row[normalized_key] = raw_value

    def _pick_header_value(headers: tuple[str, ...]) -> tuple[Any | None, str | None]:
        for header in headers:
            value = normalized_row.get(header)
            if value is None:
                continue
            if isinstance(value, str) and not value.strip():
                continue
            return value, header
        return None, None

    raw_mode, mode_header = _pick_header_value(ROW_SHIPPING_MODE_HEADERS)
    raw_cost, cost_header = _pick_header_value(ROW_SHIPPING_COST_HEADERS)
    raw_pickup, pickup_header = _pick_header_value(ROW_SHIPPING_PICKUP_HEADERS)

    mode_intent: str | None = None
    normalized_mode = normalize_shipping_value(raw_mode) if raw_mode is not None else ""
    if normalized_mode:
        if "me2" in normalized_mode:
            mode_intent = "me2"
        elif "me1" in normalized_mode:
            mode_intent = "me1"
        elif any(token in normalized_mode for token in ROW_SHIPPING_CUSTOM_TOKENS):
            mode_intent = "custom"
        elif any(token in normalized_mode for token in ROW_SHIPPING_NOT_SPECIFIED_TOKENS):
            mode_intent = "not_specified"
        elif any(token in normalized_mode for token in ROW_SHIPPING_MARKETPLACE_TOKENS):
            mode_intent = "marketplace"

    free_shipping: bool | None = use_case._coerce_shipping_bool(raw_cost)
    normalized_cost = normalize_shipping_value(raw_cost) if raw_cost is not None else ""
    if free_shipping is None and normalized_cost:
        if any(token in normalized_cost for token in ROW_SHIPPING_FREE_TRUE_TOKENS):
            free_shipping = True
        elif any(token in normalized_cost for token in ROW_SHIPPING_FREE_FALSE_TOKENS):
            free_shipping = False

    local_pick_up: bool | None = use_case._coerce_shipping_bool(raw_pickup)
    normalized_pickup = normalize_shipping_value(raw_pickup) if raw_pickup is not None else ""
    if local_pick_up is None and normalized_pickup:
        if any(token in normalized_pickup for token in ROW_SHIPPING_FALSE_TOKENS):
            local_pick_up = False
        elif any(token in normalized_pickup for token in ROW_SHIPPING_TRUE_TOKENS):
            local_pick_up = True

    source_headers: dict[str, str] = {}
    if mode_header:
        source_headers["mode"] = mode_header
    if cost_header:
        source_headers["free_shipping"] = cost_header
    if pickup_header:
        source_headers["local_pick_up"] = pickup_header

    raw_values = {}
    if raw_mode is not None:
        raw_values["mode"] = str(raw_mode)
    if raw_cost is not None:
        raw_values["free_shipping"] = str(raw_cost)
    if raw_pickup is not None:
        raw_values["local_pick_up"] = str(raw_pickup)

    return {
        "mode_intent": mode_intent,
        "free_shipping": free_shipping,
        "local_pick_up": local_pick_up,
        "source_headers": source_headers,
        "raw_values": raw_values,
    }


def _initialize_shipping_resolution_state(default_mode: str) -> dict[str, Any]:
    return {
        "requested_mode": default_mode,
        "decision_source": "runtime.default_mode",
        "decision_reason": "Using runtime default mode.",
        "resolved_mode": None,
        "resolved_logistic_type": None,
        "resolved_logistic_type_source": None,
        "resolved_runtime_tags": [],
        "resolved_runtime_constraints": {},
        "resolved_runtime_free_shipping": None,
        "resolved_available_modes": [],
        "resolved_logistic_type_by_mode": {},
        "resolved_runtime_policy_by_mode": {},
        "fallback_applied": False,
    }


def _merge_resolver_selection(use_case: Any, state: dict[str, Any], default_mode: str) -> None:
    if not use_case.shipping_resolver:
        return

    resolved_from_selection = False
    selection_getter = getattr(use_case.shipping_resolver, "get_best_shipping_selection", None)
    if callable(selection_getter):
        try:
            selection_payload = selection_getter()
        except Exception as error:
            logger.warning(
                "Shipping resolver selection failed; fallback to mode-only resolver: %s",
                error,
            )
        else:
            if isinstance(selection_payload, dict):
                resolved_mode_raw = selection_payload.get("mode")
                state["resolved_mode"] = (
                    str(resolved_mode_raw).strip() if resolved_mode_raw is not None else ""
                )
                if state["resolved_mode"]:
                    state["requested_mode"] = state["resolved_mode"]
                    state["decision_source"] = "shipping_resolver.selection"
                    state["decision_reason"] = (
                        "Resolved mode from seller shipping selection metadata."
                    )
                    resolved_from_selection = True

                available_modes_raw = selection_payload.get("available_modes")
                if isinstance(available_modes_raw, list):
                    state["resolved_available_modes"] = [
                        str(mode).strip() for mode in available_modes_raw if str(mode).strip()
                    ]

                logistic_type_by_mode_raw = selection_payload.get("logistic_type_by_mode")
                if isinstance(logistic_type_by_mode_raw, dict):
                    for mode, logistic_type in logistic_type_by_mode_raw.items():
                        normalized_mode = str(mode).strip()
                        normalized_logistic = str(logistic_type).strip()
                        if normalized_mode and normalized_logistic:
                            state["resolved_logistic_type_by_mode"][
                                normalized_mode
                            ] = normalized_logistic

                runtime_policy_by_mode_raw = selection_payload.get("runtime_policy_by_mode")
                if isinstance(runtime_policy_by_mode_raw, dict):
                    for mode, raw_policy in runtime_policy_by_mode_raw.items():
                        if not isinstance(raw_policy, dict):
                            continue
                        normalized_mode = str(mode).strip()
                        if not normalized_mode:
                            continue
                        state["resolved_runtime_policy_by_mode"][normalized_mode] = dict(raw_policy)

                resolved_logistic_type_raw = selection_payload.get("logistic_type")
                state["resolved_logistic_type"] = (
                    str(resolved_logistic_type_raw).strip()
                    if resolved_logistic_type_raw is not None
                    else ""
                )
                if state["resolved_logistic_type"]:
                    state["resolved_logistic_type_source"] = "shipping_resolver.selection"
                    logger.info(
                        "Using shipping logistic_type from resolver selection: %s",
                        state["resolved_logistic_type"],
                    )
                else:
                    state["resolved_logistic_type"] = None

                state["resolved_runtime_tags"] = use_case._normalize_seller_tags(
                    selection_payload.get("tags")
                )
                if state["resolved_runtime_tags"]:
                    logger.info(
                        "Using shipping tags from resolver selection metadata: %s",
                        state["resolved_runtime_tags"],
                    )

                state["resolved_runtime_constraints"] = use_case._normalize_shipping_constraints(
                    selection_payload.get("constraints")
                )
                if state["resolved_runtime_constraints"]:
                    logger.info(
                        "Using shipping constraints from resolver selection metadata: %s",
                        state["resolved_runtime_constraints"],
                    )

                state["resolved_runtime_free_shipping"] = use_case._coerce_shipping_bool(
                    selection_payload.get("free_shipping")
                )
                if state["resolved_runtime_free_shipping"] is not None:
                    logger.info(
                        "Using shipping free_shipping from resolver selection metadata: %s",
                        state["resolved_runtime_free_shipping"],
                    )

    if resolved_from_selection:
        return

    try:
        resolved_mode_raw = use_case.shipping_resolver.get_best_shipping_mode()
    except Exception as error:
        logger.warning(
            "Shipping resolver failed; using default mode %s: %s",
            default_mode,
            error,
        )
        state["decision_reason"] = "Shipping resolver failed; using default mode."
    else:
        state["resolved_mode"] = (
            str(resolved_mode_raw).strip() if resolved_mode_raw is not None else ""
        )
        if state["resolved_mode"]:
            state["requested_mode"] = state["resolved_mode"]
            state["decision_source"] = "shipping_resolver"
            state["decision_reason"] = "Resolved mode from seller shipping preferences."
            logger.info("Using shipping mode from resolver: %s", state["requested_mode"])
            if state["resolved_mode"] not in state["resolved_available_modes"]:
                state["resolved_available_modes"].append(state["resolved_mode"])


def _apply_mode_intent_overrides(
    use_case: Any,
    state: dict[str, Any],
    row_shipping_input: dict[str, Any],
) -> None:
    row_mode_intent = row_shipping_input.get("mode_intent")
    if not isinstance(row_mode_intent, str) or not row_mode_intent:
        return

    state["decision_source"] = "spreadsheet.headers"
    if row_mode_intent == "marketplace":
        configured_mode_priority = getattr(use_case.shipping_resolver, "mode_priority", [])
        marketplace_priority: list[str] = []
        if isinstance(configured_mode_priority, list):
            for raw_mode in configured_mode_priority:
                mode_name = str(raw_mode).strip().lower()
                if mode_name in {"me1", "me2"} and mode_name not in marketplace_priority:
                    marketplace_priority.append(mode_name)
        if not marketplace_priority:
            marketplace_priority = ["me2", "me1"]

        marketplace_modes = [
            mode for mode in marketplace_priority if mode in state["resolved_available_modes"]
        ]
        if isinstance(state["resolved_mode"], str) and state["resolved_mode"] in {"me1", "me2"}:
            state["requested_mode"] = state["resolved_mode"]
            state["decision_reason"] = (
                "Resolved Mercado Envios from spreadsheet headers using seller mode selection."
            )
        elif marketplace_modes:
            state["requested_mode"] = marketplace_modes[0]
            state["decision_reason"] = (
                "Resolved Mercado Envios from spreadsheet headers using available seller modes."
            )
        else:
            fallback_marketplace_mode = marketplace_priority[0]
            state["requested_mode"] = fallback_marketplace_mode
            state["decision_reason"] = (
                "Resolved Mercado Envios from spreadsheet headers with "
                f"{state['requested_mode'].upper()} runtime fallback."
            )
    else:
        state["requested_mode"] = row_mode_intent
        state["decision_reason"] = "Resolved shipping mode from spreadsheet headers."


def _normalize_shipping_mode(state: dict[str, Any], default_mode: str) -> str:
    shipping_mode = state["requested_mode"] or default_mode
    if state["resolved_available_modes"] and shipping_mode not in state["resolved_available_modes"]:
        fallback_mode = None
        if (
            isinstance(state["resolved_mode"], str)
            and state["resolved_mode"] in state["resolved_available_modes"]
        ):
            fallback_mode = state["resolved_mode"]
        elif default_mode in state["resolved_available_modes"]:
            fallback_mode = default_mode
        elif state["resolved_available_modes"]:
            fallback_mode = state["resolved_available_modes"][0]
        if fallback_mode != shipping_mode:
            state["fallback_applied"] = True
            state["decision_source"] = "shipping_resolver.available_modes_fallback"
            state["decision_reason"] = (
                f"Mode '{shipping_mode}' not configured; using '{fallback_mode}'."
            )
            shipping_mode = str(fallback_mode)
    return shipping_mode


def _resolve_runtime_policy_for_mode(
    use_case: Any,
    state: dict[str, Any],
    shipping_mode: str,
) -> tuple[list[str], dict[str, Any], bool | None]:
    runtime_policy_for_mode = state["resolved_runtime_policy_by_mode"].get(shipping_mode, {})
    if not runtime_policy_for_mode and shipping_mode == state["resolved_mode"]:
        runtime_policy_for_mode = {
            "tags": list(state["resolved_runtime_tags"]),
            "constraints": dict(state["resolved_runtime_constraints"]),
            "free_shipping": state["resolved_runtime_free_shipping"],
        }
    runtime_tags_for_mode = use_case._normalize_seller_tags(runtime_policy_for_mode.get("tags"))
    runtime_constraints_for_mode = use_case._normalize_shipping_constraints(
        runtime_policy_for_mode.get("constraints")
    )
    runtime_free_shipping_for_mode = use_case._coerce_shipping_bool(
        runtime_policy_for_mode.get("free_shipping")
    )
    if runtime_free_shipping_for_mode is None and shipping_mode == state["resolved_mode"]:
        runtime_free_shipping_for_mode = state["resolved_runtime_free_shipping"]
    return runtime_tags_for_mode, runtime_constraints_for_mode, runtime_free_shipping_for_mode


def _assemble_shipping_payload(
    use_case: Any,
    state: dict[str, Any],
    *,
    category_id: str | None,
    row_shipping_input: dict[str, Any],
    shipping_mode: str,
    runtime_tags_for_mode: list[str],
    runtime_constraints_for_mode: dict[str, Any],
    runtime_free_shipping_for_mode: bool | None,
) -> dict[str, Any]:
    configured_tags: list[str] = []
    selected_tags: list[str] = []
    tags_source = "runtime.default.empty"
    policy_overrides: list[str] = []

    if use_case.shipping_allow_runtime_tag_overrides and runtime_tags_for_mode:
        merged_tags = list(dict.fromkeys([*configured_tags, *runtime_tags_for_mode]))
        if merged_tags != selected_tags:
            policy_overrides.append("runtime_tags_merged")
        selected_tags = merged_tags
        tags_source = "shipping_resolver.selection"

    selected_free_shipping = False
    free_shipping_source = "default.false"
    if (
        use_case.shipping_allow_runtime_free_shipping_override
        and runtime_free_shipping_for_mode is not None
    ):
        if selected_free_shipping != runtime_free_shipping_for_mode:
            policy_overrides.append("runtime_free_shipping_override")
        selected_free_shipping = runtime_free_shipping_for_mode
        free_shipping_source = "shipping_resolver.selection"

    row_free_shipping = row_shipping_input.get("free_shipping")
    if isinstance(row_free_shipping, bool):
        if selected_free_shipping != row_free_shipping:
            policy_overrides.append("spreadsheet_free_shipping_override")
        selected_free_shipping = row_free_shipping
        free_shipping_source = "spreadsheet.header"

    mandatory_free_shipping_detected = bool(
        use_case.shipping_mandatory_free_shipping_tags.intersection(selected_tags)
    )
    mandatory_free_shipping_enforced = False
    if (
        use_case.shipping_enforce_mandatory_free_shipping
        and mandatory_free_shipping_detected
        and not selected_free_shipping
    ):
        selected_free_shipping = True
        free_shipping_source = "policy.mandatory_free_shipping_tag"
        mandatory_free_shipping_enforced = True
        policy_overrides.append("mandatory_free_shipping_enforced")

    config_shipping: dict[str, Any] = {
        "mode": shipping_mode,
        "tags": selected_tags,
        "local_pick_up": False,
        "free_shipping": selected_free_shipping,
        "logistic_type": None,
    }
    logistic_type_source = "runtime.none"
    logistic_type_for_mode = state["resolved_logistic_type_by_mode"].get(shipping_mode)
    if logistic_type_for_mode:
        config_shipping["logistic_type"] = logistic_type_for_mode
        logistic_type_source = "shipping_resolver.selection"
    elif state["resolved_logistic_type"] and shipping_mode == state["requested_mode"]:
        config_shipping["logistic_type"] = state["resolved_logistic_type"]
        if state["resolved_logistic_type_source"]:
            logistic_type_source = state["resolved_logistic_type_source"]

    selected_local_pick_up = use_case._coerce_shipping_bool(
        config_shipping.get("local_pick_up", False)
    )
    if selected_local_pick_up is None:
        selected_local_pick_up = False
    local_pick_up_source = "default.false"
    row_local_pick_up = row_shipping_input.get("local_pick_up")
    if isinstance(row_local_pick_up, bool):
        if selected_local_pick_up != row_local_pick_up:
            policy_overrides.append("spreadsheet_local_pick_up_override")
        selected_local_pick_up = row_local_pick_up
        local_pick_up_source = "spreadsheet.header"
    config_shipping["local_pick_up"] = selected_local_pick_up

    config_shipping = {k: v for k, v in config_shipping.items() if v is not None}
    selected_logistic_type = config_shipping.get("logistic_type")

    constraints: dict[str, Any] = {"category_id": category_id}
    if category_id:
        policy_summary = use_case._get_policy_artifact(category_id).get("policy_summary")
        if isinstance(policy_summary, dict):
            constraints.update(
                {
                    "listing_allowed": policy_summary.get("listing_allowed"),
                    "category_status": policy_summary.get("status"),
                }
            )
    if runtime_constraints_for_mode:
        constraints["runtime"] = dict(runtime_constraints_for_mode)
    constraints["mandatory_free_shipping_tags"] = sorted(
        use_case.shipping_mandatory_free_shipping_tags
    )
    constraints["mandatory_free_shipping_detected"] = mandatory_free_shipping_detected
    constraints["mandatory_free_shipping_enforced"] = mandatory_free_shipping_enforced

    use_case._current_shipping_policy = {
        "decision": {
            "source": state["decision_source"],
            "reason": state["decision_reason"],
            "requested_mode": state["requested_mode"],
            "selected_mode": shipping_mode,
            "default_mode": "not_specified",
            "fallback_applied": state["fallback_applied"],
            "mode_configured": (
                shipping_mode in state["resolved_available_modes"]
                if state["resolved_available_modes"]
                else False
            ),
            "available_modes": sorted(
                {str(mode) for mode in state["resolved_available_modes"] if str(mode).strip()}
            ),
            "selected_logistic_type": selected_logistic_type,
            "logistic_type_source": logistic_type_source,
            "selected_tags": list(selected_tags),
            "tags_source": tags_source,
            "selected_free_shipping": selected_free_shipping,
            "free_shipping_source": free_shipping_source,
            "selected_local_pick_up": selected_local_pick_up,
            "local_pick_up_source": local_pick_up_source,
            "row_shipping_input": row_shipping_input,
            "policy_overrides": policy_overrides,
            "constraints": constraints,
        },
        "payload": dict(config_shipping),
        "cause_decisions": [],
    }

    logger.info(f"Shipping config for {shipping_mode} mode: {config_shipping}")
    return config_shipping


def build_shipping_config(
    use_case: Any,
    category_id: str | None = None,
    row_attributes: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build shipping configuration from runtime seller capabilities and row headers."""
    default_mode = "not_specified"
    state = _initialize_shipping_resolution_state(default_mode)
    _merge_resolver_selection(use_case, state, default_mode)
    row_shipping_input = extract_row_shipping_input(use_case, row_attributes)
    _apply_mode_intent_overrides(use_case, state, row_shipping_input)
    shipping_mode = _normalize_shipping_mode(state, default_mode)
    runtime_tags_for_mode, runtime_constraints_for_mode, runtime_free_shipping_for_mode = (
        _resolve_runtime_policy_for_mode(use_case, state, shipping_mode)
    )
    return _assemble_shipping_payload(
        use_case,
        state,
        category_id=category_id,
        row_shipping_input=row_shipping_input,
        shipping_mode=shipping_mode,
        runtime_tags_for_mode=runtime_tags_for_mode,
        runtime_constraints_for_mode=runtime_constraints_for_mode,
        runtime_free_shipping_for_mode=runtime_free_shipping_for_mode,
    )
