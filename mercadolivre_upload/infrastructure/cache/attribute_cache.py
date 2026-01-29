"""Local file-based cache for category attributes."""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Protocol

from ...domain.attribute_metadata import AttributeMeta

logger = logging.getLogger(__name__)


class AttributeCache:
    """Local file-based cache for category attributes.

    Caches category attributes to JSON files to avoid repeated API calls.
    Supports TTL (time-to-live) for cache invalidation.
    """

    def __init__(self, cache_dir: str = "cache/categories", ttl_hours: int = 24):
        """Initialize cache.

        Args:
            cache_dir: Directory to store cache files
            ttl_hours: Cache TTL in hours (0 = no expiration)
        """
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.ttl_hours = ttl_hours

    def _get_cache_file(self, category_id: str) -> Path:
        """Get cache file path for category."""
        return self.cache_dir / f"{category_id}.json"

    def _is_expired(self, cache_file: Path) -> bool:
        """Check if cache file is expired based on TTL."""
        if self.ttl_hours <= 0:
            return False  # No expiration

        try:
            with open(cache_file, encoding="utf-8") as f:
                data = json.load(f)

            cached_at = datetime.fromisoformat(data.get("cached_at", "2000-01-01"))
            expiry = cached_at + timedelta(hours=self.ttl_hours)
            return datetime.now() > expiry
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning(f"Cache file corrupted, treating as expired: {e}")
            return True

    def get_attributes(self, category_id: str) -> list[dict] | None:
        """Get cached attributes if valid.

        Args:
            category_id: Category ID

        Returns:
            List of attribute dicts or None if not cached/expired
        """
        cache_file = self._get_cache_file(category_id)

        if not cache_file.exists():
            logger.debug(f"Cache miss for {category_id}: file not found")
            return None

        if self._is_expired(cache_file):
            logger.debug(f"Cache expired for {category_id}")
            return None

        try:
            with open(cache_file, encoding="utf-8") as f:
                data = json.load(f)

            attributes = data.get("attributes", [])
            logger.debug(f"Cache hit for {category_id}: {len(attributes)} attributes")
            return attributes

        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"Failed to read cache for {category_id}: {e}")
            return None

    def save_attributes(self, category_id: str, attributes: list[dict]) -> None:
        """Save attributes to cache.

        Args:
            category_id: Category ID
            attributes: List of attribute dicts
        """
        cache_file = self._get_cache_file(category_id)

        data = {
            "cached_at": datetime.now().isoformat(),
            "category_id": category_id,
            "attributes": attributes,
        }

        try:
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            logger.debug(f"Cached {len(attributes)} attributes for {category_id}")
        except IOError as e:
            logger.warning(f"Failed to write cache for {category_id}: {e}")

    def get_attribute_metadata(self, category_id: str) -> list[AttributeMeta] | None:
        """Get cached attribute metadata as normalized objects.

        Args:
            category_id: Category ID

        Returns:
            List of AttributeMeta objects or None if not cached/expired
        """
        attributes = self.get_attributes(category_id)
        if attributes is None:
            return None

        try:
            return [AttributeMeta.from_ml_api(attr) for attr in attributes]
        except (KeyError, TypeError) as e:
            logger.warning(f"Failed to normalize attributes for {category_id}: {e}")
            return None

    def save_attribute_metadata(
        self, category_id: str, metadata: list[AttributeMeta]
    ) -> None:
        """Save attribute metadata as raw dict.

        Args:
            category_id: Category ID
            metadata: List of AttributeMeta objects
        """
        # Convert AttributeMeta back to dict format for storage
        attributes = []
        for meta in metadata:
            attr = {
                "id": meta.id,
                "name": meta.name,
                "value_type": meta.value_type,
                "required": meta.required,
            }
            if meta.relevance is not None:
                attr["relevance"] = meta.relevance
            if meta.tags:
                attr["tags"] = {tag: True for tag in meta.tags}
            if meta.allowed_values:
                attr["values"] = [{"name": v} for v in meta.allowed_values]
            if meta.hierarchy != "none":
                attr["hierarchy"] = meta.hierarchy
            if meta.tooltip:
                attr["tooltip"] = meta.tooltip
            attributes.append(attr)

        self.save_attributes(category_id, attributes)

    def clear_cache(self, category_id: str | None = None) -> None:
        """Clear cache for specific category or all.

        Args:
            category_id: Category ID to clear, or None for all
        """
        if category_id:
            cache_file = self._get_cache_file(category_id)
            if cache_file.exists():
                cache_file.unlink()
                logger.info(f"Cleared cache for {category_id}")
        else:
            # Clear all cache files
            count = 0
            for cache_file in self.cache_dir.glob("*.json"):
                cache_file.unlink()
                count += 1
            logger.info(f"Cleared {count} cached category files")

    def get_cache_info(self) -> dict:
        """Get cache statistics.

        Returns:
            Dict with cache statistics
        """
        cache_files = list(self.cache_dir.glob("*.json"))
        total_size = sum(f.stat().st_size for f in cache_files)

        return {
            "cache_dir": str(self.cache_dir),
            "ttl_hours": self.ttl_hours,
            "cached_categories": len(cache_files),
            "total_size_bytes": total_size,
        }
