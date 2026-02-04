"""Main pipeline for Mercado Livre bulk upload.

3-Layer Pipeline:
1. Layer 1: Raw Excel ingestion (DynamicExcelParser)
2. Layer 2: Canonical schema (Product/FiscalData models)
3. Layer 3: API enrichment (CategoryResolver, Publisher)
"""

import logging
from pathlib import Path

from mercadolivre_upload.adapters.spreadsheet.dynamic_parser import DynamicExcelParser
from mercadolivre_upload.adapters.spreadsheet.models import Product
from mercadolivre_upload.api.category_resolver import CategoryResolver
from mercadolivre_upload.api.client import MLApiClient
from mercadolivre_upload.auth.manager import AuthManager
from mercadolivre_upload.publisher.publisher import Publisher

logger = logging.getLogger(__name__)


class MLPipeline:
    """Main pipeline for ML bulk upload."""

    def __init__(
        self,
        excel_path: Path,
        images_path: Path,
        auth_manager: AuthManager | None = None,
        dry_run: bool = False,
    ):
        """Initialize pipeline.

        Args:
            excel_path: Path to Excel file
            images_path: Base path for product images
            auth_manager: Optional auth manager
            dry_run: If True, only validate, don't publish
        """
        self.excel_path = Path(excel_path)
        self.images_path = Path(images_path)
        self.dry_run = dry_run

        # Layer 1: Parser
        self.parser = DynamicExcelParser()

        # Layer 3: API components
        self.client = MLApiClient(auth_manager)
        self.resolver = CategoryResolver(self.client)
        self.publisher = Publisher(
            api_client=self.client,
            category_resolver=self.resolver,
            images_base_path=self.images_path,
            dry_run=dry_run,
        )

        # Results
        self.products: list[Product] = []
        self.results: list[dict] = []

    def parse_excel(self) -> list[Product]:
        """Layer 1: Parse Excel with dynamic header detection."""
        logger.info(f"Parsing Excel: {self.excel_path}")
        self.products = self.parser.parse(self.excel_path)
        logger.info(f"Parsed {len(self.products)} products")
        return self.products

    def validate_products(self) -> tuple[bool, list[str]]:
        """Validate all products."""
        errors = []

        for product in self.products:
            if not product.sku:
                errors.append("Missing SKU")
            if not product.title:
                errors.append("Missing title")
            if product.price <= 0:
                errors.append(f"Invalid price for {product.sku}")
            if product.available_quantity < 1:
                errors.append(f"Invalid quantity for {product.sku}")

        return len(errors) == 0, errors

    def publish(
        self,
        category_name: str,
        batch_size: int = 100,
    ) -> dict:
        """Layer 3: Publish products to ML.

        Args:
            category_name: Category name (e.g., "Livros")
            batch_size: Number of products per batch

        Returns:
            Publication results
        """
        if not self.products:
            logger.warning("No products to publish")
            return {"published": 0, "failed": 0, "errors": ["No products"]}

        logger.info(f"Publishing {len(self.products)} products to category: {category_name}")

        # Use publisher for all products
        published, failed, errors = self.publisher.publish_products(
            self.products,
            category_name,
        )

        stats = self.publisher.get_stats()
        logger.info(f"Published: {stats['published']}, Failed: {stats['failed']}")

        return stats

    def run(
        self,
        category_name: str,
        validate_only: bool = False,
    ) -> dict:
        """Run full pipeline.

        Args:
            category_name: Category name for all products
            validate_only: If True, only parse and validate

        Returns:
            Pipeline results
        """
        # Layer 1: Parse
        self.parse_excel()

        if not self.products:
            return {"status": "error", "error": "No products parsed"}

        # Layer 2: Validate
        is_valid, errors = self.validate_products()
        if not is_valid:
            return {"status": "error", "errors": errors}

        if validate_only or self.dry_run:
            return {
                "status": "validated",
                "products": len(self.products),
                "errors": errors if errors else None,
            }

        # Layer 3: Publish
        results = self.publish(category_name)

        return {
            "status": "completed",
            "products": len(self.products),
            **results,
        }

    def get_column_mapping(self) -> dict[str, str]:
        """Get detected column mapping (for debugging)."""
        return self.parser.get_column_mapping()
