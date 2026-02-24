"""Attribute sanitization layer."""

import logging
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from mercadolivre_upload.shared.utils.config_loader import load_merged_yaml_config

from ..attribute_classifier import CLASS_EDITORIAL, AttributeClassifier
from .scoring import ScoredAttribute

logger = logging.getLogger(__name__)


def _load_sanitizer_config() -> dict[str, Any]:
    """Load sanitizer configuration with split-over-legacy precedence."""
    try:
        return load_merged_yaml_config(
            Path("config/attribute_rules.yaml"), fallback=Path("config/generic_mappings.yaml")
        )
    except (OSError, TypeError, ValueError) as e:
        logger.warning(f"Could not load sanitizer config: {e}. Using defaults.")
        return {}


def _load_protected_attributes() -> set[str]:
    """Load protected attributes from config file.

    Returns:
        Set of attribute IDs that should never be dropped
    """
    protected = _load_sanitizer_config().get("protected_attributes", [])
    return set(protected) if isinstance(protected, list) else set()


def _load_similarity_threshold() -> float:
    """Load similarity threshold from config file.

    Returns:
        Threshold value for redundancy detection
    """
    try:
        return float(
            _load_sanitizer_config().get("similarity", {}).get("redundancy_threshold", 0.9)
        )
    except (TypeError, ValueError) as e:
        logger.warning(f"Could not load similarity threshold from config: {e}. Using default 0.9.")
        return 0.9


class AttributeSanitizer:
    """Drops attributes that increase rejection risk or add noise.

    Uses configuration from config/attribute_rules.yaml as the single source of truth.

    NOTE: This sanitizer is intentionally conservative. We preserve most
    attributes because Mercado Livre's API accepts them. Only drop:
    - Very low quality attributes (score < threshold)
    - Truly redundant values (nearly identical text)

    We do NOT drop:
    - Optional logistics (HEIGHT, WIDTH, WEIGHT are important for shipping)
    - Editorial attributes (they provide useful product info)
    """

    def __init__(self, min_score: int = 40, config: dict[str, Any] | None = None):
        """Initialize the sanitizer.

        Args:
            min_score: Minimum score threshold for keeping attributes
            config: Optional custom config to override file-based config
        """
        self.min_score = min_score
        self.classifier = AttributeClassifier()

        # Load from config (single source of truth), allow override
        if config:
            self.protected_attributes = set(config.get("protected_attributes", []))
            self.similarity_threshold = config.get("similarity", {}).get(
                "redundancy_threshold", 0.9
            )
        else:
            self.protected_attributes = _load_protected_attributes()
            self.similarity_threshold = _load_similarity_threshold()

    def sanitize(self, scored_attrs: list[ScoredAttribute]) -> list[ScoredAttribute]:
        """Sanitize scored attributes by dropping low-quality data.

        Args:
            scored_attrs: List of scored attributes

        Returns:
            Filtered list of high-quality attributes
        """
        result = []
        seen_values: dict[str, str] = {}  # value -> id

        for attr in scored_attrs:
            can_be_redundant = self._can_be_redundant(attr)

            # Never drop protected attributes
            if attr.id in self.protected_attributes:
                logger.debug(f"Keeping protected attribute {attr.id}")
                result.append(attr)
                if can_be_redundant:
                    seen_values[attr.value.lower()] = attr.id
                continue

            # Drop low-score attributes (but keep protected ones above)
            if attr.score < self.min_score:
                logger.debug(f"Dropping {attr.id}: score {attr.score} < {self.min_score}")
                continue

            # Drop only truly redundant editorial attributes
            if (
                attr.classification == CLASS_EDITORIAL
                and can_be_redundant
                and self._is_redundant(attr, seen_values)
            ):
                logger.debug(f"Dropping redundant editorial {attr.id}")
                continue

            # Keep all logistics attributes (they're important for shipping)
            # The old code dropped optional logistics but we want to keep them
            if attr.classification == "logistics":
                logger.debug(f"Keeping logistics attribute {attr.id}")

            result.append(attr)
            if can_be_redundant:
                seen_values[attr.value.lower()] = attr.id

        logger.info(f"Sanitized {len(scored_attrs)} -> {len(result)} attributes")
        return result

    def _can_be_redundant(self, attr: ScoredAttribute) -> bool:
        """Return whether attribute value should participate in redundancy detection."""
        if attr.meta.value_type in {"boolean", "number", "number_unit"}:
            return False
        if attr.meta.allowed_values:
            return False
        return len(attr.value.strip()) > 4

    def _is_redundant(self, attr: ScoredAttribute, seen_values: dict[str, str]) -> bool:
        """Check for semantic similarity with already-kept attributes."""
        val_lower = attr.value.lower()

        for seen_val, seen_id in seen_values.items():
            similarity = SequenceMatcher(None, val_lower, seen_val).ratio()
            if similarity > self.similarity_threshold:
                logger.debug(
                    f"Redundant: '{attr.id}' (score {attr.score}) similar to "
                    f"'{seen_id}' ({similarity:.2f})"
                )
                return True

        return False

    def adjust_threshold(self, threshold: int) -> None:
        """Adjust the minimum score threshold."""
        self.min_score = threshold

    def get_dropped_reason(self, attr: ScoredAttribute) -> str | None:
        """Get the reason an attribute would be dropped."""
        if attr.score < self.min_score:
            return f"score too low ({attr.score} < {self.min_score})"

        if attr.classification == "logistics" and not attr.meta.required:
            return "optional logistics"

        return None
