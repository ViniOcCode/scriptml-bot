"""Tests for spreadsheet parser values, encoding, and integration scenarios."""

import tempfile
from pathlib import Path
from unittest.mock import patch

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
                "中文",  # Chinese
                "العربية",  # Arabic
                "русский",  # Russian
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
        expected_df = pd.DataFrame(
            {
                "titulo": ["Café", "Maçã"],
                "preco": [10.0, 20.0],
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
                "titulo",
                "preco",
                "categoria",
                "moeda",
                "quantidade",
                "condicao",
                "descricao",
                "sku",
                "marca",
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
        assert any(
            "Parsed" in record.message and "registros" in record.message
            for record in caplog.records
        )

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
