"""Tests for picture_builder.py module."""
import sys
from pathlib import Path

# Ensure mercadolivre_upload is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from mercadolivre_upload.application.builders.picture_builder import PictureBuilder


class TestPictureBuilderInit:
    """Tests for PictureBuilder initialization."""

    def test_init(self):
        """Test default initialization."""
        builder = PictureBuilder()

        assert builder._pictures == []


class TestAddUrl:
    """Tests for add_url method."""

    def test_add_url(self):
        """Test adding URL."""
        builder = PictureBuilder()

        result = builder.add_url("https://example.com/image.jpg")

        assert result is builder  # Returns self for chaining
        assert len(builder._pictures) == 1
        assert builder._pictures[0]["source"] == "https://example.com/image.jpg"

    def test_add_url_chaining(self):
        """Test method chaining."""
        builder = PictureBuilder()

        result = (
            builder
            .add_url("https://example.com/1.jpg")
            .add_url("https://example.com/2.jpg")
        )

        assert result is builder
        assert len(builder._pictures) == 2


class TestAddUrls:
    """Tests for add_urls method."""

    def test_add_urls(self):
        """Test adding multiple URLs."""
        builder = PictureBuilder()

        urls = [
            "https://example.com/1.jpg",
            "https://example.com/2.jpg",
            "https://example.com/3.jpg",
        ]

        result = builder.add_urls(urls)

        assert result is builder
        assert len(builder._pictures) == 3

    def test_add_urls_empty(self):
        """Test adding empty URL list."""
        builder = PictureBuilder()

        builder.add_urls([])

        assert builder._pictures == []

    def test_add_urls_chaining(self):
        """Test chaining with other methods."""
        builder = PictureBuilder()

        result = (
            builder
            .add_url("https://example.com/first.jpg")
            .add_urls(["https://example.com/2.jpg", "https://example.com/3.jpg"])
        )

        assert result is builder
        assert len(builder._pictures) == 3


class TestAddFile:
    """Tests for add_file method."""

    def test_add_file(self):
        """Test adding file path."""
        builder = PictureBuilder()

        result = builder.add_file("/path/to/image.jpg")

        assert result is builder
        assert len(builder._pictures) == 1
        assert builder._pictures[0]["source"] == "file:///path/to/image.jpg"

    def test_add_file_relative(self):
        """Test adding relative file path."""
        builder = PictureBuilder()

        builder.add_file("images/product.jpg")

        assert builder._pictures[0]["source"] == "file://images/product.jpg"


class TestAddFiles:
    """Tests for add_files method."""

    def test_add_files(self):
        """Test adding multiple files."""
        builder = PictureBuilder()

        paths = ["/path/1.jpg", "/path/2.jpg"]

        result = builder.add_files(paths)

        assert result is builder
        assert len(builder._pictures) == 2

    def test_add_files_empty(self):
        """Test adding empty file list."""
        builder = PictureBuilder()

        builder.add_files([])

        assert builder._pictures == []


class TestBuild:
    """Tests for build method."""

    def test_build_returns_copy(self):
        """Test that build returns a copy."""
        builder = PictureBuilder()
        builder.add_url("https://example.com/image.jpg")

        result1 = builder.build()
        result2 = builder.build()

        assert result1 is not result2
        assert result1 == result2

    def test_build_empty(self):
        """Test build with no pictures."""
        builder = PictureBuilder()

        result = builder.build()

        assert result == []

    def test_build_preserves_modifications(self):
        """Test that original list is not affected by modifications."""
        builder = PictureBuilder()
        builder.add_url("https://example.com/image.jpg")

        result = builder.build()
        result.append({"source": "modified"})

        # Original should not be modified
        assert len(builder._pictures) == 1


class TestClear:
    """Tests for clear method."""

    def test_clear(self):
        """Test clearing pictures."""
        builder = PictureBuilder()
        builder.add_url("https://example.com/1.jpg").add_url("https://example.com/2.jpg")

        result = builder.clear()

        assert result is builder
        assert builder._pictures == []

    def test_clear_empty(self):
        """Test clear when already empty."""
        builder = PictureBuilder()

        builder.clear()

        assert builder._pictures == []


class TestValidateUrls:
    """Tests for validate_urls method."""

    def test_validate_urls_all_valid_http(self):
        """Test validation with valid http URLs."""
        builder = PictureBuilder()
        builder.add_url("http://example.com/image.jpg")

        invalid = builder.validate_urls()

        assert invalid == []

    def test_validate_urls_all_valid_https(self):
        """Test validation with valid https URLs."""
        builder = PictureBuilder()
        builder.add_url("https://example.com/image.jpg")

        invalid = builder.validate_urls()

        assert invalid == []

    def test_validate_urls_valid_file(self):
        """Test validation with valid file URLs."""
        builder = PictureBuilder()
        builder.add_file("/path/to/image.jpg")

        invalid = builder.validate_urls()

        assert invalid == []

    def test_validate_urls_invalid(self):
        """Test validation with invalid URLs."""
        builder = PictureBuilder()
        # Add invalid URL by manipulating internal state
        builder._pictures.append({"source": "not-a-valid-url"})

        invalid = builder.validate_urls()

        assert len(invalid) == 1
        assert invalid[0] == "not-a-valid-url"

    def test_validate_urls_mixed(self):
        """Test validation with mixed valid/invalid URLs."""
        builder = PictureBuilder()
        builder.add_url("https://example.com/valid.jpg")
        builder._pictures.append({"source": "invalid-url"})

        invalid = builder.validate_urls()

        assert len(invalid) == 1
        assert invalid[0] == "invalid-url"

    def test_validate_urls_empty(self):
        """Test validation with empty list."""
        builder = PictureBuilder()

        invalid = builder.validate_urls()

        assert invalid == []


class TestIntegration:
    """Integration tests for PictureBuilder."""

    def test_full_workflow(self):
        """Test complete picture building workflow."""
        builder = PictureBuilder()

        pictures = (
            builder
            .add_url("https://example.com/main.jpg")
            .add_urls([
                "https://example.com/2.jpg",
                "https://example.com/3.jpg",
            ])
            .add_file("/local/image.jpg")
            .build()
        )

        assert len(pictures) == 4

        # Check that all sources are present
        sources = [p["source"] for p in pictures]
        assert "https://example.com/main.jpg" in sources
        assert "https://example.com/2.jpg" in sources
        assert "https://example.com/3.jpg" in sources
        assert "file:///local/image.jpg" in sources

    def test_clear_and_rebuild(self):
        """Test clearing and rebuilding."""
        builder = PictureBuilder()

        builder.add_url("https://example.com/1.jpg")
        assert len(builder.build()) == 1

        builder.clear().add_url("https://example.com/2.jpg")
        result = builder.build()

        assert len(result) == 1
        assert result[0]["source"] == "https://example.com/2.jpg"
