"""Flow/identifier/preflight tests split from validation-only use-case suite."""

from __future__ import annotations

from typing import Any

from mercadolivre_upload.application.publish_product import PublishProductUseCase
from mercadolivre_upload.domain.product.model import Product
from tests.test_validate_usecase_mode import (
    _base_config,
    _build_product,
    _ImageUploader,
    _SchemaContractResolver,
    _ValidationPublisher,
    _ValidationResolver,
)


def test_validation_only_mode_blocks_preflight_for_missing_required_contract_attributes() -> None:
    publisher = _ValidationPublisher()
    resolver = _SchemaContractResolver(
        all_attributes=[
            {"id": "BRAND", "tags": {"required": True}},
            {"id": "MODEL", "tags": {"allow_variations": True}},
        ]
    )
    use_case = PublishProductUseCase(
        category_resolver=resolver,  # type: ignore[arg-type]
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
    assert publisher.validated_items == []
    assert "Missing required attributes: BRAND" in result["errors"][0]
    assert result["item_results"][0]["cause_codes"] == ["schema_contract.preflight"]


def test_validation_only_mode_blocks_preflight_for_picture_limit() -> None:
    publisher = _ValidationPublisher()
    resolver = _SchemaContractResolver(settings={"max_pictures_per_item": 1})
    use_case = PublishProductUseCase(
        category_resolver=resolver,  # type: ignore[arg-type]
        publisher=publisher,  # type: ignore[arg-type]
        image_uploader=_ImageUploader(
            image_urls=[
                "https://example.com/image-1.jpg",
                "https://example.com/image-2.jpg",
            ]
        ),  # type: ignore[arg-type]
        config=_base_config(),
        validation_only=True,
        enable_feedback=False,
        enable_fiscal_submission=False,
    )

    result = use_case.execute([_build_product()], "MLB1234")

    assert result["success"] is False
    assert result["validated"] == 0
    assert result["failed"] == 1
    assert publisher.validated_items == []
    assert "Pictures count 2 exceeds category max 1" in result["errors"][0]


def test_validation_only_mode_blocks_preflight_for_image_diagnostic_issues() -> None:
    publisher = _ValidationPublisher()
    use_case = PublishProductUseCase(
        category_resolver=_ValidationResolver(),  # type: ignore[arg-type]
        publisher=publisher,  # type: ignore[arg-type]
        image_uploader=_ImageUploader(
            diagnostic_result={
                "status": "failed",
                "available": True,
                "checked": 1,
                "issues": ["Picture 1 diagnostic issues: text_logo"],
                "results": [
                    {
                        "index": 0,
                        "status": "issues",
                        "detections": ["text_logo"],
                    }
                ],
            }
        ),  # type: ignore[arg-type]
        config=_base_config(),
        validation_only=True,
        enable_feedback=False,
        enable_fiscal_submission=False,
    )

    result = use_case.execute([_build_product()], "MLB1234")

    assert result["success"] is False
    assert result["validated"] == 0
    assert result["failed"] == 1
    assert publisher.validated_items == []
    assert "Image diagnostic preflight failed" in result["errors"][0]
    item_result = result["item_results"][0]
    assert item_result["cause_codes"] == ["image_diagnostic.preflight"]
    assert item_result["image_diagnostics"]["status"] == "failed"
    assert item_result["image_diagnostics"]["gate_mode"] == "enforce"
    assert item_result["image_diagnostics"]["gate_decision"]["action"] == "block"


def test_validation_only_mode_continues_when_image_diagnostics_unavailable() -> None:
    publisher = _ValidationPublisher()
    use_case = PublishProductUseCase(
        category_resolver=_ValidationResolver(),  # type: ignore[arg-type]
        publisher=publisher,  # type: ignore[arg-type]
        image_uploader=_ImageUploader(
            diagnostic_result={
                "status": "unavailable",
                "available": False,
                "checked": 0,
                "issues": [],
                "results": [],
                "message": "Image diagnostics endpoint unavailable (status 404).",
            }
        ),  # type: ignore[arg-type]
        config=_base_config(),
        validation_only=True,
        enable_feedback=False,
        enable_fiscal_submission=False,
    )

    result = use_case.execute([_build_product()], "MLB1234")

    assert result["success"] is True
    assert result["validated"] == 1
    assert result["failed"] == 0
    assert len(publisher.validated_items) == 1
    assert result["item_results"][0]["image_diagnostics"]["status"] == "unavailable"
    assert result["item_results"][0]["image_diagnostics"]["gate_mode"] == "enforce"
    assert result["item_results"][0]["image_diagnostics"]["gate_decision"]["action"] == "allow"


def test_validation_only_mode_allows_image_diagnostics_issues_in_report_only_mode() -> None:
    publisher = _ValidationPublisher()
    config = _base_config()
    config["image_diagnostics"] = {"gate_mode": "report_only"}
    use_case = PublishProductUseCase(
        category_resolver=_ValidationResolver(),  # type: ignore[arg-type]
        publisher=publisher,  # type: ignore[arg-type]
        image_uploader=_ImageUploader(
            diagnostic_result={
                "status": "failed",
                "available": True,
                "checked": 1,
                "issues": ["Picture 1 diagnostic issues: text_logo"],
                "results": [
                    {
                        "index": 0,
                        "status": "issues",
                        "detections": ["text_logo"],
                    }
                ],
            }
        ),  # type: ignore[arg-type]
        config=config,
        validation_only=True,
        enable_feedback=False,
        enable_fiscal_submission=False,
    )

    result = use_case.execute([_build_product()], "MLB1234")

    assert result["success"] is True
    assert result["validated"] == 1
    assert result["failed"] == 0
    assert len(publisher.validated_items) == 1
    item_result = result["item_results"][0]
    assert item_result["image_diagnostics"]["status"] == "failed"
    assert item_result["image_diagnostics"]["gate_mode"] == "report_only"
    assert item_result["image_diagnostics"]["gate_decision"]["action"] == "allow"
    assert item_result["rollout_flags"]["image_diagnostics_gate_mode"] == "report_only"


def test_validation_only_mode_skips_legacy_variations_when_limit_is_tight() -> None:
    class _VariationMarkerBuilder:
        def build_attributes(
            self,
            _product: Product,
            _category_id: str,
        ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str], list[str]]:
            return (
                [
                    {"id": "BRAND", "value_name": "Marca X"},
                    {"id": "COLOR", "value_name": "Azul"},
                    {
                        "_variation_candidates": {
                            "COLOR": [
                                {"id": "1", "name": "Azul"},
                                {"id": "2", "name": "Verde"},
                            ]
                        }
                    },
                ],
                [],
                [],
                [],
            )

        def set_cache_mapper(self, cache_mapper: Any) -> None:  # pragma: no cover - compat hook
            del cache_mapper

    publisher = _ValidationPublisher()
    resolver = _SchemaContractResolver(settings={"max_variations_allowed": 1})
    use_case = PublishProductUseCase(
        category_resolver=resolver,  # type: ignore[arg-type]
        publisher=publisher,  # type: ignore[arg-type]
        image_uploader=_ImageUploader(),  # type: ignore[arg-type]
        config=_base_config(),
        validation_only=True,
        enable_feedback=False,
        enable_fiscal_submission=False,
    )
    use_case._attribute_builder = _VariationMarkerBuilder()  # type: ignore[assignment]

    result = use_case.execute([_build_product()], "MLB1234")

    assert result["success"] is True
    assert result["validated"] == 1
    assert result["failed"] == 0
    validated_item = publisher.validated_items[0]
    assert "variations" not in validated_item
    assert any(attr["id"] == "COLOR" for attr in validated_item["attributes"])


