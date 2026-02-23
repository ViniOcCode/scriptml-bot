"""Result types for publish operations."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PublishResult:
    """Result of a publish operation."""

    success: bool
    item_id: str | None = None
    permalink: str | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    raw_response: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        """Normalize optional mutable values."""
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
    errors: list[str] = field(default_factory=list)
    results: list[PublishResult] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Normalize optional mutable values."""
        if self.errors is None:
            self.errors = []
        if self.results is None:
            self.results = []
