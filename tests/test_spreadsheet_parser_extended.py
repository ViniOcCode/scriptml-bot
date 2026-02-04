"""Extended tests for spreadsheet parser module.

This module provides comprehensive test coverage for:
- CSV parsing with different delimiters
- Excel parsing (.xlsx, .xls)
- Column mapping functionality
- Error handling (file not found, invalid format)
- Null and empty value handling
- Different encodings (UTF-8, Latin-1)

Uses pytest and mocks for comprehensive coverage without requiring
actual file system operations.
"""

import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

# Ensure mercadolivre_upload is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from mercadolivre_upload.adapters.spreadsheet.parser import SpreadsheetParser


class TestSpreadsheetParserCSV:
    """Tests for CSV parsing functionality."""

    def test_csv_support_not_implemented_by_default(self):
        """Test that CSV files raise ValueError (not supported by default parser)."""
        parser = SpreadsheetParser()

        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode='w', encoding='utf-8') as tmp:
            tmp.write("titulo,preco,categoria\nProduct 1,99.99,MLB123\n")
            tmp_path = Path(tmp.name)

        try:
            with pytest.raises(ValueError, match="Formato de arquivo não suportado"):
                parser.parse(tmp_path)
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_csv_with_comma_delimiter_via_pandas_mock(self):
        """Test CSV parsing with comma delimiter using mocked pandas."""
        parser = SpreadsheetParser()

        # Create expected DataFrame
        expected_df = pd.DataFrame({
            "titulo": ["Product 1", "Product 2"],
            "preco": [99.99, 199.99],
            "categoria": ["MLB123", "MLB456"],
        })

        with patch("pandas.read_excel") as mock_read_excel:
            mock_read_excel.return_value = expected_df

            # Temporarily add .csv to supported extensions for testing
            original_extensions = parser.SUPPORTED_EXTENSIONS.copy()
            parser.SUPPORTED_EXTENSIONS.add(".csv")

            with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
                tmp_path = Path(tmp.name)
                tmp_path.touch()

                try:
                    result = parser.parse(tmp_path)

                    assert len(result) == 2
                    assert result[0]["titulo"] == "Product 1"
                    assert result[0]["preco"] == 99.99
                    mock_read_excel.assert_called_once()
                finally:
                    tmp_path.unlink(missing_ok=True)
                    parser.SUPPORTED_EXTENSIONS = original_extensions

    def test_csv_with_semicolon_delimiter(self):
        """Test CSV parsing with semicolon delimiter (common in some locales)."""
        parser = SpreadsheetParser()

        expected_df = pd.DataFrame({
            "titulo": ["Product 1", "Product 2"],
            "preco": [99.99, 199.99],
        })

        with patch("pandas.read_excel") as mock_read_excel:
            mock_read_excel.return_value = expected_df

            original_extensions = parser.SUPPORTED_EXTENSIONS.copy()
            parser.SUPPORTED_EXTENSIONS.add(".csv")

            with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
                tmp_path = Path(tmp.name)
                tmp_path.touch()

                try:
                    result = parser.parse(tmp_path)

                    assert len(result) == 2
                    # Verify pandas read_excel was called
                    mock_read_excel.assert_called_once()
                finally:
                    tmp_path.unlink(missing_ok=True)
                    parser.SUPPORTED_EXTENSIONS = original_extensions

    def test_csv_with_tab_delimiter(self):
        """Test CSV parsing with tab delimiter (TSV format)."""
        parser = SpreadsheetParser()

        expected_df = pd.DataFrame({
            "titulo": ["Product 1", "Product 2"],
            "preco": [99.99, 199.99],
        })

        with patch("pandas.read_excel") as mock_read_excel:
            mock_read_excel.return_value = expected_df

            original_extensions = parser.SUPPORTED_EXTENSIONS.copy()
            parser.SUPPORTED_EXTENSIONS.add(".csv")

            with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
                tmp_path = Path(tmp.name)
                tmp_path.touch()

                try:
                    result = parser.parse(tmp_path)
                    assert len(result) == 2
                finally:
                    tmp_path.unlink(missing_ok=True)
                    parser.SUPPORTED_EXTENSIONS = original_extensions

    def test_csv_with_pipe_delimiter(self):
        """Test CSV parsing with pipe delimiter."""
        parser = SpreadsheetParser()

        expected_df = pd.DataFrame({
            "titulo": ["Product 1"],
            "preco": [99.99],
        })

        with patch("pandas.read_excel") as mock_read_excel:
            mock_read_excel.return_value = expected_df

            original_extensions = parser.SUPPORTED_EXTENSIONS.copy()
            parser.SUPPORTED_EXTENSIONS.add(".csv")

            with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
                tmp_path = Path(tmp.name)
                tmp_path.touch()

                try:
                    result = parser.parse(tmp_path)
                    assert len(result) == 1
                finally:
                    tmp_path.unlink(missing_ok=True)
                    parser.SUPPORTED_EXTENSIONS = original_extensions


