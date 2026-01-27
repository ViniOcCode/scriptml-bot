"""Tests for Excel parser module."""

from pathlib import Path

import pandas as pd
import pytest

from mercadolivre_upload.parser import ExcelParser, FiscalData, Product
from mercadolivre_upload.parser.exceptions import MissingColumnError, ValidationError


class TestFiscalData:
    """Test cases for FiscalData model."""

    def test_init_required(self):
        """Test initialization with required fields."""
        fiscal = FiscalData(
            ncm="1234.56.78",
            cfop="5102",
            origin="SP",
        )
        assert fiscal.ncm == "1234.56.78"
        assert fiscal.cfop == "5102"
        assert fiscal.origin == "SP"
        assert fiscal.cest is None

    def test_init_optional(self):
        """Test initialization with optional cest."""
        fiscal = FiscalData(
            ncm="1234.56.78",
            cfop="5102",
            origin="SP",
            cest="12.345.67",
        )
        assert fiscal.cest == "12.345.67"

    def test_to_dict_without_cest(self):
        """Test dictionary conversion without cest."""
        fiscal = FiscalData(ncm="1234.56.78", cfop="5102", origin="SP")
        result = fiscal.to_dict()
        assert result == {
            "ncm": "1234.56.78",
            "cfop": "5102",
            "origin": "SP",
        }
        assert "cest" not in result

    def test_to_dict_with_cest(self):
        """Test dictionary conversion with cest."""
        fiscal = FiscalData(ncm="1234.56.78", cfop="5102", origin="SP", cest="12.345.67")
        result = fiscal.to_dict()
        assert result == {
            "ncm": "1234.56.78",
            "cfop": "5102",
            "origin": "SP",
            "cest": "12.345.67",
        }


class TestProduct:
    """Test cases for Product model."""

    @pytest.fixture
    def valid_fiscal(self):
        """Create valid fiscal data."""
        return FiscalData(ncm="1234.56.78", cfop="5102", origin="SP")

    def test_init_required(self, valid_fiscal):
        """Test initialization with required fields."""
        product = Product(
            sku="SKU123",
            title="Test Product",
            description="A test product",
            price=99.99,
            available_quantity=10,
            condition="new",
            fiscal=valid_fiscal,
        )
        assert product.sku == "SKU123"
        assert product.title == "Test Product"
        assert product.price == 99.99
        assert product.condition == "new"
        assert product.attributes == {}

    def test_init_with_attributes(self, valid_fiscal):
        """Test initialization with additional attributes."""
        product = Product(
            sku="SKU123",
            title="Test Product",
            description="A test product",
            price=99.99,
            available_quantity=10,
            condition="used",
            fiscal=valid_fiscal,
            attributes={"color": "red", "size": "L"},
        )
        assert product.attributes == {"color": "red", "size": "L"}

    def test_post_init_validates_condition(self, valid_fiscal):
        """Test that invalid condition raises ValueError."""
        with pytest.raises(ValueError, match="Condition must be 'new' or 'used'"):
            Product(
                sku="SKU123",
                title="Test",
                description="Desc",
                price=99.99,
                available_quantity=10,
                condition="invalid",
                fiscal=valid_fiscal,
            )

    def test_post_init_validates_negative_price(self, valid_fiscal):
        """Test that negative price raises ValueError."""
        with pytest.raises(ValueError, match="Price cannot be negative"):
            Product(
                sku="SKU123",
                title="Test",
                description="Desc",
                price=-10.0,
                available_quantity=10,
                condition="new",
                fiscal=valid_fiscal,
            )

    def test_post_init_validates_negative_quantity(self, valid_fiscal):
        """Test that negative quantity raises ValueError."""
        with pytest.raises(ValueError, match="Quantity cannot be negative"):
            Product(
                sku="SKU123",
                title="Test",
                description="Desc",
                price=99.99,
                available_quantity=-5,
                condition="new",
                fiscal=valid_fiscal,
            )

    def test_to_dict(self, valid_fiscal):
        """Test dictionary conversion."""
        product = Product(
            sku="SKU123",
            title="Test",
            description="Desc",
            price=99.99,
            available_quantity=10,
            condition="new",
            fiscal=valid_fiscal,
            attributes={"color": "red"},
        )
        result = product.to_dict()
        assert result["sku"] == "SKU123"
        assert result["title"] == "Test"
        assert result["price"] == 99.99
        assert result["condition"] == "new"
        assert result["attributes"] == {"color": "red"}
        assert "fiscal" in result

    def test_get_attribute(self, valid_fiscal):
        """Test getting attribute value."""
        product = Product(
            sku="SKU123",
            title="Test",
            description="Desc",
            price=99.99,
            available_quantity=10,
            condition="new",
            fiscal=valid_fiscal,
            attributes={"color": "red"},
        )
        assert product.get_attribute("color") == "red"
        assert product.get_attribute("size") is None
        assert product.get_attribute("size", "M") == "M"


