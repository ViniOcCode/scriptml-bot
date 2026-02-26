"""CLI module exports."""

from .app import app, console, err_console, main, setup_logging, state

__all__ = ["app", "console", "err_console", "main", "state", "setup_logging"]

from mercadolivre_upload.compat.auth_exports import AuthManager  # noqa: E402

__all__ += ["AuthManager"]
