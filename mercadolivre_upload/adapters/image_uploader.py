"""Image uploader adapter."""

import base64
import hashlib
import logging
import tempfile
from pathlib import Path
from typing import Any
from uuid import uuid4

import requests

from mercadolivre_upload.api.client import MLApiClient

logger = logging.getLogger(__name__)


class ImageUploader:
    """Uploads product images to ML."""

    def __init__(
        self,
        api_client: MLApiClient | None = None,
        base_path: str | Path | None = None,
    ):
        """Initialize uploader.

        Args:
            api_client: Optional ML API client
            base_path: Base directory for product images.
                Defaults to a uploads folder in the system temporary directory.
        """
        self.api_client = api_client
        resolved_base_path = (
            Path(base_path) if base_path is not None else Path(tempfile.gettempdir()) / "uploads"
        )
        self.base_path = resolved_base_path
        self.base_path.mkdir(parents=True, exist_ok=True)
        self._uploaded_images: list[dict[str, Any]] = []
        self._hash_cache: dict[str, dict[str, Any]] = {}

    def upload_images(self, sku: str) -> list[str]:
        """Upload all images for a SKU and return URLs."""
        results = self.upload_batch([str(p) for p in self._iter_images_for_sku(sku)])
        # Filter by success AND valid url
        return [result["url"] for result in results if result.get("success") and result.get("url")]

    def _iter_images_for_sku(self, sku: str) -> list[Path]:
        sku_folder = self.base_path / sku
        if not sku_folder.exists():
            logger.warning(f"Image folder not found: {sku_folder}, using base folder")
            sku_folder = self.base_path
        if not sku_folder.exists():
            logger.warning(f"Base image folder not found: {sku_folder}")
            return []
        return [
            path
            for path in sku_folder.iterdir()
            if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".gif", ".webp"}
        ]

    def validate_image(self, path: str) -> bool:
        """Validate image file exists, type, and size."""
        file_path = Path(path)
        if not file_path.exists():
            logger.error("Image not found")
            return False
        if not file_path.is_file():
            logger.error("Path is not a file")
            return False
        if file_path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".gif", ".webp"}:
            logger.error("Invalid image extension")
            return False
        if file_path.stat().st_size > 10 * 1024 * 1024:
            logger.error("Image too large")
            return False
        return True

    def calculate_hash(self, path: str) -> str:
        """Return SHA-256 hash of file contents for dedup."""
        content = Path(path).read_bytes()
        return hashlib.sha256(content).hexdigest()

    def encode_base64(self, path: str) -> str:
        """Encode image file as base64 string."""
        return base64.b64encode(Path(path).read_bytes()).decode()

    def upload(self, path: str, product_id: str | None = None) -> dict[str, Any]:
        """Upload a single image and return result payload."""
        if not self.validate_image(path):
            raise ValueError("Invalid image")
        image_hash = self.calculate_hash(path)
        if image_hash in self._hash_cache:
            return self._hash_cache[image_hash]

        if self.api_client:
            try:
                result = self.api_client.upload_image(path)
                payload = {
                    "success": True,
                    "url": result.get("secure_url") or result.get("url"),
                    "id": result.get("id"),
                    "hash": image_hash,
                    "filename": Path(path).name,
                }
            except (
                requests.RequestException,
                RuntimeError,
                ValueError,
                TypeError,
                OSError,
            ) as exc:
                logger.error("API upload failed", exc_info=exc)
                return {"success": False, "error": str(exc)}
        else:
            payload = {
                "success": True,
                "url": f"https://ml.com/images/{uuid4().hex}",
                "id": uuid4().hex,
                "hash": image_hash,
                "filename": Path(path).name,
            }

        if product_id:
            payload["product_id"] = product_id
        self._hash_cache[image_hash] = payload
        self._uploaded_images.append(payload)
        return payload

    def upload_batch(self, paths: list[str], product_id: str | None = None) -> list[dict[str, Any]]:
        """Upload multiple images and return results."""
        results = []
        for path in paths:
            try:
                result = self.upload(path, product_id=product_id)
            except ValueError as exc:
                result = {"success": False, "error": str(exc)}
            results.append(result)
        return results

    def get_uploaded_images(self) -> list[dict[str, Any]]:
        """Return list of uploaded image records."""
        return list(self._uploaded_images)

    def clear_upload_history(self) -> None:
        """Clear uploaded images and hash cache."""
        self._uploaded_images = []
        self._hash_cache = {}

    def delete_local_copy(self, path: str) -> bool:
        """Delete local image file after upload."""
        file_path = Path(path)
        if not file_path.exists():
            return False
        if not file_path.is_file():
            return False
        try:
            file_path.unlink()
        except OSError as exc:
            logger.error("Failed to delete file", exc_info=exc)
            return False
        return True
