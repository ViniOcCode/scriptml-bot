"""Tests for spreadsheet parser CSV and Excel parsing."""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from mercadolivre_upload.adapters.spreadsheet.parser import SpreadsheetParser


class TestSpreadsheetParserCSV:
    """Tests for CSV parsing functionality."""

    def test_csv_support_not_implemented_by_default(self):
        """Test that CSV files raise ValueError (not supported by default parser)."""
        parser = SpreadsheetParser()

        with tempfile.NamedTemporaryFile(
            suffix=".csv", delete=False, mode="w", encoding="utf-8"
        ) as tmp:
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
        expected_df = pd.DataFrame(
            {
                "titulo": ["Product 1", "Product 2"],
                "preco": [99.99, 199.99],
                "categoria": ["MLB123", "MLB456"],
            }
        )

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

        expected_df = pd.DataFrame(
            {
                "titulo": ["Product 1", "Product 2"],
                "preco": [99.99, 199.99],
            }
        )

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

        expected_df = pd.DataFrame(
            {
                "titulo": ["Product 1", "Product 2"],
                "preco": [99.99, 199.99],
            }
        )

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

        expected_df = pd.DataFrame(
            {
                "titulo": ["Product 1"],
                "preco": [99.99],
            }
        )

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

        df1 = pd.DataFrame(
            {
                "titulo": ["Product A"],
                "preco": [100.00],
            }
        )
        df2 = pd.DataFrame(
            {
                "titulo": ["Product B"],
                "preco": [200.00],
            }
        )

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

        df1 = pd.DataFrame(
            {
                "titulo": ["First Sheet Product"],
                "preco": [100.00],
            }
        )
        df2 = pd.DataFrame(
            {
                "titulo": ["Second Sheet Product"],
                "preco": [200.00],
            }
        )

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
