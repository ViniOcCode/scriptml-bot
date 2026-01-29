"""Attribute sanitization layer."""

import logging
from difflib import SequenceMatcher
from typing import Optional

from ..attribute_classifier import AttributeClassifier, CLASS_EDITORIAL
from .scoring import ScoredAttribute

logger = logging.getLogger(__name__)


class AttributeSanitizer:
    """Drops attributes that increase rejection risk or add noise."""

    SIMILARITY_THRESHOLD = 0.8

    def __init__(self, min_score: int = 50):
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
            # Drop low-score attributes
            if attr.score < self.min_score:
                logger.warning(
                    f"Dropping {attr.id}: score {attr.score} < {self.min_score}"
                )
                continue

            # Drop redundant editorial attributes
            if attr.classification == CLASS_EDITORIAL and self._is_redundant(
                attr, seen_values
            ):
                logger.warning(f"Dropping redundant editorial {attr.id}")
                continue

            # Drop non-required logistics
            if attr.classification == "logistics" and not attr.meta.required:
                logger.warning(f"Dropping optional logistics {attr.id}")
                continue

            result.append(attr)
            seen_values[attr.value.lower()] = attr.id

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
