"""Flow-routing helpers extracted from publish orchestration."""

from __future__ import annotations

import logging
from typing import Any, cast

from .publish_product_constants import (
    AVAILABLE_ROUTING_FLOWS,
    IMPLEMENTED_ROUTING_FLOWS,
    USER_PRODUCTS_SELLER_TAG,
)

logger = logging.getLogger(__name__)


def get_seller_capabilities_artifact(use_case: Any) -> dict[str, Any]:
    """Read seller capability tags once and reuse within the use case instance."""
    cached_artifact = use_case._seller_capabilities_artifact
    if isinstance(cached_artifact, dict):
        return cast(dict[str, Any], cached_artifact)

    seller_info: dict[str, Any] = {}
    source = "unavailable"
    for endpoint_name, method_name in (
        ("publisher/get_users_me", "get_publisher_users_me"),
        ("users/me", "get_users_me"),
    ):
        getter = getattr(use_case.publisher, method_name, None)
        if not callable(getter):
            continue
        try:
            payload = getter()
        except Exception as error:
            logger.warning(
                "Could not fetch seller capabilities from %s: %s",
                endpoint_name,
                error,
            )
            continue
        if isinstance(payload, dict):
            seller_info = payload
            source = endpoint_name
            break
        logger.warning(
            "Unexpected seller capability payload from %s: %s",
            endpoint_name,
            type(payload).__name__,
        )

    tags = use_case._normalize_seller_tags(seller_info.get("tags"))
    has_user_products_tag = USER_PRODUCTS_SELLER_TAG in tags
    artifact = {
        "source": source,
        "seller_id": seller_info.get("id"),
        "tags": tags,
        "has_user_product_seller_tag": has_user_products_tag,
    }
    use_case._seller_capabilities_artifact = artifact
    return artifact


def get_flow_routing_artifact(use_case: Any) -> dict[str, Any]:
    """Resolve deterministic publish flow routing metadata."""
    cached_artifact = use_case._flow_routing_artifact
    if isinstance(cached_artifact, dict):
        return cast(dict[str, Any], cached_artifact)

    flow_config = use_case.config.get("flow_routing", {})
    mode = "auto"
    forced_flow: str | None = None
    if isinstance(flow_config, dict):
        raw_mode = flow_config.get("mode")
        if isinstance(raw_mode, str) and raw_mode.strip():
            mode = raw_mode.strip().lower()
        raw_forced_flow = flow_config.get("forced_flow", flow_config.get("flow"))
        if isinstance(raw_forced_flow, str) and raw_forced_flow.strip():
            forced_flow = raw_forced_flow.strip().lower()

    if forced_flow:
        mode = "forced"
    if mode not in {"auto", "forced"}:
        logger.warning("Invalid flow routing mode '%s'; falling back to auto", mode)
        mode = "auto"

    seller_capabilities = get_seller_capabilities_artifact(use_case)
    seller_has_tag = bool(seller_capabilities.get("has_user_product_seller_tag"))
    user_products_enabled = use_case.flow_user_products_enabled
    user_products_validate_supported = callable(
        getattr(use_case.publisher, "validate_user_product_item", None)
    )
    user_products_create_supported = callable(
        getattr(use_case.publisher, "create_user_product_item", None)
    )
    user_products_route_supported = (
        user_products_validate_supported and user_products_create_supported
    )

    selected_flow = "legacy"
    reason = "Defaulting to legacy flow for backward compatibility."
    blocked = False
    error_message: str | None = None
    fallback_applied = False
    fallback_reason: str | None = None

    if mode == "forced":
        if forced_flow not in AVAILABLE_ROUTING_FLOWS:
            blocked = True
            error_message = (
                f"Forced publish flow '{forced_flow or 'unset'}' is not supported. "
                f"Supported values: {', '.join(sorted(AVAILABLE_ROUTING_FLOWS))}."
            )
            reason = "Configured forced flow is invalid."
            selected_flow = forced_flow or "legacy"
        elif forced_flow == "legacy":
            selected_flow = "legacy"
            reason = "Forced legacy flow selected by configuration."
        else:
            selected_flow = "user_products"
            if not user_products_enabled:
                blocked = True
                error_message = (
                    "Forced publish flow 'user_products' is disabled by rollout flag "
                    "'flow_routing.user_products_enabled'."
                )
                reason = "User-products flow was disabled by rollout controls."
            elif not seller_has_tag:
                blocked = True
                error_message = (
                    "Forced publish flow 'user_products' requires seller tag "
                    f"'{USER_PRODUCTS_SELLER_TAG}'."
                )
                reason = "Seller is not tagged for user-products flow."
            elif not user_products_route_supported:
                blocked = True
                error_message = (
                    "Forced publish flow 'user_products' requires publisher support for "
                    "'validate_user_product_item' and 'create_user_product_item'."
                )
                reason = "User-products route is not supported by publisher adapter."
            elif forced_flow not in IMPLEMENTED_ROUTING_FLOWS:
                blocked = True
                error_message = (
                    "Forced publish flow 'user_products' is not supported by this release."
                )
                reason = "User-products engine is not implemented yet."
    else:
        if seller_has_tag and user_products_enabled and user_products_route_supported:
            selected_flow = "user_products"
            reason = "Seller has user_product_seller capability; using user-products flow."
        elif seller_has_tag and user_products_enabled:
            reason = (
                "Seller has user_product_seller capability, but publisher adapter does not "
                "support user-products endpoints; using legacy flow."
            )
        elif seller_has_tag:
            reason = (
                "Seller has user_product_seller capability, but rollout disabled "
                "user-products flow; using legacy flow."
            )
        else:
            reason = "Seller does not have user_product_seller capability; using legacy flow."

    if blocked and use_case.flow_blocked_behavior == "fallback_legacy":
        fallback_applied = True
        fallback_reason = error_message or reason
        selected_flow = "legacy"
        blocked = False
        error_message = None
        reason = (
            "Flow routing fallback applied to legacy flow due to rollout setting "
            "'flow_routing.blocked_behavior=fallback_legacy'."
        )

    flow_routing: dict[str, Any] = {
        "mode": mode,
        "selected_flow": selected_flow,
        "seller_has_user_product_seller_tag": seller_has_tag,
        "seller_capability_source": seller_capabilities.get("source"),
        "reason": reason,
        "supported_flows": sorted(IMPLEMENTED_ROUTING_FLOWS),
        "blocked": blocked,
        "user_products_enabled": user_products_enabled,
        "user_products_route_supported": user_products_route_supported,
        "user_products_validate_supported": user_products_validate_supported,
        "user_products_create_supported": user_products_create_supported,
        "blocked_behavior": use_case.flow_blocked_behavior,
        "fallback_applied": fallback_applied,
    }
    if forced_flow:
        flow_routing["forced_flow"] = forced_flow
    if error_message:
        flow_routing["error"] = error_message
    if fallback_reason:
        flow_routing["fallback_reason"] = fallback_reason

    artifact = {"flow_routing": flow_routing}
    use_case._flow_routing_artifact = artifact
    return artifact
