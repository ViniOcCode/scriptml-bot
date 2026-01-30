"""Attribute sanitization layer."""

import logging
from difflib import SequenceMatcher
from typing import Optional

from ..attribute_classifier import AttributeClassifier, CLASS_EDITORIAL
from .scoring import ScoredAttribute

logger = logging.getLogger(__name__)


class AttributeSanitizer:
    """Drops attributes that increase rejection risk or add noise.
    
    NOTE: This sanitizer is intentionally conservative. We preserve most
    attributes because Mercado Livre's API accepts them. Only drop:
    - Very low quality attributes (score < threshold)
    - Truly redundant values (nearly identical text)
    
    We do NOT drop:
    - Optional logistics (HEIGHT, WIDTH, WEIGHT are important for shipping)
    - Editorial attributes (they provide useful product info)
    """

    SIMILARITY_THRESHOLD = 0.9  # Higher threshold - only drop nearly identical

    # Attributes that should never be dropped (important for ML API)
    PROTECTED_ATTRIBUTES = {
        # Dimensions - important for shipping calculations
        "HEIGHT", "WIDTH", "LENGTH", "WEIGHT",
        "SELLER_PACKAGE_HEIGHT", "SELLER_PACKAGE_WIDTH", "SELLER_PACKAGE_LENGTH", "SELLER_PACKAGE_WEIGHT",
        # Product identifiers
        "GTIN", "ISBN", "SELLER_SKU",
        # Important product features
        "WITH_AUGMENTED_REALITY", "IS_WRITTEN_IN_CAPITAL_LETTERS",
        "WITH_COLORING_PAGES", "WITH_INDEX",
        # Book-specific
        "PAGES_NUMBER", "BOOKS_NUMBER_PER_SET", "BOOK_SIZE",
    }

    def __init__(self, min_score: int = 40):  # Lower threshold to keep more
        self.min_score = min_score
        self.classifier = AttributeClassifier()

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
            # Never drop protected attributes
            if attr.id in self.PROTECTED_ATTRIBUTES:
                logger.debug(f"Keeping protected attribute {attr.id}")
                result.append(attr)
                seen_values[attr.value.lower()] = attr.id
                continue

            # Drop low-score attributes (but keep protected ones above)
            if attr.score < self.min_score:
                logger.debug(
                    f"Dropping {attr.id}: score {attr.score} < {self.min_score}"
                )
                continue

            # Drop only truly redundant editorial attributes
            if attr.classification == CLASS_EDITORIAL and self._is_redundant(
                attr, seen_values
            ):
                logger.debug(f"Dropping redundant editorial {attr.id}")
                continue

            # Keep all logistics attributes (they're important for shipping)
            # The old code dropped optional logistics but we want to keep them
            if attr.classification == "logistics":
                logger.debug(f"Keeping logistics attribute {attr.id}")

            result.append(attr)
            seen_values[attr.value.lower()] = attr.id

        logger.info(f"Sanitized {len(scored_attrs)} -> {len(result)} attributes")
        return result

    def _is_redundant(
        self, attr: ScoredAttribute, seen_values: dict[str, str]
    ) -> bool:
        """Check for semantic similarity with already-kept attributes."""
        val_lower = attr.value.lower()

        for seen_val, seen_id in seen_values.items():
            similarity = SequenceMatcher(None, val_lower, seen_val).ratio()
            if similarity > self.SIMILARITY_THRESHOLD:
                logger.debug(
                    f"Redundant: '{attr.id}' (score {attr.score}) similar to "
                    f"'{seen_id}' ({similarity:.2f})"
                )
                return True

        return False

    def adjust_threshold(self, threshold: int) -> None:
        """Adjust the minimum score threshold."""
        self.min_score = threshold

    def get_dropped_reason(
        self, attr: ScoredAttribute
    ) -> Optional[str]:
        """Get the reason an attribute would be dropped."""
        if attr.score < self.min_score:
            return f"score too low ({attr.score} < {self.min_score})"

        if attr.classification == "logistics" and not attr.meta.required:
            return "optional logistics"

        return None
