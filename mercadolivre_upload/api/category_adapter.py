"""Category adapter - implements domain port using ML API.

Infrastructure layer - depends on external API.
"""

import logging
from typing import Any

import requests

from mercadolivre_upload.api.client import MLApiClient
from mercadolivre_upload.domain.category.resolver import CategoryApiPort

logger = logging.getLogger(__name__)
RECOVERABLE_API_ERRORS = (requests.RequestException, ValueError, TypeError, RuntimeError)


class CategoryAdapter(CategoryApiPort):
    """Adapter for ML Category API.

    Implements the domain CategoryApiPort using ML API client.
    Returns safe types (empty dict/list) on errors to prevent type errors.
    """

    def __init__(self, client: MLApiClient):
        """Initialize with ML API client.

        Args:
            client: ML API client
        """
        self.client = client

    def get_site_categories(self, site_id: str) -> list[dict[str, Any]]:
        """Get all categories for a site."""
        try:
            return self.client.get_site_categories(site_id)
        except RECOVERABLE_API_ERRORS as e:
            logger.error(f"Failed to get site categories: {e}")
            return []

    def get_category(self, category_id: str) -> dict[str, Any]:
        """Get category details including children_categories."""
        try:
            result = self.client.get_category(category_id)
            # Ensure we return a dict, not a string error
            if not isinstance(result, dict):
                logger.error(f"Invalid response for {category_id}: {result}")
                return {}
            return result
        except RECOVERABLE_API_ERRORS as e:
            logger.error(f"Failed to get category {category_id}: {e}")
            return {}

    def get_category_attributes(self, category_id: str) -> list[dict[str, Any]]:
        """Get attributes for a category."""
        try:
            result = self.client.get_category_attributes(category_id)
            # Ensure we return a list
            if not isinstance(result, list):
                logger.error(f"Invalid attributes response for {category_id}: {result}")
                return []
            return result
        except RECOVERABLE_API_ERRORS as e:
            logger.error(f"Failed to get attributes for {category_id}: {e}")
            return []

    def get_category_technical_specs(self, category_id: str) -> dict[str, Any]:
        """Get technical specs input for a category."""
        try:
            result = self.client.get_category_technical_specs(category_id)
            if not isinstance(result, dict):
                logger.error(f"Invalid technical specs response for {category_id}: {result}")
                return {}
            return result
        except RECOVERABLE_API_ERRORS as e:
            logger.debug(f"Failed to get technical specs for {category_id}: {e}")
            return {}

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
                return result["required_attributes"]
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
        try:
            result = self.client.predict_category(title, site_id, limit=limit)
            # Ensure we return a list
            if not isinstance(result, list):
                logger.warning(f"Expected list for predictions, got {type(result)}")
                return []
            return result
        except RECOVERABLE_API_ERRORS as e:
            logger.warning(f"Failed to predict category for '{title}': {e}")
            return []

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
