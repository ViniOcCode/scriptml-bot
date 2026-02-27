"""Category domain exceptions."""

from __future__ import annotations


class CategoryApiUnavailableError(RuntimeError):
    """Raised when category API responses are unavailable or invalid."""

    def __init__(
        self,
        message: str,
        *,
        operation: str | None = None,
    ) -> None:
        """Initialize category API unavailable error metadata."""
        super().__init__(message)
        self.operation = operation
