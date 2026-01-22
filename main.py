import argparse
import logging
import sys
from auth import TokenManager
from ml_api import MLAPI
from publish import read_items, publish_items


def setup_logging():
    """Configure logging for the application."""
    logging.basicConfig(
        level=logging.INFO,  # Back to INFO for cleaner output
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler("bot.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def main():
    parser = argparse.ArgumentParser(description="MercadoLibre Bot")
    parser.add_argument(
        "--items_file",
        default="items.json",
        help="Path to the file containing items to publish (default: items.json)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run in dry-run mode (validate only, do not publish)",
    )
    args = parser.parse_args()

    setup_logging()
    logger = logging.getLogger(__name__)

    logger.info("=" * 50)
    logger.info("Starting MercadoLibre Bot")
    if args.dry_run:
        logger.info("MODE: DRY-RUN (No changes will be sent to API)")
    logger.info("=" * 50)

    try:
        # Initialize token manager
        logger.info("Initializing token manager...")
        token_manager = TokenManager()

        # Initialize API
        logger.info("Initializing MercadoLibre API...")
        api = MLAPI(token_manager)

        # Read items from file
        logger.info(f"Reading items from file: {args.items_file}")
        items = read_items(args.items_file)

        # Publish items
        logger.info("Starting item publication...")
        publish_items(api, items, dry_run=args.dry_run)

        logger.info("=" * 50)
        logger.info("Bot execution completed successfully")
        logger.info("=" * 50)

    except FileNotFoundError as e:
        logger.error(f"File not found: {e}")
        print(f"\n[!] Error: {e}")
        sys.exit(1)

    except ValueError as e:
        logger.error(f"Invalid data: {e}")
        print(f"\n[!] Error: {e}")
        sys.exit(1)

    except KeyboardInterrupt:
        print("\n[STOP] Execution stopped by user.")
        sys.exit(0)

    except Exception as e:
        logger.exception(f"Unexpected error occurred: {e}")
        print(f"\n[!] Unexpected error: {e}")
        sys.exit(1)

    except ValueError as e:
        logger.error(f"Invalid data: {e}")
        print(f"\n[!] Error: {e}")
        sys.exit(1)

    except KeyboardInterrupt:
        print("\n[STOP] Execution stopped by user.")
        sys.exit(0)

    except Exception as e:
        logger.exception(f"Unexpected error occurred: {e}")
        print(f"\n[!] Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
