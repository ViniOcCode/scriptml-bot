"""
Excel to JSON Converter for Mercado Libre Bulk Upload Templates

This module converts Excel files (ML bulk upload format) to JSON format
compatible with the publish.py flow. All configurations are loaded from
external JSON config files - NO HARDCODING.

Usage:
    python excel_converter.py "path/to/excel.xlsx" -c config/livros_fisicos.json -o items.json
"""

import argparse
import json
import logging
import sys
import os
from pathlib import Path
from typing import Any, Optional
from ml_api import MLAPI
from auth import TokenManager

import pandas as pd

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)


def load_config(config_path: str) -> dict:
    """
    Load configuration from JSON file.

    Args:
        config_path: Path to the configuration JSON file

    Returns:
        Configuration dictionary

    Raises:
        FileNotFoundError: If config file doesn't exist
        json.JSONDecodeError: If config file is invalid JSON
    """
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(path, "r", encoding="utf-8") as f:
        config = json.load(f)

    logger.info(f"Loaded config: {config.get('name', 'Unknown')}")
    return config


def read_excel(excel_path: str, config: dict) -> pd.DataFrame:
    """
    Read Excel file using settings from config.

    Args:
        excel_path: Path to the Excel file
        config: Configuration dictionary

    Returns:
        DataFrame with Excel data (no header, raw data)
    """
    path = Path(excel_path)
    if not path.exists():
        raise FileNotFoundError(f"Excel file not found: {excel_path}")

    excel_settings = config.get("excel_settings", {})
    sheet_name = excel_settings.get("sheet_name", 0)  # Default to first sheet

    logger.info(f"Reading Excel file: {excel_path}")
    logger.info(f"Sheet: {sheet_name}")

    # Read without header to get raw data
    df = pd.read_excel(
        excel_path, sheet_name=sheet_name, header=None, engine="openpyxl"
    )

    logger.info(f"Excel shape: {df.shape[0]} rows x {df.shape[1]} columns")
    return df


def detect_products(df: pd.DataFrame, config: dict) -> list[int]:
    """
    Detect which rows contain valid products based on config rules.

    Args:
        df: DataFrame with Excel data
        config: Configuration dictionary

    Returns:
        List of row indices that contain valid products
    """
    excel_settings = config.get("excel_settings", {})
    detection = config.get("product_detection", {})

    data_start_row = excel_settings.get("data_start_row", 0)
    required_columns = detection.get("required_columns", [])
    min_price = detection.get("min_price", 0.01)

    # Find the price column from column_mapping
    column_mapping = config.get("column_mapping", {})
    price_column = None
    for col_idx, col_config in column_mapping.items():
        if col_config.get("field") == "price":
            price_column = int(col_idx)
            break

    valid_rows = []

    for row_idx in range(data_start_row, len(df)):
        row = df.iloc[row_idx]

        # Check required columns have values
        is_valid = True
        for col_idx in required_columns:
            if col_idx >= len(row):
                is_valid = False
                break
            value = row[col_idx]
            if pd.isna(value) or str(value).strip() == "":
                is_valid = False
                break

        if not is_valid:
            continue

        # Check price if we have a price column
        if price_column is not None and price_column < len(row):
            price_value = row[price_column]
            try:
                price = float(price_value) if pd.notna(price_value) else 0
                if price < min_price:
                    continue
            except (ValueError, TypeError):
                continue

        valid_rows.append(row_idx)

    logger.info(f"Detected {len(valid_rows)} valid product rows")
    return valid_rows


def should_skip_value(value: Any, config: dict) -> bool:
    """
    Check if a value should be skipped based on config skip_values.

    Args:
        value: The value to check
        config: Configuration dictionary

    Returns:
        True if value should be skipped
    """
    if pd.isna(value):
        return True

    skip_values = config.get("skip_values", [])
    str_value = str(value).strip()

    return str_value in skip_values or str_value == ""


