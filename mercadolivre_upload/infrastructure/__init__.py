"""Infrastructure layer for Mercado Livre Upload."""

from typing import Any

from mercadolivre_upload.infrastructure.config import Settings, get_settings
from mercadolivre_upload.infrastructure.internals.migration import (
    Field,
    FieldType,
    SchemaVersion,
    Version,
)
from mercadolivre_upload.infrastructure.internals.observability import (
    BusinessMetricsCollector,
    HourlyStats,
    StructuredLogger,
)
from mercadolivre_upload.infrastructure.logging import get_logger, setup_logging
from mercadolivre_upload.infrastructure.metrics import MetricsCollector, collector

AttributeCache: Any | None
try:
    from .cache.attribute_cache import AttributeCache
except ImportError:
    AttributeCache = None

__all__ = [
    "Settings",
    "get_settings",
    "setup_logging",
    "get_logger",
    "MetricsCollector",
    "collector",
    "Field",
    "FieldType",
    "SchemaVersion",
    "Version",
    "StructuredLogger",
    "BusinessMetricsCollector",
    "HourlyStats",
]

if AttributeCache is not None:
    __all__.append("AttributeCache")
