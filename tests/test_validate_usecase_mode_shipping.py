"""Validation shipping-policy tests split from validation-only use-case suite."""

from __future__ import annotations

from mercadolivre_upload.application.publish_product import PublishProductUseCase
from tests.support.validate_usecase_mode import (
    _base_config,
    _build_product,
    _FixedShippingResolver,
    _ImageUploader,
    _SelectionShippingResolver,
    _shipping_config,
    _ValidationPublisher,
    _ValidationResolver,
)


def test_validation_only_mode_exposes_shipping_policy_metadata() -> None:
    publisher = _ValidationPublisher()
    config = _base_config()
    config["shipping"] = _shipping_config()
    use_case = PublishProductUseCase(
        category_resolver=_ValidationResolver(),  # type: ignore[arg-type]
        publisher=publisher,  # type: ignore[arg-type]
        image_uploader=_ImageUploader(),  # type: ignore[arg-type]
        shipping_resolver=_FixedShippingResolver("me2"),  # type: ignore[arg-type]
        config=config,
        validation_only=True,
        enable_feedback=False,
        enable_fiscal_submission=False,
    )

    result = use_case.execute([_build_product()], "MLB1234")

    item_result = result["item_results"][0]
    decision = item_result["shipping_policy"]["decision"]
    assert decision["source"] == "shipping_resolver"
    assert decision["selected_mode"] == "me2"
    assert decision["mode_configured"] is True
    assert decision["available_modes"] == ["me2"]
    assert decision["constraints"]["category_id"] == "MLB1234"
    assert decision["constraints"]["listing_allowed"] is True
    assert decision["constraints"]["category_status"] == "enabled"
    assert item_result["shipping_policy"]["payload"]["mode"] == "me2"


def test_validation_only_mode_exposes_selection_logistic_type_metadata() -> None:
    publisher = _ValidationPublisher()
    config = _base_config()
    config["shipping"] = _shipping_config()
    use_case = PublishProductUseCase(
        category_resolver=_ValidationResolver(),  # type: ignore[arg-type]
        publisher=publisher,  # type: ignore[arg-type]
        image_uploader=_ImageUploader(),  # type: ignore[arg-type]
        shipping_resolver=_SelectionShippingResolver("me2", logistic_type="fulfillment"),  # type: ignore[arg-type]
        config=config,
        validation_only=True,
        enable_feedback=False,
        enable_fiscal_submission=False,
    )

    result = use_case.execute([_build_product()], "MLB1234")

    item_result = result["item_results"][0]
    decision = item_result["shipping_policy"]["decision"]
    assert decision["source"] == "shipping_resolver.selection"
    assert decision["selected_mode"] == "me2"
    assert decision["selected_logistic_type"] == "fulfillment"
    assert decision["logistic_type_source"] == "shipping_resolver.selection"
    assert item_result["shipping_policy"]["payload"]["logistic_type"] == "fulfillment"


def test_validation_only_mode_applies_row_shipping_headers() -> None:
    publisher = _ValidationPublisher()
    config = _base_config()
    use_case = PublishProductUseCase(
        category_resolver=_ValidationResolver(),  # type: ignore[arg-type]
        publisher=publisher,  # type: ignore[arg-type]
        image_uploader=_ImageUploader(),  # type: ignore[arg-type]
        shipping_resolver=_FixedShippingResolver("me2"),  # type: ignore[arg-type]
        config=config,
        validation_only=True,
        enable_feedback=False,
        enable_fiscal_submission=False,
    )

    product = _build_product(
        {
            "Forma de envio": "Mercado Envios",
            "Custo de envio": "Por conta do comprador",
            "Retirar pessoalmente": "Não aceito",
        }
    )
    result = use_case.execute([product], "MLB1234")

    item_result = result["item_results"][0]
    decision = item_result["shipping_policy"]["decision"]
    payload = item_result["shipping_policy"]["payload"]
    assert decision["source"] == "spreadsheet.headers"
    assert decision["row_shipping_input"]["mode_intent"] == "marketplace"
    assert decision["free_shipping_source"] == "spreadsheet.header"
    assert decision["local_pick_up_source"] == "spreadsheet.header"
    assert payload["mode"] == "me2"
    assert payload["free_shipping"] is False
    assert payload["local_pick_up"] is False


