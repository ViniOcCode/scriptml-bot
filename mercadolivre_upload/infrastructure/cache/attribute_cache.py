from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class AttributeCache:
    """JSON file-based cache with TTL support."""

    DEFAULT_TTL = 24 * 3600

    def __init__(  # noqa: D107
        self,
        cache_dir: str | Path = "cache/categories",
        ttl_hours: int | None = None,
        cache_file: str | None = None,
        ttl: int | None = None,
    ):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        ttl_seconds = ttl if ttl is not None else (ttl_hours * 3600 if ttl_hours else None)
        self.ttl = ttl_seconds or self.DEFAULT_TTL
        if cache_file:
            self.cache_file = Path(cache_file)
        else:
            # Always inside cache_dir — never in repo root
            self.cache_file = self.cache_dir / ".attribute_cache.json"
        self._cache: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if not self.cache_file.exists():
            self._cache = {}
            return
        try:
            with open(self.cache_file, encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                self._cache = data
            else:
                self._cache = {}
            self.cleanup_expired()
        except json.JSONDecodeError:
            logger.error("Failed to parse cache file")
            self._cache = {}
        except Exception as exc:
            logger.error(f"Failed to load cache: {exc}")
            self._cache = {}

    def _save(self) -> None:
        try:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.cache_file, "w", encoding="utf-8") as fh:
                json.dump(self._cache, fh)
        except Exception as exc:
            logger.error(f"Failed to save cache: {exc}")

    def _is_expired(self, key: str) -> bool:
        entry = self._cache.get(key)
        if not entry:
            return True
        expires_at = entry.get("_expires")
        if expires_at is None:
            return False
        return time.time() >= expires_at  # type: ignore[no-any-return]

    def get(self, key: str, default: Any | None = None) -> Any | None:
        """Return cached value for key, or default if missing/expired."""
        if self._is_expired(key):
            if key in self._cache:
                del self._cache[key]
                self._save()
            return default
        entry = self._cache.get(key, {})
        
        # Handle wrapped non-dict values (lists, strings, etc.)
        if "_value" in entry and len(entry) == 3:  # _value, _expires, _created
            return entry["_value"]
        
        # Handle dict values (filter out internal keys)
        payload = {k: v for k, v in entry.items() if not k.startswith("_")}
        return payload if payload else default

    def get_many(self, keys: list[str]) -> dict[str, Any]:
        """Return cached values for multiple keys."""
        return {key: self.get(key) for key in keys if self.get(key) is not None}

    def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        """Store a value in the cache with optional TTL."""
        expires = time.time() + (ttl if ttl is not None else self.ttl)
        entry: dict[str, Any]
        entry = dict(value) if isinstance(value, dict) else {"_value": value}
        entry["_expires"] = expires
        entry["_created"] = time.time()
        self._cache[key] = entry
        self._save()

    def delete(self, key: str) -> bool:
        """Delete a key from the cache."""
        if key in self._cache:
            del self._cache[key]
            self._save()
            return True
        return False

    def clear(self) -> None:
        """Clear all entries from the cache."""
        self._cache = {}
        self._save()
        logger.info("Cache cleared")

    def clear_cache(self) -> None:
        """Clear all entries (alias for clear)."""
        self.clear()

    def keys(self) -> list[str]:
        """Return list of non-expired cache keys."""
        return [key for key in self._cache if not self._is_expired(key)]

    def exists(self, key: str) -> bool:
        """Check if a non-expired key exists in the cache."""
        return key in self._cache and not self._is_expired(key)

    def get_stats(self) -> dict[str, int]:
        """Return cache statistics."""
        total = len(self._cache)
        valid = sum(1 for key in self._cache if not self._is_expired(key))
        return {
            "total_entries": total,
            "valid_entries": valid,
            "expired_entries": total - valid,
            "ttl_seconds": int(self.ttl),
        }

    def cleanup_expired(self) -> int:
        """Remove expired entries and return count removed."""
        expired_keys = [key for key in self._cache if self._is_expired(key)]
        for key in expired_keys:
            del self._cache[key]
        if expired_keys:
            self._save()
        return len(expired_keys)

    def touch(self, key: str, ttl: int | None = None) -> bool:
        """Refresh TTL for an existing key."""
        if self._is_expired(key):
            if key in self._cache:
                del self._cache[key]
                self._save()
            return False
        entry = self._cache.get(key)
        if not entry:
            return False
        entry["_expires"] = time.time() + (ttl if ttl is not None else self.ttl)
        self._cache[key] = entry
        self._save()
        return True

    def get_attributes(self, category_id: str) -> list[dict[str, Any]] | None:
        """Get cached attributes for a category."""
        return self.get(category_id)

    def save_attributes(self, category_id: str, attributes: list[dict[str, Any]]) -> None:
        """Save attributes for a category."""
        self.set(category_id, attributes)

    def get_cache_info(self) -> dict[str, Any]:
        """Return summary info about the cache."""
        return {"cached_categories": len(self.keys())}