def test_validation_only_mode_normalizes_gtin_and_surfaces_identifier_gate() -> None:
    class _IdentifierBuilder:
        def build_attributes(
            self,
            _product: Product,
            _category_id: str,
        ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str], list[str]]:
            return ([{"id": "GTIN", "value_name": " 1234-5678 9012 "}], [], [], [])

        def set_cache_mapper(self, cache_mapper: Any) -> None:  # pragma: no cover - compat hook
            del cache_mapper

    publisher = _ValidationPublisher()
    resolver = _SchemaContractResolver(all_attributes=[{"id": "GTIN", "tags": {"required": True}}])
    use_case = PublishProductUseCase(
        category_resolver=resolver,  # type: ignore[arg-type]
        publisher=publisher,  # type: ignore[arg-type]
        image_uploader=_ImageUploader(),  # type: ignore[arg-type]
        config=_base_config(),
        validation_only=True,
        enable_feedback=False,
        enable_fiscal_submission=False,
    )
    use_case._attribute_builder = _IdentifierBuilder()  # type: ignore[assignment]

    result = use_case.execute([_build_product()], "MLB1234")

    assert result["success"] is True
    attrs_by_id = {
        attr["id"]: attr
        for attr in publisher.validated_items[0]["attributes"]
        if isinstance(attr, dict) and isinstance(attr.get("id"), str)
    }
    assert attrs_by_id["GTIN"]["value_name"] == "123456789012"
    identifier_gate = result["item_results"][0]["identifier_gate"]
    assert identifier_gate["checked"] is True
    assert identifier_gate["gtin_required"] is True
    assert identifier_gate["item_has_gtin"] is True
    assert identifier_gate["fallback_reason_available"] is False
    assert identifier_gate["violations"] == []


