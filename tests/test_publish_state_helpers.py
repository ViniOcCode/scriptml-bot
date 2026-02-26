"""Tests for publish state/report helper functions."""

from __future__ import annotations

from types import SimpleNamespace

from mercadolivre_upload.application.publish.internals.state import (
    annotate_image_diagnostics_artifact,
    build_rollout_flags_artifact,
    build_stats,
    get_problematic_attributes,
    reset_execution_state,
)


class _FeedbackStub:
    def get_feedback_summary(self) -> dict[str, int]:
        return {"errors": 2}

    def get_problematic_attributes(self) -> dict[str, int]:
        return {"WIDTH": 3}


class _FiscalResultStub:
    def __init__(self, success: bool) -> None:
        self.success = success


def test_build_rollout_flags_artifact_uses_normalized_runtime_values() -> None:
    use_case = SimpleNamespace(
        validation_decision_mode="strict",
        strict_warning_gate_mode="enforce",
        strict_attribute_warnings=True,
        image_diagnostics_gate_mode="report_only",
        flow_user_products_enabled=True,
        flow_blocked_behavior="fail",
        shipping_non_blocking_codes={"b_code", "a_code"},
        shipping_mandatory_free_shipping_tags={"tag_z", "tag_a"},
        shipping_enforce_mandatory_free_shipping=False,
        shipping_allow_runtime_tag_overrides=False,
        shipping_allow_runtime_free_shipping_override=True,
    )

    artifact = build_rollout_flags_artifact(use_case)

    assert artifact["shipping_non_blocking_codes"] == ["a_code", "b_code"]
    assert artifact["shipping_mandatory_free_shipping_tags"] == ["tag_a", "tag_z"]
    assert artifact["image_diagnostics_gate_mode"] == "report_only"


def test_annotate_image_diagnostics_artifact_marks_gate_decision() -> None:
    enforced = annotate_image_diagnostics_artifact(
        {"issues": ["x", " ", "y"]},
        gate_mode="enforce",
    )
    disabled = annotate_image_diagnostics_artifact({"issues": ["x"]}, gate_mode="disabled")

    assert enforced["gate_decision"] == {"action": "block", "issue_count": 2}
    assert disabled["gate_decision"] == {"action": "skip", "issue_count": 1}


def test_reset_execution_state_clears_per_run_fields() -> None:
    use_case = SimpleNamespace(
        published=10,
        failed=3,
        errors=["err"],
        fiscal_results=[_FiscalResultStub(True)],
        clip_results=[{"clips_uploaded": 2, "clips_failed": 1}],
        item_results=[{"id": "x"}],
        _pending_fiscal=[("MLB1", object())],
        _category_policy_cache={"MLB": {"x": 1}},
        _category_schema_contract_cache={"MLB": {"x": 1}},
        _category_non_fillable_attribute_ids_cache={"MLB": {"X"}},
        _current_cause_codes=["item.attributes.invalid"],
        _current_preflight_artifact={"old": True},
        _current_cause_taxonomy=[{"code": "x"}],
        _current_validation_decision={"ok": False},
        _current_image_diagnostics={"issues": ["x"]},
        _current_shipping_policy={"blocking": True},
        _current_flow_artifact={"flow": "legacy"},
        _current_publish_category_id="MLB123",
        _current_publish_sku="SKU-1",
        _current_variation_reference_attributes=[{"id": "COLOR"}],
    )

    reset_execution_state(use_case)

    assert use_case.published == 0
    assert use_case.failed == 0
    assert use_case.errors == []
    assert use_case._pending_fiscal == []
    assert use_case._current_preflight_artifact == {
        "identifier_gate": {"checked": False, "violations": []}
    }
    assert use_case._current_publish_sku is None


def test_build_stats_and_problematic_attributes_reflect_feedback() -> None:
    use_case = SimpleNamespace(
        published=3,
        failed=1,
        errors=["x"],
        feedback=_FeedbackStub(),
        fiscal_results=[_FiscalResultStub(True), _FiscalResultStub(False)],
        clip_results=[
            {"clips_uploaded": 2, "clips_failed": 1},
            {"clips_uploaded": 1, "clips_failed": 0},
        ],
    )

    stats = build_stats(use_case)

    assert stats["total"] == 4
    assert stats["feedback"] == {"errors": 2}
    assert stats["fiscal"] == {"submitted": 2, "success": 1, "failed": 1}
    assert stats["clips"]["success"] == 3
    assert get_problematic_attributes(use_case) == {"WIDTH": 3}

    use_case.feedback = None
    assert get_problematic_attributes(use_case) == {}
