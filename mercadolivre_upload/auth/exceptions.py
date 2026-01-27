"""Authentication exceptions."""


class AuthError(Exception):
    """Base exception for authentication errors."""
    pass


class TokenExpiredError(AuthError):
    """Raised when token refresh fails or token is expired."""
    pass


class OAuthError(AuthError):
    """Raised when OAuth flow encounters an error."""
    pass
