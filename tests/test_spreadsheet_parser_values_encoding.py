"""Tests for spreadsheet parser encoding scenarios."""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from mercadolivre_upload.adapters.spreadsheet.parser import SpreadsheetParser


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
