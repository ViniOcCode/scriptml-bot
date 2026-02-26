"""Infrastructure layer for Mercado Livre Upload."""

from typing import Any

# Original exports
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

# Migration exports
from mercadolivre_upload.infrastructure.migration import (
    DEFAULT_SCHEMA_V1,
    DEFAULT_SCHEMA_V2,
    DEFAULT_SCHEMA_V3,
    Migration,
    MigrationManager,
    MigrationResult,
    V1ToV2Migration,
    V2ToV3Migration,
    create_default_migration_manager,
)

# Observability exports
from mercadolivre_upload.infrastructure.observability import (
    Alert,
    AlertLevel,
    AlertManager,
    Dashboard,
    ObservabilityManager,
    alert_manager,
    business_metrics,
    create_observability_manager,
    log_product_upload,
    observability_logger,
)

# Ensure the cache subpackage is importable even if it's a shim we added at runtime
AttributeCache: Any | None
try:
    from .cache.attribute_cache import AttributeCache
except ImportError:
    # If the real cache package exists, it'll be imported; otherwise our shim handles it.
    AttributeCache = None

__all__ = [
    # Original
    "Settings",
    "get_settings",
    "setup_logging",
    "get_logger",
    "MetricsCollector",
    "collector",
    # Migration
    "Field",
    "FieldType",
    "Migration",
    "MigrationManager",
    "MigrationResult",
    "SchemaVersion",
    "Version",
    "create_default_migration_manager",
    "DEFAULT_SCHEMA_V1",
    "DEFAULT_SCHEMA_V2",
    "DEFAULT_SCHEMA_V3",
    "V1ToV2Migration",
    "V2ToV3Migration",
    # Observability
    "StructuredLogger",
    "BusinessMetricsCollector",
    "HourlyStats",
    "AlertManager",
    "Alert",
    "AlertLevel",
    "Dashboard",
    "ObservabilityManager",
    "create_observability_manager",
    "log_product_upload",
    "observability_logger",
    "business_metrics",
    "alert_manager",
]

if AttributeCache is not None:
    __all__.append("AttributeCache")