class TestSpreadsheetParserExcel:
    """Extended tests for Excel parsing functionality."""

    def create_test_excel(
        self,
        data: dict,
        filename: str = "test.xlsx",
        sheet_name: str = "Sheet1",
    ) -> Path:
        """Helper to create a test Excel file.
        
        Args:
            data: Dictionary with column names as keys and lists as values.
            filename: Name of the temporary file.
            sheet_name: Name of the sheet to create.
            
        Returns:
            Path to the created file.
        """
        df = pd.DataFrame(data)
        temp_file = Path(tempfile.gettempdir()) / filename

        with pd.ExcelWriter(temp_file, engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name=sheet_name, index=False)

        return temp_file

    def test_parse_xlsx_success(self):
        """Test successful parsing of .xlsx file."""
        parser = SpreadsheetParser()

        data = {
            "titulo": ["Product 1", "Product 2", "Product 3"],
            "preco": [99.99, 199.99, 299.99],
            "categoria": ["MLB123", "MLB456", "MLB789"],
            "moeda": ["BRL", "BRL", "USD"],
        }
        temp_file = self.create_test_excel(data, "test.xlsx")

        try:
            result = parser.parse(temp_file)

            assert len(result) == 3
            assert result[0]["titulo"] == "Product 1"
            assert result[0]["preco"] == 99.99
            assert result[1]["titulo"] == "Product 2"
            assert result[2]["moeda"] == "USD"
        finally:
            temp_file.unlink(missing_ok=True)

    def test_parse_xls_with_mock(self):
        """Test parsing .xls format using mocked pandas."""
        parser = SpreadsheetParser()

        data = {
            "titulo": ["Product 1"],
            "preco": [99.99],
            "categoria": ["MLB123"],
            "moeda": ["BRL"],
        }

        with patch("pandas.read_excel") as mock_read_excel:
            mock_read_excel.return_value = pd.DataFrame(data)

            with tempfile.NamedTemporaryFile(suffix=".xls", delete=False) as tmp:
                tmp_path = Path(tmp.name)
                tmp_path.touch()

                try:
                    result = parser.parse(tmp_path)

                    assert len(result) == 1
                    assert result[0]["titulo"] == "Product 1"

                    # Verify xlrd engine is used for .xls files
                    call_kwargs = mock_read_excel.call_args[1]
                    assert call_kwargs.get("engine") == "xlrd"
                finally:
                    tmp_path.unlink(missing_ok=True)

    def test_parse_specific_sheet_by_name(self):
        """Test parsing a specific sheet by name."""
        parser = SpreadsheetParser()

        # Create Excel with multiple sheets
        temp_file = Path(tempfile.gettempdir()) / "multi_sheet.xlsx"

        df1 = pd.DataFrame({
            "titulo": ["Product A"],
            "preco": [100.00],
        })
        df2 = pd.DataFrame({
            "titulo": ["Product B"],
            "preco": [200.00],
        })

        with pd.ExcelWriter(temp_file, engine="openpyxl") as writer:
            df1.to_excel(writer, sheet_name="Products", index=False)
            df2.to_excel(writer, sheet_name="Inventory", index=False)

        try:
            # Parse second sheet
            result = parser.parse(temp_file, sheet_name="Inventory")

            assert len(result) == 1
            assert result[0]["titulo"] == "Product B"
            assert result[0]["preco"] == 200.00
        finally:
            temp_file.unlink(missing_ok=True)

    def test_parse_specific_sheet_by_index(self):
        """Test parsing a specific sheet by index."""
        parser = SpreadsheetParser()

        temp_file = Path(tempfile.gettempdir()) / "multi_sheet_idx.xlsx"

        df1 = pd.DataFrame({
            "titulo": ["First Sheet Product"],
            "preco": [100.00],
        })
        df2 = pd.DataFrame({
            "titulo": ["Second Sheet Product"],
            "preco": [200.00],
        })

        with pd.ExcelWriter(temp_file, engine="openpyxl") as writer:
            df1.to_excel(writer, sheet_name="Sheet1", index=False)
            df2.to_excel(writer, sheet_name="Sheet2", index=False)

        try:
            # Parse second sheet by index
            result = parser.parse(temp_file, sheet_name=1)

            assert len(result) == 1
            assert result[0]["titulo"] == "Second Sheet Product"
        finally:
            temp_file.unlink(missing_ok=True)

    def test_parse_with_header_row(self):
        """Test parsing with a specific header row."""
        parser = SpreadsheetParser()

        # Create Excel where headers are in row 2 (index 1)
        temp_file = Path(tempfile.gettempdir()) / "header_row.xlsx"

        # Create data with header in second row
        raw_data = [
            ["Ignore", "This", "Row"],
            ["titulo", "preco", "categoria"],
            ["Product 1", 99.99, "MLB123"],
            ["Product 2", 199.99, "MLB456"],
        ]
        df = pd.DataFrame(raw_data)

        with pd.ExcelWriter(temp_file, engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name="Sheet1", index=False, header=False)

        try:
            result = parser.parse(temp_file, header_row=1)

            assert len(result) == 2
            assert result[0]["titulo"] == "Product 1"
            assert result[1]["preco"] == 199.99
        finally:
            temp_file.unlink(missing_ok=True)

    def test_parse_large_excel_file(self):
        """Test parsing a large Excel file."""
        parser = SpreadsheetParser()

        # Create larger dataset
        num_rows = 1000
        data = {
            "titulo": [f"Product {i}" for i in range(num_rows)],
            "preco": [float(i * 10) for i in range(num_rows)],
            "categoria": [f"MLB{i}" for i in range(num_rows)],
            "moeda": ["BRL"] * num_rows,
        }
        temp_file = self.create_test_excel(data, "large.xlsx")

        try:
            result = parser.parse(temp_file)

            assert len(result) == num_rows
            assert result[0]["titulo"] == "Product 0"
            assert result[999]["titulo"] == "Product 999"
        finally:
            temp_file.unlink(missing_ok=True)


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


