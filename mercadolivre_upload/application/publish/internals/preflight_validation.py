"""Identifier and schema preflight helpers extracted from publish orchestration."""

from __future__ import annotations

import logging
from typing import Any

from mercadolivre_upload.shared.utils.text_utils import PortugueseTextNormalizer

from .identifier import select_empty_gtin_reason

logger = logging.getLogger(__name__)


def run_identifier_preflight_checks(
    use_case: Any,
    *,
    schema_contract: dict[str, Any],
    item: dict[str, Any],
) -> tuple[list[str], dict[str, Any]]:
    """Run deterministic identifier preflight checks and return report artifact."""
    identifier_contract = schema_contract.get("identifier_contract", {})
    if not isinstance(identifier_contract, dict):
        identifier_contract = {}

    gtin_required = bool(identifier_contract.get("gtin_required"))
    empty_gtin_reason_attribute_id = identifier_contract.get("empty_gtin_reason_attribute_id")
    fallback_reason_available = isinstance(empty_gtin_reason_attribute_id, str) and bool(
        empty_gtin_reason_attribute_id
    )
    allowed_reason_ids = {
        str(value).strip()
        for value in identifier_contract.get("empty_gtin_reason_allowed_value_ids", [])
        if str(value).strip()
    }
    allowed_reason_value_names = sorted(
        {
            str(value).strip()
            for value in identifier_contract.get("empty_gtin_reason_allowed_value_names", [])
            if str(value).strip()
        }
    )
    allowed_reason_names = {
        PortugueseTextNormalizer.normalize(value) for value in allowed_reason_value_names
    }

    default_reason_artifact = use_case._inject_default_empty_gtin_reason(
        item=item,
        gtin_required=gtin_required,
        empty_gtin_reason_attribute_id=(
            empty_gtin_reason_attribute_id
            if isinstance(empty_gtin_reason_attribute_id, str)
            else None
        ),
        allowed_reason_ids=allowed_reason_ids,
        allowed_reason_names=allowed_reason_value_names,
    )

    item_state = use_case._collect_identifier_state(item.get("attributes"))
    variations = item.get("variations", [])
    variation_states: list[dict[str, Any]] = []
    if isinstance(variations, list):
        for variation in variations:
            attrs = variation.get("attributes") if isinstance(variation, dict) else None
            variation_states.append(use_case._collect_identifier_state(attrs))

    variation_identifier_present = any(
        bool(state.get("has_identifier_attribute")) for state in variation_states
    )

    identifier_violations: list[str] = []
    if variation_identifier_present:
        for index, state in enumerate(variation_states, start=1):
            identifier_violations.extend(
                use_case._validate_identifier_state(
                    scope=f"Variation {index}",
                    state=state,
                    gtin_required=gtin_required,
                    fallback_reason_available=fallback_reason_available,
                    enforce_identifier_coverage=True,
                    allowed_reason_ids=allowed_reason_ids,
                    allowed_reason_names=allowed_reason_names,
                )
            )
    else:
        identifier_violations.extend(
            use_case._validate_identifier_state(
                scope="Item",
                state=item_state,
                gtin_required=gtin_required,
                fallback_reason_available=fallback_reason_available,
                enforce_identifier_coverage=False,
                allowed_reason_ids=allowed_reason_ids,
                allowed_reason_names=allowed_reason_names,
            )
        )

    artifact = {
        "checked": True,
        "gtin_required": gtin_required,
        "fallback_reason_available": fallback_reason_available,
        "variation_count": len(variations) if isinstance(variations, list) else 0,
        "variation_identifier_present": variation_identifier_present,
        "item_has_gtin": bool(item_state.get("gtin")),
        "item_has_empty_gtin_reason": bool(
            item_state.get("empty_gtin_reason_value_id")
            or item_state.get("empty_gtin_reason_value_name")
        ),
        "default_empty_gtin_reason": default_reason_artifact,
        "violations": identifier_violations,
    }
    return identifier_violations, artifact


