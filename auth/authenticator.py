"""Compatibility shim for legacy auth.authenticator imports."""

from mercadolivre_upload.compat.authenticator import (
    AuthCredentials,
    AuthError,
    AuthManager,
    AuthStatus,
    ConfigError,
    TokenData,
    TokenError,
    create_auth_manager,
    get_auth_url,
)

__all__ = [
    "AuthManager",
    "AuthCredentials",
    "AuthError",
    "AuthStatus",
    "ConfigError",
    "TokenData",
    "TokenError",
    "create_auth_manager",
    "get_auth_url",
]
