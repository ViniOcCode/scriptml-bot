"""Shipping builder for ML items."""

from typing import Any


class ShippingBuilder:
    """Builds shipping configuration for ML items."""

    def __init__(self, config: dict[str, Any] | None = None):
        """Initialize with optional shipping config."""
        self.config = config or {}

    def build(self, mode: str | None = None) -> dict[str, Any]:
        """Build shipping config."""
        defaults = self.config.get("shipping", {})

        return {
            "mode": mode or defaults.get("mode", "me2"),
            "local_pick_up": defaults.get("local_pick_up", False),
            "free_shipping": defaults.get("free_shipping", False),
        }
