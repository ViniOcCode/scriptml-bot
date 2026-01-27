"""Category resolver for matching ML category names to IDs."""

import logging
from typing import Optional

from mercadolivre_upload.api.client import MLApiClient

logger = logging.getLogger(__name__)


class CategoryResolver:
    """Resolves category names to ML category IDs."""

    def __init__(self, client: MLApiClient):
        """Initialize resolver.

        Args:
            client: ML API client
        """
        self.client = client
        self._categories: dict[str, str] = {}  # name -> id cache
        self._category_cache: dict[str, dict] = {}  # id -> category data

    def _load_all_categories(self, site_id: str = "MLB") -> None:
        """Load all categories for a site."""
        logger.info(f"Loading categories for site {site_id}")
        categories = self.client.get_site_categories(site_id)

        for cat in categories:
            name_lower = cat["name"].lower().strip()
            self._categories[name_lower] = cat["id"]

    def find_category(self, name: str, site_id: str = "MLB") -> Optional[str]:
        """Find category ID by name.

        Args:
            name: Category name (partial match supported)
            site_id: Site ID (default: MLB)

        Returns:
            Category ID or None
        """
        if not self._categories:
            self._load_all_categories(site_id)

        name_lower = name.lower().strip()

        # Exact match
        if name_lower in self._categories:
            return self._categories[name_lower]

        # Partial match
        for cat_name, cat_id in self._categories.items():
            if name_lower in cat_name or cat_name in name_lower:
                logger.debug(f"Partial match: '{name}' -> '{cat_name}'")
                return cat_id

        return None

    def get_category_data(self, category_id: str) -> dict:
        """Get category data with caching."""
        if category_id not in self._category_cache:
            self._category_cache[category_id] = self.client.get_category(category_id)
        return self._category_cache[category_id]

    def get_mandatory_attributes(self, category_id: str) -> list[dict]:
        """Get mandatory attributes for a category.

        Args:
            category_id: Category ID

        Returns:
            List of mandatory attribute definitions
        """
        attributes = self.client.get_category_attributes(category_id)
        return [attr for attr in attributes if attr.get("tags", {}).get("required")]

    def get_all_attributes(self, category_id: str) -> list[dict]:
        """Get all attributes for a category."""
        return self.client.get_category_attributes(category_id)

    def build_attribute_map(self, category_id: str) -> dict[str, dict]:
        """Build name -> attribute mapping for a category.

        Args:
            category_id: Category ID

        Returns:
            Dict mapping attribute names to attribute definitions
        """
        attributes = self.get_all_attributes(category_id)
        mapping = {}

        for attr in attributes:
            names = [attr["name"].lower()]

            # Add alternative names from tags
            if "allowed_units" in attr:
                names.append(attr["id"].lower().replace("_", " "))

            for name in names:
                mapping[name] = attr

        return mapping
