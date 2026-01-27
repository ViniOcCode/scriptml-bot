"""Publish product use case.

Orchestrates domain logic and adapters to publish products.
"""

import logging
from pathlib import Path
from typing import Optional, Protocol

from mercadolivre_upload.domain.category.resolver import CategoryResolver
from mercadolivre_upload.domain.product.model import Product
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


class PublishProductUseCase:
    """Use case for publishing products to ML."""

    def __init__(
        self,
        category_resolver: CategoryResolver,
        publisher: ItemPublisherPort,
        image_uploader: ImageUploaderPort,
        dry_run: bool = False,
    ):
        """Initialize use case.

        Args:
            category_resolver: Category resolution service
            publisher: Item publisher (API adapter)
            image_uploader: Image uploader service
            dry_run: If True, only validate
        """
        self.category_resolver = category_resolver
        self.publisher = publisher
        self.image_uploader = image_uploader
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
        # Find category ID
        category_id = self.category_resolver.find_category(category_name)
        if not category_id:
            return {
                "success": False,
                "error": f"Category not found: {category_name}",
            }

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
        # Get base attributes for category
        attribute_map = self.category_resolver.build_attribute_map(category_id)

        # Map product attributes to ML format
        ml_attributes = []
        mapped_attr_ids = {}  # id -> value mapping for conditional check

        for raw_name, raw_value in product.attributes.items():
            if raw_name.lower() in attribute_map:
                attr_def = attribute_map[raw_name.lower()]
                ml_attrs_entry = {
                    "id": attr_def["id"],
                    "name": attr_def["name"],
                    "value_name": raw_value,
                }
                ml_attributes.append(ml_attrs_entry)
                mapped_attr_ids[attr_def["id"]] = raw_value

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
                elif attr_id in mapped_attr_ids:
                    ml_attributes.append({
                        "id": attr_id,
                        "name": cond_attr["name"],
                        "value_name": mapped_attr_ids[attr_id],
                    })
        except Exception as e:
            logger.warning(f"Could not get conditional attributes for {product.sku}: {e}")

        # Upload images
        picture_urls = self.image_uploader.upload_images(product.sku)

        # Build item
        item = {
            "title": product.title,
            "category_id": category_id,
            "price": product.price,
            "currency_id": "BRL",
            "available_quantity": product.available_quantity,
            "buying_mode": "buy_it_now",
            "condition": product.condition,
            "listing_type_id": "gold_special",
            "description": {"plain_text": product.description},
            "pictures": [{"source": url} for url in picture_urls],
            "attributes": ml_attributes,
        }

        if self.dry_run:
            logger.info(f"DRY RUN: Would publish {product.sku}")
            self.published += 1
            return True

        # Validate
        try:
            validation = self.publisher.validate_item(item)
            if not validation.get("valid", True):
                self.errors.append(f"{product.sku}: {validation.get('errors')}")
                self.failed += 1
                return False
        except Exception as e:
            logger.warning(f"Validation error for {product.sku}: {e}")

        # Publish
        try:
            result = self.publisher.create_item(item)
            logger.info(f"Published {product.sku}: {result.get('id')}")
            self.published += 1
            return True
        except Exception as e:
            self.errors.append(f"{product.sku}: {e}")
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
