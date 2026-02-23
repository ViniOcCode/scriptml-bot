"""Semantic scoring engine for attributes."""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mercadolivre_upload.shared.utils.config_loader import load_yaml_config

from ..attribute_classifier import (
    CLASS_LOGISTICS,
    AttributeClassifier,
)
from ..attribute_metadata import AttributeMeta

logger = logging.getLogger(__name__)


def _load_scoring_config() -> dict[str, Any]:
    """Load scoring configuration from config file.

    Returns:
        Dictionary with scoring weights and thresholds
    """
    try:
        config = load_yaml_config(
            Path("config/attribute_rules.yaml"), Path("config/generic_mappings.yaml")
        )

        scoring_config = config.get("scoring", {})

        return {
            "base_score": scoring_config.get("base_score", 100),
            "penalties": scoring_config.get("penalties", {}),
            "bonuses": scoring_config.get("bonuses", {}),
            "min_score": scoring_config.get("min_score", 40),
        }
    except (OSError, TypeError, ValueError) as e:
        logger.warning(f"Could not load scoring config: {e}. Using defaults.")
        return {
            "base_score": 100,
            "penalties": {
                "optional_attribute": 10,
                "low_relevance": 20,
                "value_not_allowed": 30,
                "free_text_leakage": 40,
                "logistics_attribute": 50,
            },
            "bonuses": {
                "required_attribute": 20,
                "high_relevance": 10,
            },
            "min_score": 40,
        }


@dataclass
class ScoredAttribute:
    """Attribute with semantic score."""

    id: str
    value: str
    score: int
    classification: str
    meta: AttributeMeta


class SemanticScorer:
    """Estimates how safe an attribute is to send.

    Uses configuration from config/attribute_rules.yaml as the single source of truth.
    """

    def __init__(
        self, attribute_metadata: list[AttributeMeta], config: dict[str, Any] | None = None
    ):
        """Initialize the scorer.

        Args:
            attribute_metadata: List of attribute metadata
            config: Optional custom config to override file-based config
        """
        self.metadata = {attr.id: attr for attr in attribute_metadata}
        self.classifier = AttributeClassifier()

        # Load scoring weights from config (single source of truth), allow override
        if config:
            self.scoring_config = config.get("scoring", {})
        else:
            self.scoring_config = _load_scoring_config()

    def score_attribute(self, attr_id: str, value: str) -> ScoredAttribute:
        """Calculate semantic score for an attribute.

        Args:
            attr_id: Attribute ID
            value: Attribute value

        Returns:
            ScoredAttribute with score and classification
        """
        meta = self.metadata.get(attr_id)

        if not meta:
            # Unknown attribute
            return ScoredAttribute(
                id=attr_id,
                value=value,
                score=0,
                classification="unknown",
                meta=AttributeMeta(
                    id=attr_id,
                    name=attr_id,
                    value_type="string",
                    required=False,
                ),
            )

        # Get scoring weights from config
        base_score = self.scoring_config.get("base_score", 100)
        penalties = self.scoring_config.get("penalties", {})
        bonuses = self.scoring_config.get("bonuses", {})

        score = base_score
        classification = self.classifier.classify(meta)

        # Penalty: Optional attribute
        if not meta.required:
            score -= penalties.get("optional_attribute", 10)

        # Penalty: Low relevance
        if meta.relevance and meta.relevance < 0.3:
            score -= penalties.get("low_relevance", 20)

        # Ensure value is a string for downstream processing
        if value is None:
            safe_value = ""
        else:
            try:
                safe_value = str(value)
            except Exception:
                safe_value = ""

        # Penalty: Value outside allowed domain
        if meta.allowed_values and safe_value not in meta.allowed_values:
            score -= penalties.get("value_not_allowed", 30)
            penalty = penalties.get("value_not_allowed", 30)
            logger.warning(
                f"Value '{safe_value}' not in allowed values for {attr_id}, score -{penalty}"
            )

        # Penalty: Free-text semantic leakage
        if self._is_free_text(safe_value) and self._looks_out_of_context(safe_value, meta):
            score -= penalties.get("free_text_leakage", 40)
            penalty = penalties.get("free_text_leakage", 40)
            logger.warning(f"Possible semantic leakage in {attr_id}, score -{penalty}")

        # Penalty: Aggressive logistics data
        if classification == CLASS_LOGISTICS:
            score -= penalties.get("logistics_attribute", 50)
            logger.debug(
                f"Logistics attribute {attr_id}, score -{penalties.get('logistics_attribute', 50)}"
            )

        # Bonus: Required attribute
        if meta.required:
            score += bonuses.get("required_attribute", 20)

        # Bonus: High relevance
        if meta.relevance and meta.relevance > 0.8:
            score += bonuses.get("high_relevance", 10)

        final_score = max(0, min(100, score))

        return ScoredAttribute(
            id=attr_id,
            value=safe_value,
            score=final_score,
            classification=classification,
            meta=meta,
        )

    def _is_free_text(self, value: str) -> bool:
        """Check if value looks like free text (not enum).

        Be defensive about input types: coerce to str before inspection so numeric
        or other non-string values don't cause TypeError when using len()/lower().
        """
        if value is None:
            return False

        try:
            value_str = str(value).strip()
        except Exception:
            return False

        if not value_str:
            return False

        # Long values suggest free text
        if len(value_str) > 50:
            return True

        # Multiple sentences
        sentences = value_str.split(".")
        if len(sentences) > 1:
            return True

        # Contains descriptive words
        descriptive_words = [
            "com",
            "para",
            "em",
            "de",
            "para",
            "como",
            "with",
            "for",
            "in",
            "on",
            "and",
            "or",
        ]
        words = value_str.lower().split()
        return sum(1 for w in words if w in descriptive_words) > 2

    def _looks_out_of_context(self, value: str, meta: AttributeMeta) -> bool:
        """Check if free text value looks out of context for attribute.

        Coerce non-string values to str before analysis to avoid TypeError
        and ensure consistent behavior across value types.
        """
        try:
            value_str = str(value)
        except Exception:
            return False

        value_str.lower()
        attr_name = meta.name.lower()

        # Check for obvious mismatches
        # Example: value describing a TV when attribute is about headphones

        # If value contains many category-specific words not related to attr
        # Long descriptions in non-editorial attributes
        return (
            len(value_str) > 30
            and "marca" not in attr_name
            and "modelo" not in attr_name
            and meta.value_type == "string"
        )

    def score_all(self, attributes: list[dict[str, Any]]) -> list[ScoredAttribute]:
        """Score all attributes.

        Args:
            attributes: List of attribute dicts with 'id' and 'value_name' keys

        Returns:
            List of ScoredAttribute objects
        """
        return [
            self.score_attribute(attr.get("id", ""), attr.get("value_name", ""))
            for attr in attributes
        ]
