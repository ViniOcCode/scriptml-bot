"""Excel parser for product data."""

import logging
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from .exceptions import MissingColumnError, ValidationError
from .models import FiscalData, Product

logger = logging.getLogger(__name__)


def _load_config_mappings() -> dict[str, Any]:
    """Load column mappings from config file.

    Returns:
        Dictionary of column mappings from config/standard_fields and config/fiscal_fields
    """
    try:
        mappings = {}

        # Load standard fields from generic_mappings.yaml
        config_path = Path("config/generic_mappings.yaml")
        with open(config_path, encoding="utf-8") as f:
            config = yaml.safe_load(f)

        standard_fields = config.get("standard_fields", {})

        for field_name, field_config in standard_fields.items():
            patterns = field_config.get("patterns", [])
            exact_matches = field_config.get("exact_matches", [])
            # Combine patterns and exact matches for column matching
            combined = patterns + exact_matches
            all_patterns = list(dict.fromkeys(combined))  # Preserve order, remove duplicates
            if all_patterns:
                mappings[field_name] = all_patterns

        # Load fiscal fields from fiscal_config.yaml
        fiscal_config_path = Path("config/fiscal_config.yaml")
        with open(fiscal_config_path, encoding="utf-8") as f:
            fiscal_config = yaml.safe_load(f)

        fiscal_fields = fiscal_config.get("fiscal_fields", {})

        for field_name, field_config in fiscal_fields.items():
            patterns = field_config.get("patterns", [])
            exact_matches = field_config.get("exact_matches", [])
            # Combine patterns and exact matches for column matching
            combined = patterns + exact_matches
            all_patterns = list(dict.fromkeys(combined))  # Preserve order, remove duplicates
            if all_patterns:
                mappings[field_name] = all_patterns

        return mappings
    except Exception as e:
        logger.warning(f"Could not load config mappings: {e}. Using empty mappings.")
        return {}


# Fallback mappings for tests when config is not available
_FALLBACK_MAPPINGS = {
    "sku": ["sku", "codigo", "código", "code", "item_id"],
    "title": ["title", "titulo", "título", "nome", "name", "produto"],
    "description": ["description", "descricao", "descrição", "desc", "detalhes"],
    "price": ["price", "preco", "preço", "valor"],
    "available_quantity": ["available_quantity", "quantidade", "estoque", "stock", "qtd"],
    "condition": ["condition", "condicao", "condição", "estado", "situacao", "situação"],
    "ncm": ["ncm", "NCM"],
    "cfop": ["cfop", "CFOP"],
    "origin": ["origin", "origem", "origem_produto"],
    "cest": ["cest", "CEST"],
}


