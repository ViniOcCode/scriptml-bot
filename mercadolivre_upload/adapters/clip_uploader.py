"""Clip uploader adapter.

Infrastructure adapter for uploading video clips to ML.
"""

import logging
from pathlib import Path
import requests

from mercadolivre_upload.api.client import MLApiClient

logger = logging.getLogger(__name__)

# Supported video extensions
SUPPORTED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".mpeg", ".avi"}


class ClipUploader:
    """Uploads video clips to ML items.

    Implements ClipUploaderPort for the application layer.
    """

    def __init__(self, client: MLApiClient):
        """Initialize with API client.

        Args:
            client: ML API client
        """
        self.client = client

    def upload_clip_for_item(
        self,
        item_id: str,
        video_path: Path,
        sites: list[dict] | None = None,
    ) -> str | None:
        """Upload a video clip for a published item.

        Args:
            item_id: Mercado Livre item ID (e.g., MLB1234567890)
            video_path: Path to the video file
            sites: Optional list of sites for clip visibility

        Returns:
            Clip UUID on success, None on failure
        """
        # Validate file exists
        if not video_path.exists():
            logger.error(f"Video file not found: {video_path}")
            return None

        # Validate extension
        if video_path.suffix.lower() not in SUPPORTED_VIDEO_EXTENSIONS:
            logger.error(
                f"Unsupported video format: {video_path.suffix}. "
                f"Supported: {SUPPORTED_VIDEO_EXTENSIONS}"
            )
            return None

        try:
            logger.info(f"Uploading clip for item {item_id}: {video_path.name}")
            result = self.client.upload_clip(
                item_id=item_id,
                file_path=str(video_path),
                sites=sites,
            )

            # Extract clip UUID from response
            clip_uuid = result.get("clip_uuid")
            if clip_uuid:
                status = result.get("status", "unknown")
                logger.info(
                    f"Clip uploaded successfully for {item_id}: {clip_uuid} (status: {status})"
                )
                return clip_uuid
            else:
                logger.error(
                    f"Clip upload API response missing 'clip_uuid' field. "
                    f"Item: {item_id}, Response: {result}. "
                    f"This may indicate API version mismatch."
                )
                return None

        except requests.HTTPError as e:
            status_code = e.response.status_code if e.response else "unknown"
            try:
                error_body = e.response.json() if e.response else {}
            except Exception:
                error_body = e.response.text if e.response else str(e)
            logger.error(
                f"HTTP error uploading clip for {item_id}: "
                f"status={status_code}, error={error_body}, "
                f"video={video_path.name}, sites={sites}"
            )
            return None
        except Exception as e:
            logger.error(
                f"Unexpected error uploading clip for {item_id}: {type(e).__name__}: {e}, "
                f"video={video_path.name}, sites={sites}",
                exc_info=True
            )
            return None

    @staticmethod
    def find_video_file(directory: Path, sku: str | None = None) -> Path | None:
        """Find a video file in a directory.

        Args:
            directory: Directory to search in
            sku: Optional SKU to search in SKU-specific subfolder first

        Returns:
            Path to video file if found, None otherwise
        """
        # Try SKU-specific folder first
        if sku:
            sku_folder = directory / sku
            if sku_folder.exists():
                for file in sku_folder.iterdir():
                    if file.suffix.lower() in SUPPORTED_VIDEO_EXTENSIONS:
                        logger.debug(f"Found video file for {sku}: {file}")
                        return file

        # Fallback to base directory
        if directory.exists():
            for file in directory.iterdir():
                if file.suffix.lower() in SUPPORTED_VIDEO_EXTENSIONS:
                    logger.debug(f"Found video file in base dir: {file}")
                    return file

        return None
