"""Image uploader adapter.

Infrastructure adapter for uploading images to ML.
"""

import logging
from pathlib import Path

from mercadolivre_upload.api.client import MLApiClient

logger = logging.getLogger(__name__)


class ImageUploader:
    """Uploads product images to ML.

    Implements ImageUploaderPort for the application layer.
    """

    def __init__(self, client: MLApiClient, images_base_path: Path):
        """Initialize with API client and image path.

        Args:
            client: ML API client
            images_base_path: Base directory for product images
        """
        self.client = client
        self.images_base_path = Path(images_base_path)
        self._cache: dict[str, list[str]] = {}  # SKU -> URLs cache

    def upload_images(self, sku: str) -> list[str]:
        """Upload images for a product SKU.

        Args:
            sku: Product SKU

        Returns:
            List of uploaded image URLs
        """
        if sku in self._cache:
            return self._cache[sku]

        sku_folder = self.images_base_path / sku

        if not sku_folder.exists():
            logger.warning(f"Image folder not found: {sku_folder}")
            return []

        urls = []
        for image_file in sku_folder.iterdir():
            if image_file.suffix.lower() in [".jpg", ".jpeg", ".png", ".gif"]:
                try:
                    result = self.client.upload_image(str(image_file))
                    # ML API returns secure_url inside variations array
                    if "variations" in result and result["variations"]:
                        url = result["variations"][0].get("secure_url") or result["variations"][0].get("url")
                        if url:
                            urls.append(url)
                        else:
                            logger.error(f"No URL found in response for {image_file}")
                    elif "secure_url" in result:
                        urls.append(result["secure_url"])
                    elif "url" in result:
                        urls.append(result["url"])
                    else:
                        logger.error(f"Unexpected response format for {image_file}: {result}")
                except Exception as e:
                    logger.error(f"Failed to upload {image_file}: {e}")

        self._cache[sku] = urls
        return urls
