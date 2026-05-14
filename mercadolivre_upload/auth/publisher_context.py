"""Strict publisher auth wiring for manifest/payload publication flows."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from mercadolivre_upload.auth.oauth import OAuthHandler
from mercadolivre_upload.auth.token_manager import TokenManager

from .exceptions import AuthError


@dataclass(frozen=True)
class PublisherAuthContext:
    settings_file: Path
    workspace_root: Path
    token_path: Path
    key_path: Path
    token_manager: TokenManager


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


def _default_secrets_dir(settings_file: Path) -> Path:
    if settings_file.parent.name == "config":
        return settings_file.parent.parent / "secrets"
    return settings_file.parent / "secrets"


def _resolve_secret_file(raw_value: object, *, secrets_dir: Path) -> Path | None:
    if isinstance(raw_value, dict) and set(raw_value) == {"file"}:
        candidate = Path(str(raw_value["file"])).expanduser()
        return candidate if candidate.is_absolute() else secrets_dir / candidate
    return None


def _load_client_credentials(settings_file: Path) -> tuple[str, str, Path]:
    payload = _read_config(settings_file)
    auth = payload.get("auth")
    auth_payload = auth if isinstance(auth, dict) else {}

    raw_client_id = auth_payload.get("ml_app_id", auth_payload.get("ml_client_id"))
    client_id = raw_client_id.strip() if isinstance(raw_client_id, str) else ""

    shared = payload.get("shared")
    secrets_dir_value = shared.get("secrets_dir") if isinstance(shared, dict) else None
    if secrets_dir_value:
        candidate = Path(str(secrets_dir_value)).expanduser()
        secrets_dir = candidate if candidate.is_absolute() else settings_file.parent / candidate
    else:
        secrets_dir = _default_secrets_dir(settings_file)

    secret_file = _resolve_secret_file(auth_payload.get("ml_client_secret"), secrets_dir=secrets_dir)
    if secret_file is None:
        secret_file = secrets_dir / "ml_app_secret"

    raw_secret = auth_payload.get("ml_client_secret")
    client_secret = raw_secret.strip() if isinstance(raw_secret, str) else ""
    if not client_secret and secret_file.exists():
        client_secret = secret_file.read_text(encoding="utf-8").strip()

    if not client_id or not client_secret:
        missing = []
        if not client_id:
            missing.append("client_id")
        if not client_secret:
            missing.append("client_secret")
        raise AuthError(
            "Missing Mercado Livre OAuth credentials "
            f"({', '.join(missing)}) for publisher config {settings_file.resolve()} "
            f"and secret file {secret_file.resolve()}"
        )

    return client_id, client_secret, secret_file


def build_publisher_auth_context(
    *,
    settings_file: Path,
    workspace_root: Path | None,
    strict: bool = True,
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

    client_id, client_secret, _secret_file = _load_client_credentials(resolved_settings)
    token_path = resolved_workspace / ".ml_token.enc"
    key_path = resolved_workspace / ".ml_fernet_key"
    oauth_handler = OAuthHandler(
        client_id=client_id,
        client_secret=client_secret,
        settings_file=resolved_settings,
    )
    token_manager = TokenManager(
        token_path=str(token_path),
        workspace_root=resolved_workspace,
        settings_file=resolved_settings,
        key_path=key_path,
        allow_fallback=not strict,
        oauth_handler=oauth_handler,
    )
    return PublisherAuthContext(
        settings_file=resolved_settings,
        workspace_root=resolved_workspace,
        token_path=token_path,
        key_path=key_path,
        token_manager=token_manager,
    )