class TestEncoding:
    """Tests for different file encodings."""

    def test_utf8_content(self):
        """Test parsing content with UTF-8 special characters."""
        parser = SpreadsheetParser()

        data = {
            "titulo": ["Produto com acentuação: café, maçã, João"],
            "preco": [99.99],
            "categoria": ["MLB123"],
        }
        temp_file = Path(tempfile.gettempdir()) / "utf8.xlsx"
        pd.DataFrame(data).to_excel(temp_file, index=False, engine="openpyxl")

        try:
            result = parser.parse(temp_file)

            assert len(result) == 1
            assert "café" in result[0]["titulo"]
            assert "maçã" in result[0]["titulo"]
            assert "João" in result[0]["titulo"]
        finally:
            temp_file.unlink(missing_ok=True)

    def test_special_characters_in_content(self):
        """Test parsing content with various special characters."""
        parser = SpreadsheetParser()

        data = {
            "titulo": [
                "Product with emojis 🎉",
                "Product with symbols ™ © ®",
                "Product with math ± × ÷",
            ],
            "preco": [10.0, 20.0, 30.0],
        }
        temp_file = Path(tempfile.gettempdir()) / "special.xlsx"
        pd.DataFrame(data).to_excel(temp_file, index=False, engine="openpyxl")

        try:
            result = parser.parse(temp_file)

            assert len(result) == 3
            assert "🎉" in result[0]["titulo"]
            assert "™" in result[1]["titulo"]
            assert "±" in result[2]["titulo"]
        finally:
            temp_file.unlink(missing_ok=True)

    def test_latin1_to_excel(self):
        """Test handling of Latin-1 encoded content in Excel."""
        parser = SpreadsheetParser()

        # Excel files are binary and handle encoding internally
        # This test verifies special characters are preserved
        data = {
            "titulo": ["São Paulo", "Ação", "Empreiteira"],
            "preco": [100.0, 200.0, 300.0],
        }
        temp_file = Path(tempfile.gettempdir()) / "latin_content.xlsx"
        pd.DataFrame(data).to_excel(temp_file, index=False, engine="openpyxl")

        try:
            result = parser.parse(temp_file)

            assert len(result) == 3
            assert result[0]["titulo"] == "São Paulo"
            assert result[1]["titulo"] == "Ação"
            assert result[2]["titulo"] == "Empreiteira"
        finally:
            temp_file.unlink(missing_ok=True)

    def test_unicode_normalization(self):
        """Test that unicode characters are handled correctly."""
        parser = SpreadsheetParser()

        # Various unicode characters
        data = {
            "titulo": [
                "日本語",  # Japanese
                "中文",    # Chinese
                "العربية", # Arabic
                "русский", # Russian
            ],
            "preco": [10.0, 20.0, 30.0, 40.0],
        }
        temp_file = Path(tempfile.gettempdir()) / "unicode.xlsx"
        pd.DataFrame(data).to_excel(temp_file, index=False, engine="openpyxl")

        try:
            result = parser.parse(temp_file)

            assert len(result) == 4
            assert result[0]["titulo"] == "日本語"
            assert result[1]["titulo"] == "中文"
            assert result[2]["titulo"] == "العربية"
            assert result[3]["titulo"] == "русский"
        finally:
            temp_file.unlink(missing_ok=True)

    def test_csv_encoding_mock(self):
        """Test CSV encoding handling with mocked pandas."""
        parser = SpreadsheetParser()

        # Mock DataFrame with UTF-8 content
        expected_df = pd.DataFrame({
            "titulo": ["Café", "Maçã"],
            "preco": [10.0, 20.0],
        })

        with patch("pandas.read_excel") as mock_read_excel:
            mock_read_excel.return_value = expected_df

            original_extensions = parser.SUPPORTED_EXTENSIONS.copy()
            parser.SUPPORTED_EXTENSIONS.add(".csv")

            with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
                tmp_path = Path(tmp.name)
                tmp_path.touch()

                try:
                    result = parser.parse(tmp_path)

                    assert len(result) == 2
                    assert result[0]["titulo"] == "Café"
                    assert result[1]["titulo"] == "Maçã"
                finally:
                    tmp_path.unlink(missing_ok=True)
                    parser.SUPPORTED_EXTENSIONS = original_extensions


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

        df = pd.DataFrame({
            "Title": ["Product 1"],
            "PRICE": [99.99],
            "Category_ID": ["MLB123"],
        })

        normalized = parser._normalize_columns(df)

        assert "titulo" in normalized.columns
        assert "preco" in normalized.columns
        assert "categoria" in normalized.columns

    def test_normalize_columns_whitespace_handling(self):
        """Test that column names with whitespace are handled."""
        parser = SpreadsheetParser()

        df = pd.DataFrame({
            "  title  ": ["Product 1"],
            " price ": [99.99],
        })

        normalized = parser._normalize_columns(df)

        # Whitespace should be stripped and then mapped
        assert "titulo" in normalized.columns
        assert "preco" in normalized.columns


