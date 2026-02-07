"""CBT ID extractor utility.

Provides robust extraction of CBT (Catalog Basic Template) parent item IDs
from Mercado Livre API responses, with multiple fallback strategies.
"""

import logging
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from mercadolivre_upload.api.client import MLApiClient

logger = logging.getLogger(__name__)


class CbtIdExtractor:
    """Extracts CBT parent item IDs from ML API responses.

    Implements multiple fallback strategies to reliably obtain the CBT ID
    required for clips upload and other Global Selling operations.
    """

    def __init__(self, api_client: "MLApiClient | None" = None):
        """Initialize extractor.

        Args:
            api_client: Optional ML API client for fallback GET requests
        """
        self.api_client = api_client
        self._cache: dict[str, str] = {}

    def extract_cbt_id(self, result: dict[str, Any]) -> str | None:
        """Extract CBT parent item ID from item creation response.

        Tries multiple strategies:
        1. Direct `cbt_item_id` or `parent_item_id` fields
        2. `id` field if it starts with "CBT"
        3. `parent_id` from marketplace_items entries
        4. Recursive search in nested structures (item_relations, etc.)
        5. Fallback GET /items/{marketplace_id} if api_client available

        Args:
            result: Response dict from POST /items or GET /items/{id}

        Returns:
            CBT item ID (e.g., "CBT1234567890") or None if not found
        """
        # Strategy 1: Direct fields (cbt_item_id, parent_item_id)
        for field in ("cbt_item_id", "parent_item_id"):
            val = result.get(field)
            if val:
                if self._is_valid_cbt_id(val):
                    return cast(str, val)
                normalized = self._normalize_if_digits(val)
                if normalized:
                    return normalized

        # Strategy 2: id field if it's already a CBT ID
        item_id = result.get("id")
        if item_id:
            if self._is_valid_cbt_id(item_id):
                return cast(str, item_id)
            normalized = self._normalize_if_digits(item_id)
            if normalized:
                return normalized

        # Strategy 3: parent_id from marketplace_items
        marketplace_items = result.get("marketplace_items", [])
        for mkt_item in marketplace_items:
            parent_id = mkt_item.get("parent_id")
            if parent_id:
                if self._is_valid_cbt_id(parent_id):
                    return cast(str, parent_id)
                normalized = self._normalize_if_digits(parent_id)
                if normalized:
                    return normalized

        # Strategy 4: Recursive search in nested structures
        found = self._search_for_cbt_in_structure(result)
        if found:
            return found

        # Strategy 5: Fallback GET request (if we have a marketplace ID and api_client)
        if item_id and not self._is_valid_cbt_id(item_id):
            # Check cache first
            if item_id in self._cache:
                return self._cache[item_id]

            # Try API fallback
            if self.api_client:
                cbt_id = self._fetch_cbt_id_from_api(item_id)
                if cbt_id:
                    self._cache[item_id] = cbt_id
                    return cbt_id

        # No CBT ID found
        logger.warning(
            f"Could not extract CBT ID from response. " f"Available fields: {list(result.keys())}"
        )
        return None

    def _is_valid_cbt_id(self, item_id: str) -> bool:
        """Check if an item ID is a valid CBT ID.

        Args:
            item_id: Item ID to validate

        Returns:
            True if item_id starts with "CBT", False otherwise
        """
        return isinstance(item_id, str) and item_id.startswith("CBT")

    def _normalize_if_digits(self, val: Any) -> str | None:
        """Normalize numeric IDs to CBT-prefixed strings when appropriate.

        If the API returns numeric parent IDs (e.g. 2796239245) instead of the
        "CBT"-prefixed form, normalize them to the canonical CBT string.
        """
        if val is None:
            return None
        if isinstance(val, int):
            return f"CBT{val}"
        if isinstance(val, str):
            s = val.strip()
            if s.isdigit():
                return f"CBT{s}"
        return None

    def _search_for_cbt_in_structure(self, obj: Any) -> str | None:
        """Recursively search a nested structure for a CBT ID.

        Handles strings, integers, dicts, lists, tuples, and sets.
        """
        if isinstance(obj, str):
            if self._is_valid_cbt_id(obj):
                return obj
            normalized = self._normalize_if_digits(obj)
            if normalized:
                return normalized
            return None

        if isinstance(obj, int):
            return f"CBT{obj}"

        if isinstance(obj, dict):
            for k, v in obj.items():
                if isinstance(k, str) and self._is_valid_cbt_id(k):
                    return k
                normalized_key = self._normalize_if_digits(k) if isinstance(k, str) else None
                if normalized_key:
                    return normalized_key
                found = self._search_for_cbt_in_structure(v)
                if found:
                    return found
            return None

        if isinstance(obj, (list, tuple, set)):
            for item in obj:
                found = self._search_for_cbt_in_structure(item)
                if found:
                    return found

        return None

    def _fetch_cbt_id_from_api(self, marketplace_item_id: str) -> str | None:
        """Fetch CBT parent ID via GET /items/{id} as fallback.

        Args:
            marketplace_item_id: Marketplace-specific item ID (e.g., MLB...)

        Returns:
            CBT parent item ID or None if not found
        """
        if not self.api_client:
            return None

        try:
            item_data = self.api_client.get(f"/items/{marketplace_item_id}")

            # Try cbt_item_id, parent_id, parent_item_id fields
            for field in ("cbt_item_id", "parent_id", "parent_item_id"):
                val = item_data.get(field)
                if val:
                    if self._is_valid_cbt_id(val):
                        return cast(str, val)
                    normalized = self._normalize_if_digits(val)
                    if normalized:
                        return normalized

            # Search nested structures
            found = self._search_for_cbt_in_structure(item_data)
            if found:
                return found

            logger.warning(f"GET /items/{marketplace_item_id} did not return a valid CBT parent ID")
            return None

        except Exception as e:
            logger.error(
                f"Failed to fetch CBT ID for {marketplace_item_id}: {e}",
                exc_info=True,
            )
            return None

    def clear_cache(self) -> None:
        """Clear the internal cache of marketplace_id -> cbt_id mappings."""
        self._cache.clear()
        logger.debug("CBT ID cache cleared")
