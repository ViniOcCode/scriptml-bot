"""Workflow step helpers for fiscal submission polling."""

import logging
import time
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


def wait_for_fiscal_data_ready(
    *,
    api_client: Any,
    item_id: str,
    sku: str,
    max_retries: int,
    wait_delay: float,
    sleep_fn: Callable[[float], None] = time.sleep,
    logger_instance: logging.Logger = logger,
) -> tuple[bool, dict[str, Any] | None, int]:
    """Wait for item to be ready for fiscal data submission."""
    for attempt in range(max_retries + 1):
        try:
            exists, response = api_client.check_fiscal_data_exists(sku)

            if not exists:
                if attempt > 0:
                    logger_instance.info(
                        f"Item {item_id} (SKU: {sku}) is ready for fiscal data submission "
                        f"after {attempt} wait cycles (fiscal_information returned 404)"
                    )
                return True, response, attempt

            logger_instance.info(
                f"Fiscal data already exists for SKU {sku} (item {item_id}), "
                f"skipping registration"
            )
            return True, response, attempt

        except Exception as exc:
            if attempt < max_retries:
                logger_instance.warning(
                    f"Error checking fiscal_information for {item_id} (SKU: {sku}): {exc}. "
                    f"Waiting {wait_delay}s before retry "
                    f"{attempt + 1}/{max_retries}"
                )
                sleep_fn(wait_delay)
            else:
                logger_instance.error(
                    f"Failed to check fiscal_information for {item_id} (SKU: {sku}) "
                    f"after {max_retries} retries: {exc}"
                )
                raise

    return False, None, max_retries


def wait_for_sku_link(
    *,
    api_client: Any,
    item_id: str,
    sku: str,
    variation_id: str | None,
    max_retries: int,
    wait_delay: float,
    retryable_statuses: set[int],
    status_code_extractor: Callable[[Exception], int],
    response_detail_extractor: Callable[[Exception], dict[str, Any] | None],
    sleep_fn: Callable[[float], None] = time.sleep,
    logger_instance: logging.Logger = logger,
) -> tuple[dict[str, Any] | None, int]:
    """Wait until SKU can be linked to the published item."""
    for attempt in range(max_retries + 1):
        try:
            link_payload: dict[str, Any] = {"sku": sku, "item_id": item_id}
            if variation_id is not None:
                link_payload["variation_id"] = variation_id
            response = api_client.link_fiscal_sku_to_item(**link_payload)
            if attempt > 0:
                logger_instance.info(
                    f"SKU {sku} linked to item {item_id} after {attempt} wait cycles"
                )
            return response, attempt
        except Exception as exc:
            status_code = status_code_extractor(exc)
            response_detail = response_detail_extractor(exc)

            if status_code == 409:
                logger_instance.info(f"SKU {sku} is already linked to item {item_id}")
                return response_detail, attempt

            if status_code and status_code not in retryable_statuses:
                raise

            if attempt < max_retries:
                logger_instance.warning(
                    f"Link SKU {sku} to item {item_id} failed (status={status_code}). "
                    f"Waiting {wait_delay}s before retry "
                    f"{attempt + 1}/{max_retries}"
                )
                sleep_fn(wait_delay)
                continue

            raise

    return None, max_retries


def wait_for_invoice_readiness(
    *,
    item_id: str,
    sku: str,
    max_retries: int,
    wait_delay: float,
    verify_invoice_operation: Callable[[], tuple[bool, dict[str, Any]]],
    execute_with_retry: Callable[
        [Callable[[], tuple[bool, dict[str, Any]]]], tuple[tuple[bool, dict[str, Any]], int]
    ],
    retryable_status_codes: set[int],
    status_code_extractor: Callable[[Exception], int],
    sleep_fn: Callable[[float], None] = time.sleep,
    logger_instance: logging.Logger = logger,
) -> tuple[bool, dict[str, Any] | None, int]:
    """Poll can_invoice endpoint until ready or timeout."""
    total_retry_count = 0
    last_response: dict[str, Any] | None = None

    for attempt in range(max_retries + 1):
        try:
            (is_ready, response), retry_count = execute_with_retry(verify_invoice_operation)
            total_retry_count += retry_count
            last_response = response

            if is_ready:
                if attempt > 0:
                    logger_instance.info(
                        f"Invoice readiness confirmed for {item_id} " f"after {attempt} wait cycles"
                    )
                return True, response, total_retry_count + attempt

            if attempt < max_retries:
                logger_instance.info(
                    f"Invoice readiness pending for {item_id} (SKU: {sku}). "
                    f"Waiting {wait_delay}s before retry "
                    f"{attempt + 1}/{max_retries}"
                )
                sleep_fn(wait_delay)
                continue

            return False, response, total_retry_count + attempt

        except Exception as exc:
            status_code = status_code_extractor(exc)
            is_retryable = (
                status_code in retryable_status_codes or status_code == 404 or status_code == 0
            )
            if not is_retryable or attempt >= max_retries:
                raise
            logger_instance.warning(
                f"Error verifying invoice readiness for {item_id} (SKU: {sku}): {exc}. "
                f"Waiting {wait_delay}s before retry "
                f"{attempt + 1}/{max_retries}"
            )
            sleep_fn(wait_delay)

    return False, last_response, total_retry_count + max_retries
