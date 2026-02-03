"""Dynamic Excel parser for messy ML templates.

Layer 1: Raw ingestion with dynamic header detection.
Handles merged cells, instructional headers, and variable column positions.
"""

import logging
import re
from pathlib import Path
from typing import Optional

import pandas as pd

from mercadolivre_upload.domain.text_normalizer import PortugueseTextNormalizer
from .exceptions import MissingColumnError, ValidationError
from .models import FiscalData, Product

logger = logging.getLogger(__name__)


class HeaderDetector:
    """Detects header rows and maps columns dynamically."""

    # Keywords to search for in column headers (case-insensitive)
    COLUMN_PATTERNS = {
        "sku": [r"\bsku\b", r"c[óo]digo", r"\bcode\b", r"item_id", r"refer[êe]ncia"],
        "title": [r"t[íi]tulo", r"\bnome\b", r"\bname\b", r"\bproduto\b", r"\bitem\b"],
        "description": [r"descri[çc][ãa]o", r"\bdesc\b", r"detalhes", r"especifica[çc][ãa]o"],
        "price": [r"\bpre[çc]o\b", r"\bpre[çc]o\s*\[?r\$\]?", r"\bprice\b", r"\bvalor\b"],
        "available_quantity": [r"\bestoque\b", r"\bquantidade\s+de\s+unidades\b", r"\bstock\b", r"\bqtd\b", r"dispon[íi]vel"],
        "quantity_pages": [r"quantidade\s+de\s+p[áa]ginas", r"p[áa]ginas"],
        "condition": [r"condi[çc][ãa]o", r"\bestado\b", r"situa[çc][ãa]o", r"novo/usado"],
        "ncm": [r"\bncm\b", r"n\.c\.m", r"n[úu]mero\s+mercad"],
        "cfop": [r"\bcfop\b", r"c\.f\.o\.p"],
        "origin": [r"\borigem\b", r"proced[êe]ncia", r"nacionalidade"],
        "cest": [r"\bcest\b", r"c\.e\.s\.t"],
        "isbn": [r"\bisbn\b", r"c[óo]d\.?\s*livro"],
        "brand": [r"\bmarca\b", r"fabricante", r"\bbrand\b"],
        "category": [r"\bcategoria\b", r"departamento", r"\bsetor\b", r"\bcategory\b"],
    }

    # Row patterns to detect header row
    HEADER_INDICATORS = [
        r"t[íi]tulo",  # Título
        r"sku",  # SKU
        r"c[óo]digo",  # Código
        r"pre[çc]o",  # Preço
        r"descri[çc][ãa]o",  # Descrição
    ]

    def __init__(self):
        self.header_row: Optional[int] = None
        self.column_mapping: dict[str, str] = {}  # canonical -> actual column name

    def detect_header_row(self, df: pd.DataFrame, max_rows: int = 10) -> int:
        """Detect which row contains the actual headers.

        Scans first N rows looking for header indicators.
        Returns the row index with most header matches.
        """
        best_row = 0
        best_score = 0

        for idx in range(min(max_rows, len(df))):
            row = df.iloc[idx].astype(str).str.lower()
            row_text = " ".join(row.dropna())

            score = 0
            for pattern in self.HEADER_INDICATORS:
                if re.search(pattern, row_text, re.IGNORECASE):
                    score += 1

            # Bonus for finding multiple different indicators
            unique_matches = set()
            for pattern in self.HEADER_INDICATORS:
                if re.search(pattern, row_text, re.IGNORECASE):
                    unique_matches.add(pattern)
            score = len(unique_matches)

            if score > best_score:
                best_score = score
                best_row = idx

        logger.debug(f"Detected header row at index {best_row} (score: {best_score})")
        return best_row

    def build_column_mapping(self, headers: list[str]) -> dict[str, str]:
        """Build mapping from canonical names to actual column names.

        Uses fuzzy matching to handle messy headers like:
        "Título: informe o produto..." -> maps to "title"
        """
        mapping = {}
        matched_columns = set()

        for canonical, patterns in self.COLUMN_PATTERNS.items():
            for col in headers:
                if col in matched_columns:
                    continue

                col_lower = col.lower()

                for pattern in patterns:
                    if re.search(pattern, col_lower, re.IGNORECASE):
                        mapping[canonical] = col
                        matched_columns.add(col)
                        logger.debug(f"Mapped '{canonical}' -> '{col}'")
                        break

        return mapping

    def process(self, df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, str]]:
        """Process DataFrame to extract clean data with header mapping.

        Returns:
            Tuple of (clean DataFrame with proper headers, column mapping)
        """
        # Detect header row
        header_idx = self.detect_header_row(df)
        self.header_row = header_idx

        # Extract headers from that row
        raw_headers = df.iloc[header_idx].astype(str).tolist()

        # Build mapping
        self.column_mapping = self.build_column_mapping(raw_headers)

        # Create clean DataFrame with headers from detected row
        data_df = df.iloc[header_idx + 1 :].copy()
        data_df.columns = raw_headers

        # Reset index
        data_df = data_df.reset_index(drop=True)

        logger.info(f"Detected {len(self.column_mapping)} columns from row {header_idx}")
        return data_df, self.column_mapping


