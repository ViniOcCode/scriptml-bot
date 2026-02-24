"""Dynamic attribute mapper for Excel columns to ML API attributes.

Uses fuzzy string matching to automatically map Excel column names
to Mercado Livre API attribute definitions.
"""

import logging
import re
from typing import Any

from mercadolivre_upload.shared.utils.text_utils import PortugueseTextNormalizer, TextNormalizer

logger = logging.getLogger(__name__)

_VARIATION_HINT_PREFIX = "varia por"
_OPERATIONAL_HEADER_PATTERNS = (
    "forma de envio",
    "custo de envio",
    "tarifa de venda",
    "retirar pessoalmente",
    "quantidade de caracteres",
    "unidade de altura",
    "unidade de largura",
    "unidade de comprimento",
    "unidade de profundidade",
    "unidade de peso",
    "unidade de tempo de garantia",
)


def _normalize_column_name(column_name: str) -> str:
    """Normalize column names to a canonical form used by mappings."""
    return PortugueseTextNormalizer.normalize(str(column_name).replace("_", " "))


def _normalize_keywords(raw_keywords: Any) -> list[str]:
    """Normalize keyword rule entries into a list of comparable tokens."""
    if raw_keywords is None:
        return []
    if isinstance(raw_keywords, str):
        raw_keywords = [raw_keywords]

    normalized = []
    for keyword in raw_keywords:
        token = _normalize_column_name(str(keyword))
        if token:
            normalized.append(token)
    return normalized


def _matches_auto_mapping_rule(column_name: str, rule: dict[str, Any]) -> bool:
    """Return whether a column matches an auto explicit mapping rule."""
    normalized = _normalize_column_name(column_name)
    contains = _normalize_keywords(rule.get("contains"))
    excludes = _normalize_keywords(rule.get("excludes"))

    if not contains:
        return False
    if not all(token in normalized for token in contains):
        return False
    return not any(token in normalized for token in excludes)


