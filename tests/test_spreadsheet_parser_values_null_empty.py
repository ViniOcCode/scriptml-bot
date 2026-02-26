"""Tests for spreadsheet parser null and empty value handling."""

import tempfile
from pathlib import Path

import pandas as pd

from mercadolivre_upload.adapters.spreadsheet.parser import SpreadsheetParser


class TestNullAndEmptyValues:
    """Tests for null and empty value handling."""

    def create_test_excel(self, data: dict, filename: str = "test.xlsx") -> Path:
        """Helper to create a test Excel file."""
        df = pd.DataFrame(data)
        temp_file = Path(tempfile.gettempdir()) / filename
        df.to_excel(temp_file, index=False, engine="openpyxl")
        return temp_file

    def test_null_values_removed(self):
        """Test that null/NaN values are removed from records."""
        parser = SpreadsheetParser()

        data = {
            "titulo": ["Product 1", "Product 2", "Product 3"],
            "preco": [99.99, None, 299.99],
            "categoria": [None, "MLB456", "MLB789"],
        }
        temp_file = self.create_test_excel(data, "nulls.xlsx")

        try:
            result = parser.parse(temp_file)

            assert len(result) == 3
            # First record should not have 'categoria'
            assert "categoria" not in result[0]
            assert result[0]["preco"] == 99.99
            # Second record should not have 'preco'
            assert "preco" not in result[1]
            assert result[1]["categoria"] == "MLB456"
        finally:
            temp_file.unlink(missing_ok=True)

    def test_empty_strings_removed(self):
        """Test that empty strings are removed from records."""
        parser = SpreadsheetParser()

        data = {
            "titulo": ["Product 1", "Product 2"],
            "descricao": ["", "A description"],
        }
        temp_file = self.create_test_excel(data, "empty.xlsx")

        try:
            result = parser.parse(temp_file)

            # First record should not have 'descricao' (empty string)
            assert "descricao" not in result[0]
            # Second record should have 'descricao'
            assert result[1]["descricao"] == "A description"
        finally:
            temp_file.unlink(missing_ok=True)

    def test_whitespace_only_strings_removed(self):
        """Test that whitespace-only strings are removed."""
        parser = SpreadsheetParser()

        data = {
            "titulo": ["Product 1", "Product 2", "Product 3"],
            "descricao": ["   ", "\t\n", "Valid description"],
        }
        temp_file = self.create_test_excel(data, "whitespace.xlsx")

        try:
            result = parser.parse(temp_file)

            # First and second records should not have 'descricao'
            assert "descricao" not in result[0]
            assert "descricao" not in result[1]
            # Third record should have 'descricao'
            assert result[2]["descricao"] == "Valid description"
        finally:
            temp_file.unlink(missing_ok=True)

    def test_empty_excel_file(self):
        """Test parsing completely empty Excel file."""
        parser = SpreadsheetParser()

        df = pd.DataFrame()
        temp_file = Path(tempfile.gettempdir()) / "empty.xlsx"
        df.to_excel(temp_file, index=False, engine="openpyxl")

        try:
            result = parser.parse(temp_file)
            assert result == []
        finally:
            temp_file.unlink(missing_ok=True)

    def test_excel_with_only_headers(self):
        """Test parsing Excel with only headers, no data rows."""
        parser = SpreadsheetParser()

        data = {
            "titulo": [],
            "preco": [],
            "categoria": [],
        }
        temp_file = self.create_test_excel(data, "headers_only.xlsx")

        try:
            result = parser.parse(temp_file)
            assert result == []
        finally:
            temp_file.unlink(missing_ok=True)

    def test_mixed_null_and_valid_values(self):
        """Test handling of mixed null and valid values."""
        parser = SpreadsheetParser()

        data = {
            "titulo": ["Product 1", "Product 2", "Product 3"],
            "preco": [99.99, float("nan"), 299.99],
            "quantidade": [10, 20, None],
            "sku": ["", "SKU002", "   "],
        }
        temp_file = self.create_test_excel(data, "mixed.xlsx")

        try:
            result = parser.parse(temp_file)

            assert len(result) == 3

            # Product 1: has all fields
            assert result[0]["preco"] == 99.99
            assert result[0]["quantidade"] == 10
            assert "sku" not in result[0]  # Empty string removed

            # Product 2: missing preco (NaN), has others
            assert "preco" not in result[1]
            assert result[1]["quantidade"] == 20
            assert result[1]["sku"] == "SKU002"

            # Product 3: missing quantidade (None), has others
            assert result[2]["preco"] == 299.99
            assert "quantidade" not in result[2]
            assert "sku" not in result[2]  # Whitespace-only removed
        finally:
            temp_file.unlink(missing_ok=True)

    def test_zero_values_preserved(self):
        """Test that zero values are preserved (not treated as null)."""
        parser = SpreadsheetParser()

        data = {
            "titulo": ["Product 1"],
            "preco": [0.0],
            "quantidade": [0],
        }
        temp_file = self.create_test_excel(data, "zeros.xlsx")

        try:
            result = parser.parse(temp_file)

            assert len(result) == 1
            assert result[0]["preco"] == 0.0
            assert result[0]["quantidade"] == 0
        finally:
            temp_file.unlink(missing_ok=True)

    def test_numeric_types_preserved(self):
        """Test that numeric types are preserved correctly."""
        parser = SpreadsheetParser()

        data = {
            "titulo": ["Product 1"],
            "preco": [99.99],  # float
            "quantidade": [100],  # int
        }
        temp_file = self.create_test_excel(data, "numeric.xlsx")

        try:
            result = parser.parse(temp_file)

            assert isinstance(result[0]["preco"], (int, float))
            assert isinstance(result[0]["quantidade"], (int, float))
            assert result[0]["preco"] == 99.99
            assert result[0]["quantidade"] == 100
        finally:
            temp_file.unlink(missing_ok=True)
