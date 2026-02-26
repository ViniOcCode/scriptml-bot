"""Cached attribute mapper for Excel columns to ML API attributes.

Uses AttributeCache to map Excel column headers to Mercado Livre API
attribute definitions with value mapping support.
"""

import re
from typing import Any, Protocol

from mercadolivre_upload.shared.utils.text_utils import PortugueseTextNormalizer

from .cache_attribute_mapper_helpers import (
    build_value_candidates as _build_value_candidates_helper,
)
from .cache_attribute_mapper_helpers import (
    extract_numeric_value as _extract_numeric_value_helper,
)
from .cache_attribute_mapper_helpers import (
    extract_variation_hint_from_normalized as _extract_variation_hint_from_normalized_helper,
)
from .cache_attribute_mapper_helpers import (
    is_blocked_header as _is_blocked_header_helper,
)
from .cache_attribute_mapper_helpers import (
    match_candidate_to_allowed_value as _match_candidate_to_allowed_value_helper,
)
from .cache_attribute_mapper_helpers import (
    simplify_match_text as _simplify_match_text,
)
from .cache_attribute_mapper_helpers import (
    token_overlap as _token_overlap,
)

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
        self._simplified_name_index: NameIndex = {}
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
        self._simplified_name_index = {}
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
            simplified_name = _simplify_match_text(normalized_name)
            if simplified_name and simplified_name not in self._simplified_name_index:
                self._simplified_name_index[simplified_name] = attr

            # Build value index for attributes that expose allowed values.
            if "values" in attr and isinstance(attr.get("values"), list) and attr.get("values"):
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
        variation_hint = self._extract_variation_hint_from_normalized(normalized_header)
        if variation_hint:
            normalized_header = variation_hint
        elif self._is_blocked_header(normalized_header):
            return None

        # Exact match on normalized name
        if normalized_header in self._name_index:
            return self._name_index[normalized_header]

        simplified_header = _simplify_match_text(normalized_header)
        if simplified_header in self._simplified_name_index:
            return self._simplified_name_index[simplified_header]

        # Near-exact match: high similarity + token overlap (avoid loose substring matches).
        best_match: AttributeDef | None = None
        best_score = 0.0

        for normalized_name, attr in self._name_index.items():
            simplified_name = _simplify_match_text(normalized_name)
            overlap = _token_overlap(
                simplified_header or normalized_header,
                simplified_name or normalized_name,
            )
            if overlap < 0.6:
                continue

            score = max(
                PortugueseTextNormalizer.similarity(normalized_header, normalized_name),
                PortugueseTextNormalizer.similarity(simplified_header, simplified_name),
            )
            if score > best_score and score >= 0.9:
                best_score = score
                best_match = attr

        return best_match

    def extract_variation_hint(self, excel_header: str) -> str | None:
        """Extract normalized variation attribute hint from a header."""
        normalized_header = PortugueseTextNormalizer.normalize(excel_header)
        return self._extract_variation_hint_from_normalized(normalized_header)

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

        # Handle attributes that expose allowed values (even when value_type is string).
        if attribute_id in self._value_index:
            matched_values = self.map_all_values(attribute_id, excel_value)
            if matched_values:
                first_match = matched_values[0]
                value_id = first_match.get("id")
                value_name = first_match.get("name")
                return {
                    "id": attribute_id,
                    "name": attr_name,
                    "value_id": value_id,
                    "value_name": value_name,
                    "values": [{"id": value_id, "name": value_name, "struct": None}],
                }

            # No allowed value match found: return empty value so caller can skip safely.
            return {
                "id": attribute_id,
                "name": attr_name,
                "value_id": None,
                "value_name": None,
                "values": [],
            }

        # For string/number types
        return {
            "id": attribute_id,
            "name": attr_name,
            "value_id": None,
            "value_name": excel_value,
            "values": [{"id": None, "name": excel_value, "struct": None}],
        }

    def map_all_values(self, attribute_id: str, excel_value: str) -> list[ValueDef]:
        """Return all allowed values matched from a potentially multi-value cell."""
        value_map = self._value_index.get(attribute_id)
        if not value_map:
            return []

        raw_value = str(excel_value).strip()
        if not raw_value:
            return []

        parts = [part.strip() for part in re.split(r"[,;/|]", raw_value) if part.strip()]
        search_candidates = parts if len(parts) > 1 else [raw_value]
        fallback_to_raw = len(parts) > 1

        matched: list[ValueDef] = []
        seen: set[tuple[Any, Any]] = set()

        for candidate in search_candidates:
            value_def = self._match_candidate_to_allowed_value(candidate, value_map)
            if not value_def:
                continue
            key = (value_def.get("id"), value_def.get("name"))
            if key in seen:
                continue
            seen.add(key)
            matched.append(value_def)

        if matched:
            return matched

        if fallback_to_raw:
            value_def = self._match_candidate_to_allowed_value(raw_value, value_map)
            if value_def:
                return [value_def]

        return []

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
        self._simplified_name_index = {}
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
        return _extract_numeric_value_helper(excel_value)

    def _is_blocked_header(self, normalized_header: str) -> bool:
        """Return whether a header is operational metadata, not a product attribute."""
        return _is_blocked_header_helper(normalized_header)

    def _extract_variation_hint_from_normalized(self, normalized_header: str) -> str | None:
        """Extract normalized variation hint from a normalized header."""
        return _extract_variation_hint_from_normalized_helper(normalized_header)

    def _match_candidate_to_allowed_value(
        self, candidate: str, value_map: dict[str, ValueDef]
    ) -> ValueDef | None:
        """Match a candidate string to the best allowed value."""
        return _match_candidate_to_allowed_value_helper(candidate, value_map)

    def _build_value_candidates(self, excel_value: str) -> list[str]:
        """Build candidate values for enum matching from potentially multi-value cells."""
        return _build_value_candidates_helper(excel_value)
