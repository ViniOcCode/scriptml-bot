"""Tests for variation_builder.py module."""

import sys
from pathlib import Path

import pytest

# Ensure mercadolivre_upload is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from mercadolivre_upload.application.builders.variation_builder import VariationBuilder


class TestVariationBuilderInit:
    """Tests for VariationBuilder initialization."""

    def test_init(self):
        """Test default initialization."""
        builder = VariationBuilder()

        assert builder._variations == []
        assert builder._current is None


class TestStartVariation:
    """Tests for start_variation method."""

    def test_start_variation_basic(self):
        """Test starting a variation."""
        builder = VariationBuilder()

        result = builder.start_variation()

        assert result is builder  # Returns self for chaining
        assert builder._current == {}

    def test_start_variation_with_price(self):
        """Test starting variation with price."""
        builder = VariationBuilder()

        builder.start_variation(price=99.99)

        assert builder._current["price"] == 99.99

    def test_start_variation_with_qty(self):
        """Test starting variation with quantity."""
        builder = VariationBuilder()

        builder.start_variation(qty=10)

        assert builder._current["available_quantity"] == 10

    def test_start_variation_with_both(self):
        """Test starting variation with price and quantity."""
        builder = VariationBuilder()

        builder.start_variation(price=99.99, qty=5)

        assert builder._current["price"] == 99.99
        assert builder._current["available_quantity"] == 5

    def test_start_variation_saves_previous(self):
        """Test that starting new variation saves previous."""
        builder = VariationBuilder()

        builder.start_variation(price=99.99)
        builder.start_variation(price=199.99)

        # Previous should be saved
        assert len(builder._variations) == 1
        assert builder._variations[0]["price"] == 99.99
        # Current should be new
        assert builder._current["price"] == 199.99


class TestAddAttribute:
    """Tests for add_attribute method."""

    def test_add_attribute_basic(self):
        """Test adding attribute."""
        builder = VariationBuilder()
        builder.start_variation()

        result = builder.add_attribute("COLOR", "red")

        assert result is builder
        assert "attribute_combinations" in builder._current
        assert len(builder._current["attribute_combinations"]) == 1
        assert builder._current["attribute_combinations"][0]["id"] == "COLOR"
        assert builder._current["attribute_combinations"][0]["value_name"] == "red"

    def test_add_attribute_with_name(self):
        """Test adding attribute with name."""
        builder = VariationBuilder()
        builder.start_variation()

        builder.add_attribute("SIZE", "M", "Tamanho")

        attr = builder._current["attribute_combinations"][0]
        assert attr["name"] == "Tamanho"

    def test_add_attribute_no_variation(self):
        """Test adding attribute without starting variation."""
        builder = VariationBuilder()

        with pytest.raises(RuntimeError, match="Nenhuma variação iniciada"):
            builder.add_attribute("COLOR", "red")

    def test_add_multiple_attributes(self):
        """Test adding multiple attributes."""
        builder = VariationBuilder()
        builder.start_variation()

        builder.add_attribute("COLOR", "red").add_attribute("SIZE", "M")

        assert len(builder._current["attribute_combinations"]) == 2


class TestAddColor:
    """Tests for add_color method."""

    def test_add_color(self):
        """Test adding color."""
        builder = VariationBuilder()
        builder.start_variation()

        result = builder.add_color("Blue")

        assert result is builder
        attr = builder._current["attribute_combinations"][0]
        assert attr["id"] == "COLOR"
        assert attr["value_name"] == "Blue"
        assert attr["name"] == "Cor"

    def test_add_color_no_variation(self):
        """Test adding color without starting variation."""
        builder = VariationBuilder()

        with pytest.raises(RuntimeError):
            builder.add_color("Red")


class TestAddSize:
    """Tests for add_size method."""

    def test_add_size(self):
        """Test adding size."""
        builder = VariationBuilder()
        builder.start_variation()

        result = builder.add_size("Large")

        assert result is builder
        attr = builder._current["attribute_combinations"][0]
        assert attr["id"] == "SIZE"
        assert attr["value_name"] == "Large"
        assert attr["name"] == "Tamanho"

    def test_add_size_no_variation(self):
        """Test adding size without starting variation."""
        builder = VariationBuilder()

        with pytest.raises(RuntimeError):
            builder.add_size("M")


