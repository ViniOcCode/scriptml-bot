"""Validation feedback loop for learning from errors."""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from .scoring import ScoredAttribute

logger = logging.getLogger(__name__)


class ValidationFeedback:
    """Records validation outcomes for pattern analysis and scoring adjustment."""

    def __init__(self, feedback_file: str = "feedback_log.json"):
        self.feedback_file = Path(feedback_file)
        self.feedback = self._load_feedback()

    def _load_feedback(self) -> list[dict]:
        """Load existing feedback from file."""
        if self.feedback_file.exists():
            try:
                with open(self.feedback_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                logger.error(f"Failed to load feedback: {e}")
                return []
        return []

    def _save_feedback(self) -> None:
        """Save feedback to file."""
        try:
            with open(self.feedback_file, "w", encoding="utf-8") as f:
                json.dump(self.feedback, f, indent=2, ensure_ascii=False)
        except IOError as e:
            logger.error(f"Failed to save feedback: {e}")

    def record_validation_result(
        self,
        sku: str,
        attributes: list[dict],
        validation_response: dict,
    ) -> None:
        """Record validation outcome for pattern analysis.

        Args:
            sku: Product SKU
            attributes: List of attributes sent
            validation_response: ML API validation response
        """
        causes = validation_response.get("cause", [])

        if not causes:
            # Record success
            self.feedback.append({
                "sku": sku,
                "timestamp": datetime.now().isoformat(),
                "cause_code": None,
                "cause_type": "success",
                "attribute_id": None,
                "message": "Validation passed",
            })
        else:
            for cause in causes:
                self.feedback.append({
                    "sku": sku,
                    "timestamp": datetime.now().isoformat(),
                    "cause_code": cause.get("code"),
                    "cause_type": cause.get("type"),
                    "attribute_id": self._extract_attribute_id(cause.get("message", "")),
                    "message": cause.get("message"),
                })

        self._save_feedback()
        logger.debug(f"Recorded feedback for {sku}")

    def _extract_attribute_id(self, message: str) -> Optional[str]:
        """Extract attribute ID from error message."""
        # Common patterns in ML validation errors
        # Example: "Attribute [BRAND] is required"
        import re

        patterns = [
            r"Attribute \[(\w+)\]",
            r"attribute\s+\[(\w+)\]",
            r"attribute\s+(\w+)",
        ]

        for pattern in patterns:
            match = re.search(pattern, message, re.IGNORECASE)
            if match:
                return match.group(1)

        return None

    def get_problematic_attributes(self) -> dict[str, int]:
        """Get attributes that frequently cause errors.

        Returns:
            Dictionary mapping attribute IDs to error counts
        """
        error_counts = {}
        for entry in self.feedback:
            if entry.get("cause_type") in ("error", "warning"):
                attr_id = entry.get("attribute_id")
                if attr_id:
                    error_counts[attr_id] = error_counts.get(attr_id, 0) + 1

        return error_counts

    def adjust_scores(
        self, scored_attrs: list[ScoredAttribute]
    ) -> list[ScoredAttribute]:
        """Adjust scores based on historical feedback.

        Args:
            scored_attrs: List of scored attributes

        Returns:
            Attributes with adjusted scores
        """
        problematic = self.get_problematic_attributes()

        result = []
        for attr in scored_attrs:
            adjusted = ScoredAttribute(
                id=attr.id,
                value=attr.value,
                score=attr.score,
                classification=attr.classification,
                meta=attr.meta,
            )

            if attr.id in problematic:
                # Apply penalty based on error frequency
                penalty = min(50, problematic[attr.id] * 10)
                adjusted.score -= penalty
                logger.warning(
                    f"Feedback penalty for {attr.id}: -{penalty} "
                    f"({problematic[attr.id]} errors)"
                )

            # Ensure score doesn't go below 0
            adjusted.score = max(0, adjusted.score)
            result.append(adjusted)

        return result

    def get_feedback_summary(self) -> dict:
        """Get summary statistics from feedback."""
        total = len(self.feedback)
        errors = sum(1 for e in self.feedback if e.get("cause_type") == "error")
        warnings = sum(1 for e in self.feedback if e.get("cause_type") == "warning")
        successes = sum(1 for e in self.feedback if e.get("cause_type") == "success")

        return {
            "total_entries": total,
            "errors": errors,
            "warnings": warnings,
            "successes": successes,
            "problematic_attributes": self.get_problematic_attributes(),
        }

    def clear_feedback(self) -> None:
        """Clear all feedback data."""
        self.feedback = []
        self._save_feedback()
        logger.info("Cleared feedback log")
