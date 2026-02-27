"""State and reporting helpers for publish use-case internals."""

from __future__ import annotations

from typing import Any


def build_rollout_flags_artifact(use_case: Any) -> dict[str, Any]:
    """Build static rollout feature flag snapshot for item/report metadata."""
    return {
        "validation_decision_mode": use_case.validation_decision_mode,
        "strict_warning_gate_mode": use_case.strict_warning_gate_mode,
        "strict_attribute_warnings": use_case.strict_attribute_warnings,
        "image_diagnostics_gate_mode": use_case.image_diagnostics_gate_mode,
        "flow_user_products_enabled": use_case.flow_user_products_enabled,
        "flow_blocked_behavior": use_case.flow_blocked_behavior,
        "shipping_non_blocking_codes": sorted(use_case.shipping_non_blocking_codes),
        "shipping_mandatory_free_shipping_tags": sorted(
            use_case.shipping_mandatory_free_shipping_tags
        ),
        "shipping_enforce_mandatory_free_shipping": (
            use_case.shipping_enforce_mandatory_free_shipping
        ),
        "shipping_allow_runtime_tag_overrides": use_case.shipping_allow_runtime_tag_overrides,
        "shipping_allow_runtime_free_shipping_override": (
            use_case.shipping_allow_runtime_free_shipping_override
        ),
        "api_validation_repair_enabled": use_case.api_validation_repair_enabled,
        "api_validation_repair_scope": use_case.api_validation_repair_scope,
        "api_validation_repair_max_attempts": use_case.api_validation_repair_max_attempts,
        "api_validation_repair_detect_mode": use_case.api_validation_repair_detect_mode,
        "api_validation_repair_drop_required_attributes": (
            use_case.api_validation_repair_drop_required_attributes
        ),
    }


def annotate_image_diagnostics_artifact(
    artifact: dict[str, Any],
    *,
    gate_mode: str,
) -> dict[str, Any]:
    """Attach gate decision metadata to image diagnostics artifact."""
    normalized = dict(artifact)
    raw_issues = normalized.get("issues", [])
    issues = (
        [str(issue) for issue in raw_issues if str(issue).strip()]
        if isinstance(raw_issues, list)
        else []
    )
    gate_blocks = gate_mode == "enforce"
    action = "allow"
    if gate_mode == "disabled":
        action = "skip"
    elif gate_blocks and issues:
        action = "block"

    normalized["gate_mode"] = gate_mode
    normalized["gate_blocks"] = gate_blocks
    normalized["gate_decision"] = {
        "action": action,
        "issue_count": len(issues),
    }
    return normalized


def reset_execution_state(use_case: Any) -> None:
    """Reset per-run counters and artifacts."""
    use_case.published = 0
    use_case.failed = 0
    use_case.errors = []
    use_case.fiscal_results = []
    use_case.clip_results = []
    use_case.item_results = []
    use_case._pending_fiscal = []
    use_case._category_policy_cache = {}
    use_case._category_schema_contract_cache = {}
    use_case._category_non_fillable_attribute_ids_cache = {}
    use_case._current_cause_codes = []
    use_case._current_preflight_artifact = {"identifier_gate": {"checked": False, "violations": []}}
    use_case._current_cause_taxonomy = []
    use_case._current_validation_decision = {}
    use_case._current_validation_repair = {}
    use_case._current_image_diagnostics = None
    use_case._current_shipping_policy = None
    use_case._current_flow_artifact = {}
    use_case._current_publish_category_id = None
    use_case._current_publish_sku = None
    use_case._current_variation_reference_attributes = []
    use_case._category_resolution_context_cache = {}


def build_stats(use_case: Any) -> dict[str, Any]:
    """Build publishing statistics payload."""
    stats: dict[str, Any] = {
        "published": use_case.published,
        "failed": use_case.failed,
        "total": use_case.published + use_case.failed,
        "errors": use_case.errors,
    }

    if use_case.feedback:
        stats["feedback"] = use_case.feedback.get_feedback_summary()

    if use_case.fiscal_results:
        fiscal_success = sum(1 for result in use_case.fiscal_results if result.success)
        fiscal_failed = len(use_case.fiscal_results) - fiscal_success
        stats["fiscal"] = {
            "submitted": len(use_case.fiscal_results),
            "success": fiscal_success,
            "failed": fiscal_failed,
        }

    if use_case.clip_results:
        clip_success = sum(result.get("clips_uploaded", 0) for result in use_case.clip_results)
        clip_failed = sum(result.get("clips_failed", 0) for result in use_case.clip_results)
        stats["clips"] = {
            "attempted": len(use_case.clip_results),
            "success": clip_success,
            "failed": clip_failed,
            "details": use_case.clip_results,
        }

    return stats


def get_problematic_attributes(use_case: Any) -> dict[str, int]:
    """Return attributes that frequently cause errors."""
    if use_case.feedback:
        raw_problematic = use_case.feedback.get_problematic_attributes()
        if isinstance(raw_problematic, dict):
            problematic: dict[str, int] = {}
            for key, raw_value in raw_problematic.items():
                key_text = str(key).strip()
                if not key_text:
                    continue
                try:
                    problematic[key_text] = int(raw_value)
                except (TypeError, ValueError):
                    continue
            return problematic
    return {}