class TestExcelParser:
    """Test cases for ExcelParser."""

    @pytest.fixture
    def parser(self):
        """Create parser instance."""
        return ExcelParser()

    @pytest.fixture
    def sample_df(self):
        """Create sample DataFrame for testing."""
        data = {
            "sku": ["SKU001", "SKU002"],
            "title": ["Product 1", "Product 2"],
            "description": ["Description 1", "Description 2"],
            "price": [99.99, 149.99],
            "available_quantity": [10, 5],
            "condition": ["new", "used"],
            "ncm": ["1234.56.78", "9876.54.32"],
            "cfop": ["5102", "5101"],
            "origin": ["SP", "RJ"],
            "cest": ["12.345.67", None],
            "color": ["red", "blue"],
        }
        return pd.DataFrame(data)

    @pytest.fixture
    def excel_file(self, tmp_path, sample_df):
        """Create temporary Excel file for testing."""
        excel_path = tmp_path / "test_products.xlsx"
        sample_df.to_excel(excel_path, index=False)
        return excel_path

    def test_init_default_mappings(self, parser):
        """Test initialization with default column mappings."""
        assert "sku" in parser.mappings
        assert "title" in parser.mappings
        assert "price" in parser.mappings
        assert "sku" in parser.mappings["sku"]
        assert "titulo" in parser.mappings["title"]
        assert "preco" in parser.mappings["price"]

    def test_init_custom_mappings(self):
        """Test initialization with custom column mappings."""
        custom = {"sku": ["my_sku", "product_code"]}
        parser = ExcelParser(column_mappings=custom)
        assert parser.mappings["sku"] == ["my_sku", "product_code"]
        # Other mappings should still exist
        assert "title" in parser.mappings

    def test_build_reverse_mapping(self, parser):
        """Test building reverse column mapping."""
        columns = ["SKU", "Título", "Preço", "Unknown"]
        reverse = parser._build_reverse_mapping(columns)
        assert reverse["sku"] == "SKU"
        assert reverse["title"] == "Título"
        assert reverse["price"] == "Preço"

    def test_validate_columns_success(self, parser):
        """Test column validation with all required columns."""
        columns = ["sku", "title", "description", "price", "available_quantity", "condition"]
        parser._validate_columns(columns)  # Should not raise

    def test_validate_columns_missing(self, parser):
        """Test column validation with missing columns."""
        columns = ["sku", "title"]  # Missing required columns
        with pytest.raises(MissingColumnError) as exc_info:
            parser._validate_columns(columns)
        assert "description" in str(exc_info.value)
        assert "price" in str(exc_info.value)

    def test_parse_price_numeric(self, parser):
        """Test parsing numeric price."""
        assert parser._parse_price(99.99) == 99.99
        assert parser._parse_price(100) == 100.0

    def test_parse_price_string_simple(self, parser):
        """Test parsing simple string price."""
        assert parser._parse_price("99.99") == 99.99
        assert parser._parse_price("100") == 100.0

    def test_parse_price_string_brazilian(self, parser):
        """Test parsing Brazilian format price."""
        assert parser._parse_price("1.234,56") == 1234.56
        assert parser._parse_price("R$ 1.234,56") == 1234.56

    def test_parse_price_string_us(self, parser):
        """Test parsing US format price."""
        assert parser._parse_price("1,234.56") == 1234.56

    def test_parse_price_invalid(self, parser):
        """Test parsing invalid price."""
        with pytest.raises(ValueError, match="Cannot parse price"):
            parser._parse_price("invalid")

    def test_parse_quantity_numeric(self, parser):
        """Test parsing numeric quantity."""
        assert parser._parse_quantity(10) == 10
        assert parser._parse_quantity(5.5) == 5

    def test_parse_quantity_string(self, parser):
        """Test parsing string quantity."""
        assert parser._parse_quantity("10") == 10
        assert parser._parse_quantity("5.5") == 5

    def test_parse_quantity_invalid(self, parser):
        """Test parsing invalid quantity."""
        with pytest.raises(ValueError, match="Cannot parse quantity"):
            parser._parse_quantity("invalid")

    def test_parse_condition_new_variants(self, parser):
        """Test parsing various 'new' condition values."""
        assert parser._parse_condition("new") == "new"
        assert parser._parse_condition("NOVO") == "new"
        assert parser._parse_condition("nueva") == "new"
        assert parser._parse_condition("0") == "new"

    def test_parse_condition_used_variants(self, parser):
        """Test parsing various 'used' condition values."""
        assert parser._parse_condition("used") == "used"
        assert parser._parse_condition("USADO") == "used"
        assert parser._parse_condition("segunda mão") == "used"
        assert parser._parse_condition("1") == "used"

    def test_parse_condition_invalid(self, parser):
        """Test parsing invalid condition."""
        with pytest.raises(ValueError, match="Invalid condition"):
            parser._parse_condition("other")

    def test_validate_row_valid(self, parser):
        """Test validating a valid row."""
        row = pd.Series({
            "sku": "SKU001",
            "title": "Test",
            "description": "Desc",
            "price": 99.99,
            "available_quantity": 10,
            "condition": "new",
        })
        parser._reverse_mapping = {
            "sku": "sku", "title": "title", "description": "description",
            "price": "price", "available_quantity": "available_quantity", "condition": "condition",
        }
        is_valid, errors = parser.validate_row(row)
        assert is_valid
        assert errors == []

    def test_validate_row_missing_fields(self, parser):
        """Test validating row with missing fields."""
        row = pd.Series({
            "sku": "",
            "title": "Test",
            "price": -10,
            "condition": "other",
        })
        parser._reverse_mapping = {
            "sku": "sku", "title": "title", "description": "description",
            "price": "price", "available_quantity": "available_quantity", "condition": "condition",
        }
        is_valid, errors = parser.validate_row(row)
        assert not is_valid
        assert len(errors) > 0

    def test_extract_attributes(self, parser):
        """Test extracting additional attributes."""
        row = pd.Series({
            "sku": "SKU001",
            "title": "Test",
            "color": "red",
            "size": "L",
        })
        parser._reverse_mapping = {"sku": "sku", "title": "title"}
        attributes = parser._extract_attributes(row)
        assert attributes == {"color": "red", "size": "L"}

    def test_parse_file_not_found(self, parser):
        """Test parsing non-existent file."""
        with pytest.raises(FileNotFoundError):
            parser.parse("/nonexistent/file.xlsx")

    def test_parse_success(self, parser, excel_file):
        """Test successful parsing of Excel file."""
        products = parser.parse(excel_file)
        assert len(products) == 2

        # Check first product
        assert products[0].sku == "SKU001"
        assert products[0].title == "Product 1"
        assert products[0].price == 99.99
        assert products[0].condition == "new"
        assert products[0].fiscal.ncm == "1234.56.78"
        assert products[0].attributes == {"color": "red"}

        # Check second product
        assert products[1].sku == "SKU002"
        assert products[1].condition == "used"
        assert products[1].attributes == {"color": "blue"}

    def test_parse_empty_file(self, parser, tmp_path):
        """Test parsing empty Excel file."""
        df = pd.DataFrame()
        excel_path = tmp_path / "empty.xlsx"
        df.to_excel(excel_path, index=False)

        products = parser.parse(excel_path)
        assert products == []

    def test_parse_with_errors(self, parser, tmp_path):
        """Test parsing file with some invalid rows."""
        data = {
            "sku": ["SKU001", "", "SKU003"],
            "title": ["Product 1", "Product 2", "Product 3"],
            "description": ["Desc", "Desc", "Desc"],
            "price": [99.99, 149.99, -10],
            "available_quantity": [10, 5, 3],
            "condition": ["new", "new", "new"],
        }
        df = pd.DataFrame(data)
        excel_path = tmp_path / "with_errors.xlsx"
        df.to_excel(excel_path, index=False)

        products = parser.parse(excel_path)
        # Only first row is valid
        assert len(products) == 1
        assert products[0].sku == "SKU001"

    def test_parse_safely_success(self, parser, excel_file):
        """Test safe parsing with valid file."""
        products, errors = parser.parse_safely(excel_file)
        assert len(products) == 2
        assert errors == []

    def test_parse_safely_file_not_found(self, parser):
        """Test safe parsing with non-existent file."""
        products, errors = parser.parse_safely("/nonexistent/file.xlsx")
        assert products == []
        assert len(errors) == 1

    def test_parse_safely_missing_columns(self, parser, tmp_path):
        """Test safe parsing with missing columns."""
        data = {"sku": ["SKU001"], "title": ["Test"]}
        df = pd.DataFrame(data)
        excel_path = tmp_path / "missing_cols.xlsx"
        df.to_excel(excel_path, index=False)

        products, errors = parser.parse_safely(excel_path)
        assert products == []
        assert len(errors) == 1


