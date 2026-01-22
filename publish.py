import os
import json
import logging
import time
from ml_api import MLAPI
from attributes import (
    get_cached_category,
    map_simple_attributes,
    auto_fill_defaults,
    auto_fill_shipping,
    auto_fill_smart,
    print_auto_fill_report,
    print_missing_attributes_report,
)
from error_collector import ErrorCollector

# ATTRIBUTE_CACHE = {} # Removed in favor of file-based cache

# CATEGORY_CACHE = {}  # Removed in favor of file-based cache

logger = logging.getLogger(__name__)

REQUIRED_FIELDS = [
    "title",
    # "category_id", # Moved to logic (can be predicted)
    "price",
    "currency_id",
    "available_quantity",
    "buying_mode",
    "condition",
    "listing_type_id",
]


JSON_FIELDS = ["sale_terms", "pictures", "attributes"]

RATE_LIMIT = 1.2


def normalize_item(item: dict) -> dict:
    """
    Normalize item to Mercado Livre BR (MLB) rules.
    Does NOT mutate business logic, only enforces compatibility.
    """

    # Enforce Brazil
    item["currency_id"] = "BRL"

    # Default listing type (safe)
    item.setdefault("listing_type_id", "free")

    # Validate category site
    if (
        "category_id" in item
        and item["category_id"]
        and not item["category_id"].startswith("MLB")
    ):
        raise ValueError(
            f"Invalid category for Mercado Livre BR: {item['category_id']}"
        )

    return item


def read_items(file="items.json"):
    if not os.path.exists(file):
        logger.error(f"JSON file not found: {file}")
        raise FileNotFoundError(f"JSON file '{file}' does not exist.")

    logger.info(f"Reading items from JSON: {file}")
    items = []

    try:
        with open(file, encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, list):
            raise ValueError("JSON root must be a list of items")

        for index, item in enumerate(data, start=1):
            try:
                # Normalization
                item = normalize_item(item)

                # Validation (basic structural)
                # Check required fields (except category_id which can be predicted)
                for field in REQUIRED_FIELDS:
                    if field not in item or not str(item[field]).strip():
                        raise ValueError(f"Missing required field '{field}'")

                # Type conversion
                item["price"] = float(item["price"])

                item["available_quantity"] = int(item["available_quantity"])

                # Value validation
                if item["price"] <= 0:
                    raise ValueError("Price must be greater than zero")

                if item["available_quantity"] < 0:
                    raise ValueError("Available quantity cannot be negative")

                # JSON fields validation
                for field in JSON_FIELDS:
                    if field in item:
                        if not isinstance(item[field], list):
                            raise ValueError(
                                f"Field '{field}' must be a list (not {type(item[field])})"
                            )

                # Normalize item AFTER validation
                item = normalize_item(item)

                items.append(item)
                logger.debug(f"Item {index}: '{item['title']}' loaded successfully")

            except Exception as e:
                logger.error(f"Item {index}: Invalid item skipped → {e}")
                continue

        logger.info(f"Successfully loaded {len(items)} valid items from JSON")

        if not items:
            logger.warning("No valid items found in JSON file")

        return items

    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON format: {e}")
        raise
    except Exception as e:
        logger.error(f"Error reading JSON file: {e}")
        raise


def validate_category_rules(item, category_data):
    """
    Validates if the item has all required attributes for its category.
    """
    required_attrs = []

    # Iterate attributes to find required ones
    for attr in category_data.get("attributes", []):
        tags = attr.get("tags")
        is_required = False

        # Handle 'tags' being either a dict or a list
        if isinstance(tags, dict):
            # Some attributes have required: true directly in dict
            is_required = tags.get("required", False)
        elif isinstance(tags, list):
            # Some are lists like ["required", "catalog_required"]
            is_required = "required" in tags

        if is_required:
            required_attrs.append(attr["id"])

    if not required_attrs:
        return

    # Compare with item["attributes"]
    item_attributes = item.get("attributes", [])
    item_attr_ids = {a.get("id") for a in item_attributes}

    missing = [req for req in required_attrs if req not in item_attr_ids]

    if missing:
        raise ValueError(
            f"Missing required attributes for category {category_data.get('id')}: {', '.join(missing)}"
        )


