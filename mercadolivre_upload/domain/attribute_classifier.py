"""Attribute classification by behavior."""

import logging
from pathlib import Path
from typing import Any

import yaml

from .attribute_metadata import AttributeMeta

logger = logging.getLogger(__name__)


# Classification categories
CLASS_EDITORIAL = "editorial"  # Descriptive attributes (title-like)
CLASS_TECHNICAL = "technical"  # Product specifications
CLASS_COMMERCIAL = "commercial"  # Warranty, pricing, terms
CLASS_LOGISTICS = "logistics"  # Shipping, packaging


def _load_yaml_config(primary: Path, fallback: Path | None = None) -> dict[str, Any]:
    """Load YAML config with optional fallback."""
    for path in (primary, fallback):
        if path and path.exists():
            with open(path, encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
    return {}


def _load_classification_config() -> dict[str, Any]:
    """Load attribute classification patterns from config file.

    Returns:
        Dictionary with logistics_patterns and commercial_patterns
    """
    try:
        config = _load_yaml_config(
            Path("config/attribute_rules.yaml"), Path("config/generic_mappings.yaml")
        )

        classification_config = config.get("attribute_classification", {})

        return {
            "logistics_patterns": set(classification_config.get("logistics_patterns", [])),
            "commercial_patterns": set(classification_config.get("commercial_patterns", [])),
        }
    except Exception as e:
        logger.warning(f"Could not load classification config: {e}. Using empty patterns.")
        return {
            "logistics_patterns": set(),
            "commercial_patterns": set(),
        }


class AttributeClassifier:
    """Classifies attributes by their behavior, not by category.

    Uses configuration from config/attribute_rules.yaml as the single source of truth.
    """

    def __init__(self, config: dict[str, Any] | None = None):
        """Initialize the classifier.

        Args:
            config: Optional custom config to override file-based config
        """
        # Load from config (single source of truth), allow override
        if config:
            self.logistics_patterns = set(config.get("logistics_patterns", []))
            self.commercial_patterns = set(config.get("commercial_patterns", []))
        else:
            classification_config = _load_classification_config()
            self.logistics_patterns = classification_config["logistics_patterns"]
            self.commercial_patterns = classification_config["commercial_patterns"]

    def classify(self, attr: AttributeMeta) -> str:
        """Classify an attribute by its behavior.

        Args:
            attr: Attribute metadata to classify

        Returns:
            Classification string (editorial, technical, commercial, logistics)
        """
        attr_id = attr.id.upper()
        attr_name = attr.name.upper()

        # Check for logistics patterns
        if any(pattern in attr_id for pattern in self.logistics_patterns):
            return CLASS_LOGISTICS
        if any(pattern in attr_name for pattern in self.logistics_patterns):
            return CLASS_LOGISTICS

        # Check for commercial patterns
        if any(pattern in attr_id for pattern in self.commercial_patterns):
            return CLASS_COMMERCIAL
        if any(pattern in attr_name for pattern in self.commercial_patterns):
            return CLASS_COMMERCIAL

        # Editorial: string/boolean with high relevance
        if attr.value_type in ("string", "boolean") and attr.relevance and attr.relevance > 0.5:
            return CLASS_EDITORIAL

        # Default to technical (product specifications)
        return CLASS_TECHNICAL

    def classify_all(self, attrs: list[AttributeMeta]) -> dict[str, list[AttributeMeta]]:
        """Classify a list of attributes into categories.

        Args:
            attrs: List of attribute metadata

        Returns:
            Dictionary mapping classification to list of attributes
        """
        result = {  # type: ignore[var-annotated]
            CLASS_EDITORIAL: [],
            CLASS_TECHNICAL: [],
            CLASS_COMMERCIAL: [],
            CLASS_LOGISTICS: [],
        }

        for attr in attrs:
            classification = self.classify(attr)
            result[classification].append(attr)

        return result

    def is_logistics(self, attr: AttributeMeta) -> bool:
        """Check if attribute is logistics-related."""
        return self.classify(attr) == CLASS_LOGISTICS

    def is_commercial(self, attr: AttributeMeta) -> bool:
        """Check if attribute is commercial-related."""
        return self.classify(attr) == CLASS_COMMERCIAL

    def is_editorial(self, attr: AttributeMeta) -> bool:
        """Check if attribute is editorial (descriptive)."""
        return self.classify(attr) == CLASS_EDITORIAL

    def is_technical(self, attr: AttributeMeta) -> bool:
        """Check if attribute is technical (specification)."""
        return self.classify(attr) == CLASS_TECHNICAL


def classify_attribute(attr: AttributeMeta) -> str:
    """Convenience function to classify a single attribute."""
    classifier = AttributeClassifier()
    return classifier.classify(attr)
