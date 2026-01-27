"""Fiscal data domain model."""

from dataclasses import dataclass
from typing import Optional


@dataclass
class FiscalData:
    """Fiscal data for products.

    Stores NCM, CFOP, origin, and CEST information.
    """

    ncm: str
    cfop: str
    origin: str
    cest: Optional[str] = None

    def __post_init__(self):
        """Normalize fiscal data."""
        self.ncm = str(self.ncm).strip() if self.ncm else ""
        self.cfop = str(self.cfop).strip() if self.cfop else ""
        self.origin = str(self.origin).strip() if self.origin else ""
        self.cest = str(self.cest).strip() if self.cest else None

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        result = {
            "ncm": self.ncm,
            "cfop": self.cfop,
            "origin": self.origin,
        }
        if self.cest:
            result["cest"] = self.cest
        return result

    @property
    def is_valid(self) -> bool:
        """Check if required fields are present."""
        return bool(self.ncm and self.cfop and self.origin)
