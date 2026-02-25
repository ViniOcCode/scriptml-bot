"""Category resolver domain logic.

Domain layer defines the interface (port) for category resolution.
Infrastructure layer provides the implementation (adapter).
"""

import logging
from typing import Any, Protocol

from mercadolivre_upload.shared.utils.text_utils import TextNormalizer

from ..attribute_metadata import AttributeMeta
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
        categories = self._api.get_site_categories(normalized_site)

        self._categories.clear()
        items: list[tuple[str, str]] = []

        for cat in categories:
            if not isinstance(cat, dict):
                continue

            category_id = self._normalize_category_id(cat.get("id"), normalized_site)
            category_name = cat.get("name")
            if not category_id or not isinstance(category_name, str):
                continue

            name_normalized = TextNormalizer.normalize(category_name)
            if name_normalized:
                items.append((name_normalized, category_id))

        for name_normalized, category_id in sorted(items, key=lambda item: (item[0], item[1])):
            self._categories[name_normalized] = category_id

        self._loaded_site_id = normalized_site

    def _get_category_children(self, category_id: str) -> list[dict[str, Any]]:
        """Get children of a category from category data."""
        if category_id not in self._children_cache:
            try:
                # Use get_category which returns children_categories in response
                category_data = self._api.get_category(category_id)
                raw_children = []
                if isinstance(category_data, dict):
                    raw_children = category_data.get("children_categories", [])

                expected_site = category_id[:3] if len(category_id) >= 3 else None
                children: list[dict[str, Any]] = []
                if isinstance(raw_children, list):
                    for child in raw_children:
                        if not isinstance(child, dict):
                            continue

                        child_id = self._normalize_category_id(child.get("id"), expected_site)
                        child_name = child.get("name")
                        if not child_id or not isinstance(child_name, str):
                            continue

                        children.append({**child, "id": child_id, "name": child_name.strip()})

                children.sort(
                    key=lambda child: (
                        TextNormalizer.normalize(str(child.get("name", ""))),
                        str(child.get("id", "")),
                    )
                )
                self._children_cache[category_id] = children
            except Exception:
                self._children_cache[category_id] = []
        return self._children_cache[category_id]

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
        if visited is None:
            visited = set()
        if context_terms is None:
            context_terms = set()
        if path_names is None:
            path_names = []

        # Prevent infinite recursion
        if depth > max_depth:
            return None

        if parent_id in visited:
            return None

        visited.add(parent_id)
        children = self._get_category_children(parent_id)
        best_match: tuple[str, tuple[Any, ...]] | None = None

        for child in children:
            child_id = self._normalize_category_id(child.get("id"), site_id)
            child_name = child.get("name")
            if not child_id or not isinstance(child_name, str):
                continue

            child_normalized = TextNormalizer.normalize(child_name)
            child_path = [*path_names, child_normalized]

            score = self._build_match_score(
                target_name=target_name,
                candidate_name=child_normalized,
                context_terms=context_terms,
                path_names=child_path,
                depth=depth + 1,
                min_similarity=min_similarity,
            )
            if score is not None:
                best_match = self._pick_best_candidate(best_match, (child_id, score))

            subtree_match = self._search_in_hierarchy(
                target_name=target_name,
                parent_id=child_id,
                context_terms=context_terms,
                path_names=child_path,
                visited=visited,
                depth=depth + 1,
                max_depth=max_depth,
                min_similarity=min_similarity,
                site_id=site_id,
            )
            best_match = self._pick_best_candidate(best_match, subtree_match)

        return best_match

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
        site_id = normalized_category_id[:3]

        data = self._api.get_category(normalized_category_id)

        # CRITICAL FIX: Prevent 'str' object error
        if not isinstance(data, dict):
            logger.error(f"Invalid API response for {normalized_category_id}: {data}")
            return normalized_category_id

        raw_children = data.get("children_categories", [])
        children: list[dict[str, Any]] = []
        if isinstance(raw_children, list):
            for child in raw_children:
                if not isinstance(child, dict):
                    continue

                child_id = self._normalize_category_id(child.get("id"), site_id)
                child_name = child.get("name")
                if not child_id or not isinstance(child_name, str):
                    continue

                children.append({**child, "id": child_id, "name": child_name.strip()})

        if not children:
            return normalized_category_id  # It's a leaf!

        # Deterministic child selection (stable and context-safe fallback)
        sorted_children = sorted(
            children,
            key=lambda child: (
                TextNormalizer.normalize(str(child.get("name", ""))),
                str(child.get("id", "")),
            ),
        )
        best_child = sorted_children[0]
        logger.info(
            f"Category {category_id} has children, selecting "
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
        attributes = self.get_all_attributes(category_id)
        return [attr for attr in attributes if attr.get("tags", {}).get("required")]

    def get_all_attributes(self, category_id: str) -> list[dict[str, Any]]:
        """Get all attributes for a category (cached)."""
        # Check cache first
        if self._attribute_cache:
            cached = self._attribute_cache.get_attributes(category_id)
            if cached is not None:
                logger.debug(f"Using cached attributes for {category_id}")
                return cached

        # Fetch from API
        attributes = self._api.get_category_attributes(category_id)

        # Save to cache
        if self._attribute_cache:
            self._attribute_cache.save_attributes(category_id, attributes)

        return attributes

    def build_attribute_map(self, category_id: str) -> dict[str, dict[str, Any]]:
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
        self, category_id: str, item_context: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Get conditional attributes based on full item context.

        Args:
            category_id: Category ID
            item_context: Full item context payload (same shape as item publish payload)

        Returns:
            List of conditional attributes
        """
        try:
            result = self._api.get_category_conditional_attributes(category_id, item_context)
            # Handle case where API returns error message or non-list
            if isinstance(result, dict) and "error" in result:
                return []
            if isinstance(result, str):
                return []
            if not isinstance(result, list):
                return []
            return result
        except Exception:
            # Log error but don't fail - conditional attrs are optional
            return []

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
        base_attrs = self.get_all_attributes(category_id)
        conditional = self.get_conditional_attributes(category_id, item_context)
        return base_attrs, conditional

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
        # Get base required attributes
        all_base = self.get_all_attributes(category_id)
        required = [attr for attr in all_base if attr.get("tags", {}).get("required")]

        # Get conditional attributes
        conditional = self.get_conditional_attributes(category_id, item_context)

        # Filter conditional required attributes
        required_conditional = [
            attr for attr in conditional if attr.get("tags", {}).get("required")
        ]

        return required + required_conditional

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
        # Try cache first if available
        raw_attributes: list[dict[str, Any]] | None = None
        if self._attribute_cache:
            cached = self._attribute_cache.get_attributes(category_id)
            if cached is not None:
                logger.debug(f"Using cached metadata for {category_id}")
                raw_attributes = cached

        # Fetch from API when cache is not available
        if raw_attributes is None:
            raw_attributes = self._api.get_category_attributes(category_id)

        # Enrich with technical specs input (relevance, hierarchy, tags)
        technical_specs = {}
        if hasattr(self._api, "get_category_technical_specs"):
            try:
                technical_specs = self._api.get_category_technical_specs(category_id)
            except Exception:
                technical_specs = {}

        if technical_specs:
            spec_map = self._extract_technical_spec_attributes(technical_specs)
            if spec_map:
                for attr in raw_attributes:
                    attr_id = attr.get("id")
                    if not isinstance(attr_id, str):
                        continue
                    spec = spec_map.get(attr_id)
                    if spec:
                        self._merge_technical_spec(attr, spec)

        # Normalize to AttributeMeta
        metadata = []
        for attr in raw_attributes:
            try:
                meta = AttributeMeta.from_ml_api(attr)
                metadata.append(meta)
            except (KeyError, TypeError) as e:
                logger.warning(f"Failed to parse attribute: {attr.get('id', 'unknown')}: {e}")

        # Save to cache
        if self._attribute_cache and raw_attributes is not None:
            self._attribute_cache.save_attributes(category_id, raw_attributes)

        return metadata
