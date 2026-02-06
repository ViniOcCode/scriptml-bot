"""Category resolver domain logic.

Domain layer defines the interface (port) for category resolution.
Infrastructure layer provides the implementation (adapter).
"""

import logging
import unicodedata
from difflib import SequenceMatcher
from typing import Any, Protocol

from ..attribute_metadata import AttributeMeta

logger = logging.getLogger(__name__)


def normalize_text(text: str) -> str:
    """Normalize text for comparison.

    - Lowercase
    - Remove accents
    - Strip whitespace

    Args:
        text: Input text

    Returns:
        Normalized text
    """
    text = text.lower().strip()
    # Remove accents (é -> e, ã -> a, etc.)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return text


def similarity(a: str, b: str) -> float:
    """Calculate string similarity ratio.

    Args:
        a: First string
        b: Second string

    Returns:
        Similarity ratio (0.0 to 1.0)
    """
    return SequenceMatcher(None, normalize_text(a), normalize_text(b)).ratio()


class CategoryApiPort(Protocol):
    """Port interface for category API operations.

    Infrastructure layer implements this.
    """

    def get_site_categories(self, site_id: str) -> list[dict]:
        """Get all categories for a site."""
        ...

    def get_category(self, category_id: str) -> dict:
        """Get category details including children_categories."""
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

    def predict_category(self, title: str, site_id: str) -> list[dict]:
        """Predict category based on product title.

        Args:
            title: Product title
            site_id: Site ID

        Returns:
            List of predicted categories with confidence scores
        """
        ...


