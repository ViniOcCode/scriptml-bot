"""Variation builder utilities."""

from typing import Any


class VariationBuilder:
    """Builds variation payloads with attribute combinations."""

    def __init__(self) -> None:
        """Initialize with empty variations list."""
        self._variations: list[dict[str, Any]] = []
        self._current: dict[str, Any] | None = None

    def start_variation(
        self, price: float | None = None, qty: int | None = None
    ) -> "VariationBuilder":
        """Start a new variation, saving the current one if present."""
        if self._current is not None:
            self._variations.append(self._current)
        self._current = {}
        if price is not None:
            self._current["price"] = price
        if qty is not None:
            self._current["available_quantity"] = qty
        return self

    def _ensure_current(self) -> dict[str, Any]:
        if self._current is None:
            raise RuntimeError("Nenhuma variação iniciada")
        return self._current

    def add_attribute(
        self, attr_id: str, value: object, name: str | None = None
    ) -> "VariationBuilder":
        """Add attribute to the current variation."""
        current = self._ensure_current()
        current.setdefault("attribute_combinations", [])
        attribute = {"id": str(attr_id).upper(), "value_name": str(value)}
        if name:
            attribute["name"] = name
        current["attribute_combinations"].append(attribute)
        return self

    def add_color(self, value: object) -> "VariationBuilder":
        """Add color attribute."""
        return self.add_attribute("COLOR", value, "Cor")

    def add_size(self, value: object) -> "VariationBuilder":
        """Add size attribute."""
        return self.add_attribute("SIZE", value, "Tamanho")

    def add_picture(self, picture_id: str) -> "VariationBuilder":
        """Add picture ID to the current variation."""
        current = self._ensure_current()
        current.setdefault("picture_ids", [])
        current["picture_ids"].append(picture_id)
        return self

    def build(self) -> list[dict[str, Any]]:
        """Return the built variations."""
        if self._current is not None:
            self._variations.append(self._current)
            self._current = None
        return [variation.copy() for variation in self._variations]

    def clear(self) -> "VariationBuilder":
        """Clear all variations."""
        self._variations = []
        self._current = None
        return self

    def count(self) -> int:
        """Count variations including the current one."""
        return len(self._variations) + (1 if self._current is not None else 0)
