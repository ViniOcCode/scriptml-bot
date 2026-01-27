"""Category adapter - implements domain port using ML API.

Infrastructure layer - depends on external API.
"""

import logging
from typing import Protocol

from mercadolivre_upload.api.client import MLApiClient
from mercadolivre_upload.domain.category.resolver import CategoryApiPort

logger = logging.getLogger(__name__)


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

    def get_site_categories(self, site_id: str) -> list[dict]:
        """Get all categories for a site."""
        return self.client.get_site_categories(site_id)

    def get_category_attributes(self, category_id: str) -> list[dict]:
        """Get attributes for a category."""
        return self.client.get_category_attributes(category_id)

    def get_category_conditional_attributes(
        self, category_id: str, current_attributes: dict
    ) -> list[dict]:
        """Get conditional attributes for a category.

        Args:
            category_id: Category ID
            current_attributes: Current attribute values

        Returns:
            List of conditional attributes
        """
        return self.client.get_category_conditional_attributes(
            category_id, current_attributes
        )

    def get_category(self, category_id: str) -> dict:
        """Get category details."""
        return self.client.get_category(category_id)

    def validate_item(self, item: dict) -> dict:
        """Validate item before publishing."""
        return self.client.validate_item(item)

    def create_item(self, item: dict) -> dict:
        """Create/publish an item."""
        return self.client.create_item(item)
