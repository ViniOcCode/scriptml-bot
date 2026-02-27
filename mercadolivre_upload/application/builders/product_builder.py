"""Product builder for spreadsheet data."""

from __future__ import annotations

from typing import Any

from mercadolivre_upload.shared.utils.text_utils import PortugueseTextNormalizer


class SmartMapper:
    """Minimal mapper for translating spreadsheet data to API fields."""

    REQUIRED_MAPPING = {
        "titulo": "title",
        "categoria": "category_id",
        "preco": "price",
        "moeda": "currency_id",
    }

    OPTIONAL_MAPPING = {
        "quantidade": "available_quantity",
        "condicao": "condition",
        "descricao": "description",
    }

    def validate_mapping(self, data: dict[str, Any], source_type: str = "spreadsheet") -> list[str]:
        """Validate that required fields exist in the data."""
        if source_type != "spreadsheet":
            return [f"Mapping not registered for source type: {source_type}"]
        missing = [key for key in self.REQUIRED_MAPPING if key not in data]
        if missing:
            return [f"Campos obrigatórios faltando: {', '.join(missing)}"]
        return []

    def map_product(self, data: dict[str, Any], source_type: str = "spreadsheet") -> dict[str, Any]:
        """Map source data fields to API fields."""
        if source_type != "spreadsheet":
            raise ValueError(f"Mapping not registered for source type: {source_type}")
        mapped = {}
        for source, target in self.REQUIRED_MAPPING.items():
            mapped[target] = data.get(source)
        for source, target in self.OPTIONAL_MAPPING.items():
            if source in data:
                mapped[target] = data.get(source)
        return mapped


class ProductBuilder:
    """Builds Mercado Livre item payloads from spreadsheet rows."""

    REQUIRED_FIELDS = ["title", "category_id", "price", "currency_id"]

    def __init__(self) -> None:
        """Initialize builder with mapper and normalizer."""
        self._mapper = SmartMapper()
        self._normalizer = PortugueseTextNormalizer()

    def _normalize_text(self, value: str) -> str:
        normalized = self._normalizer.normalize_keep_accents(value)
        return normalized.capitalize() if normalized else normalized

    def _normalize_description(self, value: str) -> str:
        return value.strip()

    def _parse_price(self, value: Any) -> float:
        if isinstance(value, (int, float)):
            return float(value)
        value_str = str(value).strip()
        value_str = value_str.replace(",", ".")
        return float(value_str)

    def _parse_quantity(self, value: Any) -> int:
        if isinstance(value, (int, float)):
            return int(value)
        value_str = str(value).strip()
        return int(float(value_str))

    def _validate_required(self, data: dict[str, Any]) -> list[str]:
        missing = []
        for field in self.REQUIRED_FIELDS:
            value = data.get(field)
            if value is None or isinstance(value, str) and not value.strip():
                missing.append(field)
        return missing

    def build(self, data: dict[str, Any], source_type: str = "spreadsheet") -> dict[str, Any]:
        """Build a product payload from source data."""
        errors = self._mapper.validate_mapping(data, source_type=source_type)
        if errors:
            raise ValueError("Campos obrigatórios faltando")

        mapped = self._mapper.map_product(data, source_type=source_type)
        missing = self._validate_required(mapped)
        if missing:
            raise ValueError("Campos obrigatórios faltando")

        payload: dict[str, Any] = {
            "title": self._normalize_text(str(mapped["title"])),
            "category_id": str(mapped["category_id"]).strip(),
            "price": self._parse_price(mapped["price"]),
            "currency_id": str(mapped["currency_id"]).strip(),
        }

        if "available_quantity" in mapped and mapped["available_quantity"] is not None:
            payload["available_quantity"] = self._parse_quantity(mapped["available_quantity"])
        if "condition" in mapped and mapped["condition"]:
            payload["condition"] = str(mapped["condition"]).strip()
        if "description" in mapped and mapped["description"] is not None:
            payload["description"] = self._normalize_description(str(mapped["description"]))

        return payload

    def validate(self, data: dict[str, Any], source_type: str = "spreadsheet") -> list[str]:
        """Validate source data and return list of errors."""
        errors = self._mapper.validate_mapping(data, source_type=source_type)
        if errors:
            return errors
        try:
            mapped = self._mapper.map_product(data, source_type=source_type)
        except (RuntimeError, ValueError, TypeError, KeyError) as exc:
            return [str(exc)]
        missing = self._validate_required(mapped)
        return [f"Campos obrigatórios faltando: {', '.join(missing)}"] if missing else []

    def build_batch(self, data_list: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Build payloads for a batch of products."""
        results = []
        for data in data_list:
            results.append(self.build(data))
        return results
