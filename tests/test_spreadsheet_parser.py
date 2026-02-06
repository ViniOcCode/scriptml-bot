"""Tests for spreadsheet parser module."""

import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

# Ensure mercadolivre_upload is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from mercadolivre_upload.adapters.spreadsheet.parser import SpreadsheetParser


class TestSpreadsheetParserInit:
    """Tests for SpreadsheetParser initialization."""

    def test_init_default(self):
        """Test default initialization."""
        parser = SpreadsheetParser()

        assert parser._data == []
        assert parser._column_mapping is not None
        assert "titulo" in parser._column_mapping.values()
        assert "preco" in parser._column_mapping.values()

    def test_init_custom_mapping(self):
        """Test initialization with custom mapping."""
        custom_map = {"col_a": "field_a", "col_b": "field_b"}
        parser = SpreadsheetParser(column_mapping=custom_map)

        assert parser._column_mapping == custom_map


class TestParse:
    """Tests for parse method."""

    def create_test_excel(
        self,
        data: dict,
        filename: str = "test.xlsx",
    ) -> Path:
        """Helper to create a test Excel file."""
        df = pd.DataFrame(data)
        temp_file = Path(tempfile.gettempdir()) / filename
        df.to_excel(temp_file, index=False, engine="openpyxl")
        return temp_file

    def test_parse_success(self):
        """Test successful parsing."""
        parser = SpreadsheetParser()

        data = {
            "titulo": ["Product 1", "Product 2"],
            "preco": [99.99, 199.99],
            "categoria": ["MLB123", "MLB456"],
            "moeda": ["BRL", "BRL"],
        }
        temp_file = self.create_test_excel(data)

        try:
            result = parser.parse(temp_file)

            assert len(result) == 2
            assert result[0]["titulo"] == "Product 1"
            assert result[0]["preco"] == 99.99
            assert result[1]["titulo"] == "Product 2"
        finally:
            temp_file.unlink(missing_ok=True)

    def test_parse_column_mapping(self):
        """Test column name mapping."""
        parser = SpreadsheetParser()

        # Use English column names that should be mapped to Portuguese
        data = {
            "title": ["Product 1"],
            "price": [99.99],
            "category_id": ["MLB123"],
            "currency_id": ["BRL"],
            "description": ["A description"],
        }
        temp_file = self.create_test_excel(data)

        try:
            result = parser.parse(temp_file)

            assert len(result) == 1
            # Should be mapped to Portuguese field names
            assert "titulo" in result[0]
            assert "preco" in result[0]
            assert "categoria" in result[0]
            assert "moeda" in result[0]
            assert "descricao" in result[0]
            assert result[0]["titulo"] == "Product 1"
        finally:
            temp_file.unlink(missing_ok=True)

    def test_parse_file_not_found(self):
        """Test parsing non-existent file."""
        parser = SpreadsheetParser()

        with pytest.raises(FileNotFoundError, match="Arquivo não encontrado"):
            parser.parse("/nonexistent/path/file.xlsx")

    def test_parse_invalid_extension(self):
        """Test parsing file with unsupported extension."""
        parser = SpreadsheetParser()

        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tmp:
            tmp.write(b"not an excel file")
            tmp_path = Path(tmp.name)

        try:
            with pytest.raises(ValueError, match="Formato de arquivo não suportado"):
                parser.parse(tmp_path)
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_parse_empty_file(self):
        """Test parsing empty Excel file."""
        parser = SpreadsheetParser()

        # Create empty DataFrame
        df = pd.DataFrame()
        temp_file = Path(tempfile.gettempdir()) / "empty.xlsx"
        df.to_excel(temp_file, index=False, engine="openpyxl")

        try:
            result = parser.parse(temp_file)
            assert result == []
        finally:
            temp_file.unlink(missing_ok=True)

    def test_parse_with_nan_values(self):
        """Test parsing with NaN/None values."""
        parser = SpreadsheetParser()

        data = {
            "titulo": ["Product 1", "Product 2", None],
            "preco": [99.99, None, 50.00],
            "categoria": ["MLB123", "MLB456", "MLB789"],
            "moeda": ["BRL", "BRL", "BRL"],
        }
        temp_file = self.create_test_excel(data)

        try:
            result = parser.parse(temp_file)

            assert len(result) == 3
            # NaN values should be cleaned
            assert "preco" not in result[1] or pd.notna(result[1].get("preco"))
        finally:
            temp_file.unlink(missing_ok=True)

    def test_parse_with_whitespace(self):
        """Test parsing with whitespace in strings."""
        parser = SpreadsheetParser()

        data = {
            "titulo": ["  Product 1  ", "Product 2"],
            "preco": [99.99, 199.99],
            "categoria": ["MLB123", "MLB456"],
            "moeda": ["BRL", "BRL"],
        }
        temp_file = self.create_test_excel(data)

        try:
            result = parser.parse(temp_file)

            assert result[0]["titulo"] == "Product 1"  # Whitespace stripped
        finally:
            temp_file.unlink(missing_ok=True)

    def test_parse_xls_format(self):
        """Test parsing .xls format (legacy Excel)."""
        parser = SpreadsheetParser()

        data = {
            "titulo": ["Product 1"],
            "preco": [99.99],
            "categoria": ["MLB123"],
            "moeda": ["BRL"],
        }
        temp_file = Path(tempfile.gettempdir()) / "test.xls"

        # Create empty file so it passes existence check
        temp_file.touch()

        # Note: xls requires xlrd, which may not be installed
        # We'll mock the read to test the code path
        with patch("pandas.read_excel") as mock_read:
            mock_df = pd.DataFrame(data)
            mock_read.return_value = mock_df

            try:
                result = parser.parse(temp_file)
                assert len(result) == 1
                mock_read.assert_called_once()
                # Verify xlrd engine is used for .xls
                call_kwargs = mock_read.call_args[1]
                assert call_kwargs.get("engine") == "xlrd"
            finally:
                temp_file.unlink(missing_ok=True)

    def test_parse_corrupted_file(self):
        """Test parsing corrupted Excel file."""
        parser = SpreadsheetParser()

        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
            tmp.write(b"corrupted content that is not valid xlsx")
            tmp_path = Path(tmp.name)

        try:
            with pytest.raises(ValueError, match="Erro ao ler arquivo Excel"):
                parser.parse(tmp_path)
        finally:
            tmp_path.unlink(missing_ok=True)


