"""Tests for publish_product module public surface."""

import mercadolivre_upload.application.publish_product as publish_product_module
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
