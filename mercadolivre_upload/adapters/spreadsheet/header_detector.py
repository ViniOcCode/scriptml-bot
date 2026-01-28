"""Header detection for messy Excel files."""

import logging
import re
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


class HeaderDetector:
    """Detects header rows and maps columns dynamically."""

    # Keywords to search for in column headers (Mercado Livre template format)
    COLUMN_PATTERNS = {
        "sku": [r"\bsku\b"],
        "title": [r"^t[íi]tulo(?!\s+do)"],  # Match "Título" at start, but not "Título do livro"
        "description": [r"descri[çc][ãa]o"],
        "price": [r"pre[çc]o"],
        "available_quantity": [r"estoque"],
        "condition": [r"condi[çc][ãa]o"],
        "isbn": [r"isbn"],
        "gtin": [r"gtin"],
        "ncm": [r"ncm"],
        "cfop": [r"cfop"],
        "origin": [r"origem"],
        "cest": [r"cest"],
        "fotos": [r"fotos"],
    }

    # Row patterns to detect header row (multiple matches needed)
    HEADER_INDICATORS = [
        (r"sku", 5),               # SKU is very strong indicator
        (r"t[ií]tulo", 4),         # Title is strong indicator
        (r"condi[cç][aã]o", 3),    # Condition is good indicator
        (r"pre[cç]o", 3),          # Price is good indicator
        (r"estoque", 2),           # Stock is medium indicator
        (r"fotos", 2),             # Fotos is medium indicator
    ]

    # Maximum length for a valid header cell
    MAX_CELL_LENGTH = 100
    # Maximum total row length
    MAX_ROW_LENGTH = 800

    def __init__(self):
        self.header_row: Optional[int] = None
        self.column_mapping: dict[str, str] = {}

    def detect_header_row(self, df: pd.DataFrame, max_rows: int = 10) -> int:
        """Detect which row contains the actual headers.

        Skips rows that look like instructions (very long text)
        and weights strong indicators like SKU higher.
        """
        best_row = 0
        best_score = 0

        for idx in range(min(max_rows, len(df))):
            row_values = df.iloc[idx].astype(str).dropna()

            # Skip rows that are too long (likely instructions)
            row_text = " ".join(row_values)
            if len(row_text) > self.MAX_ROW_LENGTH:
                continue

            # Skip rows with mostly numeric values (likely data, not headers)
            numeric_count = sum(1 for v in row_values if re.match(r'^\d+(\.\d+)?$', str(v).strip()))
            if numeric_count > len(row_values) / 2:
                continue

            # Calculate score based on individual cells (not entire row text)
            # This prevents matching partial words in long instruction cells
            score = 0
            for cell in row_values:
                cell_str = str(cell).strip()
                # Skip very long cells (likely instructions)
                if len(cell_str) > self.MAX_CELL_LENGTH:
                    continue
                cell_lower = cell_str.lower()
                for pattern, weight in self.HEADER_INDICATORS:
                    if re.search(pattern, cell_lower, re.I):
                        score += weight

            if score > best_score:
                best_score = score
                best_row = idx

        logger.info(f"Detected header row at index {best_row} (score: {best_score})")
        return best_row

    def build_column_mapping(self, headers: list[str]) -> dict[str, str]:
        """Build mapping from canonical names to actual column names."""
        mapping = {}
        matched_columns = set()

        for canonical, patterns in self.COLUMN_PATTERNS.items():
            for col in headers:
                if col in matched_columns:
                    continue

                col_lower = col.lower()
                for pattern in patterns:
                    if re.search(pattern, col_lower, re.I):
                        mapping[canonical] = col
                        matched_columns.add(col)
                        break

        return mapping

    def process(self, df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, str]]:
        """Process DataFrame to extract clean data with header mapping."""
        header_idx = self.detect_header_row(df)
        self.header_row = header_idx

        raw_headers = df.iloc[header_idx].astype(str).tolist()
        self.column_mapping = self.build_column_mapping(raw_headers)

        # Create clean DataFrame
        data_df = df.iloc[header_idx + 1 :].copy()
        data_df.columns = raw_headers
        data_df = data_df.reset_index(drop=True)

        return data_df, self.column_mapping
