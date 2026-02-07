"""Clip uploader adapter.

Infrastructure adapter for uploading video clips to ML items.
Discovers, validates, and uploads video files from anuncios/<sku>/ directories.
"""

import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import requests

from mercadolivre_upload.api.client import MLApiClient
from mercadolivre_upload.domain.validation.clip_validator import (
    SUPPORTED_EXTENSIONS,
    ClipValidator,
)

logger = logging.getLogger(__name__)


@dataclass
class ClipUploadResult:
    """Result of a single clip upload attempt."""

    file: str
    clip_uuid: str | None = None
    status: str = "pending"
    error: str | None = None


@dataclass
class ClipUploadSummary:
    """Aggregated results for all clips of a SKU."""

    item_id: str
    clips_uploaded: int = 0
    clips_failed: int = 0
    clips_skipped: int = 0
    results: list[ClipUploadResult] = field(default_factory=list)


class ClipUploader:
    """Uploads video clips to ML items after publication.

    Discovers video files in anuncios/<sku>/, validates them,
    and uploads via the ML clips API.
    """

    def __init__(
        self,
        client: MLApiClient,
        base_path: str | Path = "anuncios",
        validator: ClipValidator | None = None,
    ):
        """Initialize with API client and base path for video discovery.

        Args:
            client: ML API client instance
            base_path: Root directory containing SKU subfolders with media
            validator: Optional ClipValidator (created with defaults if None)
        """
        self.client = client
        self.base_path = Path(base_path)
        self.validator = validator or ClipValidator()
        self._hash_cache: dict[str, str] = {}

    def find_clips_for_sku(self, sku: str) -> list[Path]:
        """Discover all video files for a given SKU.

        Looks in base_path/<sku>/ for supported video extensions.

        Args:
            sku: Product SKU identifier

        Returns:
            Sorted list of video file paths found
        """
        sku_dir = self.base_path / str(sku)
        if not sku_dir.exists():
            return []

        clips = sorted(
            f for f in sku_dir.iterdir() if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS
        )
        return clips

    def _calculate_hash(self, path: Path) -> str:
        """Calculate MD5 hash for deduplication."""
        if str(path) in self._hash_cache:
            return self._hash_cache[str(path)]
        content = path.read_bytes()
        file_hash = hashlib.md5(content).hexdigest()  # noqa: S324
        self._hash_cache[str(path)] = file_hash
        return file_hash

    def upload_clip_for_item(
        self,
        item_id: str,
        video_path: Path,
        sites: list[dict[str, Any]] | None = None,
    ) -> ClipUploadResult:
        """Upload a single video clip for a published item.

        Args:
            item_id: Published ML item ID
            video_path: Path to the video file
            sites: Optional list of target sites

        Returns:
            ClipUploadResult with status and clip_uuid
        """
        result = ClipUploadResult(file=video_path.name)

        # Validate with ClipValidator
        validation = self.validator.validate(video_path)
        if not validation.is_valid:
            error_msg = "; ".join(validation.errors)
            logger.warning(f"Clip validation failed for {video_path.name}: {error_msg}")
            result.status = "validation_failed"
            result.error = error_msg
            return result

        for warning in validation.warnings:
            logger.info(f"Clip warning ({video_path.name}): {warning}")

        try:
            logger.info(f"Uploading clip for item {item_id}: {video_path.name}")
            api_result = self.client.upload_clip(
                item_id=item_id,
                file_path=str(video_path),
                sites=sites,
            )

            clip_uuid = api_result.get("clip_uuid")
            if clip_uuid:
                result.clip_uuid = clip_uuid
                result.status = api_result.get("status", "accepted")
                logger.info(
                    f"Clip uploaded for {item_id}: {clip_uuid} " f"(status: {result.status})"
                )
            else:
                result.status = "error"
                result.error = "API response missing clip_uuid"
                logger.error(f"Clip upload response missing clip_uuid: {api_result}")

        except requests.HTTPError as e:
            status_code = e.response.status_code if e.response else "unknown"
            try:
                error_body = e.response.json() if e.response else {}
                error_msg = error_body.get("message", str(error_body))
            except Exception:
                error_msg = e.response.text if e.response else str(e)
            result.status = "http_error"
            result.error = f"[{status_code}] {error_msg}"
            logger.error(f"HTTP error uploading clip for {item_id}: {result.error}")

        except Exception as e:
            result.status = "error"
            result.error = f"{type(e).__name__}: {e}"
            logger.error(
                f"Unexpected error uploading clip for {item_id}: {result.error}",
                exc_info=True,
            )

        return result

    def upload_clips(
        self,
        sku: str,
        item_id: str,
        sites: list[dict[str, Any]] | None = None,
    ) -> ClipUploadSummary:
        """Discover, validate, and upload all clips for a SKU.

        This is the main entry point. Called after item publication.

        Args:
            sku: Product SKU for video discovery
            item_id: CBT parent item ID (required, must start with 'CBT')
            sites: Optional list of target sites

        Returns:
            ClipUploadSummary with per-clip results
        """
        summary = ClipUploadSummary(item_id=item_id)

        # Clips require CBT parent IDs (Global Selling)
        if not item_id.startswith("CBT"):
            logger.warning(
                f"Skipping clip upload for {sku}: item_id '{item_id}' is not a CBT parent. "
                f"Clips API requires CBT IDs from Global Selling items."
            )
            return summary

        clips = self.find_clips_for_sku(sku)
        if not clips:
            return summary

        seen_hashes: set[str] = set()
        for clip_path in clips:
            # Deduplication by hash
            file_hash = self._calculate_hash(clip_path)
            if file_hash in seen_hashes:
                logger.info(f"Skipping duplicate clip: {clip_path.name}")
                summary.clips_skipped += 1
                summary.results.append(
                    ClipUploadResult(
                        file=clip_path.name,
                        status="skipped_duplicate",
                    )
                )
                continue
            seen_hashes.add(file_hash)

            result = self.upload_clip_for_item(item_id, clip_path, sites)
            summary.results.append(result)

            if result.clip_uuid:
                summary.clips_uploaded += 1
            elif result.status == "validation_failed":
                summary.clips_skipped += 1
            else:
                summary.clips_failed += 1

        logger.info(
            f"Clips for {sku}: "
            f"{summary.clips_uploaded} uploaded, "
            f"{summary.clips_failed} failed, "
            f"{summary.clips_skipped} skipped"
        )
        return summary
