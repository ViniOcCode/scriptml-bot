"""Tests for spreadsheet parser internal record and column normalization methods."""

import pandas as pd

from mercadolivre_upload.adapters.spreadsheet.parser import SpreadsheetParser


class TestCleanRecordMethod:
    """Direct tests for _clean_record method."""

    def test_clean_record_with_various_types(self):
        """Test cleaning record with various value types."""
        parser = SpreadsheetParser()

        record = {
            "string_field": "  Test String  ",
            "int_field": 42,
            "float_field": 3.14,
            "nan_field": float("nan"),
            "none_field": None,
            "empty_string": "",
            "whitespace_string": "   \t\n   ",
            "zero_int": 0,
            "zero_float": 0.0,
        }

        cleaned = parser._clean_record(record)

        assert cleaned["string_field"] == "Test String"  # Stripped
        assert cleaned["int_field"] == 42
        assert cleaned["float_field"] == 3.14
        assert "nan_field" not in cleaned
        assert "none_field" not in cleaned
        assert "empty_string" not in cleaned
        assert "whitespace_string" not in cleaned
        assert cleaned["zero_int"] == 0  # Preserved
        assert cleaned["zero_float"] == 0.0  # Preserved

    def test_clean_record_empty_result(self):
        """Test cleaning record that results in empty dict."""
        parser = SpreadsheetParser()

        record = {
            "field1": None,
            "field2": float("nan"),
            "field3": "",
        }

        cleaned = parser._clean_record(record)

        assert cleaned == {}


class TestNormalizeColumnsMethod:
    """Direct tests for _normalize_columns method."""

    def test_normalize_columns_with_mapping(self):
        """Test column normalization with various mappings."""
        parser = SpreadsheetParser()

        df = pd.DataFrame(
            {
                "Title": ["Product 1"],
                "PRICE": [99.99],
                "Category_ID": ["MLB123"],
            }
        )

        normalized = parser._normalize_columns(df)

        assert "titulo" in normalized.columns
        assert "preco" in normalized.columns
        assert "categoria" in normalized.columns

    def test_normalize_columns_whitespace_handling(self):
        """Test that column names with whitespace are handled."""
        parser = SpreadsheetParser()

        df = pd.DataFrame(
            {
                "  title  ": ["Product 1"],
                " price ": [99.99],
            }
        )

        normalized = parser._normalize_columns(df)

        # Whitespace should be stripped and then mapped
        assert "titulo" in normalized.columns
        assert "preco" in normalized.columns