def test_validation_only_mode_does_not_require_empty_gtin_reason_when_gtin_present() -> None:
    class _IdentifierBuilder:
        def build_attributes(
            self,
            _product: Product,
            _category_id: str,
        ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str], list[str]]:
            return ([{"id": "GTIN", "value_name": "1234567890123"}], [], [], [])

        def set_cache_mapper(self, cache_mapper: Any) -> None:  # pragma: no cover - compat hook
            del cache_mapper

    publisher = _ValidationPublisher()
    resolver = _SchemaContractResolver(
        all_attributes=[
            {"id": "GTIN", "tags": {"conditional_required": True}},
            {
                "id": "EMPTY_GTIN_REASON",
                "tags": {"conditional_required": True},
                "values": [{"id": "17055161", "name": "Outro motivo"}],
            },
        ]
    )
    use_case = PublishProductUseCase(
        category_resolver=resolver,  # type: ignore[arg-type]
        publisher=publisher,  # type: ignore[arg-type]
        image_uploader=_ImageUploader(),  # type: ignore[arg-type]
        config=_base_config(),
        validation_only=True,
        enable_feedback=False,
        enable_fiscal_submission=False,
    )
    use_case._attribute_builder = _IdentifierBuilder()  # type: ignore[assignment]

    result = use_case.execute([_build_product()], "MLB1234")

    assert result["success"] is True
    assert result["failed"] == 0
    assert publisher.validated_items != []
    assert "Missing required attributes: EMPTY_GTIN_REASON" not in " ".join(result["errors"])
    assert result["item_results"][0]["identifier_gate"]["violations"] == []


def test_validation_only_mode_accepts_valid_empty_gtin_reason_when_gtin_required() -> None:
    class _FallbackReasonBuilder:
        def build_attributes(
            self,
            _product: Product,
            _category_id: str,
        ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str], list[str]]:
            return (
                [{"id": "EMPTY_GTIN_REASON", "value_id": "17055158", "value_name": "Outro motivo"}],
                [],
                [],
                [],
            )

        def set_cache_mapper(self, cache_mapper: Any) -> None:  # pragma: no cover - compat hook
            del cache_mapper

    publisher = _ValidationPublisher()
    resolver = _SchemaContractResolver(
        all_attributes=[
            {"id": "GTIN", "tags": {"required": True}},
            {
                "id": "EMPTY_GTIN_REASON",
                "tags": {},
                "values": [{"id": "17055158", "name": "Outro motivo"}],
            },
        ]
    )
    config = _base_config()
    config["identifier_policy"] = {
        "auto_fill_empty_gtin_reason": True,
        "default_empty_gtin_reason_value_name": "teste",
    }
    use_case = PublishProductUseCase(
        category_resolver=resolver,  # type: ignore[arg-type]
        publisher=publisher,  # type: ignore[arg-type]
        image_uploader=_ImageUploader(),  # type: ignore[arg-type]
        config=config,
        validation_only=True,
        enable_feedback=False,
        enable_fiscal_submission=False,
    )
    use_case._attribute_builder = _FallbackReasonBuilder()  # type: ignore[assignment]

    result = use_case.execute([_build_product()], "MLB1234")

    assert result["success"] is True
    assert len(publisher.validated_items) == 1
    attrs_by_id = {
        attr["id"]: attr
        for attr in publisher.validated_items[0]["attributes"]
        if isinstance(attr, dict) and isinstance(attr.get("id"), str)
    }
    assert attrs_by_id["EMPTY_GTIN_REASON"]["value_id"] == "17055158"
    assert attrs_by_id["EMPTY_GTIN_REASON"]["value_name"] == "Outro motivo"
    identifier_gate = result["item_results"][0]["identifier_gate"]
    assert identifier_gate["item_has_gtin"] is False
    assert identifier_gate["item_has_empty_gtin_reason"] is True
    assert identifier_gate["fallback_reason_available"] is True
    assert identifier_gate["default_empty_gtin_reason"]["applied"] is False
    assert identifier_gate["violations"] == []


