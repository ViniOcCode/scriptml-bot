"""
Tests for attribute_cache.py - 100% coverage.
"""

import json
import logging
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from mercadolivre_upload.infrastructure.cache.attribute_cache import AttributeCache


class TestAttributeCache:
    """Test cases for AttributeCache class."""

    @pytest.fixture
    def cache(self, tmp_path):
        """Create cache instance with temp file."""
        cache_file = tmp_path / "test_cache.json"
        return AttributeCache(cache_file=str(cache_file))

    @pytest.fixture
    def existing_cache_file(self, tmp_path):
        """Create cache with existing file."""
        cache_file = tmp_path / "existing_cache.json"
        data = {
            "key1": {"value": "test1", "_expires": time.time() + 3600},
            "key2": {"value": "test2", "_expires": time.time() + 3600},
        }
        with open(cache_file, "w") as f:
            json.dump(data, f)
        return str(cache_file)

    # ==================== Initialization ====================

    def test_init_default(self):
        """Test default initialization."""
        cache = AttributeCache()
        assert cache.cache_file == Path(".attribute_cache.json")
        assert cache.ttl == AttributeCache.DEFAULT_TTL
        assert cache._cache == {}

    def test_init_custom_params(self, tmp_path):
        """Test initialization with custom parameters."""
        cache_file = tmp_path / "custom.json"
        cache = AttributeCache(cache_file=str(cache_file), ttl=7200)
        assert cache.cache_file == cache_file
        assert cache.ttl == 7200

    def test_init_loads_existing(self, existing_cache_file):
        """Test that existing cache is loaded."""
        cache = AttributeCache(cache_file=existing_cache_file)
        assert "key1" in cache._cache
        assert "key2" in cache._cache

    def test_init_filters_expired_on_load(self, tmp_path):
        """Test that expired entries are filtered on load."""
        cache_file = tmp_path / "cache.json"
        data = {
            "valid": {"value": "yes", "_expires": time.time() + 3600},
            "expired": {"value": "no", "_expires": time.time() - 100},
        }
        with open(cache_file, "w") as f:
            json.dump(data, f)

        cache = AttributeCache(cache_file=str(cache_file))
        assert "valid" in cache._cache
        assert "expired" not in cache._cache

    def test_init_handles_json_decode_error(self, tmp_path, caplog):
        """Test handling of JSON decode error on load."""
        caplog.set_level(logging.ERROR)
        cache_file = tmp_path / "corrupt.json"
        cache_file.write_text("invalid json")

        cache = AttributeCache(cache_file=str(cache_file))
        assert cache._cache == {}
        assert "Failed to parse cache file" in caplog.text

    def test_init_handles_generic_exception(self, tmp_path, caplog):
        """Test handling of generic exception on load."""
        caplog.set_level(logging.ERROR)
        cache_file = tmp_path / "cache.json"
        cache_file.write_text('{"valid": "json"}')

        with patch("builtins.open", side_effect=OSError("Permission denied")):
            cache = AttributeCache(cache_file=str(cache_file))

        assert cache._cache == {}
        assert "Failed to load cache" in caplog.text

    # ==================== _save ====================

    def test_save_creates_parent_dirs(self, tmp_path):
        """Test that parent directories are created."""
        nested_path = tmp_path / "deep" / "nested" / "cache.json"
        cache = AttributeCache(cache_file=str(nested_path))
        cache.set("key", "value")

        assert nested_path.parent.exists()

    def test_save_handles_exception(self, cache, caplog):
        """Test handling of save exception."""
        caplog.set_level(logging.ERROR)
        with patch("builtins.open", side_effect=OSError("Write failed")):
            cache.set("key", "value")

        assert "Failed to save cache" in caplog.text

    # ==================== _is_expired ====================

    def test_is_expired_nonexistent_key(self, cache):
        """Test expired check for nonexistent key."""
        assert cache._is_expired("nonexistent") is True

    def test_is_expired_expired_key(self, cache):
        """Test expired check for expired key."""
        cache._cache["expired"] = {"_expires": time.time() - 100}
        assert cache._is_expired("expired") is True

    def test_is_expired_valid_key(self, cache):
        """Test expired check for valid key."""
        cache._cache["valid"] = {"_expires": time.time() + 3600}
        assert cache._is_expired("valid") is False

    # ==================== get ====================

    def test_get_existing_key(self, cache):
        """Test getting existing key."""
        cache._cache["key"] = {"value": "test", "_expires": time.time() + 3600}
        result = cache.get("key")
        assert result == {"value": "test"}

    def test_get_expired_key_deletes_and_returns_default(self, cache):
        """Test that expired key is deleted and default returned."""
        cache._cache["expired"] = {"value": "test", "_expires": time.time() - 100}
        result = cache.get("expired", default="default_value")

        assert result == "default_value"
        assert "expired" not in cache._cache

    def test_get_nonexistent_returns_default(self, cache):
        """Test getting nonexistent key returns default."""
        result = cache.get("nonexistent", default="default")
        assert result == "default"

    def test_get_returns_empty_dict_for_internal_only(self, cache):
        """Test get when value only has internal fields."""
        cache._cache["key"] = {"_expires": time.time() + 3600, "_created": time.time()}
        result = cache.get("key")
        # Returns None (default) because result is empty dict
        assert result is None

    def test_get_returns_none_for_empty_result(self, cache):
        """Test that empty result returns default."""
        cache._cache["key"] = {"_expires": time.time() + 3600}
        result = cache.get("key", default=None)
        assert result is None

    # ==================== set ====================

    def test_set_dict_value(self, cache):
        """Test setting dict value."""
        cache.set("key", {"name": "test"})

        assert cache._cache["key"]["name"] == "test"
        assert "_expires" in cache._cache["key"]
        assert "_created" in cache._cache["key"]

    def test_set_non_dict_value(self, cache):
        """Test setting non-dict value."""
        cache.set("key", "simple_value")

        assert cache._cache["key"]["_value"] == "simple_value"
        assert "_expires" in cache._cache["key"]

    def test_set_custom_ttl(self, cache):
        """Test setting with custom TTL."""
        custom_ttl = 600
        cache.set("key", "value", ttl=custom_ttl)

        expected_expires = time.time() + custom_ttl
        assert abs(cache._cache["key"]["_expires"] - expected_expires) < 1

    def test_set_overwrites_existing(self, cache):
        """Test that set overwrites existing key."""
        cache.set("key", "old")
        cache.set("key", "new")

        assert cache._cache["key"]["_value"] == "new"

    # ==================== delete ====================

    def test_delete_existing_key(self, cache):
        """Test deleting existing key."""
        cache.set("key", "value")
        result = cache.delete("key")

        assert result is True
        assert "key" not in cache._cache

    def test_delete_nonexistent_key(self, cache):
        """Test deleting nonexistent key."""
        result = cache.delete("nonexistent")
        assert result is False

    # ==================== clear ====================

    def test_clear(self, cache, caplog):
        """Test clearing cache."""
        caplog.set_level(logging.INFO)
        cache.set("key1", "value1")
        cache.set("key2", "value2")

        cache.clear()

        assert cache._cache == {}
        assert "Cache cleared" in caplog.text

    def test_clear_empty_cache(self, cache):
        """Test clearing empty cache."""
        cache.clear()
        assert cache._cache == {}

    # ==================== keys ====================

    def test_keys_returns_valid_only(self, cache):
        """Test that keys only returns non-expired entries."""
        cache._cache["valid"] = {"_expires": time.time() + 3600}
        cache._cache["expired"] = {"_expires": time.time() - 100}

        keys = cache.keys()

        assert "valid" in keys
        assert "expired" not in keys

    def test_keys_empty(self, cache):
        """Test keys with empty cache."""
        assert cache.keys() == []

    # ==================== exists ====================

    def test_exists_true(self, cache):
        """Test exists with valid key."""
        cache.set("key", "value")
        assert cache.exists("key") is True

    def test_exists_expired(self, cache):
        """Test exists with expired key."""
        cache._cache["expired"] = {"_expires": time.time() - 100}
        assert cache.exists("expired") is False

    def test_exists_nonexistent(self, cache):
        """Test exists with nonexistent key."""
        assert cache.exists("nonexistent") is False

    # ==================== get_stats ====================

    def test_get_stats(self, cache):
        """Test getting cache statistics."""
        cache._cache["valid"] = {"_expires": time.time() + 3600}
        cache._cache["expired"] = {"_expires": time.time() - 100}

        stats = cache.get_stats()

        assert stats["total_entries"] == 2
        assert stats["valid_entries"] == 1
        assert stats["expired_entries"] == 1
        assert stats["ttl_seconds"] == cache.ttl

    def test_get_stats_empty(self, cache):
        """Test stats with empty cache."""
        stats = cache.get_stats()

        assert stats["total_entries"] == 0
        assert stats["valid_entries"] == 0
        assert stats["expired_entries"] == 0

    # ==================== cleanup_expired ====================

    def test_cleanup_expired(self, cache):
        """Test cleaning up expired entries."""
        cache._cache["valid"] = {"_expires": time.time() + 3600}
        cache._cache["expired1"] = {"_expires": time.time() - 100}
        cache._cache["expired2"] = {"_expires": time.time() - 200}

        removed = cache.cleanup_expired()

        assert removed == 2
        assert "valid" in cache._cache
        assert "expired1" not in cache._cache
        assert "expired2" not in cache._cache

    def test_cleanup_expired_none(self, cache):
        """Test cleanup when nothing to remove."""
        cache.set("valid", "value")
        removed = cache.cleanup_expired()

        assert removed == 0
        assert "valid" in cache._cache

    # ==================== touch ====================

    def test_touch_existing_valid(self, cache):
        """Test touching existing valid key."""
        cache.set("key", "value")
        original_expires = cache._cache["key"]["_expires"]

        # Wait a tiny bit to ensure time difference
        time.sleep(0.01)
        result = cache.touch("key")

        assert result is True
        assert cache._cache["key"]["_expires"] > original_expires

    def test_touch_with_custom_ttl(self, cache):
        """Test touching with custom TTL."""
        cache.set("key", "value")
        cache.touch("key", ttl=600)

        expected_expires = time.time() + 600
        assert abs(cache._cache["key"]["_expires"] - expected_expires) < 1

    def test_touch_nonexistent(self, cache):
        """Test touching nonexistent key."""
        result = cache.touch("nonexistent")
        assert result is False

    def test_touch_expired_key(self, cache):
        """Test touching expired key deletes it."""
        cache._cache["expired"] = {"_expires": time.time() - 100}
        result = cache.touch("expired")

        assert result is False
        assert "expired" not in cache._cache

    # ==================== get_many ====================

    def test_get_many_multiple_keys(self, cache):
        """Test getting multiple keys at once."""
        cache.set("key1", {"data": "value1"})
        cache.set("key2", {"data": "value2"})

        result = cache.get_many(["key1", "key2", "key3"])

        assert result == {"key1": {"data": "value1"}, "key2": {"data": "value2"}}

    def test_get_many_empty(self, cache):
        """Test get_many with empty key list."""
        result = cache.get_many([])
        assert result == {}

    def test_get_many_with_expired(self, cache):
        """Test get_many skips expired keys."""
        cache.set("valid", {"data": "value"})
        cache._cache["expired"] = {"_expires": time.time() - 100}

        result = cache.get_many(["valid", "expired"])

        assert result == {"valid": {"data": "value"}}