class TestExcelParserAlternativeColumns:
    """Test parsing with alternative column names."""

    @pytest.fixture
    def parser(self):
        """Create parser instance."""
        return ExcelParser()

    def test_parse_brazilian_column_names(self, parser, tmp_path):
        """Test parsing with Brazilian Portuguese column names."""
        data = {
            "Codigo": ["SKU001"],
            "Titulo": ["Produto 1"],
            "Descricao": ["Descricao do produto"],
            "Preco": [199.99],
            "Estoque": [10],
            "Condicao": ["novo"],
            "NCM": ["1234.56.78"],
            "CFOP": ["5102"],
            "Origem": ["SP"],
        }
        df = pd.DataFrame(data)
        excel_path = tmp_path / "brazilian.xlsx"
        df.to_excel(excel_path, index=False)

        products = parser.parse(excel_path)
        assert len(products) == 1
        assert products[0].sku == "SKU001"
        assert products[0].title == "Produto 1"
        assert products[0].condition == "new"

    def test_parse_case_insensitive(self, parser, tmp_path):
        """Test case-insensitive column matching."""
        data = {
            "SKU": ["SKU001"],
            "TITLE": ["Test"],
            "DESCRIPTION": ["Desc"],
            "PRICE": [99.99],
            "AVAILABLE_QUANTITY": [10],
            "CONDITION": ["new"],
            "NCM": ["1234.56.78"],
            "CFOP": ["5102"],
            "ORIGIN": ["SP"],
        }
        df = pd.DataFrame(data)
        excel_path = tmp_path / "uppercase.xlsx"
        df.to_excel(excel_path, index=False)

        products = parser.parse(excel_path)
        assert len(products) == 1
        assert products[0].sku == "SKU001"

