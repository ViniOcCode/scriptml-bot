"""Dependency wiring shared by quarantined spreadsheet adapters."""

from pathlib import Path
from typing import Any

from mercadolivre_upload.adapters.clip_uploader import ClipUploader
from mercadolivre_upload.adapters.image_uploader import ImageUploader
from mercadolivre_upload.api.category_adapter import CategoryAdapter
from mercadolivre_upload.api.client import MLApiClient
from mercadolivre_upload.application.publish_product import PublishProductUseCase
from mercadolivre_upload.auth import TokenManager
from mercadolivre_upload.domain.category.resolver import CategoryResolver
from mercadolivre_upload.domain.fiscal.service import FiscalService
from mercadolivre_upload.domain.shipping.resolver import ShippingResolver
from mercadolivre_upload.infrastructure.cache.attribute_cache import AttributeCache
from mercadolivre_upload.infrastructure.cache.prediction_cache import PredictionCache
from mercadolivre_upload.shared.utils.config_loader import (
    RUNTIME_SPLIT_CONFIG_PATHS,
    load_merged_yaml_config,
)


def load_config() -> dict[str, Any]:
    """Load the split configuration used by spreadsheet adapters."""
    return load_merged_yaml_config(*RUNTIME_SPLIT_CONFIG_PATHS)


def build_publish_use_case(
    *,
    images: Path,
    cache_dir: Path,
    config: dict[str, Any],
    dry_run: bool = True,
    validation_only: bool = False,
    execute: bool = False,
    confirmation: str | None = None,
    publish_inactive: bool = False,
) -> PublishProductUseCase:
    """Build the spreadsheet publication use case from local dependencies."""
    auth_manager = TokenManager()
    api_client = MLApiClient(auth_manager)
    attribute_cache = AttributeCache(cache_dir=str(cache_dir))
    prediction_cache = PredictionCache(cache_dir=str(cache_dir / "predictions"))
    category_adapter = CategoryAdapter(api_client)
    image_uploader = ImageUploader(api_client, images)
    clip_uploader = ClipUploader(api_client, base_path=images)
    category_resolver = CategoryResolver(
        category_adapter,
        attribute_cache=attribute_cache,
        prediction_cache=prediction_cache,
    )

    return PublishProductUseCase(
        category_resolver=category_resolver,
        publisher=api_client,
        image_uploader=image_uploader,
        shipping_resolver=ShippingResolver(api_client),
        fiscal_service=FiscalService(api_client),
        clip_uploader=clip_uploader,
        config=config,
        dry_run=dry_run,
        validation_only=validation_only,
        execute=execute,
        confirmation=confirmation,
        publish_inactive=publish_inactive,
        attribute_cache=attribute_cache,
    )
