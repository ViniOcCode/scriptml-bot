"""Identifier policy tests for validation-only publish flow."""

from __future__ import annotations

from typing import Any

from mercadolivre_upload.application.publish_product import PublishProductUseCase
from mercadolivre_upload.domain.product.model import Product
from tests.support.validate_usecase_mode import (
    _base_config,
    _build_product,
    _ImageUploader,
    _SchemaContractResolver,
    _ValidationPublisher,
)


def test_validation_only_mode_normalizes_gtin_and_surfaces_identifier_gate() -> None:
    class _IdentifierBuilder:
        def build_attributes(
            self,
            _product: Product,
            _category_id: str,
            *,
            drop_invalid_domain_values: bool = True,
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
            *,
            drop_invalid_domain_values: bool = True,
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
            *,
            drop_invalid_domain_values: bool = True,
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
            *,
            drop_invalid_domain_values: bool = True,
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
            *,
            drop_invalid_domain_values: bool = True,
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
            *,
            drop_invalid_domain_values: bool = True,
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
            *,
            drop_invalid_domain_values: bool = True,
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
