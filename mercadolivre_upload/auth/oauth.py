"""OAuth handler for Mercado Livre API authentication."""

from typing import Any
from urllib.parse import urlencode

import requests

from mercadolivre_upload.infrastructure.env import get_pipeline_env
from mercadolivre_upload.infrastructure.http import ResilientHTTPClient, RetryPolicy

from .exceptions import OAuthError

TOKEN_REQUEST_RETRY_POLICY = RetryPolicy(max_retries=1, base_delay=0.5, max_delay=5.0)


class OAuthHandler:
    """Handles OAuth 2.0 flows for Mercado Livre API.

    Supports authorization code flow for initial setup and
    refresh token flow for ongoing access.

    Attributes:
        client_id: Mercado Livre application client ID
        client_secret: Mercado Livre application client secret
        redirect_uri: OAuth callback URL
    """

    AUTH_URL = "https://auth.mercadolivre.com.br/authorization"
    TOKEN_URL = "https://api.mercadolibre.com/oauth/token"  # noqa: S105  # nosec B105

    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        redirect_uri: str | None = None,
        http_client: ResilientHTTPClient | None = None,
    ):
        """Initialize the OAuth handler.

        Args:
            client_id: ML client ID. Defaults to env var.
            client_secret: ML client secret. Defaults to env var.
            redirect_uri: OAuth redirect URI. Defaults to env var.
            http_client: Optional resilient HTTP client for token requests.
        """
        self.client_id = client_id or get_pipeline_env("ML_PIPE_MERCADO_LIVRE_CLIENT_ID")
        self.client_secret = client_secret or get_pipeline_env(
            "ML_PIPE_MERCADO_LIVRE_CLIENT_SECRET"
        )
        self.redirect_uri = redirect_uri or get_pipeline_env(
            "ML_PIPE_MERCADO_LIVRE_REDIRECT_URI",
            "http://localhost:8000/callback",
        )
        self.http_client = http_client or ResilientHTTPClient(timeout=30)

    def get_authorization_url(self, state: str | None = None) -> str:
        """Generate the authorization URL for OAuth flow.

        Args:
            state: Optional state parameter for CSRF protection

        Returns:
            Full authorization URL to redirect user to

        Raises:
            OAuthError: If client_id is not configured
        """
        if not self.client_id:
            raise OAuthError("Client ID is required. Set ML_PIPE_MERCADO_LIVRE_CLIENT_ID.")

        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
        }

        if state:
            params["state"] = state

        return f"{self.AUTH_URL}?{urlencode(params)}"

    def exchange_code(self, code: str) -> dict[str, Any]:
        """Exchange authorization code for access and refresh tokens.

        Args:
            code: Authorization code from OAuth callback

        Returns:
            Dictionary with access_token, refresh_token, and expires_at (timestamp)

        Raises:
            OAuthError: If token exchange fails
        """
        if not self.client_id or not self.client_secret:
            raise OAuthError("Client ID and Client Secret are required")

        payload = {
            "grant_type": "authorization_code",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": code,
            "redirect_uri": self.redirect_uri,
        }

        return self._make_token_request(payload)

    def refresh_token(self, refresh_token: str) -> dict[str, Any]:
        """Refresh the access token using a refresh token.

        Args:
            refresh_token: Valid refresh token

        Returns:
            Dictionary with new access_token, refresh_token, and expires_at (timestamp)

        Raises:
            OAuthError: If token refresh fails
        """
        if not self.client_id or not self.client_secret:
            raise OAuthError("Client ID and Client Secret are required")

        payload = {
            "grant_type": "refresh_token",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": refresh_token,
        }

        return self._make_token_request(payload)

    def _make_token_request(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Make token request and process response.

        Args:
            payload: Request payload for token endpoint

        Returns:
            Dictionary with access_token, refresh_token, and expires_at

        Raises:
            OAuthError: If request fails or response is invalid
        """
        try:
            response = self.http_client.post(
                self.TOKEN_URL,
                data=payload,
                policy=TOKEN_REQUEST_RETRY_POLICY,
                timeout=30,
            )
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            raise OAuthError(f"Token request failed: {e}") from e

        try:
            data = response.json()
        except ValueError as e:
            raise OAuthError("Invalid token response: invalid JSON") from e

        if "access_token" not in data:
            error_msg = data.get("message", data.get("error", "Unknown error"))
            raise OAuthError(f"Invalid token response: {error_msg}")

        import time

        expires_at = int(time.time()) + data.get("expires_in", 21600)

        return {
            "access_token": data["access_token"],
            "refresh_token": data.get("refresh_token"),
            "expires_at": expires_at,
        }

    def add_auth_header(
        self, headers: dict[str, Any] | None = None, token: str | None = None
    ) -> dict[str, Any]:
        """Add Bearer token authorization header to request headers.

        Args:
            headers: Existing headers dict (optional)
            token: Access token to use. If None, must be provided by caller

        Returns:
            Headers dict with Authorization header added
        """
        if headers is None:
            headers = {}

        if token:
            headers["Authorization"] = f"Bearer {token}"

        return headers
