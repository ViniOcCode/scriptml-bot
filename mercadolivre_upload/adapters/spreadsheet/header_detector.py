"""Header detection for messy Excel files."""

import logging
import re
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

logger = logging.getLogger(__name__)


def _load_yaml_config(primary: Path, fallback: Path | None = None) -> dict[str, Any]:
    """Load YAML config with optional fallback."""
    for path in (primary, fallback):
        if path and path.exists():
            with open(path, encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
    return {}


def _load_header_config() -> dict[str, Any]:
    """Load header detection config from config file.

    Returns:
        Dictionary with column_patterns, header_indicators, and validation limits
    """
    try:
        config = _load_yaml_config(
            Path("config/header_detection.yaml"), Path("config/generic_mappings.yaml")
        )

        header_config = config.get("header_detection", {})

        # Convert column_patterns from config format (dict of lists) to regex patterns
        column_patterns = {}
        for col_name, patterns in header_config.get("column_patterns", {}).items():
            column_patterns[col_name] = patterns if isinstance(patterns, list) else [patterns]

        # Convert header_indicators from config format (list of dicts) to tuples
        header_indicators = []
        for indicator in header_config.get("header_indicators", []):
            header_indicators.append((indicator["pattern"], indicator["weight"]))

        return {
            "column_patterns": column_patterns,
            "header_indicators": header_indicators,
            "max_cell_length": header_config.get("max_cell_length", 100),
            "max_row_length": header_config.get("max_row_length", 800),
        }
    except Exception as e:
        logger.warning(f"Could not load header detection config: {e}. Using defaults.")
        return {
            "column_patterns": {},
            "header_indicators": [],
            "max_cell_length": 100,
            "max_row_length": 800,
        }


class HeaderDetector:
    """Detects header rows and maps columns dynamically.

    Uses configuration from config/header_detection.yaml as the single source of truth.
    """

    def __init__(self, config: dict[str, Any] | None = None):
        """Initialize the header detector.

        Args:
            config: Optional custom config. If not provided, loads from config file.
        """
        self.header_row: int | None = None
        self.column_mapping: dict[str, str] = {}

        # Load config from file (single source of truth)
        header_config = config or _load_header_config()

        self.COLUMN_PATTERNS = header_config.get("column_patterns", {})
        self.HEADER_INDICATORS = header_config.get("header_indicators", [])
        self.MAX_CELL_LENGTH = header_config.get("max_cell_length", 100)
        self.MAX_ROW_LENGTH = header_config.get("max_row_length", 800)

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
            numeric_count = sum(1 for v in row_values if re.match(r"^\d+(\.\d+)?$", str(v).strip()))
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