class ExcelParser:
    """Parser for Excel product files.

    Reads Excel files and converts rows to Product objects.
    Supports flexible column naming with case-insensitive matching.
    Uses configuration from config/generic_mappings.yaml as the single source of truth.
    """

    REQUIRED_COLUMNS = ["sku", "title", "description", "price", "available_quantity", "condition"]
    FISCAL_COLUMNS = ["ncm", "cfop", "origin"]

    def __init__(self, column_mappings: dict[str, Any] | None = None):
        """Initialize the parser.

        Args:
            column_mappings: Optional custom column mappings. Overrides config defaults.
        """
        # Load mappings from config (single source of truth)
        config_mappings = _load_config_mappings()
        # Use fallback if config couldn't be loaded (e.g., in tests)
        self.mappings = config_mappings if config_mappings else _FALLBACK_MAPPINGS.copy()
        # Apply any custom overrides
        if column_mappings:
            self.mappings.update(column_mappings)

        self._reverse_mapping: dict[str, str] = {}
        self._normalized_columns: set[str] = set()

    def _normalize_column_name(self, name: str) -> str:
        """Normalize column name for matching."""
        return name.lower().strip()

    def _build_reverse_mapping(self, columns: list[str]) -> dict[str, str]:
        """Build mapping from actual column names to canonical names."""
        reverse_mapping = {}
        normalized_to_original = {self._normalize_column_name(col): col for col in columns}

        for canonical, alternatives in self.mappings.items():
            for alt in alternatives:
                normalized_alt = self._normalize_column_name(alt)
                if normalized_alt in normalized_to_original:
                    reverse_mapping[canonical] = normalized_to_original[normalized_alt]
                    break
            # Also check for exact match if no pattern matched
            if canonical not in reverse_mapping:
                normalized_canonical = self._normalize_column_name(canonical)
                if normalized_canonical in normalized_to_original:
                    reverse_mapping[canonical] = normalized_to_original[normalized_canonical]

        return reverse_mapping

    def _get_column_value(self, row: pd.Series, column: str, default=None) -> any:  # type: ignore[no-untyped-def, valid-type]
        """Get value from row using canonical column name."""
        if column in self._reverse_mapping:
            actual_name = self._reverse_mapping[column]
            value = row.get(actual_name, default)
            return value  # type: ignore[no-any-return]
        return default  # type: ignore[no-any-return]

    def _validate_columns(self, columns: list[str]) -> None:
        """Validate that required columns are present.

        Args:
            columns: List of column names from the Excel file.

        Raises:
            MissingColumnError: If required columns are missing.
        """
        self._reverse_mapping = self._build_reverse_mapping(columns)
        self._normalized_columns = {self._normalize_column_name(col) for col in columns}

        missing = []
        for required in self.REQUIRED_COLUMNS:
            if required not in self._reverse_mapping:
                missing.append(required)

        if missing:
            raise MissingColumnError(missing)  # type: ignore[no-untyped-call]

        logger.debug(f"Found columns: {self._reverse_mapping}")

    def _parse_price(self, value: any) -> float:  # type: ignore[valid-type]
        """Parse price value to float.

        Handles various formats:
        - Numeric: 1234.56
        - String with currency: "R$ 1.234,56" or "$1,234.56"
        - String with dots/thousands: "1.234,56" or "1,234.56"
        """
        if pd.isna(value):
            raise ValueError("Price cannot be empty")

        if isinstance(value, (int, float)):
            return float(value)

        # Handle string values
        value_str = str(value).strip()

        # Remove currency symbols
        for symbol in ["R$", "$", "€", "£"]:
            value_str = value_str.replace(symbol, "")

        value_str = value_str.strip()

        # Detect format based on last separator
        # Brazilian: 1.234,56 (dot for thousands, comma for decimals)
        # US: 1,234.56 (comma for thousands, dot for decimals)
        if "," in value_str and "." in value_str:
            # Both present - determine which is decimal
            last_comma = value_str.rfind(",")
            last_dot = value_str.rfind(".")

            if last_comma > last_dot:
                # Brazilian format: 1.234,56
                value_str = value_str.replace(".", "").replace(",", ".")
            else:
                # US format: 1,234.56
                value_str = value_str.replace(",", "")
        elif "," in value_str:
            # Could be decimal separator or thousands
            # If there's only one comma and it's followed by 2 digits at end, it's decimal
            parts = value_str.split(",")
            if len(parts) == 2 and len(parts[1]) <= 2:
                value_str = value_str.replace(",", ".")
            else:
                # It's thousands separator
                value_str = value_str.replace(",", "")

        try:
            return float(value_str)
        except ValueError:
            raise ValueError(f"Cannot parse price: {value}") from None

    def _parse_quantity(self, value: any) -> int:  # type: ignore[valid-type]
        """Parse quantity value to integer."""
        if pd.isna(value):
            raise ValueError("Quantity cannot be empty")

        if isinstance(value, (int, float)):
            return int(value)

        value_str = str(value).strip()
        try:
            return int(float(value_str))
        except ValueError:
            raise ValueError(f"Cannot parse quantity: {value}") from None

    def _parse_condition(self, value: any) -> str:  # type: ignore[valid-type]
        """Parse condition value to 'new' or 'used'."""
        if pd.isna(value):
            raise ValueError("Condition cannot be empty")

        value_str = str(value).lower().strip()

        # Map various inputs to canonical values
        new_synonyms = ["new", "novo", "nova", "nuevo", "nueva", "0"]
        used_synonyms = ["used", "usado", "usada", "segunda mao", "segunda mão", "pre-owned", "1"]

        if value_str in new_synonyms:
            return "new"
        elif value_str in used_synonyms:
            return "used"
        else:
            # Try to interpret boolean-ish values
            if value_str in ["true", "yes", "sim", "s"]:
                return "new"
            elif value_str in ["false", "no", "nao", "não", "n"]:
                return "used"

        raise ValueError(f"Invalid condition: {value}. Must be 'new' or 'used'")

    def _parse_string(self, value: any) -> str:  # type: ignore[valid-type]
        """Parse string value, handling NaN."""
        if pd.isna(value):
            return ""
        return str(value).strip()

    def _extract_attributes(self, row: pd.Series) -> dict[str, str]:
        """Extract additional attributes from non-standard columns."""
        attributes = {}
        standard_columns = set(self._reverse_mapping.values())

        for col in row.index:
            if col not in standard_columns:
                value = row.get(col)
                if pd.notna(value):
                    attributes[self._normalize_column_name(col)] = str(value).strip()

        return attributes

    def validate_row(self, row: pd.Series) -> tuple[bool, list[str]]:
        """Validate a single row.

        Args:
            row: Pandas Series representing a row.

        Returns:
            Tuple of (is_valid, list_of_errors)
        """
        errors = []

        # Check required fields
        for field in self.REQUIRED_COLUMNS:
            value = self._get_column_value(row, field)
            if pd.isna(value) or (isinstance(value, str) and not value.strip()):  # type: ignore[attr-defined]
                errors.append(f"Missing required field: {field}")

        # Validate price
        try:
            price_value = self._get_column_value(row, "price")
            if price_value is not None:
                price = self._parse_price(price_value)
                if price < 0:
                    errors.append(f"Price cannot be negative: {price}")
        except ValueError as e:
            errors.append(str(e))

        # Validate quantity
        try:
            qty_value = self._get_column_value(row, "available_quantity")
            if qty_value is not None:
                qty = self._parse_quantity(qty_value)
                if qty < 0:
                    errors.append(f"Quantity cannot be negative: {qty}")
        except ValueError as e:
            errors.append(str(e))

        # Validate condition
        try:
            cond_value = self._get_column_value(row, "condition")
            if cond_value is not None:
                self._parse_condition(cond_value)
        except ValueError as e:
            errors.append(str(e))

        return len(errors) == 0, errors

    def _row_to_product(self, row: pd.Series) -> Product:
        """Convert a DataFrame row to a Product object."""
        # Parse required fields
        sku = self._parse_string(self._get_column_value(row, "sku"))
        title = self._parse_string(self._get_column_value(row, "title"))
        description = self._parse_string(self._get_column_value(row, "description"))
        price = self._parse_price(self._get_column_value(row, "price"))
        available_quantity = self._parse_quantity(self._get_column_value(row, "available_quantity"))
        condition = self._parse_condition(self._get_column_value(row, "condition"))

        # Parse fiscal data
        fiscal = FiscalData(
            ncm=self._parse_string(self._get_column_value(row, "ncm", "")),
            cfop=self._parse_string(self._get_column_value(row, "cfop", "")),
            origin=self._parse_string(self._get_column_value(row, "origin", "")),
            cest=self._parse_string(self._get_column_value(row, "cest", "")) or None,
        )

        # Extract additional attributes
        attributes = self._extract_attributes(row)

        return Product(
            sku=sku,
            title=title,
            description=description,
            price=price,
            available_quantity=available_quantity,
            condition=condition,
            fiscal=fiscal,
            attributes=attributes,
        )

    def parse(self, file_path: str | Path, sheet_name: str | None = None) -> list[Product]:
        """Parse an Excel file and return list of products.

        Args:
            file_path: Path to the Excel file.
            sheet_name: Optional sheet name to parse. Defaults to first sheet.

        Returns:
            List of Product objects.

        Raises:
            FileNotFoundError: If file doesn't exist.
            MissingColumnError: If required columns are missing.
            ValidationError: If data validation fails.
        """
        file_path = Path(file_path)

        if not file_path.exists():
            raise FileNotFoundError(f"Excel file not found: {file_path}")

        logger.info(f"Parsing Excel file: {file_path}")

        # Read Excel file
        try:
            df = pd.read_excel(file_path, sheet_name=sheet_name)
            # Handle case where pd.read_excel returns a dict (multiple sheets without sheet_name)
            if isinstance(df, dict):
                if not df:
                    logger.warning("Excel file has no sheets")
                    return []
                # Use the first sheet
                df = next(iter(df.values()))
        except Exception as e:
            raise ValidationError(f"Failed to read Excel file: {e}") from e  # type: ignore[no-untyped-call]

        if df.empty:
            logger.warning("Excel file is empty")
            return []

        # Validate columns
        self._validate_columns(df.columns.tolist())

        # Process rows
        products = []
        row_errors = []

        for idx, row in df.iterrows():
            # Skip completely empty rows
            if row.isna().all():
                continue

            # Validate row
            is_valid, errors = self.validate_row(row)
            if not is_valid:
                row_errors.append(f"Row {idx + 2}: {', '.join(errors)}")
                continue

            try:
                product = self._row_to_product(row)
                products.append(product)
            except Exception as e:
                row_errors.append(f"Row {idx + 2}: {e}")

        if row_errors:
            logger.warning(f"Skipped {len(row_errors)} rows with errors")
            for error in row_errors[:10]:  # Show first 10 errors
                logger.warning(error)
            if len(row_errors) > 10:
                logger.warning(f"... and {len(row_errors) - 10} more errors")

        logger.info(f"Successfully parsed {len(products)} products")
        return products

    def parse_safely(
        self, file_path: str | Path, sheet_name: str | None = None
    ) -> tuple[list[Product], list[str]]:
        """Parse an Excel file and return products with errors.

        Similar to parse(), but returns all errors instead of raising.

        Args:
            file_path: Path to the Excel file.
            sheet_name: Optional sheet name to parse.

        Returns:
            Tuple of (list_of_products, list_of_errors)
        """
        file_path = Path(file_path)

        if not file_path.exists():
            return [], [f"File not found: {file_path}"]

        try:
            df = pd.read_excel(file_path, sheet_name=sheet_name)
            # Handle case where pd.read_excel returns a dict (multiple sheets without sheet_name)
            if isinstance(df, dict):
                if not df:
                    return [], []
                # Use the first sheet
                df = next(iter(df.values()))
        except Exception as e:
            return [], [f"Failed to read Excel file: {e}"]

        if df.empty:
            return [], []

        # Validate columns
        try:
            self._validate_columns(df.columns.tolist())
        except MissingColumnError as e:
            return [], [str(e)]

        # Process rows
        products = []
        errors = []

        for idx, row in df.iterrows():
            if row.isna().all():
                continue

            is_valid, row_errors = self.validate_row(row)
            if not is_valid:
                errors.extend([f"Row {idx + 2}: {err}" for err in row_errors])
                continue

            try:
                product = self._row_to_product(row)
                products.append(product)
            except Exception as e:
                errors.append(f"Row {idx + 2}: {e}")

        return products, errors
