"""Result types for publish operations."""

from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class PublishResult:
    """Result of a publish operation."""

    success: bool
    item_id: Optional[str] = None
    permalink: Optional[str] = None
    errors: list[str] = None
    warnings: list[str] = None
    raw_response: Optional[dict] = None

    def __post_init__(self):
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
    errors: list[str] = None
    results: list[PublishResult] = None

    def __post_init__(self):
        if self.errors is None:
            self.errors = []
        if self.results is None:
            self.results = []
