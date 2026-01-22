"""
Error Collector module for managing and persisting publish errors.

This module provides the ErrorCollector class which collects failed items
during the publish process and saves them to timestamped JSON files.
"""

import os
import json
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

ERRORS_DIR = "errors"


class ErrorCollector:
    """
    Collects publish errors and saves them to JSON files with full item data
    and human-readable error comments.

    Usage:
        collector = ErrorCollector()
        collector.add_error(item, "Validation failed: missing BRAND attribute")
        collector.save()  # Saves to errors/publish_errors_YYYY-MM-DD_HHMMSS.json
    """

    def __init__(self, errors_dir: str = ERRORS_DIR):
        self.errors_dir = errors_dir
        self.errors: list[dict] = []
        self.total_items: int = 0
        self.run_timestamp: datetime = datetime.now()

    def set_total_items(self, count: int) -> None:
        """Set the total number of items being processed."""
        self.total_items = count

    def add_error(self, item: dict, error_message: str) -> None:
        """
        Add a failed item with its error comment.

        Args:
            item: The original item dict that failed to publish
            error_message: Human-readable explanation of why it failed
        """
        # Create a copy to avoid mutating the original
        failed_item = item.copy()

        # Add the error comment field
        failed_item["_error_comment"] = error_message

        self.errors.append(failed_item)
        logger.debug(
            f"Error collected for item '{item.get('title', 'Unknown')}': {error_message}"
        )

    @property
    def failed_count(self) -> int:
        """Return the number of failed items."""
        return len(self.errors)

    @property
    def has_errors(self) -> bool:
        """Check if there are any errors to save."""
        return len(self.errors) > 0

    def _ensure_directory(self) -> None:
        """Create the errors directory if it doesn't exist."""
        if not os.path.exists(self.errors_dir):
            os.makedirs(self.errors_dir)
            logger.info(f"Created errors directory: {self.errors_dir}")

    def _generate_filename(self) -> str:
        """Generate a timestamped filename for the error file."""
        timestamp = self.run_timestamp.strftime("%Y-%m-%d_%H%M%S")
        return f"publish_errors_{timestamp}.json"

    def save(self, filepath: Optional[str] = None) -> Optional[str]:
        """
        Save collected errors to a JSON file.

        Args:
            filepath: Optional custom filepath. If not provided, generates
                     a timestamped file in the errors directory.

        Returns:
            The filepath where errors were saved, or None if no errors.
        """
        if not self.has_errors:
            logger.info("No errors to save")
            return None

        self._ensure_directory()

        if filepath is None:
            filepath = os.path.join(self.errors_dir, self._generate_filename())

        # Build the output structure
        output = {
            "run_timestamp": self.run_timestamp.isoformat(),
            "total_items": self.total_items,
            "failed_count": self.failed_count,
            "success_count": self.total_items - self.failed_count,
            "errors": self.errors,
        }

        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(output, f, ensure_ascii=False, indent=2)

            logger.info(f"Saved {self.failed_count} error(s) to {filepath}")
            return filepath

        except Exception as e:
            logger.error(f"Failed to save errors to {filepath}: {e}")
            return None

    def clear(self) -> None:
        """Clear all collected errors (useful for testing or reset)."""
        self.errors = []
        self.total_items = 0
        self.run_timestamp = datetime.now()

    def get_summary(self) -> dict:
        """
        Get a summary of the error collection.

        Returns:
            Dict with counts and status information.
        """
        return {
            "total_items": self.total_items,
            "failed_count": self.failed_count,
            "success_count": self.total_items - self.failed_count,
            "has_errors": self.has_errors,
            "run_timestamp": self.run_timestamp.isoformat(),
        }
