# Compatibility shim: re-export everything from mercadolivre_upload.auth
from mercadolivre_upload.auth import (
    AuthError,
    AuthManager,
    OAuthError,
    OAuthHandler,
    TokenExpiredError,
    TokenManager,
)

# Additional exports for test compatibility (from stub)
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
