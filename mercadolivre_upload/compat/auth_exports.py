"""Shared auth compatibility exports used by legacy shims."""

from mercadolivre_upload.auth import (
    AuthError,
    AuthManager,
    OAuthError,
    OAuthHandler,
    TokenExpiredError,
    TokenManager,
)
from mercadolivre_upload.auth.exceptions import AuthError as ConfigError
from mercadolivre_upload.auth.exceptions import TokenExpiredError as TokenError

__all__ = [
    "AuthManager",
    "TokenManager",
    "OAuthHandler",
    "AuthError",
    "TokenExpiredError",
    "OAuthError",
    "ConfigError",
    "TokenError",
]