class TestColumnMapping:
    """Tests for column mapping functionality."""

    def test_get_column_mapping(self):
        """Test getting current column mapping."""
        parser = SpreadsheetParser()

        mapping = parser.get_column_mapping()

        assert isinstance(mapping, dict)
        assert "title" in mapping
        assert "titulo" in mapping.values()

    def test_set_column_mapping(self):
        """Test setting custom column mapping."""
        parser = SpreadsheetParser()

        new_mapping = {"custom_col": "custom_field"}
        parser.set_column_mapping(new_mapping)

        assert parser._column_mapping == new_mapping
        assert parser.get_column_mapping() == new_mapping

    def test_get_supported_columns(self):
        """Test getting list of supported columns."""
        parser = SpreadsheetParser()

        columns = parser.get_supported_columns()

        assert isinstance(columns, list)
        assert "titulo" in columns
        assert "preco" in columns
        assert "categoria" in columns


class TestValidateFile:
    """Tests for validate_file method."""

    def test_validate_valid_file(self):
        """Test validation of valid file."""
        parser = SpreadsheetParser()

        data = {"titulo": ["Product 1"]}
        temp_file = Path(tempfile.gettempdir()) / "valid.xlsx"
        pd.DataFrame(data).to_excel(temp_file, index=False, engine="openpyxl")

        try:
            is_valid, errors = parser.validate_file(temp_file)
            assert is_valid is True
            assert errors == []
        finally:
            temp_file.unlink(missing_ok=True)

    def test_validate_nonexistent_file(self):
        """Test validation of non-existent file."""
        parser = SpreadsheetParser()

        is_valid, errors = parser.validate_file("/nonexistent/file.xlsx")

        assert is_valid is False
        assert len(errors) > 0
        assert "não encontrado" in errors[0].lower()

    def test_validate_invalid_extension(self):
        """Test validation of file with wrong extension."""
        parser = SpreadsheetParser()

        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tmp:
            tmp.write(b"content")
            tmp_path = Path(tmp.name)

        try:
            is_valid, errors = parser.validate_file(tmp_path)

            assert is_valid is False
            assert any("não suportado" in e.lower() for e in errors)
        finally:
            tmp_path.unlink(missing_ok=True)