def test_validation_only_mode_enforces_mandatory_free_shipping_tag_from_selection() -> None:
    publisher = _ValidationPublisher()
    config = _base_config()
    config["shipping"] = _shipping_config()
    use_case = PublishProductUseCase(
        category_resolver=_ValidationResolver(),  # type: ignore[arg-type]
        publisher=publisher,  # type: ignore[arg-type]
        image_uploader=_ImageUploader(),  # type: ignore[arg-type]
        shipping_resolver=_SelectionShippingResolver(  # type: ignore[arg-type]
            "me2",
            tags=["mandatory_free_shipping"],
            free_shipping=False,
            constraints={"carrier": "me2"},
        ),
        config=config,
        validation_only=True,
        enable_feedback=False,
        enable_fiscal_submission=False,
    )

    result = use_case.execute([_build_product()], "MLB1234")

    item_result = result["item_results"][0]
    decision = item_result["shipping_policy"]["decision"]
    assert decision["tags_source"] == "shipping_resolver.selection"
    assert decision["selected_tags"] == ["mandatory_free_shipping"]
    assert decision["selected_free_shipping"] is True
    assert decision["free_shipping_source"] == "policy.mandatory_free_shipping_tag"
    assert "mandatory_free_shipping_enforced" in decision["policy_overrides"]
    assert decision["constraints"]["runtime"] == {"carrier": "me2"}
    assert decision["constraints"]["mandatory_free_shipping_detected"] is True
    assert decision["constraints"]["mandatory_free_shipping_enforced"] is True
    assert item_result["shipping_policy"]["payload"]["tags"] == ["mandatory_free_shipping"]
    assert item_result["shipping_policy"]["payload"]["free_shipping"] is True


def test_validation_only_mode_allows_free_shipping_override_to_disable_enforcement() -> None:
    publisher = _ValidationPublisher()
    config = _base_config()
    config["shipping"] = _shipping_config()
    config["shipping_policy"] = {"enforce_mandatory_free_shipping": False}
    use_case = PublishProductUseCase(
        category_resolver=_ValidationResolver(),  # type: ignore[arg-type]
        publisher=publisher,  # type: ignore[arg-type]
        image_uploader=_ImageUploader(),  # type: ignore[arg-type]
        shipping_resolver=_SelectionShippingResolver(  # type: ignore[arg-type]
            "me2",
            tags=["mandatory_free_shipping"],
            free_shipping=False,
        ),
        config=config,
        validation_only=True,
        enable_feedback=False,
        enable_fiscal_submission=False,
    )

    result = use_case.execute([_build_product()], "MLB1234")

    item_result = result["item_results"][0]
    decision = item_result["shipping_policy"]["decision"]
    assert decision["selected_free_shipping"] is False
    assert decision["free_shipping_source"] == "shipping_resolver.selection"
    assert decision["constraints"]["mandatory_free_shipping_detected"] is True
    assert decision["constraints"]["mandatory_free_shipping_enforced"] is False
    assert item_result["shipping_policy"]["payload"]["free_shipping"] is False


def test_validation_only_treats_mandatory_free_shipping_added_as_non_blocking_warning() -> None:
    publisher = _ValidationPublisher(
        causes=[
            {
                "type": "warning",
                "code": "item.shipping.mandatory_free_shipping",
                "message": "Mandatory free shipping added",
            }
        ]
    )
    config = _base_config()
    use_case = PublishProductUseCase(
        category_resolver=_ValidationResolver(),  # type: ignore[arg-type]
        publisher=publisher,  # type: ignore[arg-type]
        image_uploader=_ImageUploader(),  # type: ignore[arg-type]
        shipping_resolver=_FixedShippingResolver("me2"),  # type: ignore[arg-type]
        config=config,
        validation_only=True,
        enable_feedback=False,
        enable_fiscal_submission=False,
    )

    result = use_case.execute([_build_product()], "MLB1234")

    assert result["success"] is True
    item_result = result["item_results"][0]
    assert item_result["status"] == "success"
    assert item_result["shipping_policy"]["cause_decisions"][0]["classification"] == "unknown"


