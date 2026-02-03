"""Data models for Excel parser."""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class FiscalData:
    """Fiscal data for Brazilian tax requirements.

    Attributes:
        ncm: NCM code (Nomenclatura Comum do Mercosul)
        cfop: CFOP code (Código Fiscal de Operações e Prestações)
        origin: Product origin state or country code
        cest: CEST code (Código Especificador da Substituição Tributária), optional
    """

    ncm: str
    cfop: str
    origin: str
    cest: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for API payload."""
        result = {
            "ncm": self.ncm,
            "cfop": self.cfop,
            "origin": self.origin,
        }
        if self.cest:
            result["cest"] = self.cest
        return result


@dataclass
class Product:
    """Product data for Mercado Livre publication.

    Attributes:
        sku: Product SKU (unique identifier)
        title: Product title
        description: Product description
        price: Product price (numeric)
        available_quantity: Stock quantity
        condition: Product condition ("new" or "used")
        fiscal: Fiscal data for taxes
        attributes: Additional product attributes from extra columns
    """

    sku: str
    title: str
    description: str
    price: float
    available_quantity: int
    condition: str
    fiscal: FiscalData
    attributes: dict[str, str] = field(default_factory=dict)

    def __post_init__(self):
        """Validate product data after initialization."""
        # Validate condition
        if self.condition not in ("new", "used"):
            raise ValueError(f"Condition must be 'new' or 'used', got '{self.condition}'")

        # Validate price
        if self.price < 0:
            raise ValueError(f"Price cannot be negative: {self.price}")

        # Validate quantity
        if self.available_quantity < 0:
            raise ValueError(f"Quantity cannot be negative: {self.available_quantity}")

    def to_dict(self) -> dict:
        """Convert to dictionary for API payload."""
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
        """Get an attribute value by name."""
        return self.attributes.get(name, default)