def _format_error_message(exception: Exception) -> str:
    """
    Format an exception into a human-readable error comment.

    Handles different error types and extracts meaningful information
    for the _error_comment field in the error JSON.
    """
    import requests

    error_type = type(exception).__name__

    # Handle HTTP errors with more detail
    if isinstance(exception, requests.HTTPError):
        response = exception.response
        try:
            # Try to extract API error details
            data = response.json()
            if "message" in data:
                return f"HTTP {response.status_code}: {data['message']}"
            if "cause" in data:
                causes = data.get("cause", [])
                error_msgs = [
                    f"{c.get('code', 'unknown')}: {c.get('message', '')}"
                    for c in causes
                ]
                return f"HTTP {response.status_code}: {'; '.join(error_msgs)}"
            return f"HTTP {response.status_code}: {response.text[:500]}"
        except Exception:
            return f"HTTP {response.status_code}: {response.reason}"

    # Handle ValueError (validation errors)
    if isinstance(exception, ValueError):
        return f"Validation error: {str(exception)}"

    # Handle FileNotFoundError
    if isinstance(exception, FileNotFoundError):
        return f"File not found: {str(exception)}"

    # Generic fallback
    return f"{error_type}: {str(exception)}"


def publish_items(api: MLAPI, items, dry_run=False):
    if not items:
        logger.warning("No items to publish")
        print("No items to publish.")
        return

    logger.info(f"Starting publication of {len(items)} items")
    success_count = 0
    error_count = 0

    # Initialize error collector
    error_collector = ErrorCollector()
    error_collector.set_total_items(len(items))

    for i, item in enumerate(items, start=1):
        try:
            logger.info(f"Processing item {i}/{len(items)}: {item['title']}")

            # 1. Category Prediction
            if "category_id" not in item or not item["category_id"]:
                print(f"   [i] Predicting category for '{item['title']}'...")
                prediction = api.predict_category(item["title"])

                if prediction:
                    item["category_id"] = prediction["id"]
                    logger.info(
                        f"Predicted category: {prediction['id']} ({prediction['name']})"
                    )
                else:
                    raise ValueError("Category ID missing and prediction failed")

            # 2. Attribute Mapping (Simple -> Complex)
            item = map_simple_attributes(item)

            # 3. Fetch Category Rules (Cached)
            cat_id = item["category_id"]
            category_data = get_cached_category(api, cat_id)

            # 4. Auto-Fill Defaults (basic)
            item = auto_fill_defaults(item, category_data)
            item = auto_fill_shipping(item)

            # 4.5 Smart Auto-Fill (dynamic based on category requirements)
            item, filled_attrs = auto_fill_smart(item, api, cat_id)
            if filled_attrs:
                print_auto_fill_report(filled_attrs)

            # 4.6 Pre-check: Show missing required attributes (helpful report)
            print_missing_attributes_report(item, api, cat_id)

            # 5. Local Rule Validation
            validate_category_rules(item, category_data)

            # DEBUG: Log final payload before API validation
            logger.debug(
                f"Final item payload: {json.dumps(item, indent=2, ensure_ascii=False)}"
            )

            # 6. API Pre-flight Validation
            # This ensures 100% compliance before we even try to publish
            logger.debug(f"Validating item with API...")
            validation_result = api.validate_item(item)

            if validation_result.get("status") == "warnings":
                logger.info(
                    f"Item '{item['title']}' has warnings but may still publish."
                )
                for w in validation_result.get("warnings", []):
                    print(f"   [WARN] {w.get('code')}: {w.get('message')}")

            if dry_run:
                logger.info(f"DRY RUN: Item '{item['title']}' passed all checks.")
                print(f"[DRY-RUN {i}/{len(items)}] Ready to publish: '{item['title']}'")
                success_count += 1
                continue

            # Actual Publication
            response = api.publish_item(item)
            success_count += 1
            print(f"[OK {i}/{len(items)}] {item['title']} -> id: {response['id']}")
            logger.info(f"Successfully published item with id: {response['id']}")

        except Exception as e:
            error_count += 1
            error_message = _format_error_message(e)
            error_collector.add_error(item, error_message)
            print(f"[ERROR {i}/{len(items)}] {item['title']} -> {e}")
            logger.error(f"Failed to process item '{item['title']}': {e}")

        # Rate limiting (sleep even on dry run to prevent API banning on category fetch)
        if i < len(items):
            if not dry_run or i % 10 == 0:
                time.sleep(RATE_LIMIT)

    # Save errors to JSON file if any occurred
    if error_collector.has_errors:
        error_file = error_collector.save()
        if error_file:
            print(f"\n[!] Errors saved to: {error_file}")

    logger.info(
        f"Publication complete: {success_count} successful, {error_count} failed"
    )
    print(f"\n=== Summary ===")
    print(f"Total: {len(items)} | Success: {success_count} | Failed: {error_count}")
