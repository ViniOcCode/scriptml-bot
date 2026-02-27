"""Tests for spreadsheet parser column mapping and errors."""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from mercadolivre_upload.adapters.spreadsheet.parser import SpreadsheetParser


class TestColumnMapping:
    """Extended tests for column mapping functionality."""

    def create_test_excel(self, data: dict, filename: str = "test.xlsx") -> Path:
        """Helper to create a test Excel file."""
        df = pd.DataFrame(data)
        temp_file = Path(tempfile.gettempdir()) / filename
        df.to_excel(temp_file, index=False, engine="openpyxl")
        return temp_file

    def test_default_column_mapping(self):
        """Test that default column mapping is applied correctly."""
        parser = SpreadsheetParser()

        data = {
            "title": ["Product 1"],
            "price": [99.99],
            "category": ["MLB123"],
            "currency": ["BRL"],
            "quantity": [10],
            "condition": ["new"],
            "description": ["A product"],
            "sku": ["SKU001"],
            "ean": ["123456789"],
            "brand": ["BrandX"],
            "images": ["http://example.com/image.jpg"],
        }
        temp_file = self.create_test_excel(data, "english_cols.xlsx")

        try:
            result = parser.parse(temp_file)

            # All English column names should be mapped to Portuguese
            assert "titulo" in result[0]
            assert "preco" in result[0]
            assert "categoria" in result[0]
            assert "moeda" in result[0]
            assert "quantidade" in result[0]
            assert "condicao" in result[0]
            assert "descricao" in result[0]
            assert "sku" in result[0]
            assert "gtin" in result[0]  # ean maps to gtin
            assert "marca" in result[0]
            assert "imagens" in result[0]
        finally:
            temp_file.unlink(missing_ok=True)

    def test_portuguese_column_mapping(self):
        """Test that Portuguese column names are handled correctly."""
        parser = SpreadsheetParser()

        data = {
            "título": ["Product 1"],  # With accent
            "preço": [99.99],
            "categoria": ["MLB123"],
            "moeda": ["BRL"],
        }
        temp_file = self.create_test_excel(data, "pt_cols.xlsx")

        try:
            result = parser.parse(temp_file)

            # Portuguese column names with accents should be normalized
            assert result[0]["titulo"] == "Product 1"
            assert result[0]["preco"] == 99.99
        finally:
            temp_file.unlink(missing_ok=True)

    def test_alternative_column_names(self):
        """Test alternative column name mappings."""
        parser = SpreadsheetParser()

        data = {
            "category_id": ["MLB123"],
            "currency_id": ["BRL"],
            "available_quantity": [50],
            "codigo": ["CODE001"],
        }
        temp_file = self.create_test_excel(data, "alt_cols.xlsx")

        try:
            result = parser.parse(temp_file)

            assert result[0]["categoria"] == "MLB123"
            assert result[0]["moeda"] == "BRL"
            assert result[0]["quantidade"] == 50
            assert result[0]["sku"] == "CODE001"
        finally:
            temp_file.unlink(missing_ok=True)

    def test_custom_column_mapping(self):
        """Test custom column mapping."""
        parser = SpreadsheetParser()

        custom_mapping = {
            "my_title": "titulo",
            "my_price": "preco",
            "my_category": "categoria",
        }
        parser.set_column_mapping(custom_mapping)

        data = {
            "my_title": ["Custom Product"],
            "my_price": [299.99],
            "my_category": ["MLB999"],
        }
        temp_file = self.create_test_excel(data, "custom_map.xlsx")

        try:
            result = parser.parse(temp_file)

            assert result[0]["titulo"] == "Custom Product"
            assert result[0]["preco"] == 299.99
            assert result[0]["categoria"] == "MLB999"
        finally:
            temp_file.unlink(missing_ok=True)

    def test_column_mapping_is_case_insensitive(self):
        """Test that column mapping handles case insensitivity."""
        parser = SpreadsheetParser()

        data = {
            "TITLE": ["Product 1"],
            "PRICE": [99.99],
            "CATEGORY": ["MLB123"],
        }
        temp_file = self.create_test_excel(data, "uppercase.xlsx")

        try:
            result = parser.parse(temp_file)

            # Uppercase column names should be mapped to lowercase
            assert "titulo" in result[0]
            assert "preco" in result[0]
            assert "categoria" in result[0]
        finally:
            temp_file.unlink(missing_ok=True)

    def test_unmapped_columns_preserved_lowercased(self):
        """Test that unmapped columns are preserved in lowercase."""
        parser = SpreadsheetParser()

        data = {
            "titulo": ["Product 1"],
            "custom_field": ["Custom Value"],
            "ANOTHER_FIELD": ["Another Value"],
        }
        temp_file = self.create_test_excel(data, "unmapped.xlsx")

        try:
            result = parser.parse(temp_file)

            assert result[0]["titulo"] == "Product 1"
            assert result[0]["custom_field"] == "Custom Value"
            assert result[0]["another_field"] == "Another Value"
        finally:
            temp_file.unlink(missing_ok=True)

    def test_get_column_mapping_returns_copy(self):
        """Test that get_column_mapping returns a copy, not a reference."""
        parser = SpreadsheetParser()

        mapping1 = parser.get_column_mapping()
        mapping2 = parser.get_column_mapping()

        # Should be equal but not the same object
        assert mapping1 == mapping2
        assert mapping1 is not mapping2

        # Modifying one should not affect the other
        mapping1["new_key"] = "new_value"
        assert "new_key" not in parser.get_column_mapping()

    def test_set_column_mapping_creates_copy(self):
        """Test that set_column_mapping creates a copy of the mapping."""
        parser = SpreadsheetParser()

        original_mapping = {"col1": "field1", "col2": "field2"}
        parser.set_column_mapping(original_mapping)

        # Modify original
        original_mapping["col3"] = "field3"

        # Parser's mapping should not be affected
        assert "col3" not in parser.get_column_mapping()