def apply_transform(value: Any, transform_name: str, config: dict) -> Any:
    """
    Apply a transformation to a value.

    Args:
        value: The value to transform
        transform_name: Name of the transform from config
        config: Configuration dictionary

    Returns:
        Transformed value
    """
    transforms = config.get("transforms", {})
    transform = transforms.get(transform_name, {})

    if not transform:
        return value

    operation = transform.get("operation")

    if operation == "multiply":
        factor = transform.get("factor", 1)
        try:
            return float(value) * factor
        except (ValueError, TypeError):
            return value

    return value


def transform_value(value: Any, column_config: dict, config: dict) -> Any:
    """
    Transform a cell value based on column configuration.

    Args:
        value: Raw cell value
        column_config: Configuration for this column
        config: Full configuration dictionary

    Returns:
        Transformed value
    """
    if should_skip_value(value, config):
        return None

    value_type = column_config.get("type", "string")

    # Handle different types
    if value_type == "string":
        return str(value).strip()

    elif value_type == "integer":
        try:
            return int(float(value))
        except (ValueError, TypeError):
            return column_config.get("default")

    elif value_type == "float":
        try:
            result = float(value)
            # Apply transform if specified
            transform = column_config.get("transform")
            if transform:
                result = apply_transform(result, transform, config)
            return result
        except (ValueError, TypeError):
            return column_config.get("default")

    elif value_type == "mapped":
        mapping = column_config.get("mapping", {})
        str_value = str(value).strip()
        if str_value in mapping:
            return mapping[str_value]
        return column_config.get("default")

    elif value_type == "url_list":
        separator = column_config.get("separator", ",")
        str_value = str(value).strip()
        if not str_value:
            return None
        urls = [url.strip() for url in str_value.split(separator) if url.strip()]
        return urls if urls else None

    elif value_type == "boolean":
        str_value = str(value).strip().lower()
        return str_value in ("true", "1", "yes", "sim")

    elif value_type == "number_unit":
        # Format: "{number} {unit}" (e.g., "3 cm", "300 g")
        unit = column_config.get("unit", "")
        try:
            num_val = float(value)
            # Apply transform if specified (e.g., kg_to_grams)
            transform = column_config.get("transform")
            if transform:
                num_val = apply_transform(num_val, transform, config)
            return f"{int(num_val)} {unit}"
        except (ValueError, TypeError):
            return column_config.get("default")

    return str(value).strip()


def set_nested_value(obj: dict, field_path: str, value: Any) -> None:
    """
    Set a value in a nested dictionary using dot notation.

    Args:
        obj: Dictionary to modify
        field_path: Dot-separated path (e.g., "shipping.dimensions.width")
        value: Value to set
    """
    parts = field_path.split(".")
    current = obj

    for i, part in enumerate(parts[:-1]):
        if part not in current:
            current[part] = {}
        current = current[part]

    current[parts[-1]] = value


def add_attribute(item: dict, attr_id: str, value: Any) -> None:
    """
    Add an attribute to the item's attributes list.

    Args:
        item: Item dictionary
        attr_id: Attribute ID
        value: Attribute value
    """
    if "attributes" not in item:
        item["attributes"] = []

    # Convert value to string for ML API
    str_value = str(value) if value is not None else None
    if str_value:
        item["attributes"].append({"id": attr_id, "value_name": str_value})


