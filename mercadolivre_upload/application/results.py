"""Result types for publish operations."""

from dataclasses import dataclass
from typing import Any


@dataclass
class PublishResult:
    """Result of a publish operation."""

    success: bool
    item_id: str | None = None
    permalink: str | None = None
    errors: list[str] = None  # type: ignore[assignment]
    warnings: list[str] = None  # type: ignore[assignment]
    raw_response: dict[str, Any] | None = None

    def __post_init__(self):  # type: ignore[no-untyped-def]
        """Initialize default mutable fields."""
        if self.errors is None:
            self.errors = []
        if self.warnings is None:
            self.warnings = []


@dataclass
class BatchPublishResult:
    """Result of a batch publish operation."""

    published: int
    failed: int
    success: bool
    errors: list[str] = None  # type: ignore[assignment]
    results: list[PublishResult] = None  # type: ignore[assignment]

    def __post_init__(self):  # type: ignore[no-untyped-def]
        """Initialize default mutable fields."""
        if self.errors is None:
            self.errors = []
        if self.results is None:
            self.results = []