class TestCleanRecord:
    """Tests for _clean_record method."""

    def test_clean_record_with_nan(self):
        """Test cleaning record with NaN values."""
        parser = SpreadsheetParser()

        record = {
            "titulo": "Product",
            "preco": 99.99,
            "descricao": float("nan"),
            "sku": None,
        }

        cleaned = parser._clean_record(record)

        assert "titulo" in cleaned
        assert "preco" in cleaned
        assert "descricao" not in cleaned
        assert "sku" not in cleaned

    def test_clean_record_with_whitespace(self):
        """Test cleaning record with whitespace strings."""
        parser = SpreadsheetParser()

        record = {
            "titulo": "  Product Name  ",
            "descricao": "   ",  # Only whitespace
        }

        cleaned = parser._clean_record(record)

        assert cleaned["titulo"] == "Product Name"
        assert "descricao" not in cleaned  # Empty after stripping


class TestNormalizeColumns:
    """Tests for _normalize_columns method."""

    def test_normalize_columns_mapping(self):
        """Test column normalization with mapping."""
        parser = SpreadsheetParser()

        df = pd.DataFrame(
            {
                "TITLE": ["Product 1"],
                "PRICE": [99.99],
                "CATEGORY_ID": ["MLB123"],
            }
        )

        normalized = parser._normalize_columns(df)

        assert "titulo" in normalized.columns
        assert "preco" in normalized.columns
        assert "categoria" in normalized.columns

    def test_normalize_columns_no_mapping(self):
        """Test column normalization for unmapped columns."""
        parser = SpreadsheetParser()

        df = pd.DataFrame(
            {
                "custom_column": ["value"],
            }
        )

        normalized = parser._normalize_columns(df)

        # Unmapped columns should be lowercased
        assert "custom_column" in normalized.columns


class TestIntegrationWithProductBuilder:
    """Integration tests with ProductBuilder."""

    def test_parse_output_compatible_with_product_builder(self):
        """Test that parser output can be used with ProductBuilder."""
        from mercadolivre_upload.application.builders.product_builder import (
            ProductBuilder,
        )

        parser = SpreadsheetParser()
        builder = ProductBuilder()

        data = {
            "titulo": ["Test Product"],
            "categoria": ["MLB123"],
            "preco": [99.99],
            "moeda": ["BRL"],
            "quantidade": [10],
        }
        temp_file = Path(tempfile.gettempdir()) / "integration.xlsx"
        pd.DataFrame(data).to_excel(temp_file, index=False, engine="openpyxl")

        try:
            parsed_data = parser.parse(temp_file)
            assert len(parsed_data) == 1

            # Should work with ProductBuilder
            product = builder.build(parsed_data[0])

            assert product["title"] == "Test product"
            assert product["category_id"] == "MLB123"
            assert product["price"] == 99.99
        finally:
            temp_file.unlink(missing_ok=True)

    def test_parse_with_english_columns_for_product_builder(self):
        """Test parsing English columns and using with ProductBuilder."""
        from mercadolivre_upload.application.builders.product_builder import (
            ProductBuilder,
        )

        parser = SpreadsheetParser()
        builder = ProductBuilder()

        # Use English column names
        data = {
            "title": ["Another Product"],
            "category_id": ["MLB456"],
            "price": [199.99],
            "currency_id": ["BRL"],
        }
        temp_file = Path(tempfile.gettempdir()) / "english_cols.xlsx"
        pd.DataFrame(data).to_excel(temp_file, index=False, engine="openpyxl")

        try:
            parsed_data = parser.parse(temp_file)
            # Parser maps English to Portuguese field names
            assert "titulo" in parsed_data[0]

            # ProductBuilder expects Portuguese field names for spreadsheet source
            product = builder.build(parsed_data[0])

            assert product["title"] == "Another product"
            assert product["price"] == 199.99
        finally:
            temp_file.unlink(missing_ok=True)
