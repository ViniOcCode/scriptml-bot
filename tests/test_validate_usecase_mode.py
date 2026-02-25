"""Tests for PublishProductUseCase validation-only execution mode."""

from __future__ import annotations

from typing import Any

from mercadolivre_upload.application.publish_product import PublishProductUseCase
from mercadolivre_upload.domain.attribute_metadata import AttributeMeta
from mercadolivre_upload.domain.fiscal.data import FiscalData
from mercadolivre_upload.domain.product.model import Product


class _ValidationResolver:
    def resolve_to_leaf(self, category_id: str) -> str:
        return category_id

    def is_listing_allowed(self, _category_id: str) -> bool:
        return True

    def get_attribute_metadata(self, _category_id: str) -> list[AttributeMeta]:
        return [AttributeMeta(id="BRAND", name="Marca", value_type="string", required=False)]

    def get_conditional_attributes(
        self, _category_id: str, _item_context: dict[str, Any]
    ) -> list[dict[str, Any]]:
        return []

    def get_category_data(self, category_id: str) -> dict[str, Any]:
        return {
            "id": category_id,
            "status": "enabled",
            "settings": {"status": "enabled", "listing_allowed": True},
        }

    def get_all_attributes(self, _category_id: str) -> list[dict[str, Any]]:
        return [
            {"id": "BRAND", "tags": {}},
            {"id": "MODEL", "tags": {"allow_variations": True}},
        ]


class _ValidationPublisher:
    def __init__(
        self,
        causes: list[dict[str, Any]] | None = None,
        users_me: dict[str, Any] | None = None,
    ):
        self.causes = causes or []
        self.listing_type_calls = 0
        self.sale_terms_calls = 0
        self.validated_items: list[dict[str, Any]] = []
        self.created_items: list[dict[str, Any]] = []
        self.validated_user_product_items: list[dict[str, Any]] = []
        self.created_user_product_items: list[dict[str, Any]] = []
        self.listing_types = [{"id": "gold_special"}, {"id": "free"}]
        self.sale_terms = [{"id": "WARRANTY_TYPE", "tags": {"required": True}}]
        self.users_me = users_me or {"id": 1234, "tags": []}

    def get_available_listing_types(self, _category_id: str) -> list[dict[str, Any]]:
        self.listing_type_calls += 1
        return list(self.listing_types)

    def get_category_sale_terms(self, _category_id: str) -> list[dict[str, Any]]:
        self.sale_terms_calls += 1
        return list(self.sale_terms)

    def validate_item(self, item: dict[str, Any]) -> dict[str, Any]:
        self.validated_items.append(item)
        return {"cause": self.causes}

    def validate_user_product_item(self, item: dict[str, Any]) -> dict[str, Any]:
        self.validated_user_product_items.append(item)
        return self.validate_item(item)

    def create_item(self, item: dict[str, Any]) -> dict[str, Any]:
        self.created_items.append(item)
        return {"id": "MLB1234567890"}

    def create_user_product_item(self, item: dict[str, Any]) -> dict[str, Any]:
        self.created_user_product_items.append(item)
        return self.create_item(item)

    def get_users_me(self) -> dict[str, Any]:
        return dict(self.users_me)


class _ImageUploader:
    def __init__(
        self,
        image_urls: list[str] | None = None,
        diagnostic_result: dict[str, Any] | None = None,
    ):
        self.image_urls = image_urls or ["https://example.com/image.jpg"]
        self.diagnostic_result = diagnostic_result

    def upload_images(self, _sku: str) -> list[str]:
        return list(self.image_urls)

    def get_uploaded_images(self) -> list[dict[str, str]]:
        return [
            {"url": image_url, "id": f"PIC-{index + 1}"}
            for index, image_url in enumerate(self.image_urls)
        ]

    def diagnose_images(
        self,
        *,
        sku: str,
        category_id: str,
        title: str | None,
        picture_urls: list[str],
        picture_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        del sku, category_id, title, picture_ids
        if self.diagnostic_result is None:
            return {
                "status": "unavailable",
                "available": False,
                "checked": 0,
                "issues": [],
                "results": [],
                "message": "Image diagnostics unavailable in test uploader.",
            }
        result = dict(self.diagnostic_result)
        result.setdefault("checked", len(picture_urls))
        result.setdefault("results", [])
        result.setdefault("issues", [])
        return result


class _FixedShippingResolver:
    def __init__(self, mode: str):
        self.mode = mode

    def get_best_shipping_mode(self) -> str:
        return self.mode


class _SelectionShippingResolver:
    def __init__(
        self,
        mode: str,
        logistic_type: str | None = None,
        tags: list[str] | None = None,
        free_shipping: bool | None = None,
        constraints: dict[str, Any] | None = None,
    ):
        self.mode = mode
        self.logistic_type = logistic_type
        self.tags = tags
        self.free_shipping = free_shipping
        self.constraints = constraints

    def get_best_shipping_selection(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"mode": self.mode, "logistic_type": self.logistic_type}
        if self.tags is not None:
            payload["tags"] = list(self.tags)
        if self.free_shipping is not None:
            payload["free_shipping"] = self.free_shipping
        if self.constraints is not None:
            payload["constraints"] = dict(self.constraints)
        return payload


class _SchemaContractResolver(_ValidationResolver):
    def __init__(
        self,
        *,
        all_attributes: list[dict[str, Any]] | None = None,
        settings: dict[str, Any] | None = None,
    ):
        if all_attributes is None:
            self._all_attributes = super().get_all_attributes("MLB1234")
        else:
            self._all_attributes = all_attributes
        merged_settings = {"status": "enabled", "listing_allowed": True}
        if isinstance(settings, dict):
            merged_settings.update(settings)
        self._settings = merged_settings

    def get_category_data(self, category_id: str) -> dict[str, Any]:
        return {
            "id": category_id,
            "status": "enabled",
            "settings": dict(self._settings),
        }

    def get_all_attributes(self, _category_id: str) -> list[dict[str, Any]]:
        return list(self._all_attributes)


def _build_product(attributes: dict[str, Any] | None = None) -> Product:
    title = "Produto teste"
    return Product(
        sku="SKU-1",
        title=title,
        description="Desc",
        price=10.0,
        available_quantity=1,
        condition="new",
        fiscal=FiscalData(sku="SKU-1", title=title),
        attributes=attributes or {},
    )


def _base_config() -> dict[str, Any]:
    return {
        "core_item_fields": {
            "defaults": {
                "currency_id": "BRL",
                "buying_mode": "buy_it_now",
                "listing_type_id": "gold_special",
                "sale_terms": [],
            }
        }
    }


def _shipping_config() -> dict[str, Any]:
    return {
        "default_mode": "not_specified",
        "modes": {
            "not_specified": {"local_pick_up": True, "free_shipping": False},
            "me2": {"local_pick_up": False, "free_shipping": False, "logistic_type": "drop_off"},
        },
    }


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


def test_validation_only_mode_reuses_policy_snapshot_for_same_category() -> None:
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

    result = use_case.execute([_build_product(), _build_product()], "MLB1234")

    assert len({item["policy_hash"] for item in result["item_results"]}) == 1
    assert len({item["schema_contract_hash"] for item in result["item_results"]}) == 1
    assert publisher.listing_type_calls == 1
    assert publisher.sale_terms_calls == 1


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
