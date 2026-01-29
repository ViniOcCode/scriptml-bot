"""Structural validation layer."""

import logging
import re
from dataclasses import dataclass, field
from typing import Optional

from ..attribute_metadata import AttributeMeta

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """Result of structural validation."""

    valid: bool
    blocking_errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    sanitized_attrs: list[dict] = field(default_factory=list)


class StructuralValidator:
    """Validates attributes against structural rules.

    Blocks payloads that will never be accepted by the API.
    """

    def __init__(self, attribute_metadata: list[AttributeMeta]):
        self.metadata = {attr.id: attr for attr in attribute_metadata}

    def validate(self, attributes: list[dict]) -> ValidationResult:
        """Validate attributes against structural rules.

        Args:
            attributes: List of attribute dicts with 'id' and 'value_name' keys

        Returns:
            ValidationResult with valid flag, errors, warnings, and sanitized attrs
        """
        blocking_errors = []
        warnings = []
        sanitized_attrs = []

        # Track required attributes
        required_ids = {attr.id for attr in self.metadata.values() if attr.required}
        provided_ids = set()

        for attr in attributes:
            attr_id = attr.get("id")
            value = attr.get("value_name")

            if not attr_id:
                warnings.append(f"Attribute missing ID: {attr}")
                continue

            provided_ids.add(attr_id)

            # Unknown attribute
            if attr_id not in self.metadata:
                msg = f"Unknown attribute '{attr_id}' - dropping"
                warnings.append(msg)
                logger.warning(msg)
                continue

            meta = self.metadata[attr_id]

            # Value type mismatch
            if value and not meta.validate_type(value):
                msg = f"Attribute '{attr_id}': value type mismatch ({meta.value_type}) - dropping"
                warnings.append(msg)
                logger.warning(msg)
                continue

            # Value not in allowed domain
            if value and meta.allowed_values and not meta.allows_value(value):
                msg = f"Attribute '{attr_id}': value '{value}' not in allowed domain - dropping"
                warnings.append(msg)
                logger.warning(msg)
                continue

            # Exceeds max_length
            truncated_value = value
            if value and meta.max_length and len(value) > meta.max_length:
                truncated_value = value[:meta.max_length]
                msg = f"Attribute '{attr_id}': truncated from {len(value)} to {meta.max_length} chars"
                warnings.append(msg)
                logger.warning(msg)

            # Validation pattern
            if value and meta.validation_pattern:
                if not re.match(meta.validation_pattern, str(value)):
                    msg = f"Attribute '{attr_id}': value '{value}' doesn't match pattern - dropping"
                    warnings.append(msg)
                    logger.warning(msg)
                    continue

            # Keep the (possibly truncated) attribute
            sanitized_attr = dict(attr)
            if truncated_value != value:
                sanitized_attr["value_name"] = truncated_value
            sanitized_attrs.append(sanitized_attr)

        # Check for missing required attributes
        missing_required = required_ids - provided_ids
        if missing_required:
            for attr_id in missing_required:
                msg = f"Missing required attribute '{attr_id}'"
                blocking_errors.append(msg)
                logger.error(msg)

        # Determine validity
        valid = len(blocking_errors) == 0

        return ValidationResult(
            valid=valid,
            blocking_errors=blocking_errors,
            warnings=warnings,
            sanitized_attrs=sanitized_attrs,
        )
