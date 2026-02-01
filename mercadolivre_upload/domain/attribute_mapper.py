"""Dynamic attribute mapper for Excel columns to ML API attributes.

Uses fuzzy string matching to automatically map Excel column names
to Mercado Livre API attribute definitions.
"""

import unicodedata
from difflib import SequenceMatcher
import logging

logger = logging.getLogger(__name__)


class AttributeMapper:
    """Maps Excel column names to ML API attribute definitions using fuzzy matching."""

    def __init__(self, similarity_threshold: float = 0.7):
        """Initialize mapper with similarity threshold.

        Args:
            similarity_threshold: Minimum similarity score (0.0-1.0) for a match
        """
        self.threshold = similarity_threshold

    @staticmethod
    def normalize(text: str) -> str:
        """Normalize text for comparison.

        - Lowercase
        - Remove accents
        - Remove special characters (keep only alphanumeric and spaces)

        Args:
            text: Input text

        Returns:
            Normalized text
        """
        text = text.lower().strip()
        # Remove accents (é -> e, ã -> a, etc.)
        text = unicodedata.normalize('NFKD', text)
        text = ''.join(c for c in text if not unicodedata.combining(c))
        # Remove special chars except alphanumeric and spaces
        text = ''.join(c for c in text if c.isalnum() or c.isspace())
        return text

    @staticmethod
    def similarity(a: str, b: str) -> float:
        """Calculate string similarity ratio.

        Args:
            a: First string
            b: Second string

        Returns:
            Similarity ratio (0.0 to 1.0)
        """
        return SequenceMatcher(None, a, b).ratio()

    def find_best_match(
        self,
        excel_column: str,
        ml_attributes: list[dict]
    ) -> tuple[dict | None, float]:
        """Find best matching ML attribute for an Excel column.

        Compares against both attribute name and attribute ID.

        Args:
            excel_column: Excel column name
            ml_attributes: List of ML attribute definitions

        Returns:
            Tuple of (best_attribute_definition, similarity_score) or (None, 0.0)
        """
        excel_normalized = self.normalize(excel_column)
        best_match = None
        best_score = 0.0

        for attr in ml_attributes:
            # Try matching against attribute name
            attr_name = attr.get("name", "")
            name_normalized = self.normalize(attr_name)
            name_score = self.similarity(excel_normalized, name_normalized)

            # Try matching against attribute ID (with underscores replaced by spaces)
            attr_id = attr.get("id", "").replace("_", " ").lower()
            id_score = self.similarity(excel_normalized, attr_id)

            # Use the better of the two scores
            score = max(name_score, id_score)

            if score > best_score:
                best_score = score
                best_match = attr

        return best_match, best_score

    def map_columns_to_attributes(
        self,
        excel_columns: list[str],
        ml_attributes: list[dict]
    ) -> dict[str, dict]:
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
            attr_def, score = self.find_best_match(col, ml_attributes)

            if attr_def and score >= self.threshold:
                logger.info(
                    f"Mapped '{col}' -> '{attr_def['name']}' "
                    f"(score: {score:.2f})"
                )
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
        ml_attributes: list[dict],
        explicit_mappings: dict[str, dict] | None = None
    ) -> tuple[list[dict], list[dict]]:
        """Map product attributes to ML format using fuzzy matching.

        Args:
            product_attributes: Dictionary of {column_name: value} from Excel
            ml_attributes: List of ML attribute definitions from API
            explicit_mappings: Optional dict of {excel_column: mapping_config} for direct mapping

        Returns:
            Tuple of (ml_attributes_list, sale_terms_list)
        """
        excel_columns = list(product_attributes.keys())
        ml_attributes_list = []
        sale_terms_list = []

        # Track which columns have been explicitly mapped
        explicitly_mapped = set()

        # 1. First, apply explicit mappings (bypass fuzzy matching)
        # Normalize explicit mapping keys to match parser's column cleaning
        # Parser uses: re.sub(r"[^a-zA-Z0-9_\s]", "", col_str).strip()
        import re
        normalized_explicit_mappings = {}
        if explicit_mappings:
            for col, mapping_config in explicit_mappings.items():
                # Apply same cleaning as parser: remove non-alphanumeric chars (except spaces)
                normalized_col = re.sub(r"[^a-zA-Z0-9_\s]", "", col).strip().lower()
                normalized_explicit_mappings[normalized_col] = mapping_config
        
        if normalized_explicit_mappings:
            for col, value in product_attributes.items():
                # Apply same cleaning as parser
                normalized_col = re.sub(r"[^a-zA-Z0-9_\s]", "", col).strip().lower()
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
                            sale_term["values"] = [{
                                "id": mapping_config.get("value_id"),
                                "name": sale_term["value_name"],
                                "struct": mapping_config["value_struct"]
                            }]
                            sale_term["value_type"] = "number_unit"
                        else:
                            sale_term["value_id"] = mapping_config.get("value_id")
                            sale_term["values"] = [{
                                "id": mapping_config.get("value_id"),
                                "name": sale_term["value_name"],
                                "struct": None
                            }]
                            sale_term["value_type"] = mapping_config.get("value_type", "list")
                        
                        sale_terms_list.append(sale_term)
                        logger.info(f"Explicitly mapped '{col}' -> sale_terms[{mapping_config['id']}]")
                    elif target == "listing_type_id":
                        # Map listing type (Tipo de anúncio) - use cell value, not hardcoded ID
                        # Map common Portuguese values to ML API values
                        listing_type_map = {
                            "clássico": "gold_special",
                            "classico": "gold_special",
                            "premium": "gold_premium",
                            "grátis": "free",
                            "gratis": "free",
                        }
                        mapped_value = listing_type_map.get(str(value).lower().strip(), value)
                        # Store for later use in item payload
                        ml_attributes_list.append({
                            "_listing_type_id": mapped_value,  # Special marker for publisher
                        })
                        logger.info(f"Explicitly mapped '{col}' -> listing_type_id={mapped_value}")
                    
                    else:
                        # Regular attribute mapping
                        # Sanitize numeric values: convert comma to dot for decimals
                        if value and isinstance(value, str):
                            # Check if looks like a number with comma
                            if "," in value and value.replace(",", "").replace(".", "").isdigit():
                                # Brazilian format: 0,220 -> 0.220
                                value = value.replace(",", ".")
                        
                        # Apply unit suffix if configured
                        unit_suffix = mapping_config.get("unit_suffix", "")
                        if unit_suffix and value:
                            # Check if value already has the unit
                            if not str(value).lower().endswith(unit_suffix.strip().lower()):
                                value = f"{value}{unit_suffix}"
                        
                        ml_attributes_list.append({
                            "id": mapping_config["id"],
                            "name": mapping_config.get("name", mapping_config["id"]),
                            "value_name": value or mapping_config.get("value_name", ""),
                        })
                        logger.info(f"Explicitly mapped '{col}' -> {mapping_config['id']}")

                    explicitly_mapped.add(col)

        # 2. Then apply fuzzy matching for remaining columns
        remaining_columns = [c for c in excel_columns if c not in explicitly_mapped]

        column_to_attr = self.map_columns_to_attributes(
            remaining_columns,
            ml_attributes
        )

        # Build ML attributes list from fuzzy matches
        for col, attr_def in column_to_attr.items():
            value = product_attributes.get(col)
            if value:
                ml_attributes_list.append({
                    "id": attr_def["id"],
                    "name": attr_def["name"],
                    "value_name": value,
                })

        return ml_attributes_list, sale_terms_list
