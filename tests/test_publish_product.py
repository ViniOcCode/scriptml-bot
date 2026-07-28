"""Tests for publish_product module public surface."""

from unittest.mock import MagicMock

import pytest

import mercadolivre_upload.application.publish_product as publish_product_module
from mercadolivre_upload.application.publication_intent import PublicationIntentError
from mercadolivre_upload.application.publish_product import PublishProductUseCase


def test_publish_use_case_is_available():
    """PublishProductUseCase remains the supported API entrypoint."""
    assert PublishProductUseCase is publish_product_module.PublishProductUseCase


def test_legacy_compatibility_symbols_removed():
    """Legacy compatibility wrapper symbols were removed."""
    assert not hasattr(publish_product_module, "PublishProductService")
    assert not hasattr(publish_product_module, "PublishResult")
    assert not hasattr(publish_product_module, "ValidationResult")
    assert not hasattr(publish_product_module, "LegacyPublishProductUseCase")


def _bare_use_case(**kwargs: object) -> PublishProductUseCase:
    return PublishProductUseCase(
        category_resolver=MagicMock(),
        publisher=MagicMock(),
        image_uploader=MagicMock(),
        **kwargs,
    )


def test_publish_use_case_defaults_to_non_mutating_dry_run() -> None:
    use_case = _bare_use_case()

    assert use_case.dry_run is True


def test_publish_use_case_rejects_real_execution_without_explicit_intent() -> None:
    use_case = _bare_use_case(dry_run=False)

    with pytest.raises(PublicationIntentError, match="explicit"):
        use_case.execute([], "MLB1234")


def test_publish_use_case_requires_exact_publicar_confirmation() -> None:
    use_case = _bare_use_case(dry_run=False, execute=True, confirmation="publicar")

    with pytest.raises(PublicationIntentError, match="PUBLICAR"):
        use_case.execute([], "MLB1234")


def test_publish_use_case_allows_exact_real_publication_intent(monkeypatch) -> None:
    execute_helper = MagicMock(return_value={"success": True})
    monkeypatch.setattr(publish_product_module, "_execute_publish_helper", execute_helper)
    use_case = _bare_use_case(
        dry_run=False,
        execute=True,
        confirmation="PUBLICAR",
    )

    result = use_case.execute([], "MLB1234")

    assert result == {"success": True}
    execute_helper.assert_called_once_with(use_case, [], "MLB1234")
