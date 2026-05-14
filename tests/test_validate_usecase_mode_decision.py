"""Validation decision-mode tests split from validation-only use-case suite."""

from __future__ import annotations

from mercadolivre_upload.application.publish_product import PublishProductUseCase
from tests.support.validate_usecase_mode import (
    _base_config,
    _build_product,
    _ImageUploader,
    _ValidationPublisher,
    _ValidationResolver,
)


def test_validation_only_mode_validates_without_publishing() -> None:
    publisher = _ValidationPublisher()
    use_case = PublishProductUseCase(
        category_resolver=_ValidationResolver(),  # type: ignore[arg-type]
        publisher=publisher,  # type: ignore[arg-type]
        image_uploader=_ImageUploader(),  # type: ignore[arg-type]
        config=_base_config(),
        validation_only=True,
        enable_feedback=False,
        enable_fiscal_submission=False,
    )

    result = use_case.execute([_build_product()], "MLB1234")

    assert result["success"] is True
    assert result["validated"] == 1
    assert result["published"] == 1
    assert result["failed"] == 0
    assert len(publisher.validated_items) == 1
    assert publisher.created_items == []
    item_result = result["item_results"][0]
    assert item_result["status"] == "success"
    assert isinstance(item_result.get("policy_hash"), str)
    assert len(item_result["policy_hash"]) == 64
    assert item_result["policy_summary"]["category_id"] == "MLB1234"
    assert item_result["policy_summary"]["listing_type_count"] == 2
    assert isinstance(item_result.get("schema_contract_hash"), str)
    assert len(item_result["schema_contract_hash"]) == 64
    assert item_result["schema_contract_summary"]["category_id"] == "MLB1234"
    assert item_result["category_input"] == "MLB1234"
    assert item_result["category_resolved_id"] == "MLB1234"
    assert item_result["resolution_strategy"] == "direct_id"
    assert item_result["category_path"] == []
    rollout_flags = item_result["rollout_flags"]
    assert rollout_flags["strict_warning_gate_mode"] == "enforce"
    assert rollout_flags["image_diagnostics_gate_mode"] == "enforce"
    assert rollout_flags["flow_user_products_enabled"] is True


def test_validation_only_mode_surfaces_validation_cause_codes() -> None:
    publisher = _ValidationPublisher(
        causes=[
            {
                "type": "error",
                "code": "body.invalid_fields",
                "message": "The fields [price] are invalid for requested call.",
            }
        ]
    )
    use_case = PublishProductUseCase(
        category_resolver=_ValidationResolver(),  # type: ignore[arg-type]
        publisher=publisher,  # type: ignore[arg-type]
        image_uploader=_ImageUploader(),  # type: ignore[arg-type]
        config=_base_config(),
        validation_only=True,
        enable_feedback=False,
        enable_fiscal_submission=False,
    )

    result = use_case.execute([_build_product()], "MLB1234")

    assert result["success"] is False
    assert result["validated"] == 0
    assert result["failed"] == 1
    assert len(publisher.validated_items) == 1
    assert publisher.created_items == []
    item_result = result["item_results"][0]
    assert item_result["status"] == "failed"
    assert item_result["cause_codes"] == ["body.invalid_fields"]
    assert item_result["cause_taxonomy"][0]["classification"] == "blocking_error"
    assert item_result["validation_decision"]["action"] == "block"
    assert item_result["validation_decision"]["mode"] == "strict"
    assert isinstance(item_result.get("policy_hash"), str)


