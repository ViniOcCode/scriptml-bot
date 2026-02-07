"""Picture builder utilities."""

from typing import Any
from urllib.parse import urlparse


class PictureBuilder:
    """Builds picture payloads for Mercado Livre items."""

    def __init__(self) -> None:
        """Initialize with empty pictures list."""
        self._pictures: list[dict[str, Any]] = []

    def add_url(self, url: str) -> "PictureBuilder":
        """Add an image URL."""
        self._pictures.append({"source": url})
        return self

    def add_urls(self, urls: list[str]) -> "PictureBuilder":
        """Add multiple image URLs."""
        for url in urls:
            self.add_url(url)
        return self

    def add_file(self, path: str) -> "PictureBuilder":
        """Add a local file path as file:// URL."""
        normalized = f"file://{path}"
        self._pictures.append({"source": normalized})
        return self

    def add_files(self, paths: list[str]) -> "PictureBuilder":
        """Add multiple local file paths."""
        for path in paths:
            self.add_file(path)
        return self

    def build(self) -> list[dict[str, Any]]:
        """Return a copy of built pictures."""
        return [pic.copy() for pic in self._pictures]

    def clear(self) -> "PictureBuilder":
        """Clear stored pictures."""
        self._pictures = []
        return self

    def validate_urls(self) -> list[str]:
        """Return list of invalid URLs."""
        invalid: list[str] = []
        for picture in self._pictures:
            source = picture.get("source", "")
            parsed = urlparse(source)
            if parsed.scheme not in {"http", "https", "file"} or not parsed.path:
                invalid.append(source)
        return invalid
