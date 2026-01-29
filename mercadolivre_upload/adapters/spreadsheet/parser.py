"""Spreadsheet parser adapter.

Adapts external Excel input to domain Product entities.
"""

import logging
import re
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from mercadolivre_upload.adapters.spreadsheet.header_detector import HeaderDetector
from mercadolivre_upload.domain.fiscal.data import FiscalData
from mercadolivre_upload.domain.product.model import Product

logger = logging.getLogger(__name__)


class SpreadsheetParser:
    """Parse Excel files into domain Product entities."""

    # Required columns for product creation
    # Other columns (isbn, description, etc.) are optional and handled as attributes if present
    REQUIRED_COLUMNS = ["sku", "title", "price", "condition"]

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

    def _get_value(self, row: pd.Series, canonical_name: str, default: Any = None) -> Any:
        """Get value from row using canonical column name."""
        if canonical_name not in self.column_mapping:
            return default

        actual_col = self.column_mapping[canonical_name]
        value = row.get(actual_col, default)
        return None if pd.isna(value) else value

    def _parse_price(self, value: Any) -> float:
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

    def _parse_quantity(self, value: Any) -> int:
        """Parse quantity value."""
        if isinstance(value, (int, float)):
            return int(value)

        value_str = str(value).strip()
        match = re.search(r"\d+", value_str)
        if match:
            return int(match.group())

        raise ValueError(f"Cannot parse quantity: {value}")

    def _parse_int(self, value: Any) -> int | None:
        """Parse integer value, returning None if empty."""
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)

        value_str = str(value).strip()
        if not value_str:
            return None

        # Remove any non-numeric characters except minus
        value_str = re.sub(r"[^\d-]", "", value_str)
        if value_str:
            return int(value_str)
        return None

    def _parse_float(self, value: Any) -> float | None:
        """Parse float value, returning None if empty."""
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return None
        if isinstance(value, (int, float)):
            return float(value)

        value_str = str(value).strip()
        if not value_str:
            return None

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

        try:
            return float(value_str)
        except ValueError:
            return None

    def _parse_condition(self, value: Any) -> str:
        """Parse condition value."""
        value_str = str(value).lower().strip()

        if any(x in value_str for x in ["new", "novo", "0"]):
            return "new"
        if any(x in value_str for x in ["used", "usado", "1"]):
            return "used"

        raise ValueError(f"Invalid condition: {value}")

    def _extract_attributes(self, row: pd.Series) -> dict[str, str]:
        """Extract additional attributes from non-mapped columns.

        All columns not in the standard mapping (title, price, sku, etc.)
        are treated as attributes for the Mercado Livre API.
        """
        attributes = {}
        # Get all mapped column names
        mapped_cols = set(self.column_mapping.values())

        # Also exclude 'fotos' from attributes since it's handled separately
        if "fotos" in self.column_mapping:
            mapped_cols.add(self.column_mapping["fotos"])

        for col in row.index:
            if col not in mapped_cols:
                value = row.get(col)
                if pd.notna(value) and str(value).strip():
                    # Clean the column name
                    col_str = str(col).strip()
                    # Skip instructional headers and long text
                    if len(col_str) > 100:
                        continue
                    # Clean to use as attribute name
                    clean_col = re.sub(r"[^a-zA-Z0-9_\s]", "", col_str).strip()
                    if clean_col:
                        attributes[clean_col] = str(value).strip()

        return attributes

    def _parse_row(self, row: pd.Series) -> Optional[Product]:
        """Parse a DataFrame row into a Product."""
        sku = str(self._get_value(row, "sku", "")).strip()
        title = str(self._get_value(row, "title", "")).strip()

        if not sku or not title:
            return None

        price = self._parse_price(self._get_value(row, "price"))
        # Default quantity to 1 if not specified
        quantity = 1
        if "available_quantity" in self.column_mapping:
            quantity = self._parse_quantity(self._get_value(row, "available_quantity"))
        condition = self._parse_condition(self._get_value(row, "condition"))
        # Default description to title if not present
        description = str(self._get_value(row, "description", title))

        # Parse fiscal data with all available fields
        cost_value = self._get_value(row, "cost")
        cost = self._parse_price(cost_value) if cost_value else 0.0

        fiscal = FiscalData(
            sku=sku,
            title=title,
            cost=cost,
            ncm=str(self._get_value(row, "ncm", "")),
            cfop=str(self._get_value(row, "cfop", "")) or None,
            origin_detail=str(self._get_value(row, "origin_detail", self._get_value(row, "origin", ""))),
            cest=str(self._get_value(row, "cest", "")) or None,
            origin_type=str(self._get_value(row, "origin_type", "reseller")),
            csosn=str(self._get_value(row, "csosn", "")) or None,
            tax_rule_id=self._parse_int(self._get_value(row, "tax_rule_id")),
            fci=str(self._get_value(row, "fci", "")) or None,
            ex_tipi=str(self._get_value(row, "ex_tipi", "")) or None,
            ean=str(self._get_value(row, "ean", "")) or self._get_value(row, "gtin", "") or None,
            med_anvisa_code=str(self._get_value(row, "med_anvisa_code", "")) or None,
            med_exemption_reason=str(self._get_value(row, "med_exemption_reason", "")) or None,
            net_weight=self._parse_float(self._get_value(row, "net_weight")),
            gross_weight=self._parse_float(self._get_value(row, "gross_weight")),
        )

        # Extract attributes from other columns
        attributes = self._extract_attributes(row)

        # Handle ISBN/GTIN if present
        isbn = self._get_value(row, "isbn", "") or self._get_value(row, "gtin", "")
        if isbn:
            attributes["isbn"] = str(isbn).strip()
            attributes["gtin"] = str(isbn).strip()

        # Handle Fotos column - store in attributes for image uploader
        fotos = self._get_value(row, "fotos", "")
        if fotos:
            attributes["_fotos"] = str(fotos).strip()

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
