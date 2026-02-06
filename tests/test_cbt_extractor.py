"""Tests for CBT ID extractor."""

import pytest
from unittest.mock import Mock, MagicMock

from mercadolivre_upload.api.cbt_extractor import CbtIdExtractor


class TestCbtIdExtractor:
    """Test CBT ID extraction strategies."""

    def test_extract_from_cbt_item_id_field(self):
        """Test extraction from direct cbt_item_id field."""
        extractor = CbtIdExtractor()
        result = {
            "id": "MLB1234567890",
            "cbt_item_id": "CBT9876543210",
            "site_id": "MLB",
        }
        
        cbt_id = extractor.extract_cbt_id(result)
        
        assert cbt_id == "CBT9876543210"

    def test_extract_from_id_field_when_cbt(self):
        """Test extraction from id field when it's already a CBT ID."""
        extractor = CbtIdExtractor()
        result = {
            "id": "CBT1234567890",
            "site_id": "CBT",
        }
        
        cbt_id = extractor.extract_cbt_id(result)
        
        assert cbt_id == "CBT1234567890"

    def test_extract_from_marketplace_items_parent_id(self):
        """Test extraction from marketplace_items[].parent_id."""
        extractor = CbtIdExtractor()
        result = {
            "id": "MLB1234567890",
            "site_id": "MLB",
            "marketplace_items": [
                {
                    "item_id": "MLB1234567890",
                    "site_id": "MLB",
                    "parent_id": "CBT9999999999",
                    "parent_user_id": 123456,
                },
                {
                    "item_id": "MLC9876543210",
                    "site_id": "MLC",
                    "parent_id": "CBT9999999999",
                    "parent_user_id": 123456,
                },
            ],
        }
        
        cbt_id = extractor.extract_cbt_id(result)
        
        assert cbt_id == "CBT9999999999"

    def test_extract_with_api_fallback(self):
        """Test extraction via API fallback when marketplace ID is provided."""
        mock_client = Mock()
        mock_client.get.return_value = {
            "id": "MLB1234567890",
            "cbt_item_id": "CBT7777777777",
            "parent_id": "CBT7777777777",
        }
        
        extractor = CbtIdExtractor(api_client=mock_client)
        result = {
            "id": "MLB1234567890",
            "site_id": "MLB",
        }
        
        cbt_id = extractor.extract_cbt_id(result)
        
        assert cbt_id == "CBT7777777777"
        mock_client.get.assert_called_once_with("/items/MLB1234567890")

    def test_extract_with_api_fallback_uses_cache(self):
        """Test that API fallback uses cache for repeated requests."""
        mock_client = Mock()
        mock_client.get.return_value = {
            "id": "MLB1234567890",
            "cbt_item_id": "CBT7777777777",
        }
        
        extractor = CbtIdExtractor(api_client=mock_client)
        result = {"id": "MLB1234567890"}
        
        # First call
        cbt_id_1 = extractor.extract_cbt_id(result)
        # Second call (should use cache)
        cbt_id_2 = extractor.extract_cbt_id(result)
        
        assert cbt_id_1 == "CBT7777777777"
        assert cbt_id_2 == "CBT7777777777"
        # API should only be called once
        mock_client.get.assert_called_once_with("/items/MLB1234567890")

    def test_extract_returns_none_when_no_cbt_found(self):
        """Test that None is returned when no CBT ID can be found."""
        extractor = CbtIdExtractor()
        result = {
            "id": "MLB1234567890",
            "site_id": "MLB",
        }
        
        cbt_id = extractor.extract_cbt_id(result)
        
        assert cbt_id is None

    def test_extract_api_fallback_handles_error(self):
        """Test that API fallback handles errors gracefully."""
        mock_client = Mock()
        mock_client.get.side_effect = Exception("API error")
        
        extractor = CbtIdExtractor(api_client=mock_client)
        result = {"id": "MLB1234567890"}
        
        cbt_id = extractor.extract_cbt_id(result)
        
        assert cbt_id is None

    def test_extract_rejects_invalid_cbt_prefix(self):
        """Test that IDs not starting with CBT are rejected."""
        extractor = CbtIdExtractor()
        result = {
            "cbt_item_id": "MLB1234567890",  # Wrong prefix
        }
        
        cbt_id = extractor.extract_cbt_id(result)
        
        assert cbt_id is None

    def test_extract_handles_missing_fields(self):
        """Test extraction handles missing fields gracefully."""
        extractor = CbtIdExtractor()
        result = {}
        
        cbt_id = extractor.extract_cbt_id(result)
        
        assert cbt_id is None

    def test_is_valid_cbt_id(self):
        """Test CBT ID validation."""
        extractor = CbtIdExtractor()
        
        assert extractor._is_valid_cbt_id("CBT1234567890") is True
        assert extractor._is_valid_cbt_id("MLB1234567890") is False
        assert extractor._is_valid_cbt_id("MLC1234567890") is False
        assert extractor._is_valid_cbt_id("") is False
        assert extractor._is_valid_cbt_id(None) is False
        assert extractor._is_valid_cbt_id(123) is False

    def test_clear_cache(self):
        """Test cache clearing."""
        mock_client = Mock()
        mock_client.get.return_value = {"cbt_item_id": "CBT7777777777"}
        
        extractor = CbtIdExtractor(api_client=mock_client)
        result = {"id": "MLB1234567890"}
        
        # Populate cache
        extractor.extract_cbt_id(result)
        assert len(extractor._cache) == 1
        
        # Clear cache
        extractor.clear_cache()
        assert len(extractor._cache) == 0

    def test_extract_prioritizes_cbt_item_id_over_id(self):
        """Test that cbt_item_id field takes priority over id field."""
        extractor = CbtIdExtractor()
        result = {
            "id": "CBT1111111111",
            "cbt_item_id": "CBT2222222222",
        }
        
        cbt_id = extractor.extract_cbt_id(result)
        
        # Should prefer cbt_item_id
        assert cbt_id == "CBT2222222222"

    def test_extract_api_fallback_tries_parent_id_field(self):
        """Test that API fallback tries parent_id field if cbt_item_id missing."""
        mock_client = Mock()
        mock_client.get.return_value = {
            "id": "MLB1234567890",
            "parent_id": "CBT8888888888",
        }
        
        extractor = CbtIdExtractor(api_client=mock_client)
        result = {"id": "MLB1234567890"}
        
        cbt_id = extractor.extract_cbt_id(result)
        
        assert cbt_id == "CBT8888888888"

    def test_extract_skips_invalid_parent_ids_in_marketplace_items(self):
        """Test that invalid parent_ids in marketplace_items are skipped."""
        extractor = CbtIdExtractor()
        result = {
            "id": "MLB1234567890",
            "marketplace_items": [
                {
                    "item_id": "MLB1234567890",
                    "parent_id": None,  # Invalid
                },
                {
                    "item_id": "MLC9876543210",
                    "parent_id": "MLB9999999999",  # Not CBT
                },
                {
                    "item_id": "MLM5555555555",
                    "parent_id": "CBT3333333333",  # Valid!
                },
            ],
        }
        
        cbt_id = extractor.extract_cbt_id(result)
        
        assert cbt_id == "CBT3333333333"

    def test_extract_from_parent_item_id_field(self):
        """Test extraction from top-level parent_item_id field."""
        extractor = CbtIdExtractor()
        result = {
            "id": "MLB2222222222",
            "parent_item_id": "CBT4444444444",
        }

        cbt_id = extractor.extract_cbt_id(result)

        assert cbt_id == "CBT4444444444"

    def test_extract_from_item_relations_structure(self):
        """Test extraction when CBT appears inside item_relations nested structure."""
        extractor = CbtIdExtractor()
        result = {
            "id": "MLB3333333333",
            "item_relations": [
                {"relation": "CHILD", "item_id": "MLB3333333333"},
                {"relation": "PARENT", "details": {"parent_id": "CBT5555555555"}},
            ],
        }

        cbt_id = extractor.extract_cbt_id(result)

        assert cbt_id == "CBT5555555555"
