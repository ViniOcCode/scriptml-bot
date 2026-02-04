"""Infrastructure layer for Mercado Livre Upload."""

# Original exports
from mercadolivre_upload.infrastructure.config import Settings, get_settings
from mercadolivre_upload.infrastructure.logging import get_logger, setup_logging
from mercadolivre_upload.infrastructure.metrics import MetricsCollector, collector

# Migration exports
from mercadolivre_upload.infrastructure.migration import (
    DEFAULT_SCHEMA_V1,
    DEFAULT_SCHEMA_V2,
    DEFAULT_SCHEMA_V3,
    Field,
    FieldType,
    Migration,
    MigrationManager,
    MigrationResult,
    SchemaVersion,
    V1ToV2Migration,
    V2ToV3Migration,
    Version,
    create_default_migration_manager,
)

# Observability exports
from mercadolivre_upload.infrastructure.observability import (
    Alert,
    AlertLevel,
    AlertManager,
    BusinessMetricsCollector,
    Dashboard,
    HourlyStats,
    ObservabilityManager,
    StructuredLogger,
    alert_manager,
    business_metrics,
    create_observability_manager,
    log_product_upload,
    observability_logger,
)

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
