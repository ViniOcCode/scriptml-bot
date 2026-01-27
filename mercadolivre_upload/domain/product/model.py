"""Product domain model."""

from dataclasses import dataclass, field
from typing import Optional

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

    def __post_init__(self):
        """Validate product data."""
        if self.condition not in ("new", "used"):
            raise ValueError("Condition must be 'new' or 'used'")
        if self.price < 0:
            raise ValueError("Price cannot be negative")
        if self.available_quantity < 0:
            raise ValueError("Quantity cannot be negative")

    def to_dict(self) -> dict:
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
        }

    def get_attribute(self, name: str, default: Optional[str] = None) -> Optional[str]:
        """Get attribute value."""
        return self.attributes.get(name, default)

    def set_attribute(self, name: str, value: str) -> None:
        """Set attribute value."""
        self.attributes[name] = value