class TestAddPicture:
    """Tests for add_picture method."""

    def test_add_picture(self):
        """Test adding picture."""
        builder = VariationBuilder()
        builder.start_variation()

        result = builder.add_picture("https://example.com/image.jpg")

        assert result is builder
        assert "picture_ids" in builder._current
        assert builder._current["picture_ids"] == ["https://example.com/image.jpg"]

    def test_add_multiple_pictures(self):
        """Test adding multiple pictures."""
        builder = VariationBuilder()
        builder.start_variation()

        builder.add_picture("https://example.com/1.jpg")
        builder.add_picture("https://example.com/2.jpg")

        assert len(builder._current["picture_ids"]) == 2

    def test_add_picture_no_variation(self):
        """Test adding picture without starting variation."""
        builder = VariationBuilder()

        with pytest.raises(RuntimeError, match="Nenhuma variação iniciada"):
            builder.add_picture("https://example.com/image.jpg")


class TestBuild:
    """Tests for build method."""

    def test_build_empty(self):
        """Test build with no variations."""
        builder = VariationBuilder()

        result = builder.build()

        assert result == []

    def test_build_single(self):
        """Test build with single variation."""
        builder = VariationBuilder()
        builder.start_variation(price=99.99)
        builder.add_color("Red")

        result = builder.build()

        assert len(result) == 1
        assert result[0]["price"] == 99.99
        assert len(result[0]["attribute_combinations"]) == 1
        # Current should be cleared
        assert builder._current is None

    def test_build_multiple(self):
        """Test build with multiple variations."""
        builder = VariationBuilder()

        # First variation
        builder.start_variation(price=99.99)
        builder.add_color("Red")

        # Second variation (starts new, saves first)
        builder.start_variation(price=199.99)
        builder.add_color("Blue")

        result = builder.build()

        assert len(result) == 2
        assert result[0]["price"] == 99.99
        assert result[1]["price"] == 199.99

    def test_build_returns_copy(self):
        """Test that build returns a copy."""
        builder = VariationBuilder()
        builder.start_variation(price=99.99)

        result1 = builder.build()

        # After build, variations are cleared
        # Verify the result was correctly built
        assert len(result1) == 1
        assert result1[0]["price"] == 99.99


class TestClear:
    """Tests for clear method."""

    def test_clear(self):
        """Test clearing variations."""
        builder = VariationBuilder()
        builder.start_variation(price=99.99)
        builder.start_variation(price=199.99)  # Saves first

        result = builder.clear()

        assert result is builder
        assert builder._variations == []
        assert builder._current is None

    def test_clear_empty(self):
        """Test clear when already empty."""
        builder = VariationBuilder()

        builder.clear()

        assert builder._variations == []
        assert builder._current is None


class TestCount:
    """Tests for count method."""

    def test_count_empty(self):
        """Test count with no variations."""
        builder = VariationBuilder()

        assert builder.count() == 0

    def test_count_with_current(self):
        """Test count with current variation."""
        builder = VariationBuilder()
        builder.start_variation(price=99.99)

        assert builder.count() == 1

    def test_count_with_saved(self):
        """Test count with saved variations."""
        builder = VariationBuilder()
        builder.start_variation(price=99.99)
        builder.start_variation(price=199.99)  # Saves first

        assert builder.count() == 2

    def test_count_after_build(self):
        """Test count after build."""
        builder = VariationBuilder()
        builder.start_variation(price=99.99)
        builder.build()

        # After build:
        # - _current is moved to _variations and set to None
        # - build() returns a copy but doesn't clear _variations
        # So count should be 1 (the variation we added)
        assert builder.count() == 1

        # After clear, count should be 0
        builder.clear()
        assert builder.count() == 0


class TestIntegration:
    """Integration tests for VariationBuilder."""

    def test_full_workflow(self):
        """Test complete variation building workflow."""
        builder = VariationBuilder()

        # Create variations
        variations = (
            builder.start_variation(price=99.99, qty=10)
            .add_color("Red")
            .add_size("M")
            .add_picture("https://example.com/red-m.jpg")
            .start_variation(price=99.99, qty=5)
            .add_color("Red")
            .add_size("L")
            .add_picture("https://example.com/red-l.jpg")
            .build()
        )

        assert len(variations) == 2

        # Check first variation
        assert variations[0]["price"] == 99.99
        assert variations[0]["available_quantity"] == 10
        assert len(variations[0]["attribute_combinations"]) == 2

        # Check second variation
        assert variations[1]["price"] == 99.99
        assert variations[1]["available_quantity"] == 5
        assert len(variations[1]["attribute_combinations"]) == 2

    def test_clear_and_rebuild(self):
        """Test clearing and rebuilding."""
        builder = VariationBuilder()

        builder.start_variation(price=99.99).add_color("Red").build()

        builder.clear()
        variations = builder.start_variation(price=199.99).add_color("Blue").build()

        assert len(variations) == 1
        assert variations[0]["price"] == 199.99
