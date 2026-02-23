"""Smart attribute mapper with API-driven discovery.

Maps Portuguese Excel columns directly to Mercado Livre API attribute IDs
using fuzzy matching against ML API attribute names (which are already in Portuguese).
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mercadolivre_upload.shared.utils.config_loader import load_yaml_config
from mercadolivre_upload.shared.utils.text_utils import PortugueseTextNormalizer

logger = logging.getLogger(__name__)


@dataclass
class ColumnMapping:
    """Result of mapping an Excel column."""

    excel_column: str
    target_field: str  # Either standard field name or ML attribute ID
    confidence: float
    mapping_type: str  # 'exact', 'pattern', 'fuzzy_api', 'generic'
    is_standard_field: bool  # True if it's a standard field (sku, title, etc.)


@dataclass
class UnmappedColumn:
    """Column that couldn't be mapped."""

    excel_column: str
    best_guess: str | None
    confidence: float
    reason: str


class SmartAttributeMapper:
    """Maps Excel columns to ML API attributes using API-driven discovery.

    This mapper:
    1. Uses minimal generic config for standard fields (sku, price, etc.)
    2. Fetches category attributes from ML API (cached)
    3. Fuzzy matches Excel columns directly against API attribute names
    4. Returns ML attribute IDs ready for API submission
    """

    def __init__(
        self,
        api_client: Any,  # MLApiClient
        config_path: str = "config/standard_fields.yaml",
        min_confidence: float = 0.85,
    ):
        """Initialize mapper.

        Args:
            api_client: MLApiClient instance for fetching category attributes
            config_path: Path to standard fields YAML config
            min_confidence: Minimum similarity score (0.0-1.0) to accept a match
        """
        self.api = api_client
        self.normalizer = PortugueseTextNormalizer()
        self.config = self._load_config(config_path)
        self.min_confidence = min_confidence
        self._category_cache: dict[str, list[dict[str, Any]]] = {}

    def _load_config(self, config_path: str) -> dict[str, Any]:
        """Load generic mappings from YAML config.

        Also loads fiscal fields from fiscal_config.yaml and merges them.
        """
        try:
            config_file = Path(config_path)
            legacy_file = Path("config/generic_mappings.yaml")
            config = load_yaml_config(config_file, legacy_file)
            if not config:
                logger.warning(f"Config file not found: {config_path}")
                return {}
            if config_file.exists():
                logger.info(f"Loaded config from {config_file}")
            elif legacy_file.exists():
                logger.info(f"Loaded config from {legacy_file}")

            # Also load fiscal fields from fiscal_config.yaml
            fiscal_config_path = Path("config/fiscal_config.yaml")
            if fiscal_config_path.exists():
                fiscal_config = load_yaml_config(fiscal_config_path)
                # Merge fiscal fields into config
                config["fiscal_fields"] = fiscal_config.get("fiscal_fields", {})
                logger.info(f"Loaded fiscal config from {fiscal_config_path}")

            return config
        except (OSError, TypeError, ValueError) as e:
            logger.error(f"Failed to load config: {e}")
            return {}

    def map_columns(
        self, excel_headers: list[str], category_id: str
    ) -> tuple[list[ColumnMapping], list[UnmappedColumn]]:
        """Map Excel columns to ML API fields.

        Args:
            excel_headers: List of column names from Excel
            category_id: Mercado Livre category ID

        Returns:
            Tuple of (successful_mappings, unmapped_columns)
        """
        mappings: list[ColumnMapping] = []
        unmapped: list[UnmappedColumn] = []

        # Get ML API attributes for this category
        ml_attributes = self._get_category_attributes(category_id)

        # Build index of normalized ML attribute names -> attribute IDs
        ml_index = self._build_ml_index(ml_attributes)

        for excel_col in excel_headers:
            # Skip excluded columns
            if self._is_excluded(excel_col):
                logger.debug(f"Skipping excluded column: {excel_col}")
                continue

            # Try to map this column
            mapping = self._map_single_column(excel_col, ml_index)

            if mapping:
                mappings.append(mapping)
                logger.info(
                    f"Mapped '{excel_col}' -> '{mapping.target_field}' "
                    f"({mapping.mapping_type}, confidence: {mapping.confidence:.2f})"
                )
            else:
                unmapped.append(
                    UnmappedColumn(
                        excel_column=excel_col,
                        best_guess=None,
                        confidence=0.0,
                        reason="No match found above confidence threshold",
                    )
                )
                logger.warning(f"Could not map column: {excel_col}")

        return mappings, unmapped

    def _get_category_attributes(self, category_id: str) -> list[dict[str, Any]]:
        """Fetch attributes from ML API (with caching)."""
        if category_id in self._category_cache:
            return self._category_cache[category_id]

        try:
            raw_attributes = self.api.get_category_attributes(category_id)
            if not isinstance(raw_attributes, list):
                logger.error(
                    "Unexpected attribute payload type for %s: %s",
                    category_id,
                    type(raw_attributes).__name__,
                )
                return []

            attributes = [attr for attr in raw_attributes if isinstance(attr, dict)]
            self._category_cache[category_id] = attributes
            logger.debug(f"Cached {len(attributes)} attributes for {category_id}")
            return attributes
        except Exception as e:
            logger.error(f"Failed to fetch attributes for {category_id}: {e}")
            return []

    def _build_ml_index(self, attributes: list[dict[str, Any]]) -> dict[str, str]:
        """Build index of normalized attribute names -> IDs.

        Args:
            attributes: List of ML API attribute definitions

        Returns:
            Dict mapping normalized names to attribute IDs
        """
        index = {}
        for attr in attributes:
            attr_id = attr.get("id", "")
            attr_name = attr.get("name", "")

            if attr_name:
                normalized = self.normalizer.normalize(attr_name)
                index[normalized] = attr_id

                # Also index without "do/da/de" for better matching
                simplified = self._simplify_portuguese(normalized)
                if simplified != normalized:
                    index[simplified] = attr_id

        return index

    def _simplify_portuguese(self, text: str) -> str:
        """Remove common Portuguese articles for better matching.

        Example: "titulo do livro" -> "titulo livro"
        """
        articles = ["do", "da", "de", "dos", "das"]
        words = text.split()
        simplified = [w for w in words if w not in articles]
        return " ".join(simplified)

    def _map_single_column(self, excel_col: str, ml_index: dict[str, str]) -> ColumnMapping | None:
        """Try to map a single Excel column.

        Tries in order:
        1. Exact match with standard fields
        2. Pattern match with standard fields
        3. Exact match with ML API attributes
        4. Fuzzy match with ML API attributes
        """
        normalized = self.normalizer.normalize(excel_col)

        # 1. Check standard fields (exact match)
        if mapping := self._match_standard_field_exact(excel_col, normalized):
            return mapping

        # 2. Check standard fields (pattern match)
        if mapping := self._match_standard_field_pattern(excel_col, normalized):
            return mapping

        # 3. Check ML API attributes (exact match)
        if attr_id := ml_index.get(normalized):
            return ColumnMapping(
                excel_column=excel_col,
                target_field=attr_id,
                confidence=1.0,
                mapping_type="exact_api",
                is_standard_field=False,
            )

        # 4. Fuzzy match against ML API attributes
        if mapping := self._fuzzy_match_api(excel_col, normalized, ml_index):
            return mapping

        return None

    def _match_standard_field_exact(self, excel_col: str, normalized: str) -> ColumnMapping | None:
        """Match against standard fields using exact matches."""
        standard_fields = self.config.get("standard_fields", {})

        for field_name, field_config in standard_fields.items():
            exact_matches = field_config.get("exact_matches", [])
            normalized_exacts = [self.normalizer.normalize(m) for m in exact_matches]

            if normalized in normalized_exacts:
                return ColumnMapping(
                    excel_column=excel_col,
                    target_field=field_name,
                    confidence=1.0,
                    mapping_type="exact_standard",
                    is_standard_field=True,
                )

        return None

    def _match_standard_field_pattern(
        self, excel_col: str, normalized: str
    ) -> ColumnMapping | None:
        """Match against standard fields using patterns."""
        standard_fields = self.config.get("standard_fields", {})
        fiscal_fields = self.config.get("fiscal_fields", {})
        image_fields = self.config.get("image_fields", {})

        all_fields = {**standard_fields, **fiscal_fields, **image_fields}

        for field_name, field_config in all_fields.items():
            # Check exclude patterns first
            exclude_patterns = field_config.get("exclude_patterns", [])
            for exclude in exclude_patterns:
                if self.normalizer.normalize(exclude) == normalized:
                    logger.debug(f"'{excel_col}' excluded from '{field_name}'")
                    break
            else:
                # Check include patterns
                patterns = field_config.get("patterns", [])
                for pattern in patterns:
                    norm_pattern = self.normalizer.normalize(pattern)
                    if normalized == norm_pattern:
                        return ColumnMapping(
                            excel_column=excel_col,
                            target_field=field_name,
                            confidence=0.95,
                            mapping_type="pattern_standard",
                            is_standard_field=True,
                        )

        return None

    def _fuzzy_match_api(
        self, excel_col: str, normalized: str, ml_index: dict[str, str]
    ) -> ColumnMapping | None:
        """Fuzzy match against ML API attribute names."""
        best_score = 0.0
        best_match = None

        for ml_name, attr_id in ml_index.items():
            score = self.normalizer.similarity(normalized, ml_name)

            # Boost score for partial matches (e.g., "Editora" vs "Editora do livro")
            if normalized in ml_name or ml_name in normalized:
                score = max(score, 0.9)

            if score > best_score:
                best_score = score
                best_match = attr_id

        if best_match and best_score >= self.min_confidence:
            return ColumnMapping(
                excel_column=excel_col,
                target_field=best_match,
                confidence=best_score,
                mapping_type="fuzzy_api",
                is_standard_field=False,
            )

        return None

    def _is_excluded(self, column: str) -> bool:
        """Check if column should be excluded from mapping."""
        excluded = self.config.get("excluded_columns", [])
        normalized_col = self.normalizer.normalize(column)

        for excluded_col in excluded:
            if self.normalizer.normalize(excluded_col) == normalized_col:
                return True

        return False

    def get_mapping_summary(
        self, mappings: list[ColumnMapping], unmapped: list[UnmappedColumn]
    ) -> dict[str, Any]:
        """Generate a summary of the mapping results."""
        total = len(mappings) + len(unmapped)

        by_type: dict[str, int] = {}
        for m in mappings:
            by_type[m.mapping_type] = by_type.get(m.mapping_type, 0) + 1

        standard_count = sum(1 for m in mappings if m.is_standard_field)
        attribute_count = len(mappings) - standard_count

        return {
            "total_columns": total,
            "mapped": len(mappings),
            "unmapped": len(unmapped),
            "success_rate": len(mappings) / total if total > 0 else 0,
            "by_mapping_type": by_type,
            "standard_fields": standard_count,
            "category_attributes": attribute_count,
            "unmapped_columns": [u.excel_column for u in unmapped],
        }