def load_pictures_from_sku_folder(
    sku: str, config: dict, excel_path: str
) -> Optional[list]:
    """
    Load pictures from SKU folder's pictures.json file.

    Args:
        sku: The SKU value (e.g., "17510CRIANCAU")
        config: Configuration dictionary
        excel_path: Path to Excel file (used to resolve relative paths)

    Returns:
        List of picture objects [{"source": url}, ...] or None if not found
    """
    pictures_config = config.get("pictures_source", {})
    if not pictures_config.get("enabled", False):
        return None

    base_path = pictures_config.get("base_path", "TESTE ANUNCIOS")
    suffix_to_remove = pictures_config.get("sku_suffix_to_remove", "U")
    filename = pictures_config.get("filename", "pictures.json")

    # Remove suffix from SKU to get folder name
    folder_name = sku.rstrip(suffix_to_remove) if suffix_to_remove else sku

    # Build path relative to excel file location
    excel_dir = Path(excel_path).parent
    pictures_path = excel_dir / base_path / folder_name / filename

    # Also try from current working directory
    if not pictures_path.exists():
        pictures_path = Path(base_path) / folder_name / filename

    if not pictures_path.exists():
        logger.debug(f"No pictures.json found for SKU {sku} at {pictures_path}")
        return None

    try:
        with open(pictures_path, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if not content:
                return None

            # Handle both formats:
            # 1. Just array: [{"source": "..."}, ...]
            # 2. With key: "pictures": [{"source": "..."}, ...]
            if content.startswith("["):
                pictures = json.loads(content)
            elif content.startswith('"pictures"'):
                # Wrap in braces to make it valid JSON
                pictures = json.loads("{" + content + "}")
                pictures = pictures.get("pictures", [])
            else:
                # Try parsing as-is
                data = json.loads(content)
                if isinstance(data, list):
                    pictures = data
                elif isinstance(data, dict):
                    pictures = data.get("pictures", [])
                else:
                    return None

            if pictures and len(pictures) > 0:
                logger.debug(f"Loaded {len(pictures)} pictures for SKU {sku}")
                return pictures

    except (json.JSONDecodeError, IOError) as e:
        logger.warning(f"Failed to load pictures for SKU {sku}: {e}")

    return None


def row_to_item(
    row: pd.Series, row_idx: int, config: dict, excel_path: str = ""
) -> Optional[dict]:
    """
    Convert a single Excel row to ML item JSON structure.

    Args:
        row: Pandas Series with row data
        row_idx: Row index (for logging)
        config: Configuration dictionary
        excel_path: Path to Excel file (for resolving relative paths)

    Returns:
        Item dictionary or None if conversion failed
    """
    defaults = config.get("defaults", {})
    column_mapping = config.get("column_mapping", {})
    post_processing = config.get("post_processing", {})

    # Start with defaults
    item = {
        "category_id": defaults.get("category_id"),
        "currency_id": defaults.get("currency_id", "BRL"),
        "buying_mode": defaults.get("buying_mode", "buy_it_now"),
        "listing_type_id": defaults.get("listing_type_id", "gold_special"),
    }

    # Temporary storage for post-processing fields
    temp_fields = {}

    # Process each mapped column
    for col_idx_str, col_config in column_mapping.items():
        col_idx = int(col_idx_str)

        if col_idx >= len(row):
            continue

        raw_value = row[col_idx]
        field = col_config.get("field", "")

        # Transform the value
        value = transform_value(raw_value, col_config, config)

        if value is None:
            continue

        # Handle different field types
        if field.startswith("_"):
            # Temporary field for post-processing
            temp_fields[field] = value

        elif field.startswith("attributes."):
            # Attribute field
            attr_id = field.replace("attributes.", "")
            add_attribute(item, attr_id, value)

        elif field.startswith("sale_terms."):
            # Sale terms field
            term_id = field.replace("sale_terms.", "")
            if "sale_terms" not in item:
                item["sale_terms"] = []
            item["sale_terms"].append({"id": term_id, "value_name": str(value)})

        elif field.startswith("shipping."):
            # Shipping field - use nested setter
            set_nested_value(item, field, value)

        elif field == "pictures":
            # Pictures field (url_list type returns list of URLs)
            if isinstance(value, list):
                item["pictures"] = [{"source": url} for url in value]

        else:
            # Direct field
            item[field] = value

    # Post-processing

    # Handle title fallback
    title_fallback_config = post_processing.get("title_fallback", {})
    if title_fallback_config.get("enabled", False):
        primary = title_fallback_config.get("primary", "title")
        fallback = title_fallback_config.get("fallback", "_title_fallback")
        if not item.get(primary) and fallback in temp_fields:
            item[primary] = temp_fields[fallback]

    # Combine warranty time
    warranty_config = post_processing.get("combine_warranty", {})
    if warranty_config.get("enabled", False):
        value_field = warranty_config.get("source_value", "_warranty_time_value")
        unit_field = warranty_config.get("source_unit", "_warranty_time_unit")
        target = warranty_config.get("target", "sale_terms.WARRANTY_TIME")
        fmt = warranty_config.get("format", "{value} {unit}")

        if value_field in temp_fields and unit_field in temp_fields:
            combined = fmt.format(
                value=temp_fields[value_field], unit=temp_fields[unit_field]
            )

            if "sale_terms" not in item:
                item["sale_terms"] = []

            # Check if WARRANTY_TIME already exists
            existing = [t for t in item["sale_terms"] if t.get("id") == "WARRANTY_TIME"]
            if not existing:
                item["sale_terms"].append(
                    {"id": "WARRANTY_TIME", "value_name": combined}
                )

    # Try to load pictures from SKU folder
    pictures_config = config.get("pictures_source", {})
    if pictures_config.get("enabled", False) and not item.get("pictures"):
        # Find SKU from attributes
        sku = None
        for attr in item.get("attributes", []):
            if attr.get("id") == "SELLER_SKU":
                sku = attr.get("value_name")
                break

        if sku:
            pictures = load_pictures_from_sku_folder(sku, config, excel_path)
            if pictures:
                item["pictures"] = pictures

    # Add placeholder image if pictures are still empty
    if not item.get("pictures"):
        placeholder = defaults.get("placeholder_image")
        if placeholder:
            item["pictures"] = [{"source": placeholder}]

    # Copy title to BOOK_TITLE attribute (required for books category)
    copy_title_config = post_processing.get("copy_title_to_attribute", {})
    if copy_title_config.get("enabled", False):
        source_field = copy_title_config.get("source", "title")
        target_attr = copy_title_config.get("target_attribute", "BOOK_TITLE")
        source_value = item.get(source_field)
        if source_value:
            add_attribute(item, target_attr, source_value)

    # Initialize shipping mode if shipping exists but mode doesn't
    if "shipping" in item and "mode" not in item.get("shipping", {}):
        item["shipping"]["mode"] = defaults.get("shipping_mode", "me2")

    # Remove shipping.dimensions - ML doesn't use this field
    # Dimensions should be passed as attributes (HEIGHT, WIDTH, WEIGHT, etc.)
    if "shipping" in item and "dimensions" in item.get("shipping", {}):
        del item["shipping"]["dimensions"]

    # Copy condition to ITEM_CONDITION attribute
    copy_condition_config = post_processing.get("copy_condition_to_attribute", {})
    if copy_condition_config.get("enabled", False):
        source_field = copy_condition_config.get("source", "condition")
        target_attr = copy_condition_config.get("target_attribute", "ITEM_CONDITION")
        mapping = copy_condition_config.get(
            "mapping", {"new": "Novo", "used": "Usado", "refurbished": "Recondicionado"}
        )
        source_value = item.get(source_field)
        if source_value and source_value in mapping:
            add_attribute(item, target_attr, mapping[source_value])

    # Validate required fields
    if not item.get("title"):
        logger.warning(f"Row {row_idx}: Missing title, skipping")
        return None

    if not item.get("price"):
        logger.warning(f"Row {row_idx}: Missing price, skipping")
        return None

    return item


def convert_excel(
    excel_path: str, config_path: str, output_path: str, dry_run: bool = False
) -> int:
    """
    Main conversion function.

    Args:
        excel_path: Path to Excel file
        config_path: Path to config JSON file
        output_path: Path for output JSON file
        dry_run: If True, only preview without writing

    Returns:
        Number of items converted
    """
    # Load config
    config = load_config(config_path)

    # Initialize centralized uploader (baseline per prompt5.md)
    token_manager = TokenManager()
    api = MLAPI(token_manager)

    # Read Excel
    df = read_excel(excel_path, config)

    # Detect product rows
    product_rows = detect_products(df, config)

    if not product_rows:
        logger.warning("No valid product rows detected")
        return 0

    # Convert each row
    items = []
    for row_idx in product_rows:
        row = df.iloc[row_idx]
        item = row_to_item(row, row_idx, config, excel_path)
        if not item:
            continue

        # Enrich with pictures via centralized uploader (prompt5.md baseline)
        sku = None
        for attr in item.get("attributes", []):
            if attr.get("id") == "SELLER_SKU":
                sku = str(attr.get("value_name"))
                break
        if sku:
            folder_name = sku.rstrip("U") if sku.endswith("U") else sku
            excel_dir = Path(excel_path).parent
            pictures_dir = excel_dir / "TESTE ANUNCIOS" / folder_name
            if not pictures_dir.exists():
                pictures_dir = Path("TESTE ANUNCIOS") / folder_name
            image_paths = []
            if pictures_dir.exists():
                for p in sorted(pictures_dir.iterdir(), key=lambda x: x.name):
                    if p.is_file() and p.suffix.lower() in {".jpg", ".jpeg", ".png"}:
                        image_paths.append(str(p))
            if image_paths:
                urls = api.upload_images_for_sku_folder(
                    sku, image_paths, dry_run=dry_run
                )
                if urls:
                    item["pictures"] = [{"source": u} for u in urls]
                    # Overwrite pictures.json for the SKU folder
                    pictures_json_path = pictures_dir / "pictures.json"
                    payload = {"pictures": [{"source": u} for u in urls]}
                    pictures_json_path.parent.mkdir(parents=True, exist_ok=True)
                    with open(pictures_json_path, "w", encoding="utf-8") as f:
                        json.dump(payload, f, indent=2, ensure_ascii=False)
                    logger.info(
                        f"Enriched SKU {sku} with {len(urls)} uploaded pictures; wrote {pictures_json_path}"
                    )
                else:
                    existing = load_pictures_from_sku_folder(sku, config, excel_path)
                    if existing:
                        item["pictures"] = existing
        items.append(item)
        logger.debug(f"Row {row_idx}: Converted '{item.get('title', 'Unknown')}'")

    logger.info(f"Successfully converted {len(items)} items")

    # Preview or write
    if dry_run:
        print("\n" + "=" * 60)
        print("DRY RUN - Preview of converted items:")
        print("=" * 60)
        for i, item in enumerate(items[:3], 1):  # Show first 3
            print(f"\n--- Item {i} ---")
            print(json.dumps(item, indent=2, ensure_ascii=False)[:1000])
            if len(json.dumps(item)) > 1000:
                print("... (truncated)")
        if len(items) > 3:
            print(f"\n... and {len(items) - 3} more items")
        print("\n" + "=" * 60)
    else:
        # Write to file
        output = Path(output_path)
        with open(output, "w", encoding="utf-8") as f:
            json.dump(items, f, indent=2, ensure_ascii=False)
        logger.info(f"Output written to: {output_path}")

    return len(items)


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Convert Mercado Libre Excel bulk upload to JSON",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python excel_converter.py "TESTE ANUNCIOS/file.xlsx" -c config/livros_fisicos.json
  python excel_converter.py input.xlsx -c config/livros_fisicos.json -o items.json
  python excel_converter.py input.xlsx -c config/livros_fisicos.json --dry-run
        """,
    )

    parser.add_argument("excel_file", help="Path to the Excel file to convert")

    parser.add_argument(
        "-c", "--config", required=True, help="Path to the configuration JSON file"
    )

    parser.add_argument(
        "-o",
        "--output",
        default="items.json",
        help="Output JSON file path (default: items.json)",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview conversion without writing output file",
    )

    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable verbose logging"
    )

    args = parser.parse_args()

    # Set log level
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    try:
        count = convert_excel(
            excel_path=args.excel_file,
            config_path=args.config,
            output_path=args.output,
            dry_run=args.dry_run,
        )

        if count > 0:
            print(f"\n[OK] Converted {count} items successfully")
            if not args.dry_run:
                print(f"[OK] Output: {args.output}")
        else:
            print("\n[!] No items were converted")
            sys.exit(1)

    except FileNotFoundError as e:
        print(f"\n[ERROR] {e}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"\n[ERROR] Invalid config JSON: {e}")
        sys.exit(1)
    except Exception as e:
        logger.exception(f"Unexpected error: {e}")
        print(f"\n[ERROR] {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