def test_validation_only_blocks_deterministic_shipping_policy_warning() -> None:
    publisher = _ValidationPublisher(
        causes=[
            {
                "type": "warning",
                "code": "shipping.mode.not_allowed",
                "message": "Shipping mode me2 is not allowed for this seller.",
            }
        ]
    )
    config = _base_config()
    config["shipping"] = _shipping_config()
    use_case = PublishProductUseCase(
        category_resolver=_ValidationResolver(),  # type: ignore[arg-type]
        publisher=publisher,  # type: ignore[arg-type]
        image_uploader=_ImageUploader(),  # type: ignore[arg-type]
        shipping_resolver=_FixedShippingResolver("me2"),  # type: ignore[arg-type]
        config=config,
        validation_only=True,
        enable_feedback=False,
        enable_fiscal_submission=False,
    )

    result = use_case.execute([_build_product()], "MLB1234")

    assert result["success"] is False
    assert result["failed"] == 1
    item_result = result["item_results"][0]
    assert item_result["cause_codes"] == ["shipping.mode.not_allowed"]
    assert "deterministic shipping policy violation" in item_result["error"]
    assert item_result["shipping_policy"]["cause_decisions"][0]["classification"] == "blocking"


def test_validation_only_allows_configured_non_blocking_shipping_warning() -> None:
    publisher = _ValidationPublisher(
        causes=[
            {
                "type": "warning",
                "code": "shipping.free_shipping.cost_exceeded",
                "message": "Cost exceeded for mandatory free shipping threshold.",
            }
        ]
    )
    config = _base_config()
    config["shipping"] = _shipping_config()
    config["shipping_policy"] = {"non_blocking_codes": ["shipping.free_shipping.cost_exceeded"]}
    use_case = PublishProductUseCase(
        category_resolver=_ValidationResolver(),  # type: ignore[arg-type]
        publisher=publisher,  # type: ignore[arg-type]
        image_uploader=_ImageUploader(),  # type: ignore[arg-type]
        shipping_resolver=_FixedShippingResolver("me2"),  # type: ignore[arg-type]
        config=config,
        validation_only=True,
        enable_feedback=False,
        enable_fiscal_submission=False,
    )

    result = use_case.execute([_build_product()], "MLB1234")

    assert result["success"] is True
    item_result = result["item_results"][0]
    assert item_result["status"] == "success"
    assert item_result["shipping_policy"]["cause_decisions"][0]["classification"] == "unknown"


def test_validation_only_keeps_retryable_shipping_warning_non_blocking() -> None:
    publisher = _ValidationPublisher(
        causes=[
            {
                "type": "warning",
                "code": "shipping.service_unavailable",
                "message": "Shipping service unavailable, try again later.",
            }
        ]
    )
    config = _base_config()
    config["shipping"] = _shipping_config()
    use_case = PublishProductUseCase(
        category_resolver=_ValidationResolver(),  # type: ignore[arg-type]
        publisher=publisher,  # type: ignore[arg-type]
        image_uploader=_ImageUploader(),  # type: ignore[arg-type]
        shipping_resolver=_FixedShippingResolver("me2"),  # type: ignore[arg-type]
        config=config,
        validation_only=True,
        enable_feedback=False,
        enable_fiscal_submission=False,
    )

    result = use_case.execute([_build_product()], "MLB1234")

    assert result["success"] is True
    item_result = result["item_results"][0]
    assert item_result["shipping_policy"]["cause_decisions"][0]["classification"] == "retryable"


def test_shipping_policy_keeps_resolved_mode_without_legacy_config_fallback() -> None:
    publisher = _ValidationPublisher()
    config = _base_config()
    config["shipping"] = _shipping_config()
    use_case = PublishProductUseCase(
        category_resolver=_ValidationResolver(),  # type: ignore[arg-type]
        publisher=publisher,  # type: ignore[arg-type]
        image_uploader=_ImageUploader(),  # type: ignore[arg-type]
        shipping_resolver=_FixedShippingResolver("custom_mode"),  # type: ignore[arg-type]
        config=config,
        validation_only=True,
        enable_feedback=False,
        enable_fiscal_submission=False,
    )

    result = use_case.execute([_build_product()], "MLB1234")

    item_result = result["item_results"][0]
    decision = item_result["shipping_policy"]["decision"]
    assert decision["source"] == "shipping_resolver"
    assert decision["fallback_applied"] is False
    assert item_result["shipping_policy"]["payload"]["mode"] == "custom_mode"