def test_validation_only_mode_persists_informational_warning_taxonomy() -> None:
    publisher = _ValidationPublisher(
        causes=[
            {
                "type": "warning",
                "code": "item.pictures.without_main",
                "message": "Main picture is recommended for better conversion.",
            }
        ]
    )
    use_case = PublishProductUseCase(
        category_resolver=_ValidationResolver(),  # type: ignore[arg-type]
        publisher=publisher,  # type: ignore[arg-type]
        image_uploader=_ImageUploader(),  # type: ignore[arg-type]
        config=_base_config(),
        validation_only=True,
        enable_feedback=False,
        enable_fiscal_submission=False,
    )

    result = use_case.execute([_build_product()], "MLB1234")

    assert result["success"] is True
    item_result = result["item_results"][0]
    assert item_result["status"] == "success"
    assert item_result["cause_codes"] == ["item.pictures.without_main"]
    assert item_result["cause_taxonomy"][0]["classification"] == "informational_warning"
    assert item_result["validation_decision"]["action"] == "allow"
    assert item_result["validation_status"] == "validation_passed_with_warnings"
    assert item_result["validation_report"]["warnings"][0]["code"] == "item.pictures.without_main"


def test_publish_mode_continues_to_publish_on_warning_only_validation() -> None:
    publisher = _ValidationPublisher(
        causes=[
            {
                "type": "warning",
                "code": "item.shipping.mandatory_free_shipping",
                "message": "Mandatory free shipping added.",
            }
        ]
    )
    use_case = PublishProductUseCase(
        category_resolver=_ValidationResolver(),  # type: ignore[arg-type]
        publisher=publisher,  # type: ignore[arg-type]
        image_uploader=_ImageUploader(),  # type: ignore[arg-type]
        config=_base_config(),
        validation_only=False,
        enable_feedback=False,
        enable_fiscal_submission=False,
    )

    result = use_case.execute([_build_product()], "MLB1234")

    assert result["success"] is True
    assert len(publisher.created_items) == 1
    item_result = result["item_results"][0]
    assert item_result["status"] == "success"
    assert item_result["validation_status"] == "validation_passed_with_warnings"
    assert (
        item_result["validation_report"]["warnings"][0]["code"]
        == "item.shipping.mandatory_free_shipping"
    )


def test_publish_mode_blocks_on_mixed_warning_and_error_validation() -> None:
    publisher = _ValidationPublisher(
        causes=[
            {"type": "warning", "code": "shipping.lost_me1_by_user", "message": "warn"},
            {"type": "error", "code": "item.price.invalid", "message": "bad price"},
        ]
    )
    use_case = PublishProductUseCase(
        category_resolver=_ValidationResolver(),  # type: ignore[arg-type]
        publisher=publisher,  # type: ignore[arg-type]
        image_uploader=_ImageUploader(),  # type: ignore[arg-type]
        config=_base_config(),
        validation_only=False,
        enable_feedback=False,
        enable_fiscal_submission=False,
    )

    result = use_case.execute([_build_product()], "MLB1234")

    assert result["success"] is False
    assert publisher.created_items == []
    item_result = result["item_results"][0]
    assert item_result["status"] == "failed"
    assert item_result["validation_status"] == "validation_failed"
    assert item_result["validation_report"]["warnings"][0]["code"] == "shipping.lost_me1_by_user"
    assert item_result["validation_report"]["errors"][0]["code"] == "item.price.invalid"


def test_validation_only_mode_marks_retryable_error_in_controlled_mode() -> None:
    publisher = _ValidationPublisher(
        causes=[
            {
                "type": "error",
                "code": "item.internal_error",
                "message": "Temporary internal error, try again.",
            }
        ]
    )
    config = _base_config()
    config["validation_decision_mode"] = "controlled"
    use_case = PublishProductUseCase(
        category_resolver=_ValidationResolver(),  # type: ignore[arg-type]
        publisher=publisher,  # type: ignore[arg-type]
        image_uploader=_ImageUploader(),  # type: ignore[arg-type]
        config=config,
        validation_only=True,
        enable_feedback=False,
        enable_fiscal_submission=False,
    )

    result = use_case.execute([_build_product()], "MLB1234")

    assert result["success"] is False
    item_result = result["item_results"][0]
    assert item_result["status"] == "failed"
    assert item_result["cause_taxonomy"][0]["classification"] == "retryable_error"
    assert item_result["validation_decision"]["action"] == "retry"
    assert item_result["validation_decision"]["mode"] == "controlled"