class TestErrorHandling:
    """Extended tests for error handling."""

    def test_file_not_found_error(self):
        """Test FileNotFoundError for non-existent file."""
        parser = SpreadsheetParser()

        with pytest.raises(FileNotFoundError) as exc_info:
            parser.parse("/nonexistent/path/to/file.xlsx")

        assert "Arquivo não encontrado" in str(exc_info.value)

    def test_file_not_found_with_path_object(self):
        """Test FileNotFoundError with Path object."""
        parser = SpreadsheetParser()

        with pytest.raises(FileNotFoundError) as exc_info:
            parser.parse(Path("/nonexistent/path/file.xlsx"))

        assert "Arquivo não encontrado" in str(exc_info.value)

    def test_path_is_directory_error(self):
        """Test ValueError when path is a directory."""
        parser = SpreadsheetParser()

        with tempfile.TemporaryDirectory() as tmp_dir:
            with pytest.raises(ValueError) as exc_info:
                parser.parse(tmp_dir)

            assert "Caminho não é um arquivo" in str(exc_info.value)

    def test_invalid_extension_error(self):
        """Test ValueError for invalid file extension."""
        parser = SpreadsheetParser()

        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tmp:
            tmp.write(b"not an excel file")
            tmp_path = Path(tmp.name)

        try:
            with pytest.raises(ValueError) as exc_info:
                parser.parse(tmp_path)

            assert "Formato de arquivo não suportado" in str(exc_info.value)
            assert ".txt" in str(exc_info.value)
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_invalid_extension_pdf(self):
        """Test ValueError for PDF file."""
        parser = SpreadsheetParser()

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(b"%PDF-1.4 fake pdf content")
            tmp_path = Path(tmp.name)

        try:
            with pytest.raises(ValueError) as exc_info:
                parser.parse(tmp_path)

            assert "Formato de arquivo não suportado" in str(exc_info.value)
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_corrupted_excel_error(self):
        """Test ValueError for corrupted Excel file."""
        parser = SpreadsheetParser()

        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
            tmp.write(b"This is not a valid xlsx file content")
            tmp_path = Path(tmp.name)

        try:
            with pytest.raises(ValueError) as exc_info:
                parser.parse(tmp_path)

            assert "Erro ao ler arquivo Excel" in str(exc_info.value)
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_corrupted_xls_error(self):
        """Test ValueError for corrupted XLS file."""
        parser = SpreadsheetParser()

        with tempfile.NamedTemporaryFile(suffix=".xls", delete=False) as tmp:
            tmp.write(b"This is not a valid xls file content")
            tmp_path = Path(tmp.name)

        try:
            with pytest.raises(ValueError) as exc_info:
                parser.parse(tmp_path)

            assert "Erro ao ler arquivo Excel" in str(exc_info.value)
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_pandas_exception_wrapped(self):
        """Test that pandas exceptions are wrapped in ValueError."""
        parser = SpreadsheetParser()

        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
            tmp_path = Path(tmp.name)
            tmp_path.touch()

        try:
            with patch("pandas.read_excel") as mock_read:
                mock_read.side_effect = pd.errors.EmptyDataError("No columns")

                with pytest.raises(ValueError) as exc_info:
                    parser.parse(tmp_path)

                assert "Erro ao ler arquivo Excel" in str(exc_info.value)
                assert exc_info.value.__cause__ is not None
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_validate_file_nonexistent(self):
        """Test validate_file with non-existent file."""
        parser = SpreadsheetParser()

        is_valid, errors = parser.validate_file("/nonexistent/file.xlsx")

        assert is_valid is False
        assert len(errors) == 1
        assert "não encontrado" in errors[0].lower()

    def test_validate_file_directory(self):
        """Test validate_file with directory."""
        parser = SpreadsheetParser()

        with tempfile.TemporaryDirectory() as tmp_dir:
            is_valid, errors = parser.validate_file(tmp_dir)

            assert is_valid is False
            assert any("não é um arquivo" in e.lower() for e in errors)

    def test_validate_file_invalid_extension(self):
        """Test validate_file with invalid extension."""
        parser = SpreadsheetParser()

        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
            tmp_path = Path(tmp.name)
            tmp_path.touch()

        try:
            is_valid, errors = parser.validate_file(tmp_path)

            assert is_valid is False
            assert any("não suportado" in e.lower() for e in errors)
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_validate_file_valid(self):
        """Test validate_file with valid Excel file."""
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
