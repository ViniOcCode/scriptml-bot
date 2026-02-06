"""Attribute builder utilities."""


class AttributeBuilder:
    """Builds Mercado Livre attribute payloads for tests and compatibility."""

    def __init__(self) -> None:
        self._attributes: list[dict] = []

    def add_attribute(
        self, attr_id: str, value: object, name: str | None = None
    ) -> "AttributeBuilder":
        """Add a generic attribute."""
        attribute = {"id": str(attr_id).upper(), "value_name": str(value)}
        if name:
            attribute["name"] = name
        self._attributes.append(attribute)
        return self

    def add_brand(self, value: object) -> "AttributeBuilder":
        """Add brand attribute."""
        return self.add_attribute("BRAND", value, "Marca")

    def add_model(self, value: object) -> "AttributeBuilder":
        """Add model attribute."""
        return self.add_attribute("MODEL", value, "Modelo")

    def add_gtin(self, value: object) -> "AttributeBuilder":
        """Add GTIN attribute."""
        return self.add_attribute("GTIN", value, "Código de barras")

    def add_from_dict(self, attributes: dict) -> "AttributeBuilder":
        """Add multiple attributes from a dictionary."""
        for key, value in attributes.items():
            if value is None:
                continue
            if isinstance(value, str) and not value.strip():
                continue
            self.add_attribute(str(key).upper(), value)
        return self

    def build(self) -> list[dict]:
        """Return a copy of built attributes."""
        return [attr.copy() for attr in self._attributes]

    def clear(self) -> "AttributeBuilder":
        """Clear the builder state."""
        self._attributes = []
        return self
