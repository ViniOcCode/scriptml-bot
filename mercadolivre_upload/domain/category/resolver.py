"""Category resolver domain logic.

Domain layer defines the interface (port) for category resolution.
Infrastructure layer provides the implementation (adapter).
"""

import logging
from typing import Any, Protocol

from ..attribute_metadata import AttributeMeta
from .attribute_helpers import (
    build_attribute_map as _build_attribute_map_helper,
)
from .attribute_helpers import (
    get_all_attributes as _get_all_attributes_helper,
)
from .attribute_helpers import (
    get_all_attributes_with_conditionals as _get_all_attributes_with_conditionals_helper,
)
from .attribute_helpers import (
    get_conditional_attributes as _get_conditional_attributes_helper,
)
from .attribute_helpers import (
    get_mandatory_attributes as _get_mandatory_attributes_helper,
)
from .attribute_helpers import (
    get_required_attributes as _get_required_attributes_helper,
)
from .hierarchy_helpers import (
    get_category_children as _get_category_children_helper,
)
from .hierarchy_helpers import (
    load_categories as _load_categories_helper,
)
from .hierarchy_helpers import (
    search_in_hierarchy as _search_in_hierarchy_helper,
)
from .metadata_helpers import (
    get_attribute_metadata as _get_attribute_metadata_helper,
)
from .predictor import (
    call_domain_discovery as _call_domain_discovery_helper,
)
from .predictor import (
    find_category_with_predictor as _find_category_with_predictor_helper,
)
from .predictor import (
    predict_category_from_title as _predict_category_from_title_helper,
)
from .utils import (
    build_match_score,
    extract_technical_spec_attributes,
    merge_technical_spec,
    normalize_category_id,
    normalize_site_id,
    pick_best_candidate,
    safe_float,
    split_category_query,
)

logger = logging.getLogger(__name__)


