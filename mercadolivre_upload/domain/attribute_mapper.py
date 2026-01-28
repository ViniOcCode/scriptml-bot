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
        ml_attributes: list[dict]
    ) -> list[dict]:
        """Map product attributes to ML format using fuzzy matching.

        Args:
            product_attributes: Dictionary of {column_name: value} from Excel
            ml_attributes: List of ML attribute definitions from API

        Returns:
            List of ML-formatted attribute dictionaries
        """
        excel_columns = list(product_attributes.keys())

        # Map columns to ML attribute definitions
        column_to_attr = self.map_columns_to_attributes(
            excel_columns,
            ml_attributes
        )

        # Build ML attributes list
        ml_attributes_list = []
        for col, attr_def in column_to_attr.items():
            value = product_attributes.get(col)
            if value:
                ml_attributes_list.append({
                    "id": attr_def["id"],
                    "name": attr_def["name"],
                    "value_name": value,
                })

        return ml_attributes_list
