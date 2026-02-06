"""CBT ID extractor utility.

Provides robust extraction of CBT (Catalog Basic Template) parent item IDs
from Mercado Livre API responses, with multiple fallback strategies.
"""

import logging
from typing import TYPE_CHECKING

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
    
    def extract_cbt_id(self, result: dict) -> str | None:
        """Extract CBT parent item ID from item creation response.
        
        Tries multiple strategies in order:
        1. Direct `cbt_item_id` field
        2. `id` field if it starts with "CBT"
        3. `parent_id` from first marketplace_items entry
        4. `parent_item_id` top-level field
        5. `item_relations` or other nested structures
        6. Fallback GET request to /items/{marketplace_id} (if api_client available)
        
        Args:
            result: Response dict from POST /items or GET /items/{id}
            
        Returns:
            CBT item ID (e.g., "CBT1234567890") or None if not found
        """
        # Strategy 1: Direct cbt_item_id field
        cbt_id = result.get("cbt_item_id")
        if cbt_id:
            if self._is_valid_cbt_id(cbt_id):
                logger.debug(f"CBT ID extracted from cbt_item_id field: {cbt_id}")
                return cbt_id
            # Accept numeric-only values and normalize to CBT prefix
            normalized = self._normalize_if_digits(cbt_id)
            if normalized:
                logger.debug(f"Normalized numeric cbt_item_id to CBT ID: {normalized}")
                return normalized

        # Strategy 2: id field if it's a CBT ID
        item_id = result.get("id")
        if item_id:
            if self._is_valid_cbt_id(item_id):
                logger.debug(f"CBT ID extracted from id field: {item_id}")
                return item_id
            normalized = self._normalize_if_digits(item_id)
            if normalized:
                logger.debug(f"Normalized numeric id field to CBT ID: {normalized}")
                return normalized

        # Strategy 3: parent_id from marketplace_items
        marketplace_items = result.get("marketplace_items", [])
        if marketplace_items:
            for mkt_item in marketplace_items:
                parent_id = mkt_item.get("parent_id")
                if parent_id:
                    if self._is_valid_cbt_id(parent_id):
                        logger.debug(
                            f"CBT ID extracted from marketplace_items[].parent_id: {parent_id}"
                        )
                        return parent_id
                    normalized = self._normalize_if_digits(parent_id)
                    if normalized:
                        logger.debug(
                            f"Normalized numeric marketplace_items[].parent_id to CBT ID: {normalized}"
                        )
                        return normalized

        # Strategy 4: top-level parent_item_id (some endpoints use this field)
        parent_item_id = result.get("parent_item_id")
        if parent_item_id:
            if self._is_valid_cbt_id(parent_item_id):
                logger.debug(f"CBT ID extracted from parent_item_id field: {parent_item_id}")
                return parent_item_id
            normalized = self._normalize_if_digits(parent_item_id)
            if normalized:
                logger.debug(f"Normalized numeric parent_item_id to CBT ID: {normalized}")
                return normalized

        # Strategy 5: search nested structures like item_relations for any CBT ID
        item_relations = result.get("item_relations")
        if item_relations is not None:
            found = self._search_for_cbt_in_structure(item_relations)
            if found:
                logger.debug(f"CBT ID extracted from nested item_relations: {found}")
                return found

        # As a last-ditch effort before API fallback, scan entire response for CBT ids
        found_anywhere = self._search_for_cbt_in_structure(result)
        if found_anywhere:
            logger.debug(f"CBT ID found by scanning entire response: {found_anywhere}")
            return found_anywhere

        # Strategy 6: Fallback GET request (if we have a marketplace ID)
        if item_id and not self._is_valid_cbt_id(item_id):
            # Check cache first
            if item_id in self._cache:
                cached_cbt_id = self._cache[item_id]
                logger.debug(
                    f"CBT ID retrieved from cache for {item_id}: {cached_cbt_id}"
                )
                return cached_cbt_id
            
            # Try API fallback
            if self.api_client:
                cbt_id = self._fetch_cbt_id_from_api(item_id)
                if cbt_id:
                    self._cache[item_id] = cbt_id
                    logger.info(
                        f"CBT ID fetched via API for marketplace item {item_id}: {cbt_id}"
                    )
                    return cbt_id
        
        # No CBT ID found
        logger.warning(
            f"Could not extract CBT ID from response. "
            f"Available fields: {list(result.keys())}"
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

    def _normalize_if_digits(self, val) -> str | None:
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
    
    def _search_for_cbt_in_structure(self, obj) -> str | None:
        """Recursively search a nested structure for the first CBT ID string.

        This is a defensive helper to discover CBT IDs inside unexpected
        structures such as item_relations, nested dicts, or lists.
        """
        # Strings with CBT prefix or numeric strings that can be normalized
        if isinstance(obj, str):
            if self._is_valid_cbt_id(obj):
                return obj
            # Accept numeric strings and normalize
            normalized = self._normalize_if_digits(obj)
            if normalized:
                return normalized
            return None
        # Direct integers (some APIs may return numeric IDs)
        if isinstance(obj, int):
            return f"CBT{obj}"
        if isinstance(obj, dict):
            # Search keys and values
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
            logger.debug(f"Fetching item details for {marketplace_item_id} to find CBT parent")
            item_data = self.api_client.get(f"/items/{marketplace_item_id}")
            
            # Try cbt_item_id field
            cbt_id = item_data.get("cbt_item_id")
            if cbt_id:
                if self._is_valid_cbt_id(cbt_id):
                    return cbt_id
                normalized = self._normalize_if_digits(cbt_id)
                if normalized:
                    return normalized
            
            # Try parent_id and parent_item_id fields
            parent_id = item_data.get("parent_id") or item_data.get("parent_item_id")
            if parent_id:
                if self._is_valid_cbt_id(parent_id):
                    return parent_id
                normalized = self._normalize_if_digits(parent_id)
                if normalized:
                    return normalized
            
            # Search common nested structures for CBT IDs (item_relations etc.)
            found = self._search_for_cbt_in_structure(item_data)
            if found:
                return found
            
            logger.warning(
                f"GET /items/{marketplace_item_id} did not return a valid CBT parent ID"
            )
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