class CategoryApiPort(Protocol):
    """Port interface for category API operations.

    Infrastructure layer implements this.
    """

    def get_site_categories(self, site_id: str) -> list[dict[str, Any]]:
        """Get all categories for a site."""
        ...

    def get_category(self, category_id: str) -> dict[str, Any]:
        """Get category details including children_categories."""
        ...

    def get_category_attributes(self, category_id: str) -> list[dict[str, Any]]:
        """Get attributes for a category."""
        ...

    def get_category_technical_specs(self, category_id: str) -> dict[str, Any]:
        """Get technical specs input for a category."""
        ...

    def get_category_conditional_attributes(
        self, category_id: str, item_context: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Get conditional attributes for a category.

        Args:
            category_id: Category ID
            item_context: Full item context payload used by conditional checks

        Returns:
            List of conditional attributes
        """
        ...

    def predict_category(
        self, title: str, site_id: str, limit: int | None = None
    ) -> list[dict[str, Any]]:
        """Predict category based on product title.

        Args:
            title: Product title
            site_id: Site ID
            limit: Maximum number of predictions to request

        Returns:
            List of predicted categories with confidence scores
        """
        ...


class AttributeCachePort(Protocol):
    """Port interface for attribute cache."""

    def get_attributes(self, category_id: str) -> list[dict[str, Any]] | None:
        """Get cached attributes if valid."""
        ...

    def save_attributes(self, category_id: str, attributes: list[dict[str, Any]]) -> None:
        """Save attributes to cache."""
        ...


class CategoryResolver:
    """Resolves category names to IDs using API port.

    Pure domain logic - no external dependencies.
    Supports hierarchical category resolution.
    """

    def __init__(
        self,
        api_port: CategoryApiPort,
        attribute_cache: AttributeCachePort | None = None,
        prediction_cache: Any | None = None,
        max_predictions: int = 5,
    ):
        """Initialize with API port.

        Args:
            api_port: Implementation of category API operations
            attribute_cache: Optional cache for category attributes
            prediction_cache: Optional cache for domain discovery predictions
            max_predictions: Maximum number of titles to predict (default: 5)
        """
        self._api = api_port
        self._attribute_cache = attribute_cache
        self._prediction_cache = prediction_cache
        self._max_predictions = max_predictions
        self._categories: dict[str, str] = {}  # name -> id cache
        self._category_cache: dict[str, dict[str, Any]] = {}  # id -> data cache
        self._children_cache: dict[str, list[Any]] = {}  # id -> children cache
        self._loaded_site_id: str | None = None

    @staticmethod
    def _normalize_site_id(site_id: str | None) -> str:
        return normalize_site_id(site_id)

    @staticmethod
    def _normalize_category_id(category_id: Any, expected_site_id: str | None = None) -> str | None:
        return normalize_category_id(category_id, expected_site_id)

    @staticmethod
    def _split_category_query(name: str) -> tuple[str, set[str]]:
        return split_category_query(name)

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        return safe_float(value, default)

    @staticmethod
    def _pick_best_candidate(
        current: tuple[str, tuple[Any, ...]] | None,
        candidate: tuple[str, tuple[Any, ...]] | None,
    ) -> tuple[str, tuple[Any, ...]] | None:
        return pick_best_candidate(current, candidate)

    def _build_match_score(
        self,
        target_name: str,
        candidate_name: str,
        context_terms: set[str],
        path_names: list[str],
        depth: int,
        min_similarity: float,
    ) -> tuple[Any, ...] | None:
        return build_match_score(
            target_name=target_name,
            candidate_name=candidate_name,
            context_terms=context_terms,
            path_names=path_names,
            depth=depth,
            min_similarity=min_similarity,
        )

    def load_categories(self, site_id: str = "MLB") -> None:
        """Load all categories for a site.

        Stores normalized category names (lowercase, no accents) for better matching.
        """
        normalized_site = self._normalize_site_id(site_id)
        self._categories = _load_categories_helper(
            self._api,
            normalized_site,
            self._normalize_category_id,
        )
        self._loaded_site_id = normalized_site

    def _get_category_children(self, category_id: str) -> list[dict[str, Any]]:
        """Get children of a category from category data."""
        return _get_category_children_helper(
            self._api,
            category_id,
            self._children_cache,
            self._normalize_category_id,
        )

    def _search_in_hierarchy(
        self,
        target_name: str,
        parent_id: str,
        context_terms: set[str] | None = None,
        path_names: list[str] | None = None,
        visited: set[str] | None = None,
        depth: int = 0,
        max_depth: int = 8,
        min_similarity: float = 0.8,
        site_id: str = "MLB",
    ) -> tuple[str, tuple[Any, ...]] | None:
        """Search for category name in hierarchy starting from parent.

        Args:
            target_name: Category name to search for
            parent_id: Parent category ID
            context_terms: Context path terms (e.g., "eletronicos > celulares")
            path_names: Path names from root to current parent (normalized)
            visited: Set of visited category IDs
            depth: Current recursion depth
            max_depth: Maximum recursion depth
            min_similarity: Minimum similarity for fuzzy matching (0.0-1.0)
            site_id: Expected site prefix for category IDs

        Returns:
            Tuple(category_id, score) or None
        """
        return _search_in_hierarchy_helper(
            target_name=target_name,
            parent_id=parent_id,
            get_category_children=self._get_category_children,
            normalize_category_id=self._normalize_category_id,
            build_match_score=self._build_match_score,
            pick_best_candidate=self._pick_best_candidate,
            context_terms=context_terms,
            path_names=path_names,
            visited=visited,
            depth=depth,
            max_depth=max_depth,
            min_similarity=min_similarity,
            site_id=site_id,
        )

    def resolve_to_leaf(
        self,
        category_id: str,
        visited: set[str] | None = None,
        depth: int = 0,
        max_depth: int = 20,
    ) -> str:
        """Ensure we reach a leaf category (no children).

        If the category has children, navigate down to find a leaf.

        Args:
            category_id: Starting category ID
            visited: Seen category IDs to avoid cycles
            depth: Current recursion depth
            max_depth: Maximum recursion depth

        Returns:
            Leaf category ID
        """
        normalized_category_id = self._normalize_category_id(category_id)
        if not normalized_category_id:
            logger.error(f"Invalid category ID for leaf resolution: {category_id}")
            return category_id

        if visited is None:
            visited = set()

        if normalized_category_id in visited or depth > max_depth:
            return normalized_category_id

        visited.add(normalized_category_id)
        children = self._get_category_children(normalized_category_id)

        if not children:
            return normalized_category_id  # It's a leaf!

        if len(children) > 1:
            logger.warning(
                "Category %s has %s children and no explicit child hint; "
                "keeping parent category to avoid unsafe leaf auto-selection.",
                normalized_category_id,
                len(children),
            )
            return normalized_category_id

        best_child = children[0]
        logger.info(
            f"Category {category_id} has a single child, selecting "
            f"'{best_child['name']}' ({best_child['id']})"
        )

        # Recursively resolve to leaf
        return self.resolve_to_leaf(
            best_child["id"], visited=visited, depth=depth + 1, max_depth=max_depth
        )

    def find_category(self, name: str, site_id: str = "MLB") -> str | None:
        """Find category ID by name using deterministic hierarchical matching.

        Args:
            name: Category name (e.g., "Livros Físicos")
            site_id: Site ID

        Returns:
            Category ID or None
        """
        normalized_site = self._normalize_site_id(site_id)
        if not self._categories or self._loaded_site_id != normalized_site:
            self.load_categories(normalized_site)

        target_name, context_terms = self._split_category_query(name)
        if not target_name:
            return None

        logger.info(f"Looking for category: '{name}' (target: '{target_name}')")
        sorted_roots = sorted(self._categories.items(), key=lambda item: (item[0], item[1]))
        best_match: tuple[str, tuple[Any, ...]] | None = None

        for root_name, root_id in sorted_roots:
            root_score = self._build_match_score(
                target_name=target_name,
                candidate_name=root_name,
                context_terms=context_terms,
                path_names=[root_name],
                depth=0,
                min_similarity=0.8,
            )
            if root_score is not None:
                best_match = self._pick_best_candidate(best_match, (root_id, root_score))

        # Fast path for exact root match when no context path was provided
        if best_match and best_match[1][2] == 3 and not context_terms:
            logger.info(f"Found exact root match for '{name}': {best_match[0]}")
            return best_match[0]

        for root_name, root_id in sorted_roots:
            hierarchy_match = self._search_in_hierarchy(
                target_name=target_name,
                parent_id=root_id,
                context_terms=context_terms,
                path_names=[root_name],
                visited=set(),
                depth=0,
                max_depth=8,
                min_similarity=0.8,
                site_id=normalized_site,
            )
            best_match = self._pick_best_candidate(best_match, hierarchy_match)

        if best_match:
            logger.info(f"Resolved category '{name}' to {best_match[0]}")
            return best_match[0]

        logger.info(f"Category '{name}' not found")
        return None

    def predict_category_from_title(self, title: str, site_id: str = "MLB") -> str | None:
        """Predict a category id from product title using domain discovery."""
        return _predict_category_from_title_helper(self, title, site_id)

    def _call_domain_discovery(
        self, title: str, site_id: str, limit: int = 3
    ) -> list[dict[str, Any]]:
        return _call_domain_discovery_helper(self._api, title, site_id, limit)

    def find_category_with_predictor(
        self,
        category_name: str,
        product_titles: list[str],
        site_id: str = "MLB",
    ) -> str | None:
        """Find target category by matching domain-discovery predictions."""
        return _find_category_with_predictor_helper(self, category_name, product_titles, site_id)

    def _get_category_cached(self, category_id: str) -> dict[str, Any]:
        """Get category data with caching.

        Args:
            category_id: Category ID

        Returns:
            Category data
        """
        if category_id in self._category_cache:
            return self._category_cache[category_id]

        try:
            data = self._api.get_category(category_id)
            if isinstance(data, dict):
                self._category_cache[category_id] = data
                return data
        except Exception as e:
            logger.warning(f"Failed to get category {category_id}: {e}")

        return {}

    def get_category_data(self, category_id: str) -> dict[str, Any]:
        """Get category details for policy and validation workflows."""
        return self._get_category_cached(category_id)

    def is_listing_allowed(self, category_id: str) -> bool:
        """Check whether category is enabled for listing.

        Uses category settings fields documented by Mercado Livre:
        - settings.listing_allowed should be true
        - settings.status should be enabled
        """
        data = self._get_category_cached(category_id)
        if not data:
            return False

        settings = data.get("settings", {})
        if not isinstance(settings, dict):
            return True

        if settings.get("listing_allowed") is False:
            return False

        status = settings.get("status")
        return not (isinstance(status, str) and status and status != "enabled")

    def find_category_by_name_or_title(
        self, name: str | None = None, title: str | None = None, site_id: str = "MLB"
    ) -> str | None:
        """Find category by name, falling back to title-based prediction.

        Args:
            name: Category name to search for
            title: Product title for ML prediction fallback
            site_id: Site ID

        Returns:
            Category ID or None
        """
        # First try by name
        if name:
            result = self.find_category(name, site_id)
            if result:
                return result

        # Fallback to title-based prediction
        if title:
            logger.info("Category name not found, trying domain discovery with title...")
            result = self.predict_category_from_title(title, site_id)
            if result:
                return result

        return None

    def get_mandatory_attributes(self, category_id: str) -> list[dict[str, Any]]:
        """Get mandatory attributes for a category."""
        return _get_mandatory_attributes_helper(self.get_all_attributes(category_id))

    def get_all_attributes(self, category_id: str) -> list[dict[str, Any]]:
        """Get all attributes for a category (cached)."""
        return _get_all_attributes_helper(
            category_id,
            self._api.get_category_attributes,
            self._attribute_cache,
            logger,
        )

    def build_attribute_map(self, category_id: str) -> dict[str, dict[str, Any]]:
        """Build name -> attribute mapping."""
        return _build_attribute_map_helper(self.get_all_attributes(category_id))

    def get_conditional_attributes(
        self, category_id: str, item_context: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Get conditional attributes based on full item context.

        Args:
            category_id: Category ID
            item_context: Full item context payload (same shape as item publish payload)

        Returns:
            List of conditional attributes
        """
        return _get_conditional_attributes_helper(
            category_id,
            item_context,
            self._api.get_category_conditional_attributes,
        )

    def get_all_attributes_with_conditionals(
        self, category_id: str, item_context: dict[str, Any]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Get all attributes including conditional ones.

        Args:
            category_id: Category ID
            item_context: Full item context payload

        Returns:
            Tuple of (base_attributes, conditional_attributes)
        """
        return _get_all_attributes_with_conditionals_helper(
            self.get_all_attributes(category_id),
            self.get_conditional_attributes(category_id, item_context),
        )

    def get_required_attributes(
        self, category_id: str, item_context: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Get all required attributes including conditionally required.

        Args:
            category_id: Category ID
            item_context: Full item context payload

        Returns:
            List of required attribute definitions
        """
        return _get_required_attributes_helper(
            self.get_all_attributes(category_id),
            self.get_conditional_attributes(category_id, item_context),
        )

    def _extract_technical_spec_attributes(
        self, specs: dict[str, Any]
    ) -> dict[str, dict[str, Any]]:
        return extract_technical_spec_attributes(specs)

    def _merge_technical_spec(self, attr: dict[str, Any], spec: dict[str, Any]) -> None:
        merge_technical_spec(attr, spec)

    def get_attribute_metadata(self, category_id: str) -> list[AttributeMeta]:
        """Get normalized attribute metadata for a category.

        Args:
            category_id: Category ID

        Returns:
            List of AttributeMeta objects
        """
        return _get_attribute_metadata_helper(self, category_id, logger)