def _resolve_auto_explicit_mappings(
    excel_columns: list[str],
    auto_explicit_mappings: list[dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    """Build normalized auto explicit mappings for matching columns."""
    normalized_mappings: dict[str, dict[str, Any]] = {}
    if not auto_explicit_mappings:
        return normalized_mappings

    for column in excel_columns:
        normalized_column = _normalize_column_name(column)
        for rule in auto_explicit_mappings:
            if not isinstance(rule, dict):
                continue

            match = rule.get("match", {})
            mapping = rule.get("mapping", {})
            if not isinstance(match, dict) or not isinstance(mapping, dict) or not mapping:
                continue

            if _matches_auto_mapping_rule(column, match):
                normalized_mappings[normalized_column] = mapping
                break

    return normalized_mappings


def _is_operational_header(column_name: str) -> bool:
    """Return whether header is operational metadata and should not be fuzzy-mapped."""
    normalized = _normalize_column_name(column_name)
    return normalized in _OPERATIONAL_HEADER_PATTERNS


def _extract_variation_hint(column_name: str) -> str | None:
    """Extract normalized variation attribute hint from a column name."""
    normalized = _normalize_column_name(column_name)
    if not normalized.startswith(_VARIATION_HINT_PREFIX):
        return None
    hint = normalized[len(_VARIATION_HINT_PREFIX) :].strip()
    return hint or None


def _extract_variation_candidates(value: Any) -> list[dict[str, Any]]:
    """Extract raw variation candidates from a multi-value spreadsheet cell."""
    if value is None:
        return []

    tokens = [part.strip() for part in re.split(r"[,;/|]", str(value)) if part.strip()]
    if len(tokens) <= 1:
        return []

    unique_tokens: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        normalized = PortugueseTextNormalizer.normalize(token)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        unique_tokens.append(token)

    if len(unique_tokens) <= 1:
        return []
    return [{"id": None, "name": token} for token in unique_tokens]


class AttributeMapper:
    """Maps Excel column names to ML API attribute definitions using fuzzy matching."""

    def __init__(self, similarity_threshold: float = 0.7):
        """Initialize mapper with similarity threshold.

        Args:
            similarity_threshold: Minimum similarity score (0.0-1.0) for a match
        """
        self.threshold = similarity_threshold

    def find_best_match(
        self, excel_column: str, ml_attributes: list[dict[str, Any]]
    ) -> tuple[dict[str, Any] | None, float]:
        """Find best matching ML attribute for an Excel column.

        Compares against both attribute name and attribute ID.

        Args:
            excel_column: Excel column name
            ml_attributes: List of ML attribute definitions

        Returns:
            Tuple of (best_attribute_definition, similarity_score) or (None, 0.0)
        """
        hint = _extract_variation_hint(excel_column)
        excel_normalized = TextNormalizer.normalize(hint or excel_column)
        best_match = None
        best_score = 0.0

        for attr in ml_attributes:
            # Try matching against attribute name
            attr_name = attr.get("name", "")
            name_normalized = TextNormalizer.normalize(attr_name)
            name_score = TextNormalizer.similarity(excel_normalized, name_normalized)

            # Try matching against attribute ID (with underscores replaced by spaces)
            attr_id = attr.get("id", "").replace("_", " ").lower()
            id_score = TextNormalizer.similarity(excel_normalized, attr_id)

            # Use the better of the two scores
            score = max(name_score, id_score)

            if score > best_score:
                best_score = score
                best_match = attr

        return best_match, best_score

    def map_columns_to_attributes(
        self, excel_columns: list[str], ml_attributes: list[dict[str, Any]]
    ) -> dict[str, dict[str, Any]]:
        """Map Excel column names to ML attribute definitions.

        Args:
            excel_columns: List of Excel column names
            ml_attributes: List of ML attribute definitions from API

        Returns:
            Dictionary mapping {excel_column: ml_attribute_definition}
            for columns that meet the similarity threshold
        """
        mapping = {}

        for col in excel_columns:
            if _is_operational_header(col):
                logger.debug(f"Skipping operational column: {col}")
                continue

            attr_def, score = self.find_best_match(col, ml_attributes)

            if attr_def and score >= self.threshold:
                logger.info(f"Mapped '{col}' -> '{attr_def['name']}' " f"(score: {score:.2f})")
                mapping[col] = attr_def
            else:
                logger.debug(
                    f"No match for '{col}' (best score: {score:.2f}, "
                    f"threshold: {self.threshold})"
                )

        return mapping

    def map_product_attributes(
        self,
        product_attributes: dict[str, str],
        ml_attributes: list[dict[str, Any]],
        explicit_mappings: dict[str, dict[str, Any]] | None = None,
        auto_explicit_mappings: list[dict[str, Any]] | None = None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Map product attributes to ML format using fuzzy matching.

        Args:
            product_attributes: Dictionary of {column_name: value} from Excel
            ml_attributes: List of ML attribute definitions from API
            explicit_mappings: Optional dict of {excel_column: mapping_config} for direct mapping
            auto_explicit_mappings: Optional rule list for contains-based explicit mapping

        Returns:
            Tuple of (ml_attributes_list, sale_terms_list)
        """
        excel_columns = list(product_attributes.keys())
        ml_attributes_list: list[dict[str, Any]] = []
        sale_terms_list: list[dict[str, Any]] = []
        available_attribute_ids = {
            attr_id
            for attr in ml_attributes
            if isinstance(attr, dict)
            for attr_id in [attr.get("id")]
            if isinstance(attr_id, str) and attr_id
        }

        # Track which columns have been explicitly mapped
        explicitly_mapped = set()

        # 1. First, apply explicit mappings (bypass fuzzy matching)
        # Normalize explicit mapping keys to match parser's column cleaning
        # Parser uses: re.sub(r"[^a-zA-Z0-9_\s]", "", col_str).strip()

        normalized_explicit_mappings = {}
        if explicit_mappings:
            for col, mapping_config in explicit_mappings.items():
                # Apply same cleaning as parser: remove non-alphanumeric chars (except spaces)
                normalized_col = _normalize_column_name(col)
                normalized_explicit_mappings[normalized_col] = mapping_config

        auto_normalized_mappings = _resolve_auto_explicit_mappings(
            excel_columns,
            auto_explicit_mappings=auto_explicit_mappings,
        )
        for normalized_col, mapping_config in auto_normalized_mappings.items():
            normalized_explicit_mappings.setdefault(normalized_col, mapping_config)

        if normalized_explicit_mappings:
            for col, value in product_attributes.items():
                # Apply same cleaning as parser
                normalized_col = _normalize_column_name(col)
                if normalized_col in normalized_explicit_mappings:
                    mapping_config = normalized_explicit_mappings[normalized_col]
                    target = mapping_config.get("target", "attribute")

                    if target == "sale_terms":
                        # Build sale term from config with full ML API format
                        sale_term = {
                            "id": mapping_config["id"],
                            "name": mapping_config.get("name", mapping_config["id"]),
                        }

                        # Determine value_name
                        if "value_name" in mapping_config:
                            sale_term["value_name"] = mapping_config["value_name"]
                        elif value:
                            sale_term["value_name"] = value
                        else:
                            sale_term["value_name"] = ""

                        # Build values array
                        if "value_struct" in mapping_config:
                            sale_term["value_struct"] = mapping_config["value_struct"]
                            sale_term["values"] = [
                                {
                                    "id": mapping_config.get("value_id"),
                                    "name": sale_term["value_name"],
                                    "struct": mapping_config["value_struct"],
                                }
                            ]
                            sale_term["value_type"] = "number_unit"
                        else:
                            sale_term["value_id"] = mapping_config.get("value_id")
                            sale_term["values"] = [
                                {
                                    "id": mapping_config.get("value_id"),
                                    "name": sale_term["value_name"],
                                    "struct": None,
                                }
                            ]
                            sale_term["value_type"] = mapping_config.get("value_type", "list")

                        sale_terms_list.append(sale_term)
                        logger.info(
                            f"Explicitly mapped '{col}' -> sale_terms[{mapping_config['id']}]"
                        )
                    elif target == "listing_type_id":
                        # Map listing type (Tipo de anúncio) - use cell value, not hardcoded ID
                        # Map common Portuguese values to ML API values
                        listing_type_map = {
                            "clássico": "gold_special",
                            "classico": "gold_special",
                            "premium": "gold_pro",
                            "gold pro": "gold_pro",
                            "diamante": "gold_premium",
                            "gold premium": "gold_premium",
                            "grátis": "free",
                            "gratis": "free",
                        }
                        mapped_value = listing_type_map.get(str(value).lower().strip(), value)
                        # Store for later use in item payload
                        ml_attributes_list.append(
                            {
                                "_listing_type_id": mapped_value,  # Special marker for publisher
                            }
                        )
                        logger.info(f"Explicitly mapped '{col}' -> listing_type_id={mapped_value}")

                    else:
                        # Regular attribute mapping
                        target_attr_id = mapping_config["id"]
                        if (
                            available_attribute_ids
                            and target_attr_id not in available_attribute_ids
                        ):
                            logger.info(
                                "Skipping explicit mapping '%s' -> %s (attribute not supported "
                                "by current category)",
                                col,
                                target_attr_id,
                            )
                            explicitly_mapped.add(col)
                            continue

                        # Sanitize numeric values: convert comma to dot for decimals
                        # Check if looks like a number with comma (Brazilian format)
                        if (
                            value
                            and isinstance(value, str)
                            and "," in value
                            and value.replace(",", "").replace(".", "").isdigit()
                        ):
                            # Brazilian format: 0,220 -> 0.220
                            value = value.replace(",", ".")

                        # Apply unit suffix if configured
                        unit_suffix = mapping_config.get("unit_suffix", "")
                        if (
                            unit_suffix
                            and value
                            and not str(value).lower().endswith(unit_suffix.strip().lower())
                        ):
                            value = f"{value}{unit_suffix}"

                        ml_attributes_list.append(
                            {
                                "id": target_attr_id,
                                "name": mapping_config.get("name", target_attr_id),
                                "value_name": value or mapping_config.get("value_name", ""),
                                "_source_column": col,
                            }
                        )
                        logger.info(f"Explicitly mapped '{col}' -> {target_attr_id}")

                    explicitly_mapped.add(col)

        # 2. Then apply fuzzy matching for remaining columns
        remaining_columns = [c for c in excel_columns if c not in explicitly_mapped]

        column_to_attr = self.map_columns_to_attributes(remaining_columns, ml_attributes)

        # Build ML attributes list from fuzzy matches
        for col, attr_def in column_to_attr.items():
            value = product_attributes.get(col)  # type: ignore[assignment]
            if value:
                attr_id = attr_def["id"]
                ml_attributes_list.append(
                    {
                        "id": attr_id,
                        "name": attr_def["name"],
                        "value_name": value,
                    }
                )
                if isinstance(attr_id, str):
                    variation_hint = _extract_variation_hint(col)
                    if variation_hint:
                        variation_candidates = _extract_variation_candidates(value)
                        if variation_candidates:
                            ml_attributes_list.append(
                                {"_variation_candidates": {attr_id: variation_candidates}}
                            )

        return ml_attributes_list, sale_terms_list

    def get_explicitly_mapped_columns(
        self,
        product_attributes: dict[str, str],
        explicit_mappings: dict[str, dict[str, Any]] | None = None,
        auto_explicit_mappings: list[dict[str, Any]] | None = None,
    ) -> set[str]:
        """Return columns covered by explicit mappings and configured auto-rules."""
        normalized_explicit = {}
        if explicit_mappings:
            normalized_explicit = {
                _normalize_column_name(column): mapping
                for column, mapping in explicit_mappings.items()
                if mapping
            }

        auto_mappings = _resolve_auto_explicit_mappings(
            list(product_attributes.keys()),
            auto_explicit_mappings=auto_explicit_mappings,
        )

        mapped_columns = set()
        for column in product_attributes:
            normalized_column = _normalize_column_name(column)
            if normalized_column in normalized_explicit or normalized_column in auto_mappings:
                mapped_columns.add(column)

        return mapped_columns
