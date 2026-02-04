"""Authentication manager stub."""


class AuthManager:
    """Manage authentication with Mercado Livre."""

    def __init__(self, credentials_path: str = "config/credentials.yaml"):
        self.credentials_path = credentials_path
        self._token: str | None = None

    def is_authenticated(self) -> bool:
        """Check if authenticated."""
        return self._token is not None

    def get_access_token(self) -> str | None:
        """Get access token."""
        return self._token

    def authenticate(self) -> bool:
        """Authenticate with Mercado Livre."""
        # TODO: Implement real authentication
        return False

    def get_auth_status(self) -> dict:
        """Get authentication status."""
        return {
            "authenticated": self.is_authenticated(),
            "user_id": None
        }
