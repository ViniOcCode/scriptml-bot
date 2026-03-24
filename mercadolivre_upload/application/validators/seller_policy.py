"""Seller policy validator.

Validates payload dicts against per-seller business rules loaded from seller.yaml.
Pure business logic — no API calls.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration models (Pydantic v2)
# ---------------------------------------------------------------------------


class ListingConfig(BaseModel):
    """Listing type restrictions for this seller."""

    allowed_types: list[str]
    default_type: str


class PricingConfig(BaseModel):
    """Price range constraints for this seller."""

    min_price: float
    max_price: float


class CategoriesConfig(BaseModel):
    """Category-level restrictions and overrides."""

    blocked: list[str] = []
    overrides: dict[str, str] = {}


class BatchConfig(BaseModel):
    """Batch publishing safety settings."""

    human_review_required: bool = True
    publish_inactive: bool = False


class SellerConfig(BaseModel):
    """Top-level seller configuration loaded from seller.yaml."""

    listing: ListingConfig
    pricing: PricingConfig
    categories: CategoriesConfig = CategoriesConfig()
    batch: BatchConfig = BatchConfig()


# ---------------------------------------------------------------------------
# Policy result types
# ---------------------------------------------------------------------------


@dataclass
class PolicyViolation:
    """A single policy rule violation."""

    field: str
    message: str
    severity: Literal["error", "warning"]


@dataclass
class PolicyResult:
    """Aggregated result of policy validation."""

    violations: list[PolicyViolation]

    @property
    def has_errors(self) -> bool:
        """Return True if any violation has severity 'error'."""
        return any(v.severity == "error" for v in self.violations)

    @property
    def has_warnings(self) -> bool:
        """Return True if any violation has severity 'warning'."""
        return any(v.severity == "warning" for v in self.violations)


# ---------------------------------------------------------------------------
# Config loader
# ---------------------------------------------------------------------------


def load_seller_config(path: Path) -> SellerConfig:
    """Load and validate seller.yaml.

    Args:
        path: Path to seller.yaml.

    Returns:
        Validated SellerConfig instance.

    Raises:
        FileNotFoundError: If path does not exist.
        pydantic.ValidationError: If YAML content fails schema validation.
    """
    raw: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    # Support both top-level keys and nested under "seller:"
    seller_raw = raw.get("seller", raw)
    return SellerConfig.model_validate(seller_raw)


def default_seller_config() -> SellerConfig:
    """Return a permissive SellerConfig for environments without seller.yaml."""
    return SellerConfig(
        listing=ListingConfig(
            allowed_types=[
                "gold_special",
                "gold_pro",
                "gold_premium",
                "gold",
                "silver",
                "bronze",
                "free",
            ],
            default_type="gold_special",
        ),
        pricing=PricingConfig(min_price=0.01, max_price=999_999.00),
    )


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------


class SellerPolicyValidator:
    """Validates a payload dict against the seller's policy rules.

    Does not call any external APIs — purely local business rule evaluation.
    """

    def __init__(self, config: SellerConfig) -> None:
        """Initialize with a validated SellerConfig."""
        self._config = config

    def validate(
        self,
        payload: dict[str, Any],
        *,
        ai_suggested: bool = False,
    ) -> PolicyResult:
        """Validate payload against seller rules.

        Args:
            payload: Item payload dict (without _meta).
            ai_suggested: Whether the category was suggested by AI.

        Returns:
            PolicyResult with list of violations (may be empty).
        """
        violations: list[PolicyViolation] = []

        # listing_type check
        listing_type = payload.get("listing_type_id", "")
        if listing_type not in self._config.listing.allowed_types:
            violations.append(
                PolicyViolation(
                    field="listing_type_id",
                    message=(
                        f"'{listing_type}' não é permitido para esta conta. "
                        f"Permitidos: {self._config.listing.allowed_types}"
                    ),
                    severity="error",
                )
            )

        # Price range checks
        price = float(payload.get("price", 0))
        if price < self._config.pricing.min_price:
            violations.append(
                PolicyViolation(
                    field="price",
                    message=(
                        f"Preço R${price:.2f} abaixo do mínimo "
                        f"R${self._config.pricing.min_price:.2f}"
                    ),
                    severity="error",
                )
            )
        if price > self._config.pricing.max_price:
            violations.append(
                PolicyViolation(
                    field="price",
                    message=(
                        f"Preço R${price:.2f} acima do máximo "
                        f"R${self._config.pricing.max_price:.2f}"
                    ),
                    severity="warning",
                )
            )

        # Blocked category check
        category_id = payload.get("category_id", "")
        if category_id in self._config.categories.blocked:
            violations.append(
                PolicyViolation(
                    field="category_id",
                    message=f"Categoria {category_id} bloqueada para este seller",
                    severity="error",
                )
            )

        # AI-suggested category without human review
        if ai_suggested and self._config.batch.human_review_required:
            violations.append(
                PolicyViolation(
                    field="category_id",
                    message=(
                        "Categoria sugerida por IA não foi revisada por humano. "
                        "Defina human_reviewed: true em batch_manifest.json ou "
                        "human_review_required: false em seller.yaml"
                    ),
                    severity="error",
                )
            )

        return PolicyResult(violations=violations)

    def apply_overrides(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Apply seller.yaml overrides to a copy of the payload.

        Currently applies listing_type_id overrides per category.

        Args:
            payload: Original item payload dict.

        Returns:
            New dict with overrides applied (original is not mutated).
        """
        result = payload.copy()
        category_id = result.get("category_id", "")
        if category_id in self._config.categories.overrides:
            result["listing_type_id"] = self._config.categories.overrides[category_id]
        return result
