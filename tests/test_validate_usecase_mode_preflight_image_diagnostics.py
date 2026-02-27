"""Preflight and image diagnostics tests for validation-only publish flow."""

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
            *,
            drop_invalid_domain_values: bool = True,
        ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str], list[str]]:
            del drop_invalid_domain_values
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
