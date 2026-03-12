"""
Tests for text_utils.py.
"""

from mercadolivre_upload.shared.utils.text_utils import (
    normalize_text,
)


class TestNormalizeText:
    """Test cases for normalize_text function."""

    def test_normalize_with_accents(self):
        """Test removing accents from text."""
        assert normalize_text("café") == "cafe"
        assert normalize_text("naïve") == "naive"
        assert normalize_text("São Paulo") == "Sao Paulo"

    def test_normalize_without_accents(self):
        """Test text without accents remains unchanged."""
        assert normalize_text("hello") == "hello"
        assert normalize_text("world") == "world"

    def test_normalize_non_string_input(self):
        """Test with non-string input."""
        assert normalize_text(123) == "123"
        assert normalize_text(None) == "None"
