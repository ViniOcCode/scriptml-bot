"""Authentication module for Mercado Livre API."""

from .exceptions import AuthError, OAuthError, TokenExpiredError
from .oauth import OAuthHandler
from .token_manager import TokenManager

# Alias for compatibility
AuthManager = TokenManager

__all__ = ["TokenManager", "AuthManager", "OAuthHandler", "AuthError", "TokenExpiredError", "OAuthError"]
