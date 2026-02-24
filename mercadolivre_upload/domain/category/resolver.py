"""Category resolver domain logic.

Domain layer defines the interface (port) for category resolution.
Infrastructure layer provides the implementation (adapter).
"""

import logging
import re
from typing import Any, Protocol

from mercadolivre_upload.shared.utils.text_utils import TextNormalizer

from ..attribute_metadata import AttributeMeta

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

    CATEGORY_ID_PATTERN = re.compile(r"^[A-Z]{3}\d+$")

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
        if site_id is None:
            return "MLB"
        normalized = str(site_id).strip().upper()
        return normalized if normalized else "MLB"

    @classmethod
    def _normalize_category_id(
        cls, category_id: Any, expected_site_id: str | None = None
    ) -> str | None:
        if not isinstance(category_id, str):
            return None

        normalized = category_id.strip().upper()
        if not cls.CATEGORY_ID_PATTERN.fullmatch(normalized):
            return None

        if expected_site_id:
            site_id = cls._normalize_site_id(expected_site_id)
            if not normalized.startswith(site_id):
                return None

        return normalized

    @staticmethod
    def _split_category_query(name: str) -> tuple[str, set[str]]:
        parts = [
            TextNormalizer.normalize(part)
            for part in re.split(r"\s*(?:>|/|\\|\|)\s*", str(name))
            if str(part).strip()
        ]
        if not parts:
            return "", set()
        return parts[-1], set(parts[:-1])

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _pick_best_candidate(
        current: tuple[str, tuple[Any, ...]] | None,
        candidate: tuple[str, tuple[Any, ...]] | None,
    ) -> tuple[str, tuple[Any, ...]] | None:
        if candidate is None:
            return current
        if current is None:
            return candidate

        current_id, current_score = current
        candidate_id, candidate_score = candidate
        if candidate_score > current_score:
            return candidate
        if candidate_score < current_score:
            return current
        return candidate if candidate_id < current_id else current

    def _build_match_score(
        self,
        target_name: str,
        candidate_name: str,
        context_terms: set[str],
        path_names: list[str],
        depth: int,
        min_similarity: float,
    ) -> tuple[Any, ...] | None:
        if not target_name or not candidate_name:
            return None

        match_rank = 0
        similarity = 0.0
        length_bias = -abs(len(candidate_name) - len(target_name))

        if candidate_name == target_name:
            match_rank = 3
            similarity = 1.0
        elif target_name in candidate_name or candidate_name in target_name:
            match_rank = 2
            similarity = min(len(target_name), len(candidate_name)) / max(
                len(target_name), len(candidate_name)
            )
        else:
            similarity = TextNormalizer.similarity(candidate_name, target_name)
            if similarity < min_similarity:
                return None
            match_rank = 1

        context_match_count = sum(1 for token in context_terms if token in path_names)
        context_complete = int(bool(context_terms) and context_match_count == len(context_terms))
        return (
            context_complete,
            context_match_count,
            match_rank,
            round(similarity, 6),
            length_bias,
            -depth,
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

        normalized_site = self._normalize_site_id(site_id)
        cache_key = TextNormalizer.normalize(title) or title

        # Check prediction cache
        if self._prediction_cache:
            cached = self._prediction_cache.get(cache_key, normalized_site)
            if cached is not None:
                predictions = cached
            else:
                predictions = self._call_domain_discovery(title, normalized_site)
                self._prediction_cache.set(cache_key, predictions, normalized_site)
        else:
            predictions = self._call_domain_discovery(title, normalized_site)

        if predictions and len(predictions) > 0:
            best_candidate: tuple[str, tuple[Any, ...]] | None = None
            for index, prediction in enumerate(predictions):
                if not isinstance(prediction, dict):
                    continue

                category_id = self._normalize_category_id(
                    prediction.get("category_id"), normalized_site
                )
                if not category_id:
                    continue

                confidence = self._safe_float(
                    prediction.get("confidence", prediction.get("score")), 0.0
                )
                candidate_score = (confidence, -index)
                best_candidate = self._pick_best_candidate(
                    best_candidate,
                    (category_id, candidate_score),
                )

            if best_candidate:
                category_name = next(
                    (
                        prediction.get("category_name", "unknown")
                        for prediction in predictions
                        if isinstance(prediction, dict)
                        and self._normalize_category_id(
                            prediction.get("category_id"), normalized_site
                        )
                        == best_candidate[0]
                    ),
                    "unknown",
                )
                logger.info(
                    f"Domain discovery found: '{category_name}' ({best_candidate[0]}) for title"
                )
                return best_candidate[0]

        logger.warning(f"Domain discovery returned empty for: '{title}'")
        return None

    def _call_domain_discovery(
        self, title: str, site_id: str, limit: int = 3
    ) -> list[dict[str, Any]]:
        """Call domain discovery API.

        Args:
            title: Product title
            site_id: Site ID
            limit: Maximum number of predictions to request

        Returns:
            List of predictions
        """
        try:
            logger.info(f"Calling domain discovery for: '{title[:60]}...'")
            predictions = self._api.predict_category(title, site_id, limit=limit)
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

        normalized_site = self._normalize_site_id(site_id)
        target_name, context_terms = self._split_category_query(category_name)
        if not target_name:
            return None

        logger.info(
            f"Finding category '{category_name}' using predictor "
            f"with {len(product_titles)} titles..."
        )

        # Limit number of predictions to avoid rate limits
        titles_to_check = product_titles[: self._max_predictions]
        batch_predictions: dict[str, list[dict[str, Any]]] = {}

        for title in titles_to_check:
            title_str = title.strip() if isinstance(title, str) else ""
            if len(title_str) < 3:
                continue

            normalized_title = TextNormalizer.normalize(title_str)
            if not normalized_title:
                continue

            if normalized_title in batch_predictions:
                predictions = batch_predictions[normalized_title]
            # Get predictions (cached or fresh)
            elif self._prediction_cache:
                cached = self._prediction_cache.get(normalized_title, normalized_site)
                if cached is not None:
                    predictions = cached
                else:
                    predictions = self._call_domain_discovery(title_str, normalized_site, limit=3)
                    self._prediction_cache.set(normalized_title, predictions, normalized_site)
            else:
                predictions = self._call_domain_discovery(title_str, normalized_site, limit=3)

            batch_predictions[normalized_title] = predictions

            if not predictions:
                continue

            title_best_match: tuple[str, tuple[Any, ...]] | None = None

            # Check top 3 predictions
            for prediction_rank, prediction in enumerate(predictions[:3]):
                if not isinstance(prediction, dict):
                    continue

                predicted_id = self._normalize_category_id(
                    prediction.get("category_id"), normalized_site
                )
                if not predicted_id:
                    continue

                confidence = self._safe_float(
                    prediction.get("confidence", prediction.get("score")), 0.0
                )
                depth_hint = prediction_rank

                # Get category details to check path
                category_data = self._get_category_cached(predicted_id)
                if not category_data:
                    continue

                # Check if requested category is in path
                path_from_root = category_data.get("path_from_root", [])
                normalized_path: list[str] = []
                for node in path_from_root:
                    if not isinstance(node, dict):
                        continue
                    node_id = self._normalize_category_id(node.get("id"), normalized_site)
                    node_name = node.get("name")
                    if not node_id or not isinstance(node_name, str):
                        continue

                    normalized_name = TextNormalizer.normalize(node_name)
                    normalized_path.append(normalized_name)
                    score = self._build_match_score(
                        target_name=target_name,
                        candidate_name=normalized_name,
                        context_terms=context_terms,
                        path_names=normalized_path,
                        depth=depth_hint,
                        min_similarity=0.8,
                    )
                    if score is None:
                        continue

                    candidate_score = (*score, confidence, -prediction_rank)
                    title_best_match = self._pick_best_candidate(
                        title_best_match,
                        (predicted_id, candidate_score),
                    )

                # Also check predicted category name itself
                predicted_name = prediction.get("category_name", "")
                if isinstance(predicted_name, str):
                    normalized_predicted_name = TextNormalizer.normalize(predicted_name)
                    score = self._build_match_score(
                        target_name=target_name,
                        candidate_name=normalized_predicted_name,
                        context_terms=context_terms,
                        path_names=normalized_path or [normalized_predicted_name],
                        depth=depth_hint,
                        min_similarity=0.8,
                    )
                    if score is not None:
                        candidate_score = (*score, confidence, -prediction_rank)
                        title_best_match = self._pick_best_candidate(
                            title_best_match,
                            (predicted_id, candidate_score),
                        )

            if title_best_match:
                logger.info(
                    "Found matching category from predictor: %s for '%s' using title '%s'",
                    title_best_match[0],
                    category_name,
                    title_str,
                )
                return title_best_match[0]

        logger.info(f"No prediction matched category '{category_name}' deterministically")
        return None

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
        """Flatten technical specs input into an attribute ID map."""
        attributes: dict[str, dict[str, Any]] = {}
        groups = specs.get("groups", []) if isinstance(specs, dict) else []

        for group in groups:
            components = group.get("components", []) if isinstance(group, dict) else []
            for component in components:
                comp_attrs = component.get("attributes", []) if isinstance(component, dict) else []
                for attr in comp_attrs:
                    if not isinstance(attr, dict):
                        continue
                    attr_id = attr.get("id")
                    if attr_id:
                        attributes[attr_id] = attr

        return attributes

    def _merge_technical_spec(self, attr: dict[str, Any], spec: dict[str, Any]) -> None:
        """Merge technical spec metadata into a base attribute definition."""
        if "relevance" in spec:
            attr["relevance"] = spec.get("relevance")
        if "hierarchy" in spec:
            attr["hierarchy"] = spec.get("hierarchy")

        if "tags" in spec:
            base_tags = attr.get("tags", {})
            merged_tags: dict[str, Any] = {}
            if isinstance(base_tags, dict):
                merged_tags.update(base_tags)
            elif isinstance(base_tags, list):
                merged_tags.update(dict.fromkeys(base_tags, True))

            spec_tags = spec.get("tags", [])
            if isinstance(spec_tags, dict):
                merged_tags.update(spec_tags)
            elif isinstance(spec_tags, list):
                merged_tags.update(dict.fromkeys(spec_tags, True))

            if merged_tags:
                attr["tags"] = merged_tags

        if spec.get("values") and not attr.get("values"):
            attr["values"] = spec.get("values")

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
