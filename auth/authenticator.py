# Compatibility shim: provide legacy AuthCredentials, TokenData, AuthStatus for tests
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any

from mercadolivre_upload.auth import AuthManager

# Re-export exceptions with aliases
ConfigError = Exception
TokenError = Exception
AuthError = Exception


class AuthStatus(Enum):
    """Authentication status values."""

    UNAUTHENTICATED = "unauthenticated"
    AUTHENTICATED = "authenticated"


@dataclass
class AuthCredentials:
    """OAuth credentials for Mercado Livre API."""

    app_id: str
    app_secret: str
    redirect_uri: str = "http://localhost:8000/callback"

    @staticmethod
    def from_env() -> AuthCredentials:
        """Load credentials from environment variables."""
        import os

        try:
            return AuthCredentials(
                app_id=os.environ["ML_APP_ID"],
                app_secret=os.environ["ML_APP_SECRET"],
                redirect_uri=os.environ.get("ML_REDIRECT_URI", "http://localhost:8000/callback"),
            )
        except KeyError as e:
            raise ConfigError(f"Missing env var {e.args[0]}") from e

    @staticmethod
    def from_file(path: Path) -> AuthCredentials:
        """Load credentials from a JSON file."""
        import json

        if not path.exists():
            raise ConfigError("arquivo de credenciais não encontrado")
        data = json.loads(path.read_text())
        return AuthCredentials(
            app_id=data["app_id"],
            app_secret=data["app_secret"],
            redirect_uri=data.get("redirect_uri", "http://localhost:8000/callback"),
        )


@dataclass
class TokenData:
    """OAuth token data with expiration tracking."""

    access_token: str
    refresh_token: str | None
    expires_at: datetime
    user_id: str | None = None
    scope: str | None = None
    token_type: str | None = None

    def is_expired(self, buffer_seconds: int = 0) -> bool:
        """Check if the token is expired."""
        return datetime.now() + timedelta(seconds=buffer_seconds) >= self.expires_at

    def to_dict(self) -> dict[str, Any]:
        """Serialize token data to a dictionary."""
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at.isoformat(),
            "user_id": self.user_id,
            "scope": self.scope,
            "token_type": self.token_type,
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> TokenData:
        """Deserialize token data from a dictionary."""
        expires = data.get("expires_at")
        if isinstance(expires, str):
            expires = datetime.fromisoformat(expires)
        return TokenData(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token"),
            expires_at=expires,  # type: ignore[arg-type]
            user_id=str(data.get("user_id")) if data.get("user_id") is not None else None,
            scope=data.get("scope"),
            token_type=data.get("token_type"),
        )


def create_auth_manager(
    app_id: str | None = None,
    app_secret: str | None = None,
    redirect_uri: str | None = None,
) -> AuthManager:
    """Create an AuthManager (compatibility function for tests)."""
    return AuthManager()


def get_auth_url(
    app_id: str | None = None,
    redirect_uri: str | None = None,
    scopes: list[str] | None = None,
) -> str:
    """Generate an authorization URL (compatibility function for tests)."""
    from mercadolivre_upload.auth import OAuthHandler

    handler = OAuthHandler(client_id=app_id)
    return handler.get_authorization_url()


__all__ = [
    "AuthManager",
    "AuthCredentials",
    "AuthError",
    "AuthStatus",
    "ConfigError",
    "TokenData",
    "TokenError",
    "create_auth_manager",
    "get_auth_url",
]