class DynamicExcelParser:
    """Parser that handles messy ML bulk templates.

    Layer 1: Dynamic header detection and raw data extraction.
    """

    REQUIRED_COLUMNS = ["sku", "title", "description", "price", "available_quantity", "condition"]
    FISCAL_COLUMNS = ["ncm", "cfop", "origin"]

    def __init__(self):
        self.detector = HeaderDetector()
        self.column_mapping: dict[str, str] = {}  # canonical -> actual column name
        self._data_df: Optional[pd.DataFrame] = None

    def _normalize_value(self, value: any) -> str:
        """Normalize a cell value to string."""
        if pd.isna(value):
            return ""
        return str(value).strip()

    def _get_column_value(self, row: pd.Series, canonical_name: str, default: any = None) -> any:
        """Get value from row using canonical column name."""
        if canonical_name not in self.column_mapping:
            return default

        actual_col = self.column_mapping[canonical_name]
        value = row.get(actual_col, default)

        if pd.isna(value):
            return default

        return value

    def _parse_price(self, value: any) -> float:
        """Parse price from various formats."""
        if pd.isna(value):
            raise ValueError("Price cannot be empty")

        if isinstance(value, (int, float)):
            return float(value)

        value_str = str(value).strip()

        # Remove currency symbols and extra text
        value_str = re.sub(r"[Rr]$\s*", "", value_str)
        value_str = value_str.split()[0]  # Take first part if multiple values

        # Handle Brazilian format: 1.234,56
        if "." in value_str and "," in value_str:
            last_dot = value_str.rfind(".")
            last_comma = value_str.rfind(",")
            if last_comma > last_dot:
                value_str = value_str.replace(".", "").replace(",", ".")
            else:
                value_str = value_str.replace(",", "")
        elif "," in value_str:
            # Check if comma is decimal separator
            parts = value_str.split(",")
            if len(parts) == 2 and len(parts[1]) <= 2:
                value_str = value_str.replace(",", ".")
            else:
                value_str = value_str.replace(",", "")

        try:
            return float(value_str)
        except ValueError:
            raise ValueError(f"Cannot parse price: {value}")

    def _parse_quantity(self, value: any) -> int:
        """Parse quantity value."""
        if pd.isna(value):
            raise ValueError("Quantity cannot be empty")

        if isinstance(value, (int, float)):
            return int(value)

        value_str = str(value).strip()
        # Extract first number
        match = re.search(r"\d+", value_str)
        if match:
            return int(match.group())

        raise ValueError(f"Cannot parse quantity: {value}")

    def _parse_condition(self, value: any) -> str:
        """Parse condition to 'new' or 'used'."""
        if pd.isna(value):
            raise ValueError("Condition cannot be empty")

        value_str = str(value).lower().strip()

        # Extract first word
        match = re.search(r"[a-z]+", value_str)
        if match:
            value_str = match.group()

        new_patterns = ["new", "novo", "nova", "0", "nuevo", "nueva"]
        used_patterns = ["used", "usado", "usada", "1", "segunda", "mão", "mao"]

        if any(p in value_str for p in new_patterns):
            return "new"
        if any(p in value_str for p in used_patterns):
            return "used"

        raise ValueError(f"Invalid condition: {value}")

    def _extract_attributes(self, row: pd.Series) -> dict[str, str]:
        """Extract additional attributes from non-mapped columns."""
        attributes = {}
        mapped_cols = set(self.column_mapping.values())

        for col in row.index:
            if col not in mapped_cols:
                value = row.get(col)
                if pd.notna(value) and str(value).strip():
                    # Skip columns that are too long (likely instructional headers)
                    col_str = str(col).strip()
                    if len(col_str) > 100:
                        continue
                    # Skip columns with certain keywords
                    if re.search(r"informe|caso crie|voc[êe] deve|ttulo:", col_str, re.I):
                        continue
                    # Clean column name - normalize first to handle accents, then remove special chars
                    normalized_col = PortugueseTextNormalizer.normalize(col_str)
                    clean_col = re.sub(r"[^a-z0-9_\s]", "", normalized_col).strip()
                    if clean_col and len(clean_col) < 50:
                        attributes[clean_col.replace(" ", "_")] = str(value).strip()

        return attributes

    def parse(self, file_path: str | Path, sheet_name: Optional[str] = None) -> list[Product]:
        """Parse Excel file with dynamic header detection.

        Args:
            file_path: Path to Excel file
            sheet_name: Optional sheet name

        Returns:
            List of Product objects
        """
        file_path = Path(file_path)

        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        logger.info(f"Parsing Excel file: {file_path}")

        # Read raw Excel
        try:
            raw_df = pd.read_excel(file_path, sheet_name=sheet_name, header=None)
            if isinstance(raw_df, dict):
                raw_df = next(iter(raw_df.values()))
        except Exception as e:
            raise ValidationError(f"Failed to read Excel: {e}")

        if raw_df.empty:
            logger.warning("Excel file is empty")
            return []

        # Layer 1: Dynamic header detection
        data_df, self.column_mapping = self.detector.process(raw_df)
        self._data_df = data_df

        logger.info(f"Column mapping: {self.column_mapping}")

        # Validate required columns
        missing = [c for c in self.REQUIRED_COLUMNS if c not in self.column_mapping]
        if missing:
            raise MissingColumnError(missing)

        # Layer 2: Convert to canonical schema
        products = []
        errors = []

        for idx, row in data_df.iterrows():
            # Skip empty rows
            if row.isna().all():
                continue

            # Check if SKU is empty (end of data)
            sku = self._get_column_value(row, "sku")
            if pd.isna(sku) or str(sku).strip() == "":
                continue

            try:
                product = self._row_to_product(row)
                products.append(product)
            except Exception as e:
                errors.append(f"Row {idx + 1}: {e}")
                logger.warning(f"Row {idx + 1} error: {e}")

        if errors:
            logger.warning(f"Skipped {len(errors)} rows with errors")

        logger.info(f"Successfully parsed {len(products)} products")
        return products

    def _row_to_product(self, row: pd.Series) -> Product:
        """Convert a DataFrame row to Product model."""
        # Required fields
        sku = self._normalize_value(self._get_column_value(row, "sku"))
        title = self._normalize_value(self._get_column_value(row, "title"))
        description = self._normalize_value(self._get_column_value(row, "description"))

        if not sku:
            raise ValueError("SKU is required")
        if not title:
            raise ValueError("Title is required")

        price = self._parse_price(self._get_column_value(row, "price"))
        quantity = self._parse_quantity(self._get_column_value(row, "available_quantity"))
        condition = self._parse_condition(self._get_column_value(row, "condition"))

        # Fiscal data
        fiscal = FiscalData(
            ncm=self._normalize_value(self._get_column_value(row, "ncm", "")),
            cfop=self._normalize_value(self._get_column_value(row, "cfop", "")),
            origin=self._normalize_value(self._get_column_value(row, "origin", "")),
            cest=self._normalize_value(self._get_column_value(row, "cest", "")) or None,
        )

        # Additional attributes
        attributes = self._extract_attributes(row)

        return Product(
            sku=sku,
            title=title,
            description=description,
            price=price,
            available_quantity=quantity,
            condition=condition,
            fiscal=fiscal,
            attributes=attributes,
        )

    def get_raw_data(self) -> Optional[pd.DataFrame]:
        """Get the raw DataFrame after header detection (for debugging)."""
        return self._data_df

    def get_column_mapping(self) -> dict[str, str]:
        """Get the detected column mapping."""
        return self.column_mapping.copy()
