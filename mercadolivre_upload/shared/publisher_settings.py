"""Canonical publisher configuration snapshot loading."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import yaml

from mercadolivre_upload.auth.exceptions import AuthError

_SECRET_KEYS = frozenset(
    {
        "access_token",
        "api_key",
        "client_secret",
        "password",
        "refresh_token",
        "secret",
        "token",
    }
)


def _reject_embedded_secrets(value: Any, *, path: str = "publisher_config") -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = str(key).strip().lower()
            if normalized in _SECRET_KEYS or normalized.endswith("_secret"):
                raise AuthError(f"{path}: secret fields are forbidden")
            _reject_embedded_secrets(nested, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _reject_embedded_secrets(nested, path=f"{path}[{index}]")


def _validate_document(raw: Any, *, source: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise AuthError(f"Publisher configuration must be an object: {source}")
    document = dict(raw)
    _reject_embedded_secrets(document)
    return document


def load_publisher_settings(settings_file: Path | None = None) -> dict[str, Any]:
    """Load the invocation snapshot, then canonical SQLite, with dev-only YAML."""
    snapshot = os.getenv("MLBOT_PUBLISHER_CONFIG_SNAPSHOT")
    if snapshot is not None:
        try:
            raw = json.loads(snapshot)
        except json.JSONDecodeError as exc:
            raise AuthError("Publisher configuration snapshot is invalid JSON") from exc
        return _validate_document(raw, source="MLBOT_PUBLISHER_CONFIG_SNAPSHOT")

    settings_db = os.getenv("MLBOT_SETTINGS_DB")
    if settings_db:
        try:
            from ml_app_settings_core import SettingsStoreError, load_settings_document
        except ImportError as exc:
            raise AuthError("Canonical settings core is unavailable") from exc
        try:
            raw = load_settings_document(
                "publisher_config",
                db_path=settings_db,
                required=True,
            )
        except SettingsStoreError as exc:
            raise AuthError("Canonical publisher configuration is unavailable") from exc
        return _validate_document(raw, source="SQLite publisher_config")

    app_env = os.getenv("APP_ENV", "").strip().lower()
    if app_env not in {"development", "test"}:
        raise AuthError("Canonical publisher configuration database is required")
    if settings_file is None:
        raise AuthError("Development publisher configuration path is required")
    try:
        raw = yaml.safe_load(settings_file.read_text(encoding="utf-8")) or {}
    except OSError as exc:
        raise AuthError(f"Could not read development publisher config: {settings_file}") from exc
    except yaml.YAMLError as exc:
        raise AuthError(f"Invalid development publisher config: {settings_file}") from exc
    return _validate_document(raw, source=str(settings_file))


__all__ = ["load_publisher_settings"]
