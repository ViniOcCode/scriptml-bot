"""Tests for attribute_builder.py module."""

import sys
from pathlib import Path

# Ensure mercadolivre_upload is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from mercadolivre_upload.application.builders.attribute_builder import AttributeBuilder


class TestAttributeBuilderInit:
    """Tests for AttributeBuilder initialization."""

    def test_init(self):
        """Test default initialization."""
        builder = AttributeBuilder()

        assert builder._attributes == []


class TestAddAttribute:
    """Tests for add_attribute method."""

    def test_add_attribute_basic(self):
        """Test adding a basic attribute."""
        builder = AttributeBuilder()

        result = builder.add_attribute("COLOR", "red")

        assert result is builder  # Returns self for chaining
        assert len(builder._attributes) == 1
        assert builder._attributes[0]["id"] == "COLOR"
        assert builder._attributes[0]["value_name"] == "red"

    def test_add_attribute_with_name(self):
        """Test adding attribute with name."""
        builder = AttributeBuilder()

        builder.add_attribute("SIZE", "M", "Tamanho")

        assert builder._attributes[0]["name"] == "Tamanho"

    def test_add_attribute_numeric_value(self):
        """Test adding attribute with numeric value."""
        builder = AttributeBuilder()

        builder.add_attribute("WEIGHT", 100)

        assert builder._attributes[0]["value_name"] == "100"

    def test_add_attribute_chaining(self):
        """Test method chaining."""
        builder = AttributeBuilder()

        result = (
            builder.add_attribute("COLOR", "red")
            .add_attribute("SIZE", "M")
            .add_attribute("WEIGHT", 10)
        )

        assert result is builder
        assert len(builder._attributes) == 3


class TestAddBrand:
    """Tests for add_brand method."""

    def test_add_brand(self):
        """Test adding brand attribute."""
        builder = AttributeBuilder()

        result = builder.add_brand("Nike")

        assert result is builder
        assert len(builder._attributes) == 1
        assert builder._attributes[0]["id"] == "BRAND"
        assert builder._attributes[0]["value_name"] == "Nike"
        assert builder._attributes[0]["name"] == "Marca"


class TestAddModel:
    """Tests for add_model method."""

    def test_add_model(self):
        """Test adding model attribute."""
        builder = AttributeBuilder()

        result = builder.add_model("Air Max")

        assert result is builder
        assert len(builder._attributes) == 1
        assert builder._attributes[0]["id"] == "MODEL"
        assert builder._attributes[0]["value_name"] == "Air Max"
        assert builder._attributes[0]["name"] == "Modelo"


class TestAddGtin:
    """Tests for add_gtin method."""

    def test_add_gtin(self):
        """Test adding GTIN attribute."""
        builder = AttributeBuilder()

        result = builder.add_gtin("1234567890123")

        assert result is builder
        assert len(builder._attributes) == 1
        assert builder._attributes[0]["id"] == "GTIN"
        assert builder._attributes[0]["value_name"] == "1234567890123"
        assert builder._attributes[0]["name"] == "Código de barras"


class TestAddFromDict:
    """Tests for add_from_dict method."""

    def test_add_from_dict(self):
        """Test adding attributes from dictionary."""
        builder = AttributeBuilder()

        attributes = {
            "color": "red",
            "size": "M",
            "material": "cotton",
        }

        result = builder.add_from_dict(attributes)

        assert result is builder
        assert len(builder._attributes) == 3

    def test_add_from_dict_skips_none(self):
        """Test that None values are skipped."""
        builder = AttributeBuilder()

        attributes = {
            "color": "red",
            "size": None,
            "material": "",
        }

        builder.add_from_dict(attributes)

        assert len(builder._attributes) == 1
        assert builder._attributes[0]["id"] == "COLOR"


class TestBuild:
    """Tests for build method."""

    def test_build_returns_copy(self):
        """Test that build returns a copy."""
        builder = AttributeBuilder()
        builder.add_attribute("COLOR", "red")

        result1 = builder.build()
        result2 = builder.build()

        assert result1 is not result2
        assert result1 == result2

    def test_build_empty(self):
        """Test build with no attributes."""
        builder = AttributeBuilder()

        result = builder.build()

        assert result == []


class TestClear:
    """Tests for clear method."""

    def test_clear(self):
        """Test clearing attributes."""
        builder = AttributeBuilder()
        builder.add_attribute("COLOR", "red").add_attribute("SIZE", "M")

        result = builder.clear()

        assert result is builder
        assert builder._attributes == []

    def test_clear_empty(self):
        """Test clear when already empty."""
        builder = AttributeBuilder()

        builder.clear()

        assert builder._attributes == []


class TestIntegration:
    """Integration tests for AttributeBuilder."""

    def test_full_workflow(self):
        """Test complete attribute building workflow."""
        builder = AttributeBuilder()

        attributes = (
            builder.add_brand("Nike")
            .add_model("Air Max")
            .add_gtin("1234567890123")
            .add_from_dict({"material": "leather", "weight": "1kg"})
            .build()
        )

        assert len(attributes) == 5

        # Verify all attributes
        ids = [a["id"] for a in attributes]
        assert "BRAND" in ids
        assert "MODEL" in ids
        assert "GTIN" in ids
        assert "MATERIAL" in ids
        assert "WEIGHT" in ids
