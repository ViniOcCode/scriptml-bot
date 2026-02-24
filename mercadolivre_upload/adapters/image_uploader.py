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

    @staticmethod
    def _extract_diagnostic_detection_names(response: Any) -> list[str]:
        """Extract unique diagnostic detection names from API response."""
        if not isinstance(response, dict):
            return []
        diagnostics = response.get("diagnostics", [])
        if not isinstance(diagnostics, list):
            return []

        names: list[str] = []
        for diagnostic in diagnostics:
            if not isinstance(diagnostic, dict):
                continue
            detections = diagnostic.get("detections", [])
            if not isinstance(detections, list):
                continue
            for detection in detections:
                if not isinstance(detection, dict):
                    continue
                name = detection.get("name")
                if isinstance(name, str) and name and name not in names:
                    names.append(name)
        return names

    def diagnose_images(
        self,
        *,
        sku: str,
        category_id: str,
        title: str | None,
        picture_urls: list[str],
        picture_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Run optional diagnostics for uploaded images."""
        artifact: dict[str, Any] = {
            "status": "unavailable",
            "available": False,
            "checked": 0,
            "issues": [],
            "results": [],
        }

        if not picture_urls:
            artifact["status"] = "skipped"
            return artifact

        if self.api_client is None:
            message = f"Image diagnostics unavailable for {sku}: API client not configured."
            logger.warning(message)
            artifact["message"] = message
            return artifact

        diagnose_picture = getattr(self.api_client, "diagnose_picture", None)
        if not callable(diagnose_picture):
            message = f"Image diagnostics unavailable for {sku}: client has no diagnose_picture."
            logger.warning(message)
            artifact["message"] = message
            return artifact

        issues: list[str] = []
        results: list[dict[str, Any]] = []
        had_errors = False

        for index, picture_url in enumerate(picture_urls):
            picture_id = None
            if isinstance(picture_ids, list) and index < len(picture_ids):
                candidate = picture_ids[index]
                if isinstance(candidate, str) and candidate:
                    picture_id = candidate

            context: dict[str, Any] = {
                "category_id": category_id,
                "picture_type": "thumbnail" if index == 0 else "other",
            }
            if isinstance(title, str) and title.strip():
                context["title"] = title.strip()

            diagnose_kwargs: dict[str, Any] = {"context": context}
            if picture_id:
                diagnose_kwargs["picture_id"] = picture_id
            else:
                diagnose_kwargs["picture_url"] = picture_url

            try:
                response = diagnose_picture(**diagnose_kwargs)
            except Exception as exc:
                status_code = getattr(getattr(exc, "response", None), "status_code", None)
                if isinstance(status_code, int) and status_code in {404, 405, 501}:
                    message = (
                        "Image diagnostics endpoint unavailable "
                        f"(status {status_code}) for {sku}; continuing without diagnostic gate."
                    )
                    logger.warning(message)
                    artifact["message"] = message
                    artifact["issues"] = issues
                    artifact["results"] = results
                    artifact["checked"] = len(results)
                    return artifact

                logger.warning(
                    "Image diagnostics failed for %s picture %s: %s",
                    sku,
                    index + 1,
                    exc,
                )
                had_errors = True
                results.append(
                    {
                        "index": index,
                        "picture_url": picture_url,
                        "picture_id": picture_id,
                        "status": "error",
                        "error": str(exc),
                    }
                )
                continue

            detections = self._extract_diagnostic_detection_names(response)
            if detections:
                issues.append(f"Picture {index + 1} diagnostic issues: {', '.join(detections)}")
            results.append(
                {
                    "index": index,
                    "picture_url": picture_url,
                    "picture_id": picture_id,
                    "status": "issues" if detections else "ok",
                    "detections": detections,
                }
            )

        artifact["available"] = True
        artifact["checked"] = len(results)
        artifact["issues"] = issues
        artifact["results"] = results
        if issues:
            artifact["status"] = "failed"
        elif had_errors:
            artifact["status"] = "partial"
        else:
            artifact["status"] = "passed"
        return artifact

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
