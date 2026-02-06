"""CLI module with compatibility exports for tests."""

from .app import app, console, err_console, main, setup_logging, state

__all__ = ["app", "console", "err_console", "main", "state", "setup_logging"]

# Compatibility exports expected by tests
from auth.authenticator import AuthManager  # noqa: E402
from mercadolivre_upload.application.publish_product import PublishProductService  # noqa: E402

__all__ += ["PublishProductService", "AuthManager"]
