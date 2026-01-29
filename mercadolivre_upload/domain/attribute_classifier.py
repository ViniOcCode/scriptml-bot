"""Attribute classification by behavior."""

from .attribute_metadata import AttributeMeta


# Classification categories
CLASS_EDITORIAL = "editorial"   # Descriptive attributes (title-like)
CLASS_TECHNICAL = "technical"   # Product specifications
CLASS_COMMERCIAL = "commercial"  # Warranty, pricing, terms
CLASS_LOGISTICS = "logistics"   # Shipping, packaging


class AttributeClassifier:
    """Classifies attributes by their behavior, not by category."""

    # ID patterns for logistics attributes
    LOGISTICS_PATTERNS = {
        "SELLER", "PACKAGE", "SHIPPING", "WEIGHT",
        "DIMENSION", "LENGTH", "WIDTH", "HEIGHT",
        "DIMENSIONS", "SIZE_CM"
    }

    # ID patterns for commercial attributes
    COMMERCIAL_PATTERNS = {
        "WARRANTY", "GARANTIA", "PRICE", "DISCOUNT",
        "PAYMENT", "FINANCING", "INSTALLMENTS", "COST"
    }

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
        if any(pattern in attr_id for pattern in self.LOGISTICS_PATTERNS):
            return CLASS_LOGISTICS
        if any(pattern in attr_name for pattern in self.LOGISTICS_PATTERNS):
            return CLASS_LOGISTICS

        # Check for commercial patterns
        if any(pattern in attr_id for pattern in self.COMMERCIAL_PATTERNS):
            return CLASS_COMMERCIAL
        if any(pattern in attr_name for pattern in self.COMMERCIAL_PATTERNS):
            return CLASS_COMMERCIAL

        # Editorial: string/boolean with high relevance
        if attr.value_type in ("string", "boolean"):
            if attr.relevance and attr.relevance > 0.5:
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
        result = {
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
