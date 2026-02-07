"""Cached attribute mapper for Excel columns to ML API attributes.

Uses AttributeCache to map Excel column headers to Mercado Livre API
attribute definitions with value mapping support.
"""

from typing import Any, Protocol

from mercadolivre_upload.shared.utils.text_utils import PortugueseTextNormalizer

# Type aliases for clarity
AttributeDef = dict[str, Any]
ValueDef = dict[str, Any]
NameIndex = dict[str, AttributeDef]
ValueIndex = dict[str, dict[str, ValueDef]]
MLPayload = dict[str, Any]


class AttributeCachePort(Protocol):
    """Protocol for attribute cache implementations."""

    def get_attributes(self, category_id: str) -> list[dict[str, Any]] | None:
        """Get cached attributes for a category."""
        ...


class CachedAttributeMapper:
    """Maps Excel column headers to ML API attributes using cached category data.

    Uses AttributeCache to load category attribute definitions and provides
    methods to:
    - Find attribute definitions by Excel column header (name matching)
    - Map Excel cell values to ML API value IDs for list-type attributes
    - Return complete ML API payload format

    Example:
        from mercadolivre_upload.infrastructure.cache import AttributeCache
        cache = AttributeCache(cache_dir="cache/categories")
        mapper = CachedAttributeMapper(cache, "MLB437616")
        attr = mapper.find_attribute_by_name("Idioma")
        value_payload = mapper.map_value("LANGUAGE", "Português")
    """

    def __init__(self, attribute_cache: AttributeCachePort, category_id: str):
        """Initialize mapper with attribute cache and category ID.

        Args:
            attribute_cache: AttributeCache instance for retrieving category attributes
            category_id: ML category ID (e.g., "MLB437616")
        """
        self.attribute_cache = attribute_cache
        self.category_id = category_id
        self._cache: dict[str, Any] = {}
        self._name_index: NameIndex = {}
        self._value_index: ValueIndex = {}

        # Load cache and build indexes on initialization
        self.load_cache()
        self.build_name_index()

    def load_cache(self) -> dict[str, Any]:
        """Load category cache from AttributeCache.

        Returns:
            Dictionary containing category attributes cache

        Raises:
            ValueError: If cache doesn't contain attributes for this category
        """
        attributes = self.attribute_cache.get_attributes(self.category_id)

        if attributes is None:
            raise ValueError(
                f"No cached attributes found for category {self.category_id}. "
                f"Attributes may not have been fetched yet."
            )

        # Wrap in cache structure format expected by the rest of the class
        self._cache = {"attributes": attributes}

        return self._cache

    def build_name_index(self) -> NameIndex:
        """Build index mapping normalized attribute names to definitions.

        Creates two-level index:
        1. Normalized name -> attribute definition
        2. Value name index for list-type attributes

        Returns:
            Dictionary mapping normalized names to attribute definitions
        """
        self._name_index = {}
        self._value_index = {}

        attributes = self._cache.get("attributes", [])

        for attr in attributes:
            name = attr.get("name", "")
            attr_id = attr.get("id", "")

            if not name or not attr_id:
                continue

            # Index by normalized name
            normalized_name = PortugueseTextNormalizer.normalize(name)
            self._name_index[normalized_name] = attr

            # Build value index for list-type attributes
            if attr.get("value_type") == "list" and "values" in attr:
                value_map: dict[str, ValueDef] = {}
                for value in attr["values"]:
                    value_name = value.get("name", "")
                    if value_name:
                        normalized_value = PortugueseTextNormalizer.normalize(value_name)
                        value_map[normalized_value] = value
                self._value_index[attr_id] = value_map

        return self._name_index

    def find_attribute_by_name(self, excel_header: str) -> AttributeDef | None:
        """Find attribute definition by Excel column header.

        Performs exact match first, then falls back to near-exact matching
        using normalized text comparison.

        Args:
            excel_header: Excel column header text

        Returns:
            Attribute definition dict if found, None otherwise

        Example:
            >>> mapper.find_attribute_by_name("Idioma")
            {'id': 'LANGUAGE', 'name': 'Idioma', 'value_type': 'list', ...}
        """
        if not excel_header:
            return None

        normalized_header = PortugueseTextNormalizer.normalize(excel_header)

        # Exact match on normalized name
        if normalized_header in self._name_index:
            return self._name_index[normalized_header]

        # Near-exact match: look for high similarity
        best_match: AttributeDef | None = None
        best_score = 0.0

        for normalized_name, attr in self._name_index.items():
            # Check for substring containment (high score for contained matches)
            if normalized_header in normalized_name or normalized_name in normalized_header:
                score = 0.95
                if score > best_score:
                    best_score = score
                    best_match = attr
            else:
                # Use similarity for fuzzy matching
                attr_name = attr.get("name", "")
                score = PortugueseTextNormalizer.similarity(excel_header, attr_name)
                if score > best_score and score >= 0.85:  # High threshold for near-exact
                    best_score = score
                    best_match = attr

        return best_match

    def map_value(self, attribute_id: str, excel_value: str) -> MLPayload:
        """Map Excel cell value to ML API value payload.

        For list-type attributes, finds the matching value_id from the cache.
        For string/number types, uses the value directly.

        Args:
            attribute_id: ML API attribute ID
            excel_value: Value from Excel cell

        Returns:
            Complete ML API payload dict with id, name, value_id, value_name, values

        Example:
            >>> mapper.map_value("LANGUAGE", "Português")
            {
                "id": "LANGUAGE",
                "name": "Idioma",
                "value_id": "1258229",
                "value_name": "Português",
                "values": [{"id": "1258229", "name": "Português", "struct": null}]
            }
        """
        # Find the attribute definition
        attr: AttributeDef | None = None
        for a in self._cache.get("attributes", []):
            if a.get("id") == attribute_id:
                attr = a
                break

        if not attr:
            # Return minimal payload if attribute not found
            return {
                "id": attribute_id,
                "name": excel_value,
                "value_id": None,
                "value_name": excel_value,
                "values": [],
            }

        attr_name = attr.get("name", "")
        value_type = attr.get("value_type", "string")
        default_unit = attr.get("default_unit")

        # Handle number_unit type attributes (WIDTH, HEIGHT, WEIGHT, etc.)
        if value_type == "number_unit" and default_unit:
            # Extract numeric value from the input
            numeric_value = self._extract_numeric_value(excel_value)
            if numeric_value is not None:
                value_with_unit = f"{numeric_value} {default_unit}"
                return {
                    "id": attribute_id,
                    "name": attr_name,
                    "value_id": None,
                    "value_name": value_with_unit,
                    "values": [
                        {
                            "id": None,
                            "name": value_with_unit,
                            "struct": {"number": numeric_value, "unit": default_unit},
                        }
                    ],
                }

        # Handle list-type attributes
        if value_type == "list" and attribute_id in self._value_index:
            normalized_input = PortugueseTextNormalizer.normalize(excel_value)
            value_map = self._value_index[attribute_id]

            # Try exact match first
            if normalized_input in value_map:
                matched_value = value_map[normalized_input]
                value_id = matched_value.get("id")
                value_name = matched_value.get("name")
                return {
                    "id": attribute_id,
                    "name": attr_name,
                    "value_id": value_id,
                    "value_name": value_name,
                    "values": [{"id": value_id, "name": value_name, "struct": None}],
                }

            # Try partial/fuzzy matching
            best_match: ValueDef | None = None
            best_score = 0.0

            for normalized_value, value_def in value_map.items():
                # Check for containment
                if normalized_input in normalized_value or normalized_value in normalized_input:
                    score = 0.9
                else:
                    score = PortugueseTextNormalizer.similarity(
                        excel_value, value_def.get("name", "")
                    )

                if score > best_score:
                    best_score = score
                    best_match = value_def

            if best_match and best_score >= 0.8:
                value_id = best_match.get("id")
                value_name = best_match.get("name")
                return {
                    "id": attribute_id,
                    "name": attr_name,
                    "value_id": value_id,
                    "value_name": value_name,
                    "values": [{"id": value_id, "name": value_name, "struct": None}],
                }

        # For string/number types or when no value match found
        return {
            "id": attribute_id,
            "name": attr_name,
            "value_id": None,
            "value_name": excel_value,
            "values": [{"id": None, "name": excel_value, "struct": None}],
        }

    def map_product_attributes(self, product_attributes: dict[str, str]) -> list[MLPayload]:
        """Map all product attributes from Excel to ML API format.

        Args:
            product_attributes: Dictionary mapping Excel column headers to cell values

        Returns:
            List of complete ML API attribute payloads

        Example:
            >>> mapper.map_product_attributes({"Idioma": "Português", "Autor": "John Doe"})
            [
                {
                    "id": "LANGUAGE",
                    "name": "Idioma",
                    "value_id": "1258229",
                    "value_name": "Português",
                    "values": [{"id": "1258229", "name": "Português", "struct": null}]
                },
                {
                    "id": "AUTHOR",
                    "name": "Autor",
                    "value_id": null,
                    "value_name": "John Doe",
                    "values": [{"id": null, "name": "John Doe", "struct": null}]
                }
            ]
        """
        result: list[MLPayload] = []

        for excel_header, excel_value in product_attributes.items():
            if not excel_value:
                continue

            # Find attribute by column header
            attr = self.find_attribute_by_name(excel_header)
            if not attr:
                continue

            attribute_id = attr.get("id")
            if not attribute_id:
                continue

            # Map the value
            payload = self.map_value(attribute_id, str(excel_value))
            result.append(payload)

        return result

    def get_attribute_by_id(self, attribute_id: str) -> AttributeDef | None:
        """Get attribute definition by its ID.

        Args:
            attribute_id: ML API attribute ID

        Returns:
            Attribute definition if found, None otherwise
        """
        for attr in self._cache.get("attributes", []):
            if attr.get("id") == attribute_id:
                return attr  # type: ignore[no-any-return]
        return None

    def get_available_attributes(self) -> list[AttributeDef]:
        """Get list of all available attributes in the category.

        Returns:
            List of attribute definitions
        """
        return self._cache.get("attributes", [])  # type: ignore[no-any-return]

    def reload_cache(self) -> dict[str, Any]:
        """Reload cache from disk and rebuild indexes.

        Returns:
            Reloaded cache dictionary
        """
        self._cache = {}
        self._name_index = {}
        self._value_index = {}
        self.load_cache()
        self.build_name_index()
        return self._cache

    def _extract_numeric_value(self, excel_value: str) -> float | int | None:
        """Extract numeric value from Excel cell value.

        Handles various formats like "23", "23 cm", "0.3", "3 kg", etc.

        Args:
            excel_value: Value from Excel cell

        Returns:
            Numeric value as int or float, or None if no number found
        """
        if not excel_value:
            return None

        import re

        # Convert to string and strip whitespace
        value_str = str(excel_value).strip()

        # Try to extract a number (integer or decimal)
        # Match patterns like "23", "23.5", "0.3", etc.
        match = re.match(r"^([\d]+(?:\.\d+)?)", value_str.replace(",", "."))

        if match:
            num_str = match.group(1)
            # Return as int if it's a whole number, otherwise float
            if "." in num_str:
                return float(num_str)
            else:
                return int(num_str)

        return None