class AttributeCachePort(Protocol):
    """Port interface for attribute cache."""

    def get_attributes(self, category_id: str) -> list[dict] | None:
        """Get cached attributes if valid."""
        ...

    def save_attributes(self, category_id: str, attributes: list[dict]) -> None:
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
        self._category_cache: dict[str, dict] = {}  # id -> data cache
        self._children_cache: dict[str, list] = {}  # id -> children cache

    def load_categories(self, site_id: str = "MLB") -> None:
        """Load all categories for a site.

        Stores normalized category names (lowercase, no accents) for better matching.
        """
        categories = self._api.get_site_categories(site_id)

        for cat in categories:
            name_normalized = normalize_text(cat["name"])
            self._categories[name_normalized] = cat["id"]

    def _get_category_children(self, category_id: str) -> list[dict]:
        """Get children of a category from category data."""
        if category_id not in self._children_cache:
            try:
                # Use get_category which returns children_categories in response
                category_data = self._api.get_category(category_id)
                children = category_data.get("children_categories", [])
                self._children_cache[category_id] = children
            except Exception:
                self._children_cache[category_id] = []
        return self._children_cache[category_id]

    def _search_in_hierarchy(
        self,
        name: str,
        parent_id: str,
        parent_name: str = "",
        visited: set | None = None,
        depth: int = 0,
        max_depth: int = 5,
        min_similarity: float = 0.8,
    ) -> str | None:
        """Search for category name in hierarchy starting from parent.

        Args:
            name: Category name to search for
            parent_id: Parent category ID
            parent_name: Parent category name (for logging)
            visited: Set of visited category IDs
            depth: Current recursion depth
            max_depth: Maximum recursion depth
            min_similarity: Minimum similarity for fuzzy matching (0.0-1.0)

        Returns:
            Category ID or None
        """
        if visited is None:
            visited = set()

        # Prevent infinite recursion
        if depth > max_depth:
            return None

        if parent_id in visited:
            return None

        visited.add(parent_id)
        name_normalized = normalize_text(name)

        # Get children of this category
        children = self._get_category_children(parent_id)

        best_match = None
        best_similarity = 0.0

        for child in children:
            child_name = child["name"]
            child_id = child["id"]
            child_normalized = normalize_text(child_name)

            # Cache this child
            self._categories[child_normalized] = child_id

            # Exact normalized match
            if child_normalized == name_normalized:
                logger.info(f"Found exact match: '{child_name}' ({child_id})")
                return child_id

            # Contains check
            if name_normalized in child_normalized or child_normalized in name_normalized:
                logger.info(f"Found substring match: '{child_name}' ({child_id})")
                return child_id

            # Fuzzy similarity check
            sim = similarity(child_name, name)
            if sim > best_similarity:
                best_similarity = sim
                best_match = (child_id, child_name)

            # Recursively search in child's children
            result = self._search_in_hierarchy(
                name, child_id, child_name, visited, depth + 1, max_depth, min_similarity
            )
            if result:
                return result

        # If we found a good fuzzy match, return it
        if best_match and best_similarity >= min_similarity:
            logger.info(
                f"Found fuzzy match (similarity={best_similarity:.2f}): "
                f"'{best_match[1]}' ({best_match[0]})"
            )
            return best_match[0]

        return None

    def resolve_to_leaf(self, category_id: str) -> str:
        """Ensure we reach a leaf category (no children).

        If the category has children, navigate down to find a leaf.

        Args:
            category_id: Starting category ID

        Returns:
            Leaf category ID
        """
        data = self._api.get_category(category_id)

        # CRITICAL FIX: Prevent 'str' object error
        if not isinstance(data, dict):
            logger.error(f"Invalid API response for {category_id}: {data}")
            return category_id

        children = data.get("children_categories", [])
        if not children:
            return category_id  # It's a leaf!

        # Pick the child with most items as the best guess
        # Sort by total_items_in_this_category (descending)
        sorted_children = sorted(
            children, key=lambda x: x.get("total_items_in_this_category", 0), reverse=True
        )
        best_child = sorted_children[0]
        logger.info(
            f"Category {category_id} has children, selecting "
            f"'{best_child['name']}' ({best_child['id']})"
        )

        # Recursively resolve to leaf
        return self.resolve_to_leaf(best_child["id"])

    def find_category(self, name: str, site_id: str = "MLB") -> str | None:
        """Find category ID by name using fast root matching.

        Searches only root categories with fuzzy matching.
        Does NOT traverse hierarchy to avoid excessive API calls.

        Args:
            name: Category name (e.g., "Livros Físicos")
            site_id: Site ID

        Returns:
            Category ID or None
        """
        if not self._categories:
            self.load_categories(site_id)

        name_normalized = normalize_text(name)
        logger.info(f"Looking for category: '{name}' (normalized: '{name_normalized}')")

        # Fast path: Check root categories with fuzzy matching
        best_root_match = None
        best_root_sim = 0.0

        for cat_name, cat_id in list(self._categories.items()):
            # Direct normalized match
            if cat_name == name_normalized:
                logger.info(f"Found exact match in root: '{name}' -> '{cat_name}' ({cat_id})")
                return cat_id

            # Substring match
            if name_normalized in cat_name or cat_name in name_normalized:
                logger.info(f"Found substring match in root: '{name}' -> '{cat_name}' ({cat_id})")
                return cat_id

            # Track best fuzzy match
            sim = similarity(cat_name, name)
            if sim > best_root_sim:
                best_root_sim = sim
                best_root_match = (cat_name, cat_id)

        # If good fuzzy match in root, return it
        if best_root_match and best_root_sim >= 0.8:
            logger.info(
                f"Found fuzzy match in root (similarity={best_root_sim:.2f}): "
                f"'{name}' -> '{best_root_match[0]}' ({best_root_match[1]})"
            )
            return best_root_match[1]

        logger.info(f"Category '{name}' not in root categories")
        return None

    def predict_category_from_title(self, title: str, site_id: str = "MLB") -> str | None:
        """Predict category based on product title using ML domain discovery.

        Args:
            title: Product title
            site_id: Site ID

        Returns:
            Category ID or None
        """
        if not title or not isinstance(title, str):
            logger.warning(f"Invalid title for domain discovery: {title}")
            return None

        title = title.strip()
        if len(title) < 3:
            logger.warning(f"Title too short for domain discovery: '{title}'")
            return None

        # Check prediction cache
        if self._prediction_cache:
            cached = self._prediction_cache.get(title, site_id)
            if cached:
                predictions = cached
            else:
                predictions = self._call_domain_discovery(title, site_id)
                if predictions:
                    self._prediction_cache.set(title, predictions, site_id)
        else:
            predictions = self._call_domain_discovery(title, site_id)

        if predictions and len(predictions) > 0:
            # Get the first (highest confidence) prediction
            best_match = predictions[0]
            category_id = best_match.get("category_id")
            category_name = best_match.get("category_name", "unknown")
            logger.info(f"Domain discovery found: '{category_name}' ({category_id}) for title")
            return category_id

        logger.warning(f"Domain discovery returned empty for: '{title}'")
        return None

    def _call_domain_discovery(self, title: str, site_id: str) -> list[dict]:
        """Call domain discovery API.

        Args:
            title: Product title
            site_id: Site ID

        Returns:
            List of predictions
        """
        try:
            logger.info(f"Calling domain discovery for: '{title[:60]}...'")
            predictions = self._api.predict_category(title, site_id)
            logger.debug(f"Domain discovery response: {predictions}")
            return predictions if isinstance(predictions, list) else []
        except Exception as e:
            logger.warning(f"Domain discovery failed: {e}")
            return []

    def find_category_with_predictor(
        self,
        category_name: str,
        product_titles: list[str],
        site_id: str = "MLB",
    ) -> str | None:
        """Find category using domain discovery predictions.

        Predicts categories for product titles and checks if any prediction
        matches the requested category name in its path.

        Args:
            category_name: Requested category name
            product_titles: List of product titles to predict
            site_id: Site ID

        Returns:
            Category ID if found, None otherwise
        """
        if not product_titles:
            return None

        category_normalized = normalize_text(category_name)
        logger.info(
            f"Finding category '{category_name}' using predictor "
            f"with {len(product_titles)} titles..."
        )

        # Limit number of predictions to avoid rate limits
        titles_to_check = product_titles[: self._max_predictions]

        for title in titles_to_check:
            if not title or len(title) < 3:
                continue

            # Get predictions (cached or fresh)
            if self._prediction_cache:
                cached = self._prediction_cache.get(title, site_id)
                if cached:
                    predictions = cached
                else:
                    predictions = self._call_domain_discovery(title, site_id)
                    if predictions:
                        self._prediction_cache.set(title, predictions, site_id)
            else:
                predictions = self._call_domain_discovery(title, site_id)

            if not predictions:
                continue

            # Check top prediction
            for prediction in predictions[:3]:  # Check top 3 predictions
                predicted_id = prediction.get("category_id")
                if not predicted_id:
                    continue

                # Get category details to check path
                category_data = self._get_category_cached(predicted_id)
                if not category_data:
                    continue

                # Check if requested category is in path
                path_from_root = category_data.get("path_from_root", [])
                for node in path_from_root:
                    node_name = node.get("name", "")
                    if normalize_text(node_name) == category_normalized:
                        logger.info(
                            f"Found matching category in prediction path: "
                            f"'{node_name}' ({node.get('id')})"
                        )
                        return node.get("id")

                # Also check predicted category name itself
                predicted_name = prediction.get("category_name", "")
                if normalize_text(predicted_name) == category_normalized:
                    logger.info(
                        f"Predicted category matches requested: "
                        f"'{predicted_name}' ({predicted_id})"
                    )
                    return predicted_id

        logger.info(f"No prediction matched category '{category_name}'")
        return None

    def _get_category_cached(self, category_id: str) -> dict:
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

    def get_mandatory_attributes(self, category_id: str) -> list[dict]:
        """Get mandatory attributes for a category."""
        attributes = self.get_all_attributes(category_id)
        return [attr for attr in attributes if attr.get("tags", {}).get("required")]

    def get_all_attributes(self, category_id: str) -> list[dict]:
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

    def get_conditional_attributes(self, category_id: str, current_attributes: dict) -> list[dict]:
        """Get conditional attributes based on current attribute values.

        Args:
            category_id: Category ID
            current_attributes: Current attribute values (name -> value)

        Returns:
            List of conditional attributes
        """
        try:
            result = self._api.get_category_conditional_attributes(category_id, current_attributes)
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

    def get_required_attributes(self, category_id: str, product_attributes: dict) -> list[dict]:
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

    def get_attribute_metadata(self, category_id: str) -> list[AttributeMeta]:
        """Get normalized attribute metadata for a category.

        Args:
            category_id: Category ID

        Returns:
            List of AttributeMeta objects
        """
        # Try cache first if available
        if self._attribute_cache:
            cached = self._attribute_cache.get_attributes(category_id)
            if cached is not None:
                logger.debug(f"Using cached metadata for {category_id}")
                # Convert cached dicts to AttributeMeta objects
                return [AttributeMeta.from_ml_api(attr) for attr in cached]

        # Fetch from API
        raw_attributes = self._api.get_category_attributes(category_id)

        # Normalize to AttributeMeta
        metadata = []
        for attr in raw_attributes:
            try:
                meta = AttributeMeta.from_ml_api(attr)
                metadata.append(meta)
            except (KeyError, TypeError) as e:
                logger.warning(f"Failed to parse attribute: {attr.get('id', 'unknown')}: {e}")

        # Save to cache
        if self._attribute_cache:
            self._attribute_cache.save_attributes(category_id, raw_attributes)

        return metadata
