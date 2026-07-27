"""Strict publisher auth wiring for manifest/payload publication flows."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

try:
    from ml_app_settings_core import SecretStoreError, build_secret_store_from_env
except Exception:  # pragma: no cover - standalone package fallback
    SecretStoreError = Exception
    build_secret_store_from_env = None

from mercadolivre_upload.auth.oauth import OAuthHandler
from mercadolivre_upload.auth.token_manager import TokenManager

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
    try:
        raw = yaml.safe_load(settings_file.read_text(encoding="utf-8")) or {}
    except OSError as exc:
        raise AuthError(f"Could not read publisher config: {settings_file}") from exc
    except yaml.YAMLError as exc:
        raise AuthError(f"Invalid publisher config YAML: {settings_file}") from exc
    if not isinstance(raw, dict):
        raise AuthError(f"Publisher config must be a mapping: {settings_file}")
    return raw


def _load_client_id(settings_file: Path, explicit_client_id: str | None = None) -> str:
    if explicit_client_id is not None and explicit_client_id.strip():
        return explicit_client_id.strip()
    payload = _read_config(settings_file)
    auth = payload.get("auth")
    auth_payload = auth if isinstance(auth, dict) else {}

    raw_client_id = auth_payload.get("ml_app_id", auth_payload.get("ml_client_id"))
    client_id = raw_client_id.strip() if isinstance(raw_client_id, str) else ""
    if not client_id:
        raise AuthError(
            f"Missing Mercado Livre OAuth client_id for publisher config {settings_file.resolve()}"
        )
    return client_id


def _secret_profile() -> str:
    return os.getenv("MLBOT_SECRET_PROFILE", "default").strip() or "default"


def _vault_store():
    backend = ""
    for name in (
        "MLBOT_SECRET_BACKEND",
        "ML_PUBLISHER_SECRET_BACKEND",
        "ML_DASHBOARD_SECRET_BACKEND",
    ):
        value = os.getenv(name)
        if value and value.strip():
            backend = value.strip().lower()
            break
    if backend not in {"openbao", "vault"}:
        raise AuthError(
            "Set MLBOT_SECRET_BACKEND=openbao to use Mercado Livre credentials "
            "from OpenBao/Vault"
        )
    if build_secret_store_from_env is None:
        raise AuthError("OpenBao/Vault secret store is not available")
    try:
        return build_secret_store_from_env()
    except SecretStoreError as exc:
        raise AuthError(f"OpenBao/Vault unavailable: {exc}") from exc


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
    if strict and not resolved_settings.exists():
        raise AuthError(f"Publisher config not found: {resolved_settings}")
    if strict and workspace_root is None:
        raise AuthError("workspace_root is required for publication flows")
    if workspace_root is None:
        raise AuthError("workspace_root is required")
    resolved_workspace = Path(workspace_root).expanduser().resolve()

    profile = _secret_profile()
    client_id = _load_client_id(resolved_settings, ml_client_id)
    store = _vault_store()
    client_secret_path = f"profiles/{profile}/mercadolivre/client_secret"
    token_secret_path = f"profiles/{profile}/mercadolivre/tokens"
    try:
        client_secret = store.get_secret(client_secret_path)
        token_payload = store.get_secret(token_secret_path)
    except SecretStoreError as exc:
        raise AuthError(f"OpenBao/Vault Mercado Livre credentials unavailable: {exc}") from exc
    if not client_secret:
        raise AuthError(
            f"Mercado Livre client_secret not found in OpenBao/Vault: {client_secret_path}"
        )
    if not token_payload:
        raise AuthError(f"Mercado Livre tokens not found in OpenBao/Vault: {token_secret_path}")
    oauth_handler = OAuthHandler(
        client_id=client_id,
        client_secret=client_secret,
        settings_file=resolved_settings,
    )
    token_manager = TokenManager(
        settings_file=resolved_settings,
        allow_fallback=False,
        oauth_handler=oauth_handler,
        secret_store=store,
        token_secret_path=token_secret_path,
    )
    return PublisherAuthContext(
        settings_file=resolved_settings,
        workspace_root=resolved_workspace,
        token_path=token_secret_path,
        key_path=None,
        token_manager=token_manager,
        expected_seller_id=(
            expected_seller_id.strip() if isinstance(expected_seller_id, str) else None
        )
        or None,
        expected_document_type=(
            expected_document_type.strip().upper()
            if isinstance(expected_document_type, str)
            else None
        )
        or None,
    )
