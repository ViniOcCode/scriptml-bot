"""Category resolver for matching ML category names to IDs."""

import logging
from typing import Any, cast

import requests

from mercadolivre_upload.api.client import MLApiClient

logger = logging.getLogger(__name__)


class CategoryResolver:
    """Resolves category names to ML category IDs.

    Supports hierarchical category resolution by traversing the category tree.
    """

    def __init__(self, client: MLApiClient):
        """Initialize resolver.

        Args:
            client: ML API client
        """
        self.client = client
        self._categories: dict[str, str] = {}  # name -> id cache
        self._category_cache: dict[str, dict[str, Any]] = {}  # id -> category data cache
        self._children_cache: dict[str, list[dict[str, Any]]] = {}  # id -> children cache

    def _load_all_categories(self, site_id: str = "MLB") -> None:
        """Load all categories for a site (root level only)."""
        logger.info(f"Loading categories for site {site_id}")
        categories = self.client.get_site_categories(site_id)

        for cat in categories:
            name_lower = cat["name"].lower().strip()
            self._categories[name_lower] = cat["id"]

    def _get_category_children(self, category_id: str) -> list[dict[str, Any]]:
        """Get children of a category.

        Args:
            category_id: Parent category ID

        Returns:
            List of child categories
        """
        if category_id not in self._children_cache:
            try:
                children = self.client.get_category(category_id).get("children_categories", [])
                self._children_cache[category_id] = children
            except (
                requests.RequestException,
                RuntimeError,
                ValueError,
                TypeError,
                KeyError,
            ) as e:
                logger.warning(f"Could not get children for {category_id}: {e}")
                self._children_cache[category_id] = []
        return self._children_cache[category_id]

    def _search_in_hierarchy(
        self, name: str, parent_id: str, visited: set[str] | None = None
    ) -> str | None:
        """Search for category name in hierarchy starting from parent.

        Args:
            name: Category name to search for
            parent_id: Starting category ID
            visited: Set of already visited category IDs (to prevent cycles)

        Returns:
            Category ID or None
        """
        if visited is None:
            visited = set()

        if parent_id in visited:
            return None

        visited.add(parent_id)
        name_lower = name.lower().strip()

        # Get children of this category
        children = self._get_category_children(parent_id)

        for child in children:
            child_name = child["name"].lower().strip()
            child_id = child["id"]

            # Cache this child
            self._categories[child_name] = child_id

            # Exact match
            if child_name == name_lower:
                return cast(str, child_id)

            # Partial match
            if name_lower in child_name or child_name in name_lower:
                logger.debug(f"Partial match: '{name}' -> '{child_name}'")
                return cast(str, child_id)

            # Recursively search in child's children
            result = self._search_in_hierarchy(name, child_id, visited)
            if result:
                return result

        return None

    def find_category(self, name: str, site_id: str = "MLB") -> str | None:
        """Find category ID by name.

        Searches through the category hierarchy (root categories and their children).

        Args:
            name: Category name (e.g., "Livros Físicos")
            site_id: Site ID (default: MLB)

        Returns:
            Category ID or None
        """
        # First try to find in cached categories
        if not self._categories:
            self._load_all_categories(site_id)

        name_lower = name.lower().strip()

        # Exact match in root categories
        if name_lower in self._categories:
            return self._categories[name_lower]

        # Partial match in root categories
        for cat_name, cat_id in list(self._categories.items()):
            if name_lower in cat_name or cat_name in name_lower:
                logger.debug(f"Partial match in root: '{name}' -> '{cat_name}'")
                return cat_id

        # Search in hierarchy - try each root category
        logger.info(f"Searching category hierarchy for '{name}'")
        for root_id in list(self._categories.values()):
            result = self._search_in_hierarchy(name, root_id)
            if result:
                logger.info(f"Found '{name}' -> {result}")
                return result

        return None

    def get_category_data(self, category_id: str) -> dict[str, Any]:
        """Get category data with caching."""
        if category_id not in self._category_cache:
            self._category_cache[category_id] = self.client.get_category(category_id)
        return self._category_cache[category_id]

    def get_mandatory_attributes(self, category_id: str) -> list[dict[str, Any]]:
        """Get mandatory attributes for a category.

        Args:
            category_id: Category ID

        Returns:
            List of mandatory attribute definitions
        """
        attributes = self.client.get_category_attributes(category_id)
        return [attr for attr in attributes if attr.get("tags", {}).get("required")]

    def get_all_attributes(self, category_id: str) -> list[dict[str, Any]]:
        """Get all attributes for a category."""
        return self.client.get_category_attributes(category_id)

    def build_attribute_map(self, category_id: str) -> dict[str, dict[str, Any]]:
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