def test_validation_only_mode_auto_fills_default_empty_gtin_reason_when_configured() -> None:
    class _NoIdentifierBuilder:
        def build_attributes(
            self,
            _product: Product,
            _category_id: str,
        ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str], list[str]]:
            return ([{"id": "BRAND", "value_name": "Marca X"}], [], [], [])

        def set_cache_mapper(self, cache_mapper: Any) -> None:  # pragma: no cover - compat hook
            del cache_mapper

    publisher = _ValidationPublisher()
    resolver = _SchemaContractResolver(
        all_attributes=[
            {"id": "GTIN", "tags": {"required": True}},
            {
                "id": "EMPTY_GTIN_REASON",
                "tags": {},
                "values": [{"id": "17055158", "name": "Outro motivo"}],
            },
        ]
    )
    config = _base_config()
    config["identifier_policy"] = {
        "auto_fill_empty_gtin_reason": True,
        "default_empty_gtin_reason_value_name": "teste",
    }
    use_case = PublishProductUseCase(
        category_resolver=resolver,  # type: ignore[arg-type]
        publisher=publisher,  # type: ignore[arg-type]
        image_uploader=_ImageUploader(),  # type: ignore[arg-type]
        config=config,
        validation_only=True,
        enable_feedback=False,
        enable_fiscal_submission=False,
    )
    use_case._attribute_builder = _NoIdentifierBuilder()  # type: ignore[assignment]

    result = use_case.execute([_build_product()], "MLB1234")

    assert result["success"] is True
    attrs_by_id = {
        attr["id"]: attr
        for attr in publisher.validated_items[0]["attributes"]
        if isinstance(attr, dict) and isinstance(attr.get("id"), str)
    }
    assert attrs_by_id["EMPTY_GTIN_REASON"]["value_name"] == "Outro motivo"
    assert attrs_by_id["EMPTY_GTIN_REASON"]["value_id"] == "17055158"
    identifier_gate = result["item_results"][0]["identifier_gate"]
    assert identifier_gate["item_has_gtin"] is False
    assert identifier_gate["item_has_empty_gtin_reason"] is True
    assert identifier_gate["default_empty_gtin_reason"]["applied"] is True
    assert identifier_gate["default_empty_gtin_reason"]["warning"] is not None
    assert identifier_gate["violations"] == []


def test_validation_only_mode_auto_fills_default_empty_gtin_reason_without_allowed_values() -> None:
    class _NoIdentifierBuilder:
        def build_attributes(
            self,
            _product: Product,
            _category_id: str,
        ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str], list[str]]:
            return ([{"id": "BRAND", "value_name": "Marca X"}], [], [], [])

        def set_cache_mapper(self, cache_mapper: Any) -> None:  # pragma: no cover - compat hook
            del cache_mapper

    publisher = _ValidationPublisher()
    resolver = _SchemaContractResolver(
        all_attributes=[
            {"id": "GTIN", "tags": {"required": True}},
            {"id": "EMPTY_GTIN_REASON", "tags": {}},
        ]
    )
    config = _base_config()
    config["identifier_policy"] = {
        "auto_fill_empty_gtin_reason": True,
        "default_empty_gtin_reason_value_name": "teste",
    }
    use_case = PublishProductUseCase(
        category_resolver=resolver,  # type: ignore[arg-type]
        publisher=publisher,  # type: ignore[arg-type]
        image_uploader=_ImageUploader(),  # type: ignore[arg-type]
        config=config,
        validation_only=True,
        enable_feedback=False,
        enable_fiscal_submission=False,
    )
    use_case._attribute_builder = _NoIdentifierBuilder()  # type: ignore[assignment]

    result = use_case.execute([_build_product()], "MLB1234")

    assert result["success"] is True
    attrs_by_id = {
        attr["id"]: attr
        for attr in publisher.validated_items[0]["attributes"]
        if isinstance(attr, dict) and isinstance(attr.get("id"), str)
    }
    assert attrs_by_id["EMPTY_GTIN_REASON"]["value_name"] == "teste"
    assert "value_id" not in attrs_by_id["EMPTY_GTIN_REASON"]
    identifier_gate = result["item_results"][0]["identifier_gate"]
    assert identifier_gate["default_empty_gtin_reason"]["applied"] is True
    assert identifier_gate["default_empty_gtin_reason"]["warning"] is None


