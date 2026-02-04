"""Ports (interfaces) for the publish product use case.

These protocols define the interface between the application layer
and the infrastructure/adapters layer.
"""

from pathlib import Path
from typing import Protocol


class ImageUploaderPort(Protocol):
    """Port for image upload operations."""

    def upload_images(self, sku: str) -> list[str]:
        """Upload images for SKU and return URLs."""
        ...


class ItemPublisherPort(Protocol):
    """Port for item publishing operations."""

    def validate_item(self, item: dict) -> dict:
        """Validate item payload."""
        ...

    def create_item(self, item: dict) -> dict:
        """Create/publish item."""
        ...


class ShippingResolverPort(Protocol):
    """Port for shipping mode resolution."""

    def get_best_shipping_mode(self) -> str:
        """Get best available shipping mode for user."""
        ...


class ClipUploaderPort(Protocol):
    """Port for video clip upload operations."""

    def upload_clip_for_item(
        self, item_id: str, video_path: Path, sites: list[dict] | None = None
    ) -> str | None:
        """Upload a video clip for a published item.

        Args:
            item_id: Mercado Livre item ID (e.g., MLB1234567890)
            video_path: Path to the video file
            sites: Optional list of sites for clip visibility

        Returns:
            Clip UUID on success, None on failure
        """
        ...
