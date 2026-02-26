"""Validation policy-snapshot tests split from validation-only use-case suite."""

from __future__ import annotations

from mercadolivre_upload.application.publish_product import PublishProductUseCase
from tests.support.validate_usecase_mode import (
    _base_config,
    _build_product,
    _ImageUploader,
    _ValidationPublisher,
    _ValidationResolver,
)


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
