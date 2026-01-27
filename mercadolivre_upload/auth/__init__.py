"""Authentication module for Mercado Livre API."""

from .token_manager import TokenManager
from .oauth import OAuthHandler
from .exceptions import AuthError, TokenExpiredError, OAuthError

# Alias for compatibility
AuthManager = TokenManager

__all__ = ["TokenManager", "AuthManager", "OAuthHandler", "AuthError", "TokenExpiredError", "OAuthError"]
