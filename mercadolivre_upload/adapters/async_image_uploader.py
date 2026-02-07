"""Async image uploader implementation used by tests."""

from __future__ import annotations

import asyncio
import base64
import logging
from pathlib import Path
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)


class AsyncImageUploader:
    """Async uploader compatible with unit tests."""

    def __init__(
        self,
        api_base_url: str = "https://api.mercadolivre.com",
        max_concurrent: int = 5,
        timeout: int = 30,
    ):
        """Initialize async uploader with connection settings."""
        self.api_base_url = api_base_url
        self.max_concurrent = max_concurrent
        self.timeout = timeout
        self._session: aiohttp.ClientSession | None = None
        self._upload_results: list[dict[str, Any]] = []

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=self.timeout)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    async def close(self) -> None:
        """Close the HTTP session."""
        if self._session:
            if not self._session.closed:
                await self._session.close()
            self._session = None

    async def validate_image_async(self, path: str) -> bool:
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

    async def read_image_async(self, path: str) -> bytes:
        """Read image file contents as bytes."""
        return Path(path).read_bytes()

    async def upload_single(
        self, path: str, auth_token: str | None = None, product_id: str | None = None
    ) -> dict[str, Any]:
        """Upload a single image via the API."""
        if not await self.validate_image_async(path):
            return {"success": False, "error": "Invalid image"}
        try:
            content = await self.read_image_async(path)
        except Exception as exc:
            logger.error("Failed to read image", exc_info=exc)
            return {"success": False, "error": str(exc)}

        session = await self._get_session()
        payload = {"image": base64.b64encode(content).decode()}
        headers = {}
        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"
        if product_id:
            headers["X-Product-ID"] = str(product_id)
        try:
            async with session.post(
                f"{self.api_base_url}/images", json=payload, headers=headers
            ) as response:
                if response.status == 401:
                    return {"success": False, "error": "Unauthorized"}
                if response.status == 413:
                    return {"success": False, "error": "File too large"}
                if response.status >= 400:
                    return {"success": False, "error": f"HTTP {response.status}"}
                data = await response.json()
                result = {"success": True, **data}
        except TimeoutError:
            logger.error("Upload timeout")
            return {"success": False, "error": "Timeout"}
        except aiohttp.ClientError as exc:
            logger.error("Upload failed", exc_info=exc)
            return {"success": False, "error": f"Client error: {exc}"}
        except Exception as exc:
            logger.error("Unexpected error", exc_info=exc)
            return {"success": False, "error": str(exc)}

        self._upload_results.append(result)
        return result

    async def upload_batch(self, paths: list[str]) -> list[dict[str, Any]]:
        """Upload multiple images concurrently."""
        semaphore = asyncio.Semaphore(self.max_concurrent)

        async def _wrap(path: str) -> dict[str, Any]:
            async with semaphore:
                try:
                    return await self.upload_single(path)
                except Exception as exc:
                    return {"success": False, "error": str(exc)}

        return await asyncio.gather(*[_wrap(path) for path in paths])

    def get_results(self) -> list[dict[str, Any]]:
        """Return list of upload results."""
        return list(self._upload_results)

    async def __aenter__(self) -> AsyncImageUploader:
        """Enter async context manager."""
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # type: ignore[no-untyped-def]
        """Exit async context manager and close session."""
        await self.close()
