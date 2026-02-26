"""Validation error-taxonomy tests split from validation-only use-case suite."""

from __future__ import annotations

from typing import Any

from mercadolivre_upload.application.publish_product import PublishProductUseCase
from tests.support.validate_usecase_mode import (
    _base_config,
    _build_product,
    _ImageUploader,
    _ValidationPublisher,
    _ValidationResolver,
)


def test_publish_mode_surfaces_taxonomy_for_publish_exception() -> None:
    class _Response:
        text = "raw publish error"

        @staticmethod
        def json() -> dict[str, Any]:
            return {
                "cause": [
                    {
                        "type": "error",
                        "code": "body.invalid_fields",
                        "message": "invalid attribute",
                    }
                ]
            }

    class _PublishErrorPublisher(_ValidationPublisher):
        def create_item(self, item: dict[str, Any]) -> dict[str, Any]:
            self.created_items.append(item)
            error = RuntimeError("publish failed")
            error.response = _Response()  # type: ignore[attr-defined]
            raise error

    publisher = _PublishErrorPublisher()
    use_case = PublishProductUseCase(
        category_resolver=_ValidationResolver(),  # type: ignore[arg-type]
        publisher=publisher,  # type: ignore[arg-type]
        image_uploader=_ImageUploader(),  # type: ignore[arg-type]
        config=_base_config(),
        enable_feedback=False,
        enable_fiscal_submission=False,
    )

    result = use_case.execute([_build_product()], "MLB1234")

    assert result["success"] is False
    assert result["published"] == 0
    assert result["failed"] == 1
    item_result = result["item_results"][0]
    assert item_result["cause_codes"] == ["body.invalid_fields"]
    assert item_result["cause_taxonomy"][0]["classification"] == "blocking_error"
    assert item_result["validation_decision"]["action"] == "block"


def test_validation_only_mode_uses_response_excerpt_for_non_json_validation_errors() -> None:
    class _Response:
        text = "upstream html payload"

        @staticmethod
        def json() -> dict[str, Any]:
            raise ValueError("not json")

    class _ValidationErrorPublisher(_ValidationPublisher):
        def validate_item(self, item: dict[str, Any]) -> dict[str, Any]:
            self.validated_items.append(item)
            error = RuntimeError("validation crashed")
            error.response = _Response()  # type: ignore[attr-defined]
            raise error

    publisher = _ValidationErrorPublisher()
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
    assert result["failed"] == 1
    assert "validation crashed - upstream html payload" in result["errors"][0]


def test_execute_row_build_failure_includes_observability_taxonomy() -> None:
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

    result = use_case.execute([{"sku": "SKU-BAD", "titulo": "Produto sem preço"}], "MLB1234")

    assert result["success"] is False
    assert result["failed"] == 1
    assert publisher.validated_items == []
    item_result = result["item_results"][0]
    assert item_result["cause_codes"] == ["input.row_build_failed"]
    assert item_result["cause_taxonomy"][0]["classification"] == "blocking_error"
    assert item_result["validation_decision"]["action"] == "block"
