"""Attribute metadata models for normalized ML API representation."""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AttributeMeta:
    """Normalized representation of a Mercado Livre attribute."""

    id: str
    name: str
    value_type: str  # "string", "number", "boolean", "list"
    required: bool
    tags: set[str] = field(default_factory=set)
    allowed_values: Optional[set[str]] = None
    relevance: Optional[float] = None  # 0.0 to 1.0 from ML API
    hierarchy: str = "none"  # "parent", "child", "none"
    validation_pattern: Optional[str] = None  # Regex pattern if provided
    max_length: Optional[int] = None
    tooltip: Optional[str] = None  # Help text from ML

    @classmethod
    def from_ml_api(cls, api_data: dict) -> "AttributeMeta":
        """Create AttributeMeta from ML API attribute response."""
        tags = set(api_data.get("tags", {}).keys())

        # Parse allowed values if present
        allowed_values = None
        if "values" in api_data and api_data["values"]:
            allowed_values = {v.get("name", "") for v in api_data["values"] if v.get("name")}

        # Determine hierarchy
        hierarchy = "none"
        if "hierarchy" in api_data:
            hierarchy = api_data["hierarchy"]

        # Extract relevance if available
        relevance = None
        if "relevance" in api_data:
            try:
                relevance = float(api_data["relevance"])
            except (ValueError, TypeError):
                pass

        # Extract validation rules
        validation_pattern = None
        max_length = None
        if "validation_rules" in api_data:
            rules = api_data["validation_rules"]
            if "pattern" in rules:
                validation_pattern = rules["pattern"]
            if "max_length" in rules:
                try:
                    max_length = int(rules["max_length"])
                except (ValueError, TypeError):
                    pass

        return cls(
            id=api_data.get("id", ""),
            name=api_data.get("name", ""),
            value_type=api_data.get("value_type", "string"),
            required="required" in tags or api_data.get("required", False),
            tags=tags,
            allowed_values=allowed_values if allowed_values else None,
            relevance=relevance,
            hierarchy=hierarchy,
            validation_pattern=validation_pattern,
            max_length=max_length,
            tooltip=api_data.get("tooltip"),
        )

    def allows_value(self, value: str) -> bool:
        """Check if a value is allowed for this attribute."""
        if not self.allowed_values:
            return True  # Free-text attribute
        return value in self.allowed_values

    def validate_type(self, value: str) -> bool:
        """Validate value type matches expected type."""
        if self.value_type == "number":
            try:
                float(value)
                return True
            except (ValueError, TypeError):
                return False
        elif self.value_type == "boolean":
            return value.lower() in ("true", "false", "yes", "no", "1", "0", "sim", "não", "nao")
        elif self.value_type == "list":
            # List type usually means selecting from allowed values
            return self.allows_value(value)
        return True  # String type accepts anything

    def __hash__(self) -> int:
        return hash(self.id)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, AttributeMeta):
            return False
        return self.id == other.id
