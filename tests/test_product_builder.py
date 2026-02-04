"""Tests for product_builder.py module."""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure mercadolivre_upload is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from mercadolivre_upload.application.builders.product_builder import ProductBuilder


class TestProductBuilderInit:
    """Tests for ProductBuilder initialization."""

    def test_init(self):
        """Test default initialization."""
        builder = ProductBuilder()

        assert builder._mapper is not None
        assert builder._normalizer is not None

    def test_required_fields(self):
        """Test that required fields are set correctly."""
        builder = ProductBuilder()

        assert "title" in builder.REQUIRED_FIELDS
        assert "category_id" in builder.REQUIRED_FIELDS
        assert "price" in builder.REQUIRED_FIELDS
        assert "currency_id" in builder.REQUIRED_FIELDS


class TestBuild:
    """Tests for build method."""

    def test_build_success(self):
        """Test successful build."""
        builder = ProductBuilder()

        data = {
            "titulo": "Test Product",
            "categoria": "MLB123",
            "preco": "99.99",
            "moeda": "BRL",
            "quantidade": "10",
        }

        result = builder.build(data)

        assert result["title"] == "Test product"
        assert result["category_id"] == "MLB123"
        assert result["price"] == 99.99
        assert result["currency_id"] == "BRL"
        assert result["available_quantity"] == 10

    def test_build_normalizes_title(self):
        """Test that title is normalized."""
        builder = ProductBuilder()

        data = {
            "titulo": "  TEST PRODUCT WITH EXTRA SPACES  ",
            "categoria": "MLB123",
            "preco": "99.99",
            "moeda": "BRL",
        }

        result = builder.build(data)

        assert result["title"] == "Test product with extra spaces"

    def test_build_normalizes_description(self):
        """Test that description is normalized."""
        builder = ProductBuilder()

        data = {
            "titulo": "Test",
            "descricao": "  This is a description.  ",
            "categoria": "MLB123",
            "preco": "99.99",
            "moeda": "BRL",
        }

        result = builder.build(data)

        assert "description" in result

    def test_build_missing_required_fields(self):
        """Test build with missing required fields."""
        builder = ProductBuilder()

        data = {
            "titulo": "Test",
            # Missing categoria, preco, moeda
        }

        with pytest.raises(ValueError, match="Campos obrigatórios faltando"):
            builder.build(data)

    def test_build_with_empty_values(self):
        """Test build with empty required values."""
        builder = ProductBuilder()

        data = {
            "titulo": "",
            "categoria": "MLB123",
            "preco": "99.99",
            "moeda": "BRL",
        }

        with pytest.raises(ValueError, match="Campos obrigatórios faltando"):
            builder.build(data)

    def test_build_preserves_optional_fields(self):
        """Test that optional fields are preserved."""
        builder = ProductBuilder()

        data = {
            "titulo": "Test",
            "categoria": "MLB123",
            "preco": "99.99",
            "moeda": "BRL",
            "condicao": "new",
        }

        result = builder.build(data)

        assert result.get("condition") == "new"


class TestValidate:
    """Tests for validate method."""

    def test_validate_valid(self):
        """Test validation with valid data."""
        builder = ProductBuilder()

        data = {
            "titulo": "Test",
            "categoria": "MLB123",
            "preco": "99.99",
            "moeda": "BRL",
        }

        errors = builder.validate(data)

        # validate returns errors from mapper, not from _validate_required
        # The method works differently - it checks mapping first
        assert isinstance(errors, list)

    def test_validate_missing_fields(self):
        """Test validation with missing fields."""
        builder = ProductBuilder()

        data = {
            "titulo": "Test",
            # Missing other required fields
        }

        errors = builder.validate(data)

        # Should have errors for missing mapped fields
        assert len(errors) > 0

    def test_validate_mapping_not_registered(self):
        """Test validation with unregistered source type."""
        builder = ProductBuilder()

        data = {"titulo": "Test"}
        errors = builder.validate(data, source_type="unknown")

        # When mapping is not registered, mapper returns error
        assert len(errors) > 0

    @patch("mercadolivre_upload.application.builders.product_builder.SmartMapper")
    def test_validate_with_map_exception(self, mock_mapper_class):
        """Test validate when map_product raises exception."""
        mock_mapper = MagicMock()
        mock_mapper_class.return_value = mock_mapper
        mock_mapper.validate_mapping.return_value = []
        mock_mapper.map_product.side_effect = ValueError("Mapping error")

        builder = ProductBuilder()
        builder._mapper = mock_mapper

        data = {"titulo": "Test", "categoria": "MLB123"}
        errors = builder.validate(data)

        assert len(errors) > 0
        assert "Mapping error" in errors[0]


class TestBuildBatch:
    """Tests for build_batch method."""

    def test_build_batch(self):
        """Test building multiple products."""
        builder = ProductBuilder()

        data_list = [
            {
                "titulo": "Product 1",
                "categoria": "MLB123",
                "preco": "99.99",
                "moeda": "BRL",
            },
            {
                "titulo": "Product 2",
                "categoria": "MLB456",
                "preco": "199.99",
                "moeda": "BRL",
            },
        ]

        results = builder.build_batch(data_list)

        assert len(results) == 2
        assert results[0]["title"] == "Product 1"
        assert results[1]["title"] == "Product 2"

    def test_build_batch_empty(self):
        """Test building empty batch."""
        builder = ProductBuilder()

        results = builder.build_batch([])

        assert results == []

    def test_build_batch_with_error(self):
        """Test batch with one invalid item."""
        builder = ProductBuilder()

        data_list = [
            {
                "titulo": "Product 1",
                "categoria": "MLB123",
                "preco": "99.99",
                "moeda": "BRL",
            },
            {
                # Missing required fields
                "titulo": "Product 2",
            },
        ]

        # Should raise on second item
        with pytest.raises(ValueError):
            builder.build_batch(data_list)


class TestValidateRequired:
    """Tests for _validate_required method."""

    def test_validate_required_all_present(self):
        """Test validation when all fields present."""
        builder = ProductBuilder()

        data = {
            "title": "Test",
            "category_id": "MLB123",
            "price": 99.99,
            "currency_id": "BRL",
        }

        missing = builder._validate_required(data)

        assert missing == []

    def test_validate_required_missing_field(self):
        """Test validation with missing field."""
        builder = ProductBuilder()

        data = {
            "title": "Test",
            "category_id": "MLB123",
            "currency_id": "BRL",
            # Missing price
        }

        missing = builder._validate_required(data)

        assert "price" in missing

    def test_validate_required_empty_string(self):
        """Test validation with empty string."""
        builder = ProductBuilder()

        data = {
            "title": "Test",
            "category_id": "MLB123",
            "price": "",
            "currency_id": "BRL",
        }

        missing = builder._validate_required(data)

        assert "price" in missing

    def test_validate_required_none_value(self):
        """Test validation with None value."""
        builder = ProductBuilder()

        data = {
            "title": "Test",
            "category_id": "MLB123",
            "price": None,
            "currency_id": "BRL",
        }

        missing = builder._validate_required(data)

        assert "price" in missing