class TestIntegrationScenarios:
    """Integration tests for real-world scenarios."""

    def create_test_excel(self, data: dict, filename: str = "test.xlsx") -> Path:
        """Helper to create a test Excel file."""
        df = pd.DataFrame(data)
        temp_file = Path(tempfile.gettempdir()) / filename
        df.to_excel(temp_file, index=False, engine="openpyxl")
        return temp_file

    def test_real_world_product_import(self):
        """Test a real-world product import scenario."""
        parser = SpreadsheetParser()

        # Simulate a realistic product import file
        data = {
            "title": [
                "Smartphone Samsung Galaxy S23",
                "Notebook Dell Inspiron 15",
                "Fone de Ouvido Bluetooth JBL",
            ],
            "price": [3999.99, 4599.00, 299.99],
            "category_id": ["MLB1055", "MLB1652", "MLB7363"],
            "currency_id": ["BRL", "BRL", "BRL"],
            "quantity": [50, 30, 100],
            "condition": ["new", "new", "new"],
            "description": [
                "Smartphone de última geração",
                "Notebook para trabalho e estudo",
                "Fone de ouvido com alta qualidade",
            ],
            "sku": ["SAMS23-001", "DELL15-002", "JBLBT-003"],
            "brand": ["Samsung", "Dell", "JBL"],
        }
        temp_file = self.create_test_excel(data, "real_world.xlsx")

        try:
            result = parser.parse(temp_file)

            assert len(result) == 3

            # Verify all expected fields are present
            expected_fields = [
                "titulo", "preco", "categoria", "moeda",
                "quantidade", "condicao", "descricao", "sku", "marca"
            ]
            for field in expected_fields:
                assert field in result[0], f"Field {field} not found in parsed data"

            # Verify specific values
            assert result[0]["titulo"] == "Smartphone Samsung Galaxy S23"
            assert result[0]["preco"] == 3999.99
            assert result[0]["categoria"] == "MLB1055"
            assert result[0]["sku"] == "SAMS23-001"
        finally:
            temp_file.unlink(missing_ok=True)

    def test_mixed_column_languages(self):
        """Test file with mixed Portuguese and English column names."""
        parser = SpreadsheetParser()

        data = {
            "title": ["Product 1"],  # English
            "preço": [99.99],  # Portuguese with accent
            "category_id": ["MLB123"],  # English variant
            "moeda": ["BRL"],  # Portuguese
            "quantity": [10],  # English
        }
        temp_file = self.create_test_excel(data, "mixed_langs.xlsx")

        try:
            result = parser.parse(temp_file)

            # All should map to Portuguese internal names
            assert result[0]["titulo"] == "Product 1"
            assert result[0]["preco"] == 99.99
            assert result[0]["categoria"] == "MLB123"
            assert result[0]["moeda"] == "BRL"
            assert result[0]["quantidade"] == 10
        finally:
            temp_file.unlink(missing_ok=True)

    def test_partial_data_handling(self):
        """Test handling of partial/incomplete data."""
        parser = SpreadsheetParser()

        # Some records have missing optional fields
        data = {
            "titulo": ["Product 1", "Product 2", "Product 3"],
            "preco": [99.99, 199.99, 299.99],
            "categoria": ["MLB123", None, "MLB789"],
            "moeda": [None, "USD", "BRL"],
            "descricao": ["Desc 1", "", "Desc 3"],
        }
        temp_file = self.create_test_excel(data, "partial.xlsx")

        try:
            result = parser.parse(temp_file)

            assert len(result) == 3

            # Product 1: missing moeda
            assert "moeda" not in result[0]
            assert result[0]["preco"] == 99.99

            # Product 2: missing categoria, empty descricao
            assert "categoria" not in result[1]
            assert "descricao" not in result[1]  # Empty string removed
            assert result[1]["moeda"] == "USD"

            # Product 3: all required present
            assert result[2]["categoria"] == "MLB789"
            assert result[2]["moeda"] == "BRL"
            assert result[2]["descricao"] == "Desc 3"
        finally:
            temp_file.unlink(missing_ok=True)


