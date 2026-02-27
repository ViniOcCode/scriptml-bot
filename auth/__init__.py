"""Compatibility shim for legacy auth package imports."""

from mercadolivre_upload.compat.auth_exports import (
    AuthError,
    AuthManager,
    ConfigError,
    OAuthError,
    OAuthHandler,
    TokenError,
    TokenExpiredError,
    TokenManager,
)

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
