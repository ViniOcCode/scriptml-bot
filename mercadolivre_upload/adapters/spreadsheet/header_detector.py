"""Header detection for messy Excel files."""

import logging
import re
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


class HeaderDetector:
    """Detects header rows and maps columns dynamically."""

    # Keywords to search for in column headers
    COLUMN_PATTERNS = {
        "sku": [r"\bsku\b", r"c[óo]digo", r"\bcode\b"],
        "title": [r"t[íi]tulo", r"\bnome\b", r"\bproduto\b"],
        "description": [r"descri[çc][ãa]o", r"\bdesc\b"],
        "price": [r"\bpre[çc]o\b", r"\bprice\b", r"\bvalor\b"],
        "available_quantity": [r"\bestoque\b", r"\bstock\b"],
        "condition": [r"condi[çc][ãa]o", r"\bestado\b"],
        "ncm": [r"\bncm\b"],
        "cfop": [r"\bcfop\b"],
        "origin": [r"\borigem\b"],
        "cest": [r"\bcest\b"],
        "isbn": [r"\bisbn\b"],
    }

    # Row patterns to detect header row
    HEADER_INDICATORS = [
        r"t[íi]tulo",
        r"sku",
        r"pre[çc]o",
        r"descri",
    ]

    def __init__(self):
        self.header_row: Optional[int] = None
        self.column_mapping: dict[str, str] = {}

    def detect_header_row(self, df: pd.DataFrame, max_rows: int = 10) -> int:
        """Detect which row contains the actual headers."""
        best_row = 0
        best_score = 0

        for idx in range(min(max_rows, len(df))):
            row_text = " ".join(df.iloc[idx].astype(str).dropna()).lower()

            unique_matches = set()
            for pattern in self.HEADER_INDICATORS:
                if re.search(pattern, row_text, re.I):
                    unique_matches.add(pattern)

            score = len(unique_matches)
            if score > best_score:
                best_score = score
                best_row = idx

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