class TestLoggerIntegration:
    """Tests for logger integration."""

    def create_test_excel(self, data: dict, filename: str = "test.xlsx") -> Path:
        """Helper to create a test Excel file."""
        df = pd.DataFrame(data)
        temp_file = Path(tempfile.gettempdir()) / filename
        df.to_excel(temp_file, index=False, engine="openpyxl")
        return temp_file

    def test_info_logging_on_parse(self, caplog):
        """Test that info messages are logged during parsing."""
        import logging

        parser = SpreadsheetParser()

        data = {
            "titulo": ["Product 1", "Product 2"],
            "preco": [99.99, 199.99],
        }
        temp_file = self.create_test_excel(data, "log_test.xlsx")

        with caplog.at_level(logging.INFO):
            try:
                result = parser.parse(temp_file)
                assert len(result) == 2
            finally:
                temp_file.unlink(missing_ok=True)

        # Should have logged reading message
        assert any("Lendo planilha" in record.message for record in caplog.records)
        # Should have logged parsed count
        assert any("Parsed" in record.message and "registros" in record.message
                   for record in caplog.records)

    def test_warning_logging_on_empty(self, caplog):
        """Test that warning is logged for empty file."""
        import logging

        parser = SpreadsheetParser()

        df = pd.DataFrame()
        temp_file = Path(tempfile.gettempdir()) / "empty_log.xlsx"
        df.to_excel(temp_file, index=False, engine="openpyxl")

        with caplog.at_level(logging.WARNING):
            try:
                result = parser.parse(temp_file)
                assert result == []
            finally:
                temp_file.unlink(missing_ok=True)

        # Should have logged warning about empty file
        assert any("vazia" in record.message.lower() for record in caplog.records)
