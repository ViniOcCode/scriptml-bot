"""Seller policy validator.

Validates payload dicts against per-seller business rules loaded from publisher.yaml.
Pure business logic — no API calls.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration models (Pydantic v2)
# ---------------------------------------------------------------------------


class ListingConfig(BaseModel):
    """Listing type restrictions for this seller."""

    model_config = ConfigDict(extra="forbid")

    allowed_types: list[str]
    default_type: str


class PricingConfig(BaseModel):
    """Price range constraints for this seller."""

    model_config = ConfigDict(extra="forbid")

    min_price: float
    max_price: float


class CategoriesConfig(BaseModel):
    """Category-level restrictions and overrides."""

    model_config = ConfigDict(extra="forbid")

    blocked: list[str] = Field(default_factory=list)
    overrides: dict[str, str] = Field(default_factory=dict)


class BatchConfig(BaseModel):
    """Batch publishing safety settings."""

    model_config = ConfigDict(extra="forbid")

    human_review_required: bool = True
    publish_inactive: bool = False
    min_ai_confidence: float = 0.0  # 0.0 = disabled; e.g. 0.70 blocks AI categories < 70%


class SellerConfig(BaseModel):
    """Top-level seller configuration loaded from seller.yaml."""

    model_config = ConfigDict(extra="forbid")

    listing: ListingConfig
    pricing: PricingConfig
    categories: CategoriesConfig = Field(default_factory=CategoriesConfig)
    batch: BatchConfig = Field(default_factory=BatchConfig)


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
    """Load and validate publisher.yaml.

    Args:
        path: Path to publisher.yaml.

    Returns:
        Validated SellerConfig instance.

    Raises:
        FileNotFoundError: If path does not exist.
        pydantic.ValidationError: If YAML content fails schema validation.
    """
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"Publisher config must contain a mapping: {path}")

    # Support both top-level keys and nested under "seller:", but forbid mixed top-level ownership.
    if "seller" in raw:
        extra_top_level = sorted(set(raw.keys()) - {"seller"})
        if extra_top_level:
            raise ValueError(
                "Publisher config contains unsupported top-level fields: "
                + ", ".join(extra_top_level)
            )
        seller_raw = raw["seller"]
    else:
        seller_raw = raw
    if not isinstance(seller_raw, dict):
        raise ValueError(f"Publisher config seller section must be a mapping: {path}")
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
# Helpers
# ---------------------------------------------------------------------------


def _effective_price(payload: dict[str, Any]) -> float:
    """Return effective price for policy checks.

    For variation items, uses the minimum variation price (most conservative
    check — ensures every variation meets the floor).
    Returns 0.0 when no price can be determined anywhere.
    """
    root_price = payload.get("price")
    if root_price is not None:
        return float(root_price)
    variations: list[dict[str, Any]] = payload.get("variations") or []
    prices = [float(v["price"]) for v in variations if v.get("price") is not None]
    return min(prices) if prices else 0.0


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
        category_confidence: float | None = None,
    ) -> PolicyResult:
        """Validate payload against seller rules.

        Args:
            payload: Item payload dict (without _meta).
            ai_suggested: Whether the category was suggested by AI.
            category_confidence: AI confidence score (0.0–1.0); None = not available.

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

        # Price range checks — for variation items, use minimum variation price
        price = _effective_price(payload)
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
                        "Defina review evidence no run_manifest.json ou "
                        "human_review_required: false em publisher.yaml"
                    ),
                    severity="error",
                )
            )

        # AI confidence threshold check
        min_conf = self._config.batch.min_ai_confidence
        confidence = category_confidence if category_confidence is not None else 0.0
        if ai_suggested and min_conf > 0.0 and confidence < min_conf:
            violations.append(
                PolicyViolation(
                    field="category_id",
                    message=(
                        f"Confiança da categoria IA {confidence:.1%} abaixo do mínimo "
                        f"configurado {min_conf:.1%}. Revise a categoria manualmente."
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
