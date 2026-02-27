"""Integration and logging tests for spreadsheet parser."""

import tempfile
from pathlib import Path

import pandas as pd

from mercadolivre_upload.adapters.spreadsheet.parser import SpreadsheetParser


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
