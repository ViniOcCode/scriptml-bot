"""Authentication module for Mercado Livre API."""

from .exceptions import AuthError, OAuthError, TokenExpiredError
from .oauth import OAuthHandler
from .token_manager import TokenManager

__all__ = [
    "TokenManager",
    "OAuthHandler",
    "AuthError",
    "TokenExpiredError",
    "OAuthError",
]
