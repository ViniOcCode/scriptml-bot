"""Ports (interfaces) for the publish product use case.

These protocols define the interface between the application layer
and the infrastructure/adapters layer.
"""

from typing import Any, Protocol


class ImageUploaderPort(Protocol):
    """Port for image upload operations."""

    def upload_images(self, sku: str) -> list[str]:
        """Upload images for SKU and return URLs."""
        ...


class ItemPublisherPort(Protocol):
    """Port for item publishing operations."""

    def validate_item(self, item: dict[str, Any]) -> dict[str, Any]:
        """Validate item payload."""
        ...

    def create_item(self, item: dict[str, Any]) -> dict[str, Any]:
        """Create/publish item."""
        ...

    def get_available_listing_types(self, category_id: str) -> list[dict[str, Any]]:
        """Get listing types available for current user in a category."""
        ...

    def get_category_sale_terms(self, category_id: str) -> list[dict[str, Any]]:
        """Get sale terms metadata for a category."""
        ...

    def create_item_description(self, item_id: str, plain_text: str) -> dict[str, Any]:
        """Create/update item description using description endpoint."""
        ...


class ShippingResolverPort(Protocol):
    """Port for shipping mode resolution."""

    def get_best_shipping_mode(self) -> str:
        """Get best available shipping mode for user."""
        ...


class ClipUploaderPort(Protocol):
    """Port for video clip upload operations."""

    def upload_clips(
        self, sku: str, item_id: str, sites: list[dict[str, Any]] | None = None
    ) -> Any:
        """Discover, validate, and upload all clips for a SKU.

        Args:
            sku: Product SKU for video discovery
            item_id: Published ML item ID
            sites: Optional list of target sites

        Returns:
            ClipUploadSummary with per-clip results
        """
        ...