def test_validation_only_mode_blocks_invalid_empty_gtin_reason_metadata() -> None:
    class _InvalidFallbackReasonBuilder:
        def build_attributes(
            self,
            _product: Product,
            _category_id: str,
        ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str], list[str]]:
            return (
                [{"id": "EMPTY_GTIN_REASON", "value_id": "999999", "value_name": "Inválido"}],
                [],
                [],
                [],
            )

        def set_cache_mapper(self, cache_mapper: Any) -> None:  # pragma: no cover - compat hook
            del cache_mapper

    publisher = _ValidationPublisher()
    resolver = _SchemaContractResolver(
        all_attributes=[
            {"id": "GTIN", "tags": {"required": True}},
            {
                "id": "EMPTY_GTIN_REASON",
                "tags": {},
                "values": [{"id": "17055158", "name": "Outro motivo"}],
            },
        ]
    )
    use_case = PublishProductUseCase(
        category_resolver=resolver,  # type: ignore[arg-type]
        publisher=publisher,  # type: ignore[arg-type]
        image_uploader=_ImageUploader(),  # type: ignore[arg-type]
        config=_base_config(),
        validation_only=True,
        enable_feedback=False,
        enable_fiscal_submission=False,
    )
    use_case._attribute_builder = _InvalidFallbackReasonBuilder()  # type: ignore[assignment]

    result = use_case.execute([_build_product()], "MLB1234")

    assert result["success"] is False
    assert publisher.validated_items == []
    assert "Item has invalid EMPTY_GTIN_REASON metadata" in result["errors"][0]
    assert result["item_results"][0]["cause_codes"] == ["schema_contract.preflight"]
    assert result["item_results"][0]["identifier_gate"]["violations"] == [
        "Item has invalid EMPTY_GTIN_REASON metadata"
    ]


def test_validation_only_mode_blocks_variation_identifier_incoherence() -> None:
    class _VariationIdentifierBuilder:
        def build_attributes(
            self,
            _product: Product,
            _category_id: str,
        ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str], list[str]]:
            return (
                [
                    {"id": "BRAND", "value_name": "Marca X"},
                    {
                        "_variation_candidates": {
                            "COLOR": [{"id": "1", "name": "Azul"}, {"id": "2", "name": "Verde"}]
                        }
                    },
                ],
                [],
                [],
                [],
            )

        def set_cache_mapper(self, cache_mapper: Any) -> None:  # pragma: no cover - compat hook
            del cache_mapper

    publisher = _ValidationPublisher()
    use_case = PublishProductUseCase(
        category_resolver=_SchemaContractResolver(),  # type: ignore[arg-type]
        publisher=publisher,  # type: ignore[arg-type]
        image_uploader=_ImageUploader(),  # type: ignore[arg-type]
        config=_base_config(),
        validation_only=True,
        enable_feedback=False,
        enable_fiscal_submission=False,
    )
    use_case._attribute_builder = _VariationIdentifierBuilder()  # type: ignore[assignment]

    def _fake_build_variations_from_candidates(  # type: ignore[no-untyped-def]
        *,
        variation_candidates,
        quantity,
        price,
        picture_ids=None,
    ):
        del variation_candidates, quantity, price, picture_ids
        return [
            {
                "attribute_combinations": [{"id": "COLOR", "value_name": "Azul"}],
                "available_quantity": 1,
                "price": 10.0,
                "picture_ids": ["PIC-1"],
                "attributes": [{"id": "GTIN", "value_name": "1234-5678"}],
            },
            {
                "attribute_combinations": [{"id": "COLOR", "value_name": "Verde"}],
                "available_quantity": 1,
                "price": 10.0,
                "picture_ids": ["PIC-1"],
                "attributes": [],
            },
        ]

    use_case._build_variations_from_candidates = _fake_build_variations_from_candidates

    result = use_case.execute([_build_product()], "MLB1234")

    assert result["success"] is False
    assert publisher.validated_items == []
    assert "Variation 2 missing GTIN/EMPTY_GTIN_REASON identifier coverage" in result["errors"][0]
    assert result["item_results"][0]["identifier_gate"]["variation_identifier_present"] is True


