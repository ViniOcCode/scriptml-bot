"""Shared helper functions for infrastructure metrics."""

from __future__ import annotations


def format_metric_labels(labels: dict[str, str]) -> str:
    """Format labels dict into a stable metric key suffix."""
    if not labels:
        return ""
    return "_" + "_".join(f"{key}={value}" for key, value in sorted(labels.items()))


def cap_metric_values(values: list[float], limit: int = 1000) -> list[float]:
    """Keep only the most recent values up to ``limit`` items."""
    if len(values) <= limit:
        return values
    return values[-limit:]


def get_timer_statistics(values: list[float]) -> dict[str, float]:
    """Calculate timer summary statistics."""
    if not values:
        return {"count": 0, "sum": 0.0, "mean": 0.0, "min": 0.0, "max": 0.0}

    sorted_values = sorted(values)
    total = sum(values)
    value_count = len(sorted_values)

    def percentile(percent: float) -> float:
        idx = int(value_count * percent / 100)
        return sorted_values[min(idx, value_count - 1)]

    return {
        "count": float(value_count),
        "sum": total,
        "mean": total / value_count,
        "min": sorted_values[0],
        "max": sorted_values[-1],
        "p50": percentile(50),
        "p95": percentile(95),
        "p99": percentile(99),
    }
