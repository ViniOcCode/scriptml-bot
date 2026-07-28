"""Strict publisher auth wiring for manifest/payload publication flows."""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mercadolivre_upload.auth.oauth import OAuthHandler
from mercadolivre_upload.auth.token_manager import TokenManager
from mercadolivre_upload.shared.publisher_settings import load_publisher_settings

from .exceptions import AuthError


@dataclass(frozen=True)
class PublisherAuthContext:
    """Resolved authentication and account binding for one publisher operation."""

    settings_file: Path
    workspace_root: Path
    token_path: str
    key_path: None
    token_manager: TokenManager
    expected_seller_id: str | None
    expected_document_type: str | None


def _read_config(settings_file: Path) -> dict[str, Any]:
    return load_publisher_settings(settings_file)


def _load_client_id(settings_file: Path, explicit_client_id: str | None = None) -> str:
    del settings_file
    try:
        from ml_app_settings_core import RuntimeSecretError, RuntimeSecretReader

        client_id = RuntimeSecretReader().require("ML_CLIENT_ID").strip()
    except (ImportError, RuntimeSecretError) as exc:
        raise AuthError("Mercado Livre client id is unavailable in the runtime snapshot") from exc
    if explicit_client_id is not None and explicit_client_id.strip() != client_id:
        raise AuthError("Requested Mercado Livre client id does not match the runtime snapshot")
    return client_id


def _active_oauth_identity(
    database_path: Path,
    *,
    expected_seller_id: str | None,
    expected_document_type: str | None,
) -> tuple[str, str, str]:
    """Resolve one active profile and its dashboard-confirmed OAuth identity."""
    profile_slug = os.getenv("MLBOT_SECRET_PROFILE", "default").strip() or "default"
    try:
        with closing(sqlite3.connect(database_path)) as connection:
            profiles = connection.execute(
                "SELECT id,slug FROM integration_profiles WHERE active=1"
            ).fetchall()
            if len(profiles) != 1 or str(profiles[0][1]) != profile_slug:
                raise AuthError("Active integration profile does not match the worker profile")
            profile_id = str(profiles[0][0])
            row = connection.execute(
                "SELECT value_json FROM dashboard_settings WHERE key=?",
                (f"ml_oauth_active_identity:{profile_id}",),
            ).fetchone()
    except sqlite3.Error as exc:
        raise AuthError("Could not resolve the active OAuth identity") from exc
    if row is None:
        raise AuthError("Confirmed Mercado Livre OAuth identity is missing")
    try:
        identity = json.loads(str(row[0]))
    except json.JSONDecodeError as exc:
        raise AuthError("Confirmed Mercado Livre OAuth identity is invalid") from exc
    if not isinstance(identity, dict):
        raise AuthError("Confirmed Mercado Livre OAuth identity is invalid")
    seller_id = str(identity.get("seller_id") or "").strip()
    document_type = str(identity.get("document_type") or "").strip().upper()
    if not seller_id or not document_type:
        raise AuthError("Confirmed Mercado Livre OAuth identity is incomplete")
    if expected_seller_id and seller_id != expected_seller_id.strip():
        raise AuthError("Confirmed OAuth seller does not match the requested seller")
    if expected_document_type and document_type != expected_document_type.strip().upper():
        raise AuthError("Confirmed OAuth taxpayer document does not match the requested document")
    return profile_id, seller_id, document_type


def build_publisher_auth_context(
    *,
    settings_file: Path,
    workspace_root: Path | None,
    strict: bool = True,
    ml_client_id: str | None = None,
    expected_seller_id: str | None = None,
    expected_document_type: str | None = None,
) -> PublisherAuthContext:
    """Build the only auth context used by real publisher commands."""
    resolved_settings = Path(settings_file).expanduser().resolve()
    if strict and workspace_root is None:
        raise AuthError("workspace_root is required for publication flows")
    if workspace_root is None:
        raise AuthError("workspace_root is required")
    resolved_workspace = Path(workspace_root).expanduser().resolve()

    client_id = _load_client_id(resolved_settings, ml_client_id)
    database_value = os.getenv("MLBOT_SETTINGS_DB", "").strip()
    if not database_value:
        raise AuthError("MLBOT_SETTINGS_DB is required for publisher authentication")
    database_path = Path(database_value).expanduser().resolve()
    try:
        from ml_app_settings_core import (
            OAuthCredentialRepository,
            OAuthRepositoryError,
            RuntimeSecretError,
            RuntimeSecretReader,
        )
    except ImportError as exc:
        raise AuthError("Canonical settings core is unavailable") from exc
    try:
        secrets = RuntimeSecretReader()
        client_secret = secrets.require("ML_CLIENT_SECRET")
        encryption_key = secrets.require("OAUTH_TOKEN_ENCRYPTION_KEY")
    except RuntimeSecretError as exc:
        raise AuthError("Publisher runtime secret snapshot is unavailable") from exc
    profile_id, seller_id, document_type = _active_oauth_identity(
        database_path,
        expected_seller_id=expected_seller_id,
        expected_document_type=expected_document_type,
    )
    repository = OAuthCredentialRepository(database_path, encryption_key)
    try:
        credential = repository.load_active(
            profile_id=profile_id,
            provider="mercadolivre",
            external_account_id=seller_id,
            credential_kind="tokens",
        )
    except OAuthRepositoryError as exc:
        raise AuthError("Encrypted Mercado Livre OAuth credentials are unavailable") from exc
    oauth_handler = OAuthHandler(
        client_id=client_id,
        client_secret=client_secret,
    )
    token_manager = TokenManager(
        allow_fallback=False,
        oauth_handler=oauth_handler,
        oauth_repository=repository,
        oauth_credential=credential,
    )
    repository_location = "sqlite:oauth_credentials"
    return PublisherAuthContext(
        settings_file=resolved_settings,
        workspace_root=resolved_workspace,
        token_path=repository_location,
        key_path=None,
        token_manager=token_manager,
        expected_seller_id=seller_id,
        expected_document_type=document_type,
    )
