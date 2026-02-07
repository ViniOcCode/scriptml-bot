# Compatibility shim: provide legacy AuthCredentials, TokenData, AuthStatus for tests
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any

from mercadolivre_upload.auth import TokenManager

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


class AuthManager(TokenManager):
    """Compatibility wrapper around TokenManager with legacy constructor signature."""

    def __init__(
        self,
        credentials: AuthCredentials | None = None,
        token_file: Path | None = None,
        auto_save: bool = False,
    ):
        """Initialize auth manager (compatibility constructor for tests)."""
        # Initialize parent TokenManager
        token_path = str(token_file) if token_file else None
        super().__init__(token_path=token_path)

        # Store compatibility attributes
        self.credentials = credentials
        self._auto_save = auto_save
        self._token_file = token_file

        # Create token file directory if needed
        if token_file:
            token_file.parent.mkdir(parents=True, exist_ok=True)

        # Try to load credentials from env if not provided
        if credentials is None:
            try:
                self.credentials = AuthCredentials.from_env()
            except Exception:
                self.credentials = None

    def get_token_data(self) -> TokenData | None:
        """Return current token data or None (compatibility method)."""
        try:
            tokens = self.load_tokens()
            expires_at_ts = tokens.get("expires_at", 0)
            if isinstance(expires_at_ts, (int, float)):
                expires_at = datetime.fromtimestamp(expires_at_ts)
            else:
                expires_at = datetime.fromisoformat(str(expires_at_ts))

            return TokenData(
                access_token=tokens["access_token"],
                refresh_token=tokens.get("refresh_token"),
                expires_at=expires_at,
                user_id=tokens.get("user_id"),
            )
        except Exception:
            return None

    def start_auth_flow(self, state: str | None = None, scopes: list[str] | None = None) -> str:
        """Build and return the authorization URL (compatibility method)."""
        from urllib.parse import urlencode

        from mercadolivre_upload.auth import OAuthHandler

        # Use OAuthHandler to get base URL
        handler = OAuthHandler(
            client_id=self.credentials.app_id if self.credentials else None,
            redirect_uri=self.credentials.redirect_uri if self.credentials else None,
        )
        base_url = handler.get_authorization_url(state=state or "state123")

        # Add scopes if provided (OAuthHandler doesn't support scopes yet)
        if scopes:
            scope_param = "+".join(scopes)
            sep = "&" if "?" in base_url else "?"
            base_url = f"{base_url}{sep}scope={scope_param}"

        return base_url

    def exchange_code_for_token(self, code: str, state: str | None = None) -> TokenData:
        """Exchange an authorization code for tokens (compatibility method)."""
        from mercadolivre_upload.auth import OAuthHandler

        handler = OAuthHandler(
            client_id=self.credentials.app_id if self.credentials else None,
            client_secret=self.credentials.app_secret if self.credentials else None,
            redirect_uri=self.credentials.redirect_uri if self.credentials else None,
        )
        token_dict = handler.exchange_code(code)

        # Save tokens
        self.save_tokens(token_dict)

        # Return as TokenData
        return TokenData.from_dict(token_dict)


def create_auth_manager(
    app_id: str | None = None,
    app_secret: str | None = None,
    redirect_uri: str | None = None,
) -> AuthManager:
    """Create an AuthManager (compatibility function for tests)."""
    creds = None
    if app_id and app_secret:
        creds = AuthCredentials(
            app_id=app_id,
            app_secret=app_secret,
            redirect_uri=redirect_uri or "http://localhost:8000/callback",
        )
    return AuthManager(credentials=creds)


def get_auth_url(
    app_id: str | None = None,
    redirect_uri: str | None = None,
    scopes: list[str] | None = None,
) -> str:
    """Generate an authorization URL (compatibility function for tests)."""
    from mercadolivre_upload.auth import OAuthHandler

    handler = OAuthHandler(client_id=app_id, redirect_uri=redirect_uri)
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