def test_validation_only_mode_includes_auto_flow_routing_metadata() -> None:
    publisher = _ValidationPublisher(users_me={"id": 1234, "tags": []})
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

    routing = result["item_results"][0]["flow_routing"]
    assert routing["mode"] == "auto"
    assert routing["selected_flow"] == "legacy"
    assert routing["seller_has_user_product_seller_tag"] is False
    assert routing["seller_capability_source"] == "users/me"
    assert routing["blocked"] is False
    assert "using legacy flow" in routing["reason"]


def test_flow_routing_prefers_publisher_users_me_when_available() -> None:
    class _PreferredPublisher(_ValidationPublisher):
        def get_publisher_users_me(self) -> dict[str, Any]:
            return {"id": 4321, "tags": ["user_product_seller"]}

        def get_users_me(self) -> dict[str, Any]:
            return {"id": 4321, "tags": []}

    publisher = _PreferredPublisher()
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

    routing = result["item_results"][0]["flow_routing"]
    assert routing["seller_capability_source"] == "publisher/get_users_me"
    assert routing["seller_has_user_product_seller_tag"] is True
    assert routing["selected_flow"] == "user_products"


def test_auto_flow_routing_falls_back_to_legacy_when_user_products_routes_are_unavailable() -> None:
    class _LegacyOnlyPublisher:
        def __init__(self) -> None:
            self.validated_items: list[dict[str, Any]] = []
            self.created_items: list[dict[str, Any]] = []

        def get_users_me(self) -> dict[str, Any]:
            return {"id": 1234, "tags": ["user_product_seller"]}

        def get_available_listing_types(self, _category_id: str) -> list[dict[str, Any]]:
            return [{"id": "gold_special"}]

        def get_category_sale_terms(self, _category_id: str) -> list[dict[str, Any]]:
            return []

        def validate_item(self, item: dict[str, Any]) -> dict[str, Any]:
            self.validated_items.append(item)
            return {"cause": []}

        def create_item(self, item: dict[str, Any]) -> dict[str, Any]:
            self.created_items.append(item)
            return {"id": "MLB1234567890"}

    publisher = _LegacyOnlyPublisher()
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

    routing = result["item_results"][0]["flow_routing"]
    assert routing["selected_flow"] == "legacy"
    assert routing["user_products_route_supported"] is False
    assert "publisher adapter does not support user-products endpoints" in routing["reason"]


def test_forced_user_products_flow_falls_back_to_legacy_when_configured() -> None:
    publisher = _ValidationPublisher(users_me={"id": 1234, "tags": []})
    config = _base_config()
    config["flow_routing"] = {
        "mode": "forced",
        "forced_flow": "user_products",
        "blocked_behavior": "fallback_legacy",
    }
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

    assert result["success"] is True
    assert result["validated"] == 1
    assert result["failed"] == 0
    assert len(publisher.validated_items) == 1
    assert publisher.validated_user_product_items == []
    routing = result["item_results"][0]["flow_routing"]
    assert routing["selected_flow"] == "legacy"
    assert routing["fallback_applied"] is True
    assert routing["blocked"] is False
    assert "requires seller tag" in routing["fallback_reason"]
    assert result["item_results"][0]["rollout_flags"]["flow_blocked_behavior"] == "fallback_legacy"