def inject_default_empty_gtin_reason(
    use_case: Any,
    *,
    item: dict[str, Any],
    gtin_required: bool,
    empty_gtin_reason_attribute_id: str | None,
    allowed_reason_ids: set[str],
    allowed_reason_names: list[str],
) -> dict[str, Any]:
    """Inject configured EMPTY_GTIN_REASON when GTIN is missing."""
    artifact: dict[str, Any] = {
        "applied": False,
        "value_id": None,
        "value_name": None,
        "warning": None,
    }
    if not gtin_required:
        return artifact

    policy = use_case.config.get("identifier_policy")
    if not isinstance(policy, dict) or not bool(policy.get("auto_fill_empty_gtin_reason")):
        return artifact

    default_value_name = use_case._normalize_identifier_text(
        policy.get("default_empty_gtin_reason_value_name")
    )
    if default_value_name is None:
        return artifact

    attributes = item.get("attributes")
    if not isinstance(attributes, list):
        return artifact

    state = use_case._collect_identifier_state(attributes)
    if state.get("gtin"):
        return artifact
    if state.get("empty_gtin_reason_value_id") or state.get("empty_gtin_reason_value_name"):
        return artifact

    target_id = (
        empty_gtin_reason_attribute_id
        if isinstance(empty_gtin_reason_attribute_id, str) and empty_gtin_reason_attribute_id
        else "EMPTY_GTIN_REASON"
    )

    reason_attribute: dict[str, Any] | None = None
    for attribute in attributes:
        if not isinstance(attribute, dict):
            continue
        attribute_id = attribute.get("id")
        if isinstance(attribute_id, str) and attribute_id.strip().upper() == "EMPTY_GTIN_REASON":
            reason_attribute = attribute
            break

    if reason_attribute is None:
        reason_attribute = {"id": target_id}
        attributes.append(reason_attribute)

    selected_reason_id, selected_reason_name, warning_message = select_empty_gtin_reason(
        default_value_name=default_value_name,
        allowed_reason_ids=allowed_reason_ids,
        allowed_reason_names=allowed_reason_names,
    )

    if selected_reason_id is not None:
        reason_attribute["value_id"] = selected_reason_id
    else:
        reason_attribute.pop("value_id", None)
    if selected_reason_name is not None:
        reason_attribute["value_name"] = selected_reason_name
    else:
        reason_attribute.pop("value_name", None)

    artifact.update(
        {
            "applied": True,
            "value_id": selected_reason_id,
            "value_name": selected_reason_name,
            "warning": warning_message,
        }
    )
    if warning_message:
        logger.warning(warning_message)
    logger.warning("Auto-filled EMPTY_GTIN_REASON with configured default value for missing GTIN.")
    return artifact


def run_schema_contract_preflight(
    use_case: Any,
    *,
    category_id: str,
    item: dict[str, Any],
) -> list[str]:
    """Run deterministic preflight checks using compiled schema metadata."""
    compiled = use_case._get_schema_contract_compiled(category_id)
    schema_contract = compiled.get("schema_contract", {})
    if not isinstance(schema_contract, dict):
        use_case._current_preflight_artifact = {
            "identifier_gate": {"checked": False, "violations": []}
        }
        return []

    violations: list[str] = []
    identifier_violations, identifier_artifact = use_case._run_identifier_preflight_checks(
        schema_contract=schema_contract,
        item=item,
    )
    use_case._current_preflight_artifact = {"identifier_gate": identifier_artifact}

    required_ids_raw = schema_contract.get("required_attribute_ids", [])
    required_ids = {attr_id for attr_id in required_ids_raw if isinstance(attr_id, str)}
    required_ids.discard("")
    required_ids.discard("GTIN")
    required_ids.discard("EMPTY_GTIN_REASON")
    if required_ids:
        provided_ids = {
            attr.get("id")
            for attr in item.get("attributes", [])
            if isinstance(attr, dict) and isinstance(attr.get("id"), str)
        }
        missing = sorted(attr_id for attr_id in required_ids if attr_id not in provided_ids)
        if missing:
            violations.append(f"Missing required attributes: {', '.join(missing)}")

    limits = schema_contract.get("limits", {})
    if isinstance(limits, dict):
        pictures = item.get("pictures", [])
        picture_count = len(pictures) if isinstance(pictures, list) else 0
        max_pictures = limits.get("max_pictures")
        if isinstance(max_pictures, int) and max_pictures >= 0 and picture_count > max_pictures:
            violations.append(f"Pictures count {picture_count} exceeds category max {max_pictures}")

        variations = item.get("variations", [])
        if not isinstance(variations, list):
            variations = []
        if not variations:
            user_product = item.get("user_product", {})
            if isinstance(user_product, dict):
                user_product_variations = user_product.get("variations", [])
                if isinstance(user_product_variations, list):
                    variations = user_product_variations
        variation_count = len(variations)
        max_variations_allowed = limits.get("max_variations_allowed")
        if (
            isinstance(max_variations_allowed, int)
            and max_variations_allowed >= 0
            and variation_count > max_variations_allowed
        ):
            violations.append(
                "Variations count "
                f"{variation_count} exceeds category max {max_variations_allowed}"
            )

    violations.extend(identifier_violations)
    return violations


__all__ = [
    "inject_default_empty_gtin_reason",
    "run_identifier_preflight_checks",
    "run_schema_contract_preflight",
]
