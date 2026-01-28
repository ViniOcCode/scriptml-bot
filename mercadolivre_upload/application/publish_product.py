"""Publish product use case.

Orchestrates domain logic and adapters to publish products.
"""

import logging
import re
from pathlib import Path
from typing import Optional, Protocol

from mercadolivre_upload.domain.category.resolver import CategoryResolver
from mercadolivre_upload.domain.product.model import Product
from mercadolivre_upload.domain.attribute_mapper import AttributeMapper
from mercadolivre_upload.adapters.spreadsheet.parser import SpreadsheetParser

logger = logging.getLogger(__name__)


class ImageUploaderPort(Protocol):
    """Port for image upload operations."""

    def upload_images(self, sku: str) -> list[str]:
        """Upload images for SKU and return URLs."""
        ...


class ItemPublisherPort(Protocol):
    """Port for item publishing operations."""

    def validate_item(self, item: dict) -> dict:
        """Validate item payload."""
        ...

    def create_item(self, item: dict) -> dict:
        """Create/publish item."""
        ...


class ShippingResolverPort(Protocol):
    """Port for shipping mode resolution."""

    def get_best_shipping_mode(self) -> str:
        """Get best available shipping mode for user."""
        ...


class PublishProductUseCase:
    """Use case for publishing products to ML."""

    def __init__(
        self,
        category_resolver: CategoryResolver,
        publisher: ItemPublisherPort,
        image_uploader: ImageUploaderPort,
        shipping_resolver: Optional[ShippingResolverPort] = None,
        dry_run: bool = False,
    ):
        """Initialize use case.

        Args:
            category_resolver: Category resolution service
            publisher: Item publisher (API adapter)
            image_uploader: Image uploader service
            shipping_resolver: Shipping mode resolver (optional)
            dry_run: If True, only validate
        """
        self.category_resolver = category_resolver
        self.publisher = publisher
        self.image_uploader = image_uploader
        self.shipping_resolver = shipping_resolver
        self.dry_run = dry_run

        self.published = 0
        self.failed = 0
        self.errors: list[str] = []

    def execute(self, products: list[Product], category_name: str) -> dict:
        """Execute publishing use case.

        Args:
            products: List of products to publish
            category_name: Category name for all products

        Returns:
            Execution results
        """
        # Find category ID using predictor-first strategy
        category_id = self.category_resolver.find_category(category_name)

        # Fallback: try domain discovery with product titles
        if not category_id and products:
            logger.info(f"Category not found by name, trying domain discovery...")
            for product in products:
                if product.title:
                    category_id = self.category_resolver.predict_category_from_title(
                        product.title
                    )
                    if category_id:
                        logger.info(f"Found category from title '{product.title[:30]}...'")
                        break

        if not category_id:
            error_msg = f"Category not found: {category_name}"
            logger.error(error_msg)
            return {
                "success": False,
                "published": 0,
                "failed": len(products),
                "errors": [error_msg],
            }

        # Ensure we have a leaf category (no children)
        leaf_category_id = self.category_resolver.resolve_to_leaf(category_id)
        if leaf_category_id != category_id:
            logger.info(f"Resolved to leaf category: {leaf_category_id}")
            category_id = leaf_category_id

        logger.info(f"Publishing {len(products)} products to category {category_id}")

        for product in products:
            self._publish_one(product, category_id)

        return {
            "success": self.failed == 0,
            "published": self.published,
            "failed": self.failed,
            "errors": self.errors,
        }

    def _publish_one(self, product: Product, category_id: str) -> bool:
        """Publish a single product."""
        logger.info(f"Publishing product: {product.sku} (title: {product.title[:50]}...)")

        # Get base attributes for category
        ml_attributes_list = self.category_resolver.get_all_attributes(category_id)

        # Initialize attribute mapper with default threshold
        attribute_mapper = AttributeMapper(similarity_threshold=0.7)

        # Map product attributes to ML format using fuzzy matching
        ml_attributes = attribute_mapper.map_product_attributes(
            product.attributes,
            ml_attributes_list
        )

        # Build mapped_attr_ids for conditional attribute lookup
        mapped_attr_ids = {
            attr["id"]: attr["value_name"]
            for attr in ml_attributes
        }

        # Get conditional attributes based on current attribute values
        try:
            conditional_attrs = self.category_resolver.get_conditional_attributes(
                category_id, mapped_attr_ids
            )

            # Add any conditional attributes that are provided by the product
            for cond_attr in conditional_attrs:
                attr_id = cond_attr.get("id")
                attr_name = cond_attr.get("name", "").lower()

                # Check if this attribute is provided in product attributes
                if attr_id in mapped_attr_ids:
                    # Already added above
                    continue

                # Check by name
                if attr_name in product.attributes:
                    ml_attributes.append({
                        "id": attr_id,
                        "name": cond_attr["name"],
                        "value_name": product.attributes[attr_name],
                    })
                    mapped_attr_ids[attr_id] = product.attributes[attr_name]
        except Exception as e:
            logger.warning(f"Could not get conditional attributes for {product.sku}: {e}")

        # Upload images
        picture_urls = self.image_uploader.upload_images(product.sku)

        # Build pictures list
        pictures = [{"source": url} for url in picture_urls]

        # If no pictures, use empty placeholder (will fail for gold_special)
        # or use a different listing type
        if not pictures:
            logger.warning(f"No pictures for {product.sku}")

        # Determine shipping mode
        shipping_mode = "not_specified"
        if self.shipping_resolver:
            shipping_mode = self.shipping_resolver.get_best_shipping_mode()
            logger.info(f"Using shipping mode: {shipping_mode}")

        # Build shipping config
        shipping_config = {"mode": shipping_mode}
        if shipping_mode == "not_specified":
            # For accounts without Mercado Envios, enable local pickup
            shipping_config["local_pick_up"] = True
            logger.info("Enabled local_pick_up for not_specified shipping")
        elif shipping_mode in ("me1", "me2"):
            # For Mercado Envios modes
            # Do NOT set free_shipping=True - account has mandatory free shipping
            # Explicit declaration triggers legacy validator bug referencing ME1
            shipping_config["logistic_type"] = "drop_off"
            shipping_config["local_pick_up"] = False
            shipping_config["methods"] = []
            logger.info(f"Shipping config for {shipping_mode} mode (free shipping automatic)")

        # DEBUG: Log full shipping config
        logger.debug(f"Shipping config for {product.sku}: {shipping_config}")

        # Build item
        item = {
            "title": product.title,
            "category_id": category_id,
            "price": product.price,
            "currency_id": "BRL",
            "available_quantity": product.available_quantity,
            "buying_mode": "buy_it_now",
            "condition": product.condition,
            "listing_type_id": "free" if not pictures else "gold_special",
            "description": {"plain_text": product.description},
            "pictures": pictures,
            "attributes": ml_attributes,
            "shipping": shipping_config,
        }

        # Log shipping section before validation
        logger.info(f"Final shipping config for {product.sku}: mode={shipping_config.get('mode')}, "
                    f"free_shipping={shipping_config.get('free_shipping')}, "
                    f"logistic_type={shipping_config.get('logistic_type')}, "
                    f"local_pick_up={shipping_config.get('local_pick_up')}")

        if self.dry_run:
            logger.info(f"DRY RUN: Would publish {product.sku}")
            self.published += 1
            return True

        # Normalize attributes before validation/publish (ensure units)
        self._normalize_item_attributes(item)

        # DEBUG: Log full item payload (with sensitive data redacted if needed)
        debug_item = item.copy()
        debug_item.pop('description', None)  # Remove long description for cleaner logs
        logger.debug(f"Full item payload for {product.sku}: {debug_item}")

        # Validate
        try:
            validation = self.publisher.validate_item(item)
            logger.debug(f"Validation response for {product.sku}: {validation}")

            # Parse validation causes to distinguish warnings from errors
            causes = validation.get("cause", [])
            errors = []
            warnings = []
            shipping_issues = []

            for cause in causes:
                cause_type = cause.get("type", "").lower()
                cause_code = cause.get("code", "")
                cause_message = cause.get("message", "")
                logger.debug(f"Validation cause for {product.sku}: {cause}")

                # Check for shipping-specific issues
                if "shipping" in str(cause_code).lower() or "shipping" in str(cause_message).lower():
                    shipping_issues.append(f"{cause_code}: {cause_message}")

                # Separate actual errors from warnings
                if cause_type == "error":
                    errors.append(f"{cause_code}: {cause_message}")
                elif cause_type == "warning":
                    warnings.append(f"{cause_code}: {cause_message}")

            # Log shipping issues
            if shipping_issues:
                logger.info(f"Shipping validation issues for {product.sku}: {shipping_issues}")

            # Log warnings (don't block publishing)
            if warnings:
                logger.warning(f"Validation warnings for {product.sku}: {warnings}")

            # Only fail if there are actual errors
            if errors:
                logger.error(f"Validation failed for {product.sku}: {errors}")
                self.errors.append(f"{product.sku}: {errors}")
                self.failed += 1
                return False
        except Exception as e:
            # Try to extract error details from exception
            error_msg = str(e)
            error_detail = None
            if hasattr(e, 'response') and e.response is not None:
                try:
                    error_detail = e.response.json()
                    error_msg = f"{error_msg} - {error_detail}"
                    # Check for shipping-specific errors
                    causes = error_detail.get("cause", []) if isinstance(error_detail, dict) else []
                    for cause in causes:
                        cause_code = cause.get("code", "").lower()
                        cause_message = cause.get("message", "").lower()
                        if "shipping" in cause_code or "shipping" in cause_message:
                            logger.error(f"Shipping validation error for {product.sku}: {cause}")
                except Exception:
                    error_msg = f"{error_msg} - {e.response.text[:200]}"
            logger.error(f"Validation error for {product.sku}: {error_msg}")
            self.errors.append(f"{product.sku}: {error_msg}")
            self.failed += 1
            return False

        # Publish
        try:
            result = self.publisher.create_item(item)
            logger.info(f"Published {product.sku}: {result.get('id')}")
            self.published += 1
            return True
        except Exception as e:
            error_msg = str(e)
            if hasattr(e, 'response') and e.response is not None:
                try:
                    error_detail = e.response.json()
                    error_msg = f"{error_msg} - {error_detail}"
                    # Check for shipping-specific errors
                    causes = error_detail.get("cause", []) if isinstance(error_detail, dict) else []
                    for cause in causes:
                        cause_code = cause.get("code", "").lower()
                        cause_message = cause.get("message", "").lower()
                        if "shipping" in cause_code or "shipping" in cause_message:
                            logger.error(f"Shipping publish error for {product.sku}: {cause}")
                except Exception:
                    error_msg = f"{error_msg} - {e.response.text[:200]}"
            logger.error(f"Publish error for {product.sku}: {error_msg}")
            self.errors.append(f"{product.sku}: {error_msg}")
            self.failed += 1
            return False

    def get_stats(self) -> dict:
        """Get publishing statistics."""
        return {
            "published": self.published,
            "failed": self.failed,
            "total": self.published + self.failed,
            "errors": self.errors,
        }

    def _normalize_item_attributes(self, item: dict) -> None:
        """Ensure numeric dimensions have units.

        Appends ' cm' to pure-numeric dimension attributes (height/width/length/depth).
        Operates in-place on `item['attributes']`.
        """
        attrs = item.get("attributes")
        if not isinstance(attrs, list):
            return

        # Patterns
        numeric_only = re.compile(r"^\s*\d+(?:[\.,]\d+)?\s*$")
        unit_marker = re.compile(r"\b(cm|mm|m|in|pouce|polegadas)\b", re.IGNORECASE)

        for attr in attrs:
            try:
                name = str(attr.get("name", "")).lower()
            except Exception:
                name = ""

            # Normalize dimension-like attributes
            if name and any(k in name for k in ("height", "altura", "width", "largura", "length", "comprimento", "depth", "profundidade")):
                val = attr.get("value_name")
                if isinstance(val, (int, float)):
                    attr["value_name"] = f"{val} cm"
                elif isinstance(val, str):
                    if numeric_only.match(val) and not unit_marker.search(val):
                        # Convert comma decimals to dot (ML accepts dot) then append cm
                        normalized = val.strip().replace(",", ".")
                        attr["value_name"] = f"{normalized} cm"
