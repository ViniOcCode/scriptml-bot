"""Category adapter - implements domain port using ML API.

Infrastructure layer - depends on external API.
"""

import logging
from collections.abc import Callable
from typing import Any, cast

import requests

from mercadolivre_upload.api.client import MLApiClient
from mercadolivre_upload.domain.category.errors import CategoryApiUnavailableError
from mercadolivre_upload.domain.category.resolver import CategoryApiPort

logger = logging.getLogger(__name__)
RECOVERABLE_API_ERRORS = (requests.RequestException, ValueError, TypeError, RuntimeError)


class CategoryAdapter(CategoryApiPort):
    """Adapter for ML Category API.

    Implements the domain CategoryApiPort using ML API client.
    """

    def __init__(self, client: MLApiClient):
        """Initialize with ML API client.

        Args:
            client: ML API client
        """
        self.client = client

    def _call_list(
        self,
        operation: Callable[[], Any],
        *,
        context: str,
        error_level: str = "error",
    ) -> list[dict[str, Any]]:
        """Execute client operation and normalize list responses."""
        try:
            result = operation()
        except RECOVERABLE_API_ERRORS as e:
            message = f"{context}: {e}"
            getattr(logger, error_level)(message)
            raise CategoryApiUnavailableError(message, operation=context) from e

        if not isinstance(result, list):
            message = f"{context}: invalid response type {type(result).__name__}"
            getattr(logger, error_level)(message)
            raise CategoryApiUnavailableError(message, operation=context)
        return cast(list[dict[str, Any]], result)

    def _call_dict(
        self,
        operation: Callable[[], Any],
        *,
        context: str,
        error_level: str = "error",
    ) -> dict[str, Any]:
        """Execute client operation and normalize dict responses."""
        try:
            result = operation()
        except RECOVERABLE_API_ERRORS as e:
            message = f"{context}: {e}"
            getattr(logger, error_level)(message)
            raise CategoryApiUnavailableError(message, operation=context) from e

        if not isinstance(result, dict):
            message = f"{context}: invalid response type {type(result).__name__}"
            getattr(logger, error_level)(message)
            raise CategoryApiUnavailableError(message, operation=context)
        return cast(dict[str, Any], result)

    def get_site_categories(self, site_id: str) -> list[dict[str, Any]]:
        """Get all categories for a site."""
        return self._call_list(
            lambda: self.client.get_site_categories(site_id),
            context=f"Failed to get site categories for site {site_id}",
        )

    def get_category(self, category_id: str) -> dict[str, Any]:
        """Get category details including children_categories."""
        return self._call_dict(
            lambda: self.client.get_category(category_id),
            context=f"Failed to get category {category_id}",
        )

    def get_category_attributes(self, category_id: str) -> list[dict[str, Any]]:
        """Get attributes for a category."""
        return self._call_list(
            lambda: self.client.get_category_attributes(category_id),
            context=f"Failed to get attributes for {category_id}",
        )

    def get_category_technical_specs(self, category_id: str) -> dict[str, Any]:
        """Get technical specs input for a category."""
        return self._call_dict(
            lambda: self.client.get_category_technical_specs(category_id),
            context=f"Failed to get technical specs for {category_id}",
            error_level="debug",
        )

    def get_category_conditional_attributes(
        self, category_id: str, item_context: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Get conditional attributes for a category.

        Args:
            category_id: Category ID
            item_context: Full item context payload

        Returns:
            List of conditional attributes
        """
        try:
            result = self.client.get_category_conditional_attributes(category_id, item_context)
            # API returns dict with 'required_attributes' key, not a list
            if isinstance(result, dict) and "required_attributes" in result:
                required = result["required_attributes"]
                return required if isinstance(required, list) else []
            # Ensure we return a list
            if not isinstance(result, list):
                logger.debug(f"Expected list or dict for conditionals, got {type(result)}")
                return []
            return result
        except RECOVERABLE_API_ERRORS as e:
            logger.debug(f"Failed to get conditional attributes for {category_id}: {e}")
            return []

    def predict_category(
        self, title: str, site_id: str = "MLB", limit: int | None = None
    ) -> list[dict[str, Any]]:
        """Predict category based on product title."""
        return self._call_list(
            lambda: self.client.predict_category(title, site_id, limit=limit),
            context=f"Failed to predict category for '{title}'",
            error_level="warning",
        )

    def validate_item(self, item: dict[str, Any]) -> dict[str, Any]:
        """Validate item before publishing."""
        try:
            return self.client.validate_item(item)
        except RECOVERABLE_API_ERRORS as e:
            logger.error(f"Failed to validate item: {e}")
            return {"valid": False, "error": str(e)}

    def create_item(self, item: dict[str, Any]) -> dict[str, Any]:
        """Create/publish an item."""
        return self.client.create_item(item)
