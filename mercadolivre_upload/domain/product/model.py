"""Product domain model."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mercadolivre_upload.domain.fiscal.data import FiscalData


@dataclass
class Product:
    """Product domain entity.

    Pure business object with no external dependencies.
    """

    sku: str
    title: str
    description: str
    price: float
    available_quantity: int
    condition: str  # "new" or "used"
    fiscal: FiscalData
    attributes: dict[str, str] = field(default_factory=dict)
    clip_file_path: Path | None = None  # New field for video file path
    clip_uuid: str | None = None  # New field for clip UUID

    def __post_init__(self):  # type: ignore[no-untyped-def]
        """Validate product data."""
        if self.condition not in ("new", "used"):
            raise ValueError("Condition must be 'new' or 'used'")
        if self.price < 0:
            raise ValueError("Price cannot be negative")
        if self.available_quantity < 0:
            raise ValueError("Quantity cannot be negative")

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "sku": self.sku,
            "title": self.title,
            "description": self.description,
            "price": self.price,
            "available_quantity": self.available_quantity,
            "condition": self.condition,
            "fiscal": self.fiscal.to_dict(),
            "attributes": self.attributes,
            "clip_file_path": (
                str(self.clip_file_path) if self.clip_file_path else None
            ),  # Include clip_file_path
            "clip_uuid": self.clip_uuid,  # Include clip_uuid
        }

    def get_attribute(self, name: str, default: str | None = None) -> str | None:
        """Get attribute value."""
        return self.attributes.get(name, default)

    def set_attribute(self, name: str, value: str) -> None:
        """Set attribute value."""
        self.attributes[name] = value
