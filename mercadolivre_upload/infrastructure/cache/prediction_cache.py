"""Cache for category predictions from domain discovery.

Simple TTL-based cache using hash-based filenames for safety.
"""

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any
from ml_workflow_contracts.runtime_paths import resolve_ml_bot_paths

logger = logging.getLogger(__name__)


class PredictionCache:
    """TTL-based cache for domain discovery predictions."""

    def __init__(  # noqa: D107
        self, cache_dir: str | None = None, ttl_seconds: int = 86400
    ):
        default_cache_dir = (
            resolve_ml_bot_paths().cache_root / "scriptml" / "mercadolivre" / "categories" / "predictions"
        )
        self.cache_dir = Path(cache_dir) if cache_dir is not None else default_cache_dir
        self.ttl_seconds = ttl_seconds
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _get_cache_path(self, title: str, site_id: str) -> Path:
        """Hash-based filename to avoid filesystem issues with special chars."""
        key = f"{site_id}:{title}".encode()
        digest = hashlib.sha256(key).hexdigest()[:16]
        return self.cache_dir / f"{site_id}_{digest}.json"

    def get(self, title: str, site_id: str = "MLB") -> list[dict[str, Any]] | None:
        """Return cached predictions for a title, or None if expired/missing."""
        cache_path = self._get_cache_path(title, site_id)
        if not cache_path.exists():
            return None

        try:
            with open(cache_path, encoding="utf-8") as f:
                data = json.load(f)

            age = time.time() - data.get("cached_at", 0)
            if age > self.ttl_seconds:
                logger.debug("Prediction cache expired for '%s...'", title[:30])
                return None

            logger.debug("Using cached prediction for '%s...'", title[:30])
            return data.get("predictions", [])  # type: ignore[no-any-return]

        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to read prediction cache: %s", e)
            return None

    def set(self, title: str, predictions: list[dict[str, Any]], site_id: str = "MLB") -> None:
        """Store predictions in the cache."""
        cache_path = self._get_cache_path(title, site_id)
        try:
            data = {
                "title": title,
                "site_id": site_id,
                "cached_at": time.time(),
                "predictions": predictions,
            }
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except OSError as e:
            logger.warning("Failed to write prediction cache: %s", e)

    def clear_expired(self) -> int:
        """Remove expired cache files and return count removed."""
        removed = 0
        now = time.time()
        for cache_file in self.cache_dir.glob("*.json"):
            try:
                with open(cache_file, encoding="utf-8") as f:
                    data = json.load(f)
                if now - data.get("cached_at", 0) > self.ttl_seconds:
                    cache_file.unlink()
                    removed += 1
            except (json.JSONDecodeError, OSError):
                pass
        return removed
