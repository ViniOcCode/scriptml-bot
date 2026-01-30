"""Main entry point for Mercado Livre Bulk Upload.

Clean Architecture entry point:
- Initializes adapters
- Wires dependencies
- Executes use case
"""

import argparse
import logging
import sys
from pathlib import Path

import yaml

from mercadolivre_upload.adapters.image_uploader import ImageUploader
from mercadolivre_upload.adapters.spreadsheet.parser import SpreadsheetParser
from mercadolivre_upload.api.category_adapter import CategoryAdapter
from mercadolivre_upload.api.client import MLApiClient
from mercadolivre_upload.application.publish_product import PublishProductUseCase
from mercadolivre_upload.auth import AuthManager
from mercadolivre_upload.domain.category.resolver import CategoryResolver
from mercadolivre_upload.domain.shipping.resolver import ShippingResolver
from mercadolivre_upload.infrastructure.cache.attribute_cache import AttributeCache

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Mercado Livre Bulk Upload")
    parser.add_argument(
        "--excel",
        required=True,
        help="Path to Excel file",
    )
    parser.add_argument(
        "--images",
        required=True,
        help="Path to images directory",
    )
    parser.add_argument(
        "--category",
        required=True,
        help="Category name (e.g., 'Livros', 'Eletrônicos', 'Celulares e Smartphones')",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate only, don't publish",
    )
    parser.add_argument(
        "--cache-dir",
        default="cache/categories",
        help="Directory for attribute cache",
    )
    parser.add_argument(
        "--cache-ttl",
        type=int,
        default=24,
        help="Cache TTL in hours (0 = no expiration)",
    )
    parser.add_argument(
        "--clear-cache",
        action="store_true",
        help="Clear attribute cache before running",
    )

    args = parser.parse_args()

    # Load configuration
    config_path = Path("config/generic_mappings.yaml")
    config = {}
    if config_path.exists():
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
            logger.info(f"Loaded config from {config_path}")
        except Exception as e:
            logger.warning(f"Failed to load config: {e}")

    # Initialize cache
    attribute_cache = AttributeCache(
        cache_dir=args.cache_dir,
        ttl_hours=args.cache_ttl,
    )

    # Handle clear cache option
    if args.clear_cache:
        attribute_cache.clear_cache()
        logger.info("Cache cleared")

    # Log cache info
    cache_info = attribute_cache.get_cache_info()
    logger.info(f"Cache: {cache_info['cached_categories']} categories cached")

    # Initialize infrastructure (outer layer)
    auth_manager = AuthManager()
    api_client = MLApiClient(auth_manager)

    # Initialize adapters
    category_adapter = CategoryAdapter(api_client)
    image_uploader = ImageUploader(api_client, Path(args.images))

    # Initialize domain (inner layer - business logic)
    category_resolver = CategoryResolver(
        category_adapter,
        attribute_cache=attribute_cache,
    )
    shipping_resolver = ShippingResolver(api_client)

    # Initialize application layer (orchestration)
    use_case = PublishProductUseCase(
        category_resolver=category_resolver,
        publisher=api_client,
        image_uploader=image_uploader,
        shipping_resolver=shipping_resolver,
        config=config,
        dry_run=args.dry_run,
    )

    # Parse spreadsheet (input adapter)
    logger.info(f"Parsing: {args.excel}")
    spreadsheet_parser = SpreadsheetParser()
    products = spreadsheet_parser.parse(args.excel)

    if not products:
        logger.error("No products found in spreadsheet")
        sys.exit(1)

    logger.info(f"Found {len(products)} products")

    # Execute use case
    results = use_case.execute(products, args.category)

    # Report results
    logger.info("=" * 50)
    logger.info(f"Published: {results['published']}")
    logger.info(f"Failed: {results['failed']}")

    if results['errors']:
        logger.error("Errors:")
        for error in results['errors'][:10]:
            logger.error(f"  - {error}")

    sys.exit(0 if results['success'] else 1)


if __name__ == "__main__":
    main()
