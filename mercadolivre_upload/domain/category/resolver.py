"""Category resolver domain logic.

Domain layer defines the interface (port) for category resolution.
Infrastructure layer provides the implementation (adapter).
"""

from abc import ABC, abstractmethod
from typing import Optional, Protocol


class CategoryApiPort(Protocol):
    """Port interface for category API operations.

    Infrastructure layer implements this.
    """

    def get_site_categories(self, site_id: str) -> list[dict]:
        """Get all categories for a site."""
        ...

    def get_category_attributes(self, category_id: str) -> list[dict]:
        """Get attributes for a category."""
        ...

    def get_category_conditional_attributes(
        self, category_id: str, current_attributes: dict
    ) -> list[dict]:
        """Get conditional attributes for a category.

        Args:
            category_id: Category ID
            current_attributes: Current attribute values to check conditions against

        Returns:
            List of conditional attributes
        """
        ...


class CategoryResolver:
    """Resolves category names to IDs using API port.

    Pure domain logic - no external dependencies.
    """

    def __init__(self, api_port: CategoryApiPort):
        """Initialize with API port.

        Args:
            api_port: Implementation of category API operations
        """
        self._api = api_port
        self._categories: dict[str, str] = {}  # name -> id cache
        self._category_cache: dict[str, dict] = {}  # id -> data cache

    def load_categories(self, site_id: str = "MLB") -> None:
        """Load all categories for a site."""
        categories = self._api.get_site_categories(site_id)

        for cat in categories:
            name_lower = cat["name"].lower().strip()
            self._categories[name_lower] = cat["id"]

    def find_category(self, name: str, site_id: str = "MLB") -> Optional[str]:
        """Find category ID by name.

        Args:
            name: Category name
            site_id: Site ID

        Returns:
            Category ID or None
        """
        if not self._categories:
            self.load_categories(site_id)

        name_lower = name.lower().strip()

        # Exact match
        if name_lower in self._categories:
            return self._categories[name_lower]

        # Partial match
        for cat_name, cat_id in self._categories.items():
            if name_lower in cat_name or cat_name in name_lower:
                return cat_id

        return None

    def get_mandatory_attributes(self, category_id: str) -> list[dict]:
        """Get mandatory attributes for a category."""
        attributes = self._api.get_category_attributes(category_id)
        return [attr for attr in attributes if attr.get("tags", {}).get("required")]

    def get_all_attributes(self, category_id: str) -> list[dict]:
        """Get all attributes for a category."""
        return self._api.get_category_attributes(category_id)

    def build_attribute_map(self, category_id: str) -> dict[str, dict]:
        """Build name -> attribute mapping."""
        attributes = self.get_all_attributes(category_id)
        mapping = {}

        for attr in attributes:
            name = attr["name"].lower()
            mapping[name] = attr

            # Also map by ID
            mapping[attr["id"].lower()] = attr

        return mapping

    def get_conditional_attributes(
        self, category_id: str, current_attributes: dict
    ) -> list[dict]:
        """Get conditional attributes based on current attribute values.

        Args:
            category_id: Category ID
            current_attributes: Current attribute values (name -> value)

        Returns:
            List of conditional attributes
        """
        try:
            return self._api.get_category_conditional_attributes(
                category_id, current_attributes
            )
        except Exception as e:
            # Log error but don't fail - conditional attrs are optional
            return []

    def get_all_attributes_with_conditionals(
        self, category_id: str, product_attributes: dict
    ) -> tuple[list[dict], list[dict]]:
        """Get all attributes including conditional ones.

        Args:
            category_id: Category ID
            product_attributes: Current product attribute values

        Returns:
            Tuple of (base_attributes, conditional_attributes)
        """
        base_attrs = self.get_all_attributes(category_id)
        conditional = self.get_conditional_attributes(category_id, product_attributes)
        return base_attrs, conditional

    def get_required_attributes(
        self, category_id: str, product_attributes: dict
    ) -> list[dict]:
        """Get all required attributes including conditionally required.

        Args:
            category_id: Category ID
            product_attributes: Current product attribute values

        Returns:
            List of required attribute definitions
        """
        # Get base required attributes
        all_base = self.get_all_attributes(category_id)
        required = [attr for attr in all_base if attr.get("tags", {}).get("required")]

        # Get conditional attributes
        conditional = self.get_conditional_attributes(category_id, product_attributes)

        # Filter conditional required attributes
        required_conditional = [
            attr for attr in conditional if attr.get("tags", {}).get("required")
        ]

        return required + required_conditional
