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
        # Get base attributes for category
        attribute_map = self.category_resolver.build_attribute_map(category_id)

        # Map product attributes to ML format
        ml_attributes = []
        mapped_attr_ids = {}  # id -> value mapping for conditional check

        # Also map the main product fields to attributes
        field_mappings = {
            "title": ["BOOK_TITLE", "TÍTULO DO LIVRO", "TITULO DO LIVRO"],
            "autor": ["AUTHOR", "AUTOR"],
            "gnero_do_livro": ["BOOK_GENRE", "GÊNERO DO LIVRO", "GENERO DO LIVRO"],
            "isbn": ["GTIN", "ISBN"],
            "gtin": ["GTIN", "ISBN"],
            "editora_do_livro": ["BOOK_PUBLISHER", "EDITORA DO LIVRO"],
        }

        # Add main product fields as attributes if they map to required ML attrs
        for field_name, ml_attr_names in field_mappings.items():
            value = None
            if field_name == "title":
                value = product.title
            elif field_name in product.attributes:
                value = product.attributes[field_name]

            if value:
                # Find matching ML attribute
                for ml_name in ml_attr_names:
                    ml_name_lower = ml_name.lower()
                    if ml_name_lower in attribute_map:
                        attr_def = attribute_map[ml_name_lower]
                        if attr_def["id"] not in mapped_attr_ids:
                            ml_attributes.append({
                                "id": attr_def["id"],
                                "name": attr_def["name"],
                                "value_name": value,
                            })
                            mapped_attr_ids[attr_def["id"]] = value
                            break

        # Map other product attributes
        for raw_name, raw_value in product.attributes.items():
            if raw_name.lower() in attribute_map:
                attr_def = attribute_map[raw_name.lower()]
                if attr_def["id"] not in mapped_attr_ids:
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

        # Build pictures list
        pictures = [{"source": url} for url in picture_urls]

        # If no pictures, use empty placeholder (will fail for gold_special)
        # or use a different listing type
        if not pictures:
            logger.warning(f"No pictures for {product.sku}")

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
        }

        if self.dry_run:
            logger.info(f"DRY RUN: Would publish {product.sku}")
            self.published += 1
            return True

        # Validate
        try:
            validation = self.publisher.validate_item(item)
            if not validation.get("valid", True):
                errors = validation.get('errors', validation)
                logger.error(f"Validation failed for {product.sku}: {errors}")
                self.errors.append(f"{product.sku}: {errors}")
                self.failed += 1
                return False
        except Exception as e:
            # Try to extract error details from exception
            error_msg = str(e)
            if hasattr(e, 'response') and e.response is not None:
                try:
                    error_detail = e.response.json()
                    error_msg = f"{error_msg} - {error_detail}"
                except:
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
