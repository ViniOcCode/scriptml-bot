"""Token manager for Mercado Livre API authentication."""

import json
import os
import time
from pathlib import Path
from typing import Optional

from .exceptions import TokenExpiredError
from .oauth import OAuthHandler


class TokenManager:
    """Manages access and refresh tokens for Mercado Livre API.

    Handles loading, saving, and automatic refresh of tokens.
    Tokens are stored in JSON format with expiration timestamp.

    Attributes:
        token_path: Path to the tokens.json file
        oauth_handler: OAuthHandler instance for token refresh
        _tokens: Cached token data
    """

    def __init__(
        self,
        token_path: Optional[str] = None,
        oauth_handler: Optional[OAuthHandler] = None,
    ):
        """Initialize the token manager.

        Args:
            token_path: Path to tokens.json. Defaults to 'tokens.json' in current directory
            oauth_handler: OAuthHandler for token refresh. If None, creates default
        """
        self.token_path = Path(token_path or os.getenv("MERCADO_LIVRE_TOKEN_PATH", "tokens.json"))
        self.oauth_handler = oauth_handler or OAuthHandler()
        self._tokens: Optional[dict] = None

    def load_tokens(self) -> dict:
        """Load tokens from the JSON file.

        Returns:
            Dictionary containing access_token, refresh_token, and expires_at

        Raises:
            FileNotFoundError: If token file doesn't exist
            json.JSONDecodeError: If token file is invalid JSON
        """
        if self._tokens is None:
            with open(self.token_path, "r", encoding="utf-8") as f:
                self._tokens = json.load(f)
        return self._tokens

    def save_tokens(self, tokens: dict) -> None:
        """Save tokens to the JSON file.

        Args:
            tokens: Dictionary containing access_token, refresh_token, and expires_at
        """
        with open(self.token_path, "w", encoding="utf-8") as f:
            json.dump(tokens, f, indent=2)
        self._tokens = tokens

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
            return time.time() >= (expires_at - buffer_seconds)
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

            refresh_token = tokens.get("refresh_token")
            if not refresh_token:
                raise TokenExpiredError("No refresh token available")

            new_tokens = self.oauth_handler.refresh_token(refresh_token)
            self.save_tokens(new_tokens)
            tokens = new_tokens

        return tokens["access_token"]

    def get_refresh_token(self) -> str:
        """Get the current refresh token.

        Returns:
            Refresh token string

        Raises:
            KeyError: If refresh_token is not in tokens
        """
        tokens = self.load_tokens()
        return tokens["refresh_token"]

    def invalidate_cache(self) -> None:
        """Clear the in-memory token cache.

        Call this if tokens.json is modified externally.
        """
        self._tokens = None
