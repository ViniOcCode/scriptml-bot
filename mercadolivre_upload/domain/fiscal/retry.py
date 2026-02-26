"""Retry primitives for fiscal workflow operations."""

import logging
import time
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


class RetryConfig:
    """Configuration for retry logic."""

    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        exponential_base: float = 2.0,
        retryable_status_codes: set[int] | None = None,
    ):
        """Initialize retry configuration."""
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.retryable_status_codes = retryable_status_codes or {429, 500, 502, 503, 504}

    def get_delay(self, attempt: int) -> float:
        """Calculate delay for retry attempt with exponential backoff."""
        delay = self.base_delay * (self.exponential_base**attempt)
        return min(delay, self.max_delay)


def extract_status_code(exception: Exception) -> int:
    """Extract HTTP status code from exception."""
    response = getattr(exception, "response", None)
    if response is not None:
        return getattr(response, "status_code", 0)
    return 0


def extract_response_detail(exception: Exception) -> dict[str, Any] | None:
    """Extract JSON response body from API exception when available."""
    response = getattr(exception, "response", None)
    if response is None:
        return None
    try:
        payload = response.json()
        return payload if isinstance(payload, dict) else None
    except ValueError:
        return None


def execute_with_retry(
    operation: Callable[[], Any],
    *,
    operation_name: str,
    sku: str,
    item_id: str,
    retry_config: RetryConfig,
    sleep_fn: Callable[[float], None] = time.sleep,
    logger_instance: logging.Logger = logger,
    status_code_extractor: Callable[[Exception], int] = extract_status_code,
) -> tuple[Any, int]:
    """Execute an operation with retry logic."""
    last_exception: Exception | None = None

    for attempt in range(retry_config.max_retries + 1):
        try:
            result = operation()
            if attempt > 0:
                logger_instance.info(
                    f"{operation_name} succeeded for SKU {sku} (item {item_id}) "
                    f"after {attempt} retries"
                )
            return result, attempt
        except Exception as exc:
            last_exception = exc
            status_code = status_code_extractor(exc)

            if status_code not in retry_config.retryable_status_codes:
                logger_instance.error(
                    f"{operation_name} failed for SKU {sku} (item {item_id}) "
                    f"with non-retryable error: {exc}"
                )
                raise

            if attempt < retry_config.max_retries:
                delay = retry_config.get_delay(attempt)
                logger_instance.warning(
                    f"{operation_name} failed for SKU {sku} (item {item_id}) "
                    f"with status {status_code}, retrying in {delay:.1f}s "
                    f"(attempt {attempt + 1}/{retry_config.max_retries})"
                )
                sleep_fn(delay)
            else:
                logger_instance.error(
                    f"{operation_name} failed for SKU {sku} (item {item_id}) "
                    f"after {retry_config.max_retries} retries: {exc}"
                )

    raise last_exception or Exception(f"{operation_name} failed")
