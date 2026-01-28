"""Spreadsheet parser adapter.

Adapts external Excel input to domain Product entities.
"""

import logging
import re
from pathlib import Path
from typing import Optional

import pandas as pd

from mercadolivre_upload.adapters.spreadsheet.header_detector import HeaderDetector
from mercadolivre_upload.domain.fiscal.data import FiscalData
from mercadolivre_upload.domain.product.model import Product

logger = logging.getLogger(__name__)


class SpreadsheetParser:
    """Parse Excel files into domain Product entities."""

    REQUIRED_COLUMNS = ["sku", "title", "description", "price", "available_quantity", "condition"]

    def __init__(self):
        self.detector = HeaderDetector()
        self.column_mapping: dict[str, str] = {}

    def parse(self, file_path: str | Path) -> list[Product]:
        """Parse Excel file into Product entities.

        Args:
            file_path: Path to Excel file

        Returns:
            List of Product entities
        """
        file_path = Path(file_path)

        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        logger.info(f"Parsing spreadsheet: {file_path}")

        # Read raw Excel (no headers)
        raw_df = pd.read_excel(file_path, header=None)
        if raw_df.empty:
            return []

        # Detect headers and build mapping
        data_df, self.column_mapping = self.detector.process(raw_df)

        # Validate required columns
        missing = [c for c in self.REQUIRED_COLUMNS if c not in self.column_mapping]
        if missing:
            raise ValueError(f"Missing required columns: {missing}")

        # Parse rows into Products
        products = []
        for idx, row in data_df.iterrows():
            if row.isna().all():
                continue

            try:
                product = self._parse_row(row)
                if product:
                    products.append(product)
            except Exception as e:
                logger.warning(f"Row {idx + 1}: {e}")

        logger.info(f"Parsed {len(products)} products")
        return products

    def _get_value(self, row: pd.Series, canonical_name: str, default: any = None) -> any:
        """Get value from row using canonical column name."""
        if canonical_name not in self.column_mapping:
            return default

        actual_col = self.column_mapping[canonical_name]
        value = row.get(actual_col, default)
        return None if pd.isna(value) else value

    def _parse_price(self, value: any) -> float:
        """Parse price value."""
        if isinstance(value, (int, float)):
            return float(value)

        value_str = str(value).strip()
        value_str = re.sub(r"[Rr]\$\s*", "", value_str)

        # Handle Brazilian format
        if "," in value_str and "." in value_str:
            last_comma = value_str.rfind(",")
            last_dot = value_str.rfind(".")
            if last_comma > last_dot:
                value_str = value_str.replace(".", "").replace(",", ".")
            else:
                value_str = value_str.replace(",", "")
        elif "," in value_str:
            value_str = value_str.replace(",", ".")

        return float(value_str)

    def _parse_quantity(self, value: any) -> int:
        """Parse quantity value."""
        if isinstance(value, (int, float)):
            return int(value)

        value_str = str(value).strip()
        match = re.search(r"\d+", value_str)
        if match:
            return int(match.group())

        raise ValueError(f"Cannot parse quantity: {value}")

    def _parse_condition(self, value: any) -> str:
        """Parse condition value."""
        value_str = str(value).lower().strip()

        if any(x in value_str for x in ["new", "novo", "0"]):
            return "new"
        if any(x in value_str for x in ["used", "usado", "1"]):
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
                    col_str = str(col).strip()
                    # Skip instructional headers
                    if len(col_str) > 100 or "informe" in col_str.lower():
                        continue
                    clean_col = re.sub(r"[^a-zA-Z0-9_\s]", "", col_str).strip()
                    if clean_col:
                        attributes[clean_col.lower().replace(" ", "_")] = str(value).strip()

        return attributes

    def _parse_row(self, row: pd.Series) -> Optional[Product]:
        """Parse a DataFrame row into a Product."""
        sku = str(self._get_value(row, "sku", "")).strip()
        title = str(self._get_value(row, "title", "")).strip()

        if not sku or not title:
            return None

        price = self._parse_price(self._get_value(row, "price"))
        quantity = self._parse_quantity(self._get_value(row, "available_quantity"))
        condition = self._parse_condition(self._get_value(row, "condition"))
        description = str(self._get_value(row, "description", ""))

        fiscal = FiscalData(
            ncm=str(self._get_value(row, "ncm", "")),
            cfop=str(self._get_value(row, "cfop", "")),
            origin=str(self._get_value(row, "origin", "")),
            cest=str(self._get_value(row, "cest", "")) or None,
        )

        attributes = self._extract_attributes(row)

        # Extract special attributes that are mapped but not in standard columns
        isbn = self._get_value(row, "isbn", "") or self._get_value(row, "gtin", "")
        if isbn:
            attributes["isbn"] = str(isbn).strip()
            attributes["gtin"] = str(isbn).strip()  # ISBN is used as GTIN

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
