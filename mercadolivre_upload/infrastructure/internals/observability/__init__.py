"""Forward-compatible shims for observability internals."""

from mercadolivre_upload.infrastructure.internals.observability.logger import (
    DEFAULT_LOG_DIR,
    MAX_LOG_RETENTION_DAYS,
    StructuredLogger,
)
from mercadolivre_upload.infrastructure.internals.observability.metrics import (
    BusinessMetricsCollector,
    HourlyStats,
)

from .helpers import (
    build_discord_alert_payload,
    build_operation_extra,
    build_slack_alert_payload,
    build_structured_log_data,
    format_recent_failures,
    has_alert_capacity,
    success_rate_color,
)

__all__ = [
    "DEFAULT_LOG_DIR",
    "MAX_LOG_RETENTION_DAYS",
    "StructuredLogger",
    "BusinessMetricsCollector",
    "HourlyStats",
    "build_discord_alert_payload",
    "build_operation_extra",
    "build_slack_alert_payload",
    "build_structured_log_data",
    "format_recent_failures",
    "has_alert_capacity",
    "success_rate_color",
]
