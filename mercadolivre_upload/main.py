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

from mercadolivre_upload.adapters.image_uploader import ImageUploader
from mercadolivre_upload.adapters.spreadsheet.parser import SpreadsheetParser
from mercadolivre_upload.api.category_adapter import CategoryAdapter
from mercadolivre_upload.api.client import MLApiClient
from mercadolivre_upload.application.publish_product import PublishProductUseCase
from mercadolivre_upload.auth import AuthManager
from mercadolivre_upload.domain.category.resolver import CategoryResolver

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
        default="Livros",
        help="Category name (default: Livros)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate only, don't publish",
    )

    args = parser.parse_args()

    # Initialize infrastructure (outer layer)
    auth_manager = AuthManager()
    api_client = MLApiClient(auth_manager)

    # Initialize adapters
    category_adapter = CategoryAdapter(api_client)
    image_uploader = ImageUploader(api_client, Path(args.images))

    # Initialize domain (inner layer - business logic)
    category_resolver = CategoryResolver(category_adapter)

    # Initialize application layer (orchestration)
    use_case = PublishProductUseCase(
        category_resolver=category_resolver,
        publisher=api_client,
        image_uploader=image_uploader,
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
