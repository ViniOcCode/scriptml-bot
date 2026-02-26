"""Helper functions for observability infrastructure."""

from __future__ import annotations

import traceback
from collections import deque
from datetime import datetime, timedelta
from typing import Any


def build_structured_log_data(
    *,
    base_context: dict[str, Any],
    logger_name: str,
    level: str,
    message: str,
    component: str | None,
    correlation_id: str | None,
    extra: dict[str, Any] | None,
    exception: Exception | None,
) -> dict[str, Any]:
    """Build structured log payload for JSON logging."""
    log_data = {
        **base_context,
        "level": level,
        "message": message,
        "component": component or logger_name,
        "correlation_id": correlation_id,
    }

    if extra:
        log_data["extra"] = extra

    if exception:
        log_data["exception"] = {
            "type": type(exception).__name__,
            "message": str(exception),
            "traceback": traceback.format_exc() if exception else None,
        }

    return {key: value for key, value in log_data.items() if value is not None}


def build_operation_extra(
    operation: str,
    success: bool,
    duration_ms: float,
    extra: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build common payload used for operation logs."""
    return {
        "operation": operation,
        "success": success,
        "duration_ms": duration_ms,
        **(extra or {}),
    }


def build_slack_alert_payload(
    *,
    level: str,
    title: str,
    message: str,
    component: str,
    timestamp: datetime,
    details: dict[str, Any],
) -> dict[str, Any]:
    """Build Slack webhook payload for alerts."""
    colors = {
        "info": "#36a64f",
        "warning": "#ff9900",
        "error": "#ff0000",
        "critical": "#990000",
    }

    return {
        "attachments": [
            {
                "color": colors.get(level, "#808080"),
                "title": f"[{level.upper()}] {title}",
                "text": message,
                "fields": [
                    {"title": "Component", "value": component, "short": True},
                    {"title": "Time", "value": timestamp.isoformat(), "short": True},
                    *[
                        {"title": key, "value": str(value), "short": True}
                        for key, value in details.items()
                    ],
                ],
                "footer": "mercadolivre-upload",
                "ts": int(timestamp.timestamp()),
            }
        ]
    }


def build_discord_alert_payload(
    *,
    level: str,
    title: str,
    message: str,
    component: str,
    timestamp: datetime,
    details: dict[str, Any],
) -> dict[str, Any]:
    """Build Discord webhook payload for alerts."""
    colors = {
        "info": 0x36A64F,
        "warning": 0xFF9900,
        "error": 0xFF0000,
        "critical": 0x990000,
    }

    embed = {
        "title": f"[{level.upper()}] {title}",
        "description": message,
        "color": colors.get(level, 0x808080),
        "timestamp": timestamp.isoformat(),
        "footer": {"text": "mercadolivre-upload"},
        "fields": [
            {"name": "Component", "value": component, "inline": True},
        ],
    }

    for key, value in details.items():
        embed["fields"].append({"name": key, "value": str(value)[:1024], "inline": True})  # type: ignore[attr-defined]

    return {"embeds": [embed]}


def has_alert_capacity(alert_history: deque[datetime], rate_limit: int) -> bool:
    """Check if alert history is below per-minute limit."""
    now = datetime.now()
    one_minute_ago = now - timedelta(minutes=1)

    while alert_history and alert_history[0] < one_minute_ago:
        alert_history.popleft()

    return len(alert_history) < rate_limit


def success_rate_color(success_rate: float) -> str:
    """Return Rich color name for a success rate."""
    if success_rate >= 0.9:
        return "green"
    if success_rate >= 0.7:
        return "yellow"
    return "red"


def format_recent_failures(recent_failures: list[dict[str, Any]]) -> str:
    """Format recent failures list for dashboard footer."""
    if not recent_failures:
        return "Nenhuma falha recente"

    lines = []
    for operation in recent_failures:
        time_str = operation["timestamp"][11:19]  # HH:MM:SS
        error = operation.get("error_category", "unknown")
        lines.append(f"[{time_str}] {error}")

    return "\n".join(lines)