def test_forced_user_products_flow_requires_explicit_family_name() -> None:
    publisher = _ValidationPublisher(users_me={"id": 1234, "tags": ["user_product_seller"]})
    config = _base_config()
    config["flow_routing"] = {"mode": "forced", "forced_flow": "user_products"}
    use_case = PublishProductUseCase(
        category_resolver=_ValidationResolver(),  # type: ignore[arg-type]
        publisher=publisher,  # type: ignore[arg-type]
        image_uploader=_ImageUploader(),  # type: ignore[arg-type]
        config=config,
        enable_feedback=False,
        enable_fiscal_submission=False,
    )

    result = use_case.execute([_build_product()], "MLB1234")

    assert result["success"] is False
    assert result["published"] == 0
    assert result["failed"] == 1
    assert publisher.created_user_product_items == []
    assert "missing required field 'family_name'" in result["errors"][0]
    routing = result["item_results"][0]["flow_routing"]
    assert routing["mode"] == "forced"
    assert routing["selected_flow"] == "user_products"
    assert routing["blocked"] is False


def test_dry_run_executes_validation_pipeline_and_skips_publish_create_step() -> None:
    publisher = _ValidationPublisher()
    use_case = PublishProductUseCase(
        category_resolver=_ValidationResolver(),  # type: ignore[arg-type]
        publisher=publisher,  # type: ignore[arg-type]
        image_uploader=_ImageUploader(),  # type: ignore[arg-type]
        config=_base_config(),
        dry_run=True,
        enable_feedback=False,
        enable_fiscal_submission=False,
    )

    result = use_case.execute([_build_product()], "MLB1234")

    assert result["success"] is True
    assert result["published"] == 1
    assert result["failed"] == 0
    assert len(publisher.validated_items) == 1
    assert publisher.created_items == []


def test_user_products_flow_builds_distinct_pxv_payload_and_artifacts() -> None:
    class _VariationMarkerBuilder:
        def build_attributes(
            self,
            _product: Product,
            _category_id: str,
        ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str], list[str]]:
            return (
                [
                    {"id": "MODEL", "value_name": "Model X"},
                    {"id": "COLOR", "value_name": "Azul"},
                    {
                        "_variation_candidates": {
                            "COLOR": [
                                {"id": "1", "name": "Azul"},
                                {"id": "2", "name": "Verde"},
                            ]
                        }
                    },
                ],
                [],
                [],
                [],
            )

        def set_cache_mapper(self, cache_mapper: Any) -> None:  # pragma: no cover - compat hook
            del cache_mapper

    publisher = _ValidationPublisher(users_me={"id": 1234, "tags": ["user_product_seller"]})
    config = _base_config()
    config["flow_routing"] = {"mode": "forced", "forced_flow": "user_products"}
    use_case = PublishProductUseCase(
        category_resolver=_ValidationResolver(),  # type: ignore[arg-type]
        publisher=publisher,  # type: ignore[arg-type]
        image_uploader=_ImageUploader(),  # type: ignore[arg-type]
        config=config,
        enable_feedback=False,
        enable_fiscal_submission=False,
    )
    use_case._attribute_builder = _VariationMarkerBuilder()  # type: ignore[assignment]

    result = use_case.execute([_build_product({"family_name": "Linha Alpha"})], "MLB1234")

    assert result["success"] is True
    assert publisher.created_user_product_items
    created_item = publisher.created_user_product_items[0]
    assert "variations" not in created_item
    assert "title" not in created_item
    assert created_item["family_name"] == "Linha Alpha"
    assert "user_product" not in created_item
    attribute_ids = {
        attr.get("id") for attr in created_item["attributes"] if isinstance(attr, dict)
    }
    assert "MODEL" in attribute_ids
    assert "COLOR" in attribute_ids
    routing = result["item_results"][0]["flow_routing"]
    assert routing["selected_flow"] == "user_products"
    assert routing["payload_builder"] == "user_products_pxv"
    assert routing["selected_model"] == "Model X"
    assert routing["up_family_name"] == "Linha Alpha"
    assert routing["up_family_name_source"] == "attribute"
    assert routing["up_attribute_ids"] == ["COLOR"]
    assert routing["up_variation_count"] == 2
