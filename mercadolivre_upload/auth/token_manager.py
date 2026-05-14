"""Token manager for Mercado Livre API authentication."""

import json
import time
from pathlib import Path
from typing import Any

from mercadolivre_upload.infrastructure.env import get_pipeline_env, get_pipeline_flag

from .exceptions import AuthError, TokenExpiredError
from .oauth import OAuthHandler
from .secure_storage import SecureStorageError, SecureTokenStorage, migrate_plaintext_tokens


class TokenManager:
    """Manages access and refresh tokens for Mercado Livre API.

    Handles loading, saving, and automatic refresh of tokens.
    Tokens are stored in JSON format with expiration timestamp.

    Attributes:
        token_path: Path to the tokens.json file
        oauth_handler: OAuthHandler instance for token refresh
        _tokens: Cached token data
    """

    _PERSISTED_TOKEN_FIELDS = frozenset({"access_token", "refresh_token", "expires_at"})

    def __init__(
        self,
        token_path: str | None = None,
        workspace_root: Path | None = None,
        settings_file: Path | None = None,
        key_path: Path | None = None,
        allow_fallback: bool = True,
        oauth_handler: OAuthHandler | None = None,
    ):
        """Initialize the token manager.

        Args:
            token_path: Path to tokens.json. Defaults to 'tokens.json' in current directory
            oauth_handler: OAuthHandler for token refresh. If None, creates default
        """
        if not allow_fallback and workspace_root is None and token_path is None:
            raise AuthError("workspace_root or token_path is required when fallback auth is disabled")

        if not allow_fallback and settings_file is None and oauth_handler is None:
            raise AuthError("settings_file or oauth_handler is required when fallback auth is disabled")

        if workspace_root is not None:
            resolved_workspace = Path(workspace_root).expanduser().resolve()
            default_path = str(resolved_workspace / ".ml_token.enc")
            encryption_key_path = key_path or resolved_workspace / ".ml_fernet_key"
        else:
            default_path = token_path
            if allow_fallback:
                default_path = (
                    default_path or get_pipeline_env("ML_PIPE_MERCADO_LIVRE_TOKEN_PATH") or "tokens.json"
                )
            encryption_key_path = key_path
        if default_path is None:
            raise AuthError("Token path is required")
        self.token_path = Path(default_path)
        self.oauth_handler = oauth_handler or OAuthHandler(settings_file=settings_file)
        self._tokens: dict[str, Any] | None = None
        self._secure_storage: SecureTokenStorage | None = None

        use_secure_storage = get_pipeline_flag(
            "ML_PIPE_MERCADO_LIVRE_USE_SECURE_STORAGE",
            default=True,
        )
        if use_secure_storage or self.token_path.suffix == ".enc":
            secure_path = (
                self.token_path
                if self.token_path.suffix == ".enc"
                else Path(f"{self.token_path}.enc")
            )
            auto_migrate = get_pipeline_flag(
                "ML_PIPE_MERCADO_LIVRE_AUTO_MIGRATE_TOKENS",
                default=True,
            )
            if auto_migrate and self.token_path.exists() and not secure_path.exists():
                migrated = migrate_plaintext_tokens(self.token_path, secure_path)
                if not migrated:
                    raise AuthError(
                        f"Secure token migration failed for {self.token_path}. "
                        "Fix token file contents or disable auto-migration."
                    )

            self.token_path = secure_path
            self._secure_storage = SecureTokenStorage(
                token_path=self.token_path,
                encryption_key_path=encryption_key_path,
            )

    @classmethod
    def _persistable_tokens(cls, tokens: dict[str, Any]) -> dict[str, Any]:
        """Return only the token fields allowed to be persisted."""
        persisted: dict[str, Any] = {}
        for field in cls._PERSISTED_TOKEN_FIELDS:
            if field in tokens:
                persisted[field] = tokens[field]
        return persisted

    def load_tokens(self) -> dict[str, Any]:
        """Load tokens from the JSON file.

        Returns:
            Dictionary containing access_token, refresh_token, and expires_at

        Raises:
            FileNotFoundError: If token file doesn't exist
            json.JSONDecodeError: If token file is invalid JSON
        """
        if self._tokens is None:
            if self._secure_storage is not None:
                try:
                    loaded = self._secure_storage.load_tokens()
                except SecureStorageError as err:
                    raise AuthError(
                        f"Secure token storage error at {self.token_path}: {err}"
                    ) from err
                if loaded is None:
                    raise FileNotFoundError(f"Token file not found: {self.token_path}")
                self._tokens = self._persistable_tokens(loaded)
            else:
                with open(self.token_path, encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    self._tokens = self._persistable_tokens(loaded)
                else:
                    raise ValueError("Invalid token file format")
        return self._tokens

    def save_tokens(self, tokens: dict[str, Any]) -> None:
        """Save tokens to the JSON file.

        Args:
            tokens: Dictionary containing access_token, refresh_token, and expires_at
        """
        persisted_tokens = self._persistable_tokens(tokens)
        if self._secure_storage is not None:
            try:
                self._secure_storage.save_tokens(persisted_tokens)
            except SecureStorageError as err:
                raise AuthError(f"Secure token storage error at {self.token_path}: {err}") from err
        else:
            with open(self.token_path, "w", encoding="utf-8") as f:
                json.dump(persisted_tokens, f, indent=2)
        self._tokens = persisted_tokens

    def is_token_expired(self, buffer_seconds: int = 300) -> bool:
        """Check if the current access token is expired or about to expire.

        Args:
            buffer_seconds: Seconds before actual expiration to consider token expired
                          Defaults to 5 minutes to avoid edge cases

        Returns:
            True if token is expired or will expire within buffer_seconds
        """
        try:
            tokens = self.load_tokens()
            expires_at = tokens.get("expires_at", 0)

            # Handle both timestamp and ISO string formats
            if isinstance(expires_at, str):
                from datetime import datetime

                expires_at = datetime.fromisoformat(expires_at).timestamp()

            expires_at_float = float(expires_at)
            return time.time() >= (expires_at_float - buffer_seconds)
        except (TypeError, ValueError):
            return True
        except FileNotFoundError:
            return True

    def get_access_token(self, auto_refresh: bool = True) -> str:
        """Get the current access token, refreshing if necessary.

        Args:
            auto_refresh: Whether to automatically refresh expired tokens

        Returns:
            Valid access token string

        Raises:
            TokenExpiredError: If token is expired and refresh fails
            FileNotFoundError: If no token file exists and auto_refresh is False
        """
        tokens = self.load_tokens()

        if self.is_token_expired():
            if not auto_refresh:
                raise TokenExpiredError("Access token is expired")
            tokens = self.refresh_token()

        access_token = tokens.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise TokenExpiredError("Access token is missing")
        return access_token

    def refresh_token(self) -> dict[str, Any]:
        """Refresh and persist tokens using the current refresh token.

        Returns:
            Updated token payload.

        Raises:
            TokenExpiredError: If no refresh token is available.
            OAuthError: If the OAuth provider rejects the refresh.
        """
        tokens = self.load_tokens()
        refresh_token_value = tokens.get("refresh_token")
        if not refresh_token_value:
            raise TokenExpiredError("No refresh token available")

        new_tokens = self.oauth_handler.refresh_token(refresh_token_value)
        if "refresh_token" not in new_tokens and isinstance(refresh_token_value, str):
            new_tokens["refresh_token"] = refresh_token_value
        self.save_tokens(new_tokens)
        return new_tokens

    def get_refresh_token(self) -> str:
        """Get the current refresh token.

        Returns:
            Refresh token string

        Raises:
            TokenExpiredError: If refresh_token is missing or empty
        """
        tokens = self.load_tokens()
        refresh_token = tokens.get("refresh_token")
        if not isinstance(refresh_token, str) or not refresh_token:
            raise TokenExpiredError("No refresh token available")
        return refresh_token

    def invalidate_cache(self) -> None:
        """Clear the in-memory token cache.

        Call this if tokens.json is modified externally.
        """
        self._tokens = None

    def is_authenticated(self) -> bool:
        """Check if authenticated with valid token.

        Returns:
            True if token exists and is not expired
        """
        try:
            tokens = self.load_tokens()
            return not self.is_token_expired() and bool(tokens.get("access_token"))
        except FileNotFoundError:
            return False

    def get_auth_status(self) -> dict[str, Any]:
        """Get current authentication status.

        Returns:
            Dictionary with authenticated status, status string, and user_id
        """
        try:
            self.load_tokens()
            authenticated = self.is_authenticated()
            return {
                "authenticated": authenticated,
                "status": "authenticated" if authenticated else "unauthenticated",
                "user_id": None,
            }
        except FileNotFoundError:
            return {
                "authenticated": False,
                "status": "unauthenticated",
                "user_id": None,
            }

    def set_token(
        self,
        access_token: str,
        refresh_token: str | None = None,
        expires_in: int = 3600,
        user_id: str | None = None,
    ) -> None:
        """Set token data manually (for testing).

        Args:
            access_token: Access token string
            refresh_token: Optional refresh token
            expires_in: Token lifetime in seconds (default: 3600)
            user_id: Optional user ID
        """
        expires_at = int(time.time()) + expires_in
        tokens = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_at": expires_at,
        }
        self.save_tokens(tokens)

    def get_valid_token(self) -> str:
        """Get valid access token, refreshing if needed.

        This is an alias for get_access_token() for backward compatibility.

        Returns:
            Valid access token string

        Raises:
            TokenExpiredError: If token is expired and refresh fails
            AuthError: If not authenticated
        """
        try:
            self.load_tokens()
        except FileNotFoundError as err:
            raise AuthError("Not authenticated") from err
        return self.get_access_token(auto_refresh=True)

    def logout(self) -> None:
        """Clear tokens and remove token file."""
        self._tokens = None
        if self._secure_storage is not None:
            self._secure_storage.delete_tokens()
        elif self.token_path.exists():
            self.token_path.unlink()
