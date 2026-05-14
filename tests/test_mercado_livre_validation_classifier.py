"""Tests for shared Mercado Livre validation response classification."""

from mercadolivre_upload.application.publish.internals.validation import (
    classify_mercado_livre_validation_response,
)


def test_204_empty_validation_response_passes() -> None:
    result = classify_mercado_livre_validation_response({})

    assert result.status == "validation_passed"
    assert result.should_block is False
    assert result.to_report_dict()["status"] == "validation_passed"


def test_warning_only_validation_response_continues_and_preserves_details() -> None:
    response = {
        "error": "validation_error",
        "status": 400,
        "cause": [
            {
                "type": "warning",
                "code": "item.attributes.omitted",
                "department": "items",
                "message": "Attribute WIDTH was omitted.",
                "references": ["item.attributes"],
            }
        ],
    }

    result = classify_mercado_livre_validation_response(response)
    report = result.to_report_dict()

    assert result.status == "validation_passed_with_warnings"
    assert result.should_block is False
    assert report["warnings"] == [
        {
            "type": "warning",
            "code": "item.attributes.omitted",
            "message": "Attribute WIDTH was omitted.",
            "department": "items",
            "references": ["item.attributes"],
        }
    ]
    assert report["raw_response"] == response


def test_mandatory_free_shipping_warning_continues() -> None:
    result = classify_mercado_livre_validation_response(
        {
            "error": "validation_error",
            "status": 400,
            "cause": [
                {
                    "type": "warning",
                    "code": "item.shipping.mandatory_free_shipping",
                    "message": "Mandatory free shipping added.",
                }
            ],
        }
    )

    assert result.status == "validation_passed_with_warnings"
    assert result.should_block is False


def test_lost_me1_warning_continues() -> None:
    result = classify_mercado_livre_validation_response(
        {
            "error": "validation_error",
            "status": 400,
            "cause": [
                {
                    "type": "warning",
                    "code": "shipping.lost_me1_by_user",
                    "message": "User has not mode me1.",
                }
            ],
        }
    )

    assert result.status == "validation_passed_with_warnings"
    assert result.should_block is False


def test_mixed_warning_and_error_blocks_and_preserves_both() -> None:
    result = classify_mercado_livre_validation_response(
        {
            "error": "validation_error",
            "status": 400,
            "cause": [
                {"type": "warning", "code": "shipping.lost_me1_by_user", "message": "warn"},
                {"type": "error", "code": "item.price.invalid", "message": "bad price"},
            ],
        }
    )

    report = result.to_report_dict()

    assert result.status == "validation_failed"
    assert result.should_block is True
    assert report["warnings"][0]["code"] == "shipping.lost_me1_by_user"
    assert report["errors"][0]["code"] == "item.price.invalid"


def test_error_only_validation_response_blocks() -> None:
    result = classify_mercado_livre_validation_response(
        {
            "error": "validation_error",
            "status": 400,
            "cause": [{"type": "error", "code": "item.title.required", "message": "missing"}],
        }
    )

    assert result.status == "validation_failed"
    assert result.should_block is True
    assert result.error_messages() == ["[item.title.required] | missing"]


def test_validation_error_without_clear_causes_blocks_conservatively() -> None:
    result = classify_mercado_livre_validation_response(
        {"error": "validation_error", "status": 400, "cause": []}
    )

    assert result.status == "validation_failed"
    assert result.should_block is True
    assert result.to_report_dict()["message"] == "validation_error"
