"""Fiscal service for managing tax information submission.

This service handles the post-publication submission of fiscal data
to Mercado Livre's fiscal information endpoint following the workflow:
1. Check if item is ready for fiscal data (GET /items/fiscal_information/{SKU})
2. Wait and retry if not ready (1 minute delay)
3. Check if fiscal data exists (GET /items/fiscal_information/{SKU})
4. Register new fiscal data if not exists (POST /items/fiscal_information)
5. Verify invoice readiness (GET /can_invoice/items/{ITEM_ID})

The fiscal_information check must return 200 before sending fiscal data.
If 404, wait 1 minute and retry.
"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol

from .data import FiscalData

logger = logging.getLogger(__name__)


class FiscalSubmissionStatus(Enum):
    """Status of fiscal data submission."""

    ALREADY_EXISTS = "already_exists"
    REGISTERED = "registered"
    VERIFIED = "verified"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class FiscalSubmissionResult:
    """Result of fiscal data submission."""

    success: bool
    item_id: str
    sku: str
    status: FiscalSubmissionStatus
    fiscal_data: FiscalData | None = None
    response: dict[str, Any] | None = None
    error_message: str | None = None
    error_code: str | None = None
    retry_count: int = 0


class FiscalApiPort(Protocol):
    """Port for fiscal API operations."""

    def check_fiscal_data_exists(self, sku: str) -> tuple[bool, dict[str, Any] | None]:
        """Check if fiscal data exists for a SKU.

        Args:
            sku: Product SKU

        Returns:
            Tuple of (exists, response_data)
        """
        ...

    def register_fiscal_data(self, fiscal_data: dict[str, Any]) -> dict[str, Any]:
        """Register new fiscal data.

        Args:
            fiscal_data: Fiscal data payload

        Returns:
            API response
        """
        ...

    def verify_invoice_readiness(self, item_id: str) -> tuple[bool, dict[str, Any]]:
        """Verify if item is ready for invoice generation.

        Args:
            item_id: Mercado Livre item ID

        Returns:
            Tuple of (is_ready, response_data)
        """
        ...


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
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.retryable_status_codes = retryable_status_codes or {429, 500, 502, 503, 504}

    def get_delay(self, attempt: int) -> float:
        """Calculate delay for retry attempt with exponential backoff."""
        delay = self.base_delay * (self.exponential_base**attempt)
        return min(delay, self.max_delay)


class FiscalService:
    """Service for managing fiscal data submission.

    This service orchestrates the complete workflow for fiscal information:
    1. Check if item is ready for fiscal data via can_invoice endpoint
    2. Wait and retry if not ready (1 minute delay)
    3. Check if fiscal data already exists
    4. Register new fiscal data if needed
    5. Verify invoice readiness

    Includes retry logic for transient failures and comprehensive logging.
    """

    def __init__(
        self,
        api_client: FiscalApiPort,
        retry_config: RetryConfig | None = None,
        can_invoice_wait_delay: float = 60.0,
        can_invoice_max_retries: int = 5,
    ):
        """Initialize fiscal service.

        Args:
            api_client: API client implementing FiscalApiPort
            retry_config: Optional retry configuration for API calls
            can_invoice_wait_delay: Delay in seconds between can_invoice retries (default: 60s)
            can_invoice_max_retries: Maximum number of retries for can_invoice check (default: 5)
        """
        self.api_client = api_client
        self.retry_config = retry_config or RetryConfig()
        self.can_invoice_wait_delay = can_invoice_wait_delay
        self.can_invoice_max_retries = can_invoice_max_retries

    def _execute_with_retry(
        self, operation: Callable[[], Any], operation_name: str, sku: str, item_id: str
    ) -> tuple[Any, int]:
        """Execute an operation with retry logic.

        Args:
            operation: Callable to execute
            operation_name: Name of operation for logging
            sku: Product SKU for logging
            item_id: Item ID for logging

        Returns:
            Tuple of (result, retry_count)
        """
        last_exception: Exception | None = None

        for attempt in range(self.retry_config.max_retries + 1):
            try:
                result = operation()
                if attempt > 0:
                    logger.info(
                        f"{operation_name} succeeded for SKU {sku} (item {item_id}) "
                        f"after {attempt} retries"
                    )
                return result, attempt
            except Exception as e:
                last_exception = e
                status_code = self._extract_status_code(e)

                if status_code not in self.retry_config.retryable_status_codes:
                    logger.error(
                        f"{operation_name} failed for SKU {sku} (item {item_id}) "
                        f"with non-retryable error: {e}"
                    )
                    raise

                if attempt < self.retry_config.max_retries:
                    delay = self.retry_config.get_delay(attempt)
                    logger.warning(
                        f"{operation_name} failed for SKU {sku} (item {item_id}) "
                        f"with status {status_code}, retrying in {delay:.1f}s "
                        f"(attempt {attempt + 1}/{self.retry_config.max_retries})"
                    )
                    time.sleep(delay)
                else:
                    logger.error(
                        f"{operation_name} failed for SKU {sku} (item {item_id}) "
                        f"after {self.retry_config.max_retries} retries: {e}"
                    )

        raise last_exception or Exception(f"{operation_name} failed")

    def _extract_status_code(self, exception: Exception) -> int:
        """Extract HTTP status code from exception."""
        response = getattr(exception, "response", None)
        if response is not None:
            return getattr(response, "status_code", 0)
        return 0

    def _wait_for_fiscal_data_ready(
        self, item_id: str, sku: str
    ) -> tuple[bool, dict[str, Any] | None, int]:
        """Wait for item to be ready for fiscal data submission.

        Polls the fiscal_information endpoint (GET /items/fiscal_information/{SKU})
        until it returns 404 (no fiscal data yet, ready to receive) or max retries reached.
        Waits 1 minute between retries as per ML API requirements.

        Args:
            item_id: Mercado Livre item ID (for logging)
            sku: Product SKU to check

        Returns:
            Tuple of (is_ready, response_data, retry_count)
        """
        for attempt in range(self.can_invoice_max_retries + 1):
            try:
                exists, response = self.api_client.check_fiscal_data_exists(sku)

                if not exists:
                    # 404 returned - item has no fiscal data yet, ready to receive
                    if attempt > 0:
                        logger.info(
                            f"Item {item_id} (SKU: {sku}) is ready for fiscal data submission "
                            f"after {attempt} wait cycles (fiscal_information returned 404)"
                        )
                    return True, response, attempt

                # 200 returned - fiscal data already exists, skip
                logger.info(
                    f"Fiscal data already exists for SKU {sku} (item {item_id}), "
                    f"skipping registration"
                )
                return True, response, attempt

            except Exception as e:
                if attempt < self.can_invoice_max_retries:
                    logger.warning(
                        f"Error checking fiscal_information for {item_id} (SKU: {sku}): {e}. "
                        f"Waiting {self.can_invoice_wait_delay}s before retry "
                        f"{attempt + 1}/{self.can_invoice_max_retries}"
                    )
                    time.sleep(self.can_invoice_wait_delay)
                else:
                    logger.error(
                        f"Failed to check fiscal_information for {item_id} (SKU: {sku}) "
                        f"after {self.can_invoice_max_retries} retries: {e}"
                    )
                    raise

        return False, None, self.can_invoice_max_retries

    def submit_fiscal_data_workflow(
        self, item_id: str, fiscal_data: FiscalData
    ) -> FiscalSubmissionResult:
        """Execute complete fiscal data submission workflow.

        Workflow:
        1. Check if item is ready for fiscal data (GET /can_invoice/items/{ITEM_ID})
        2. If status is false: wait 1 minute and retry (up to max_retries)
        3. Check if fiscal data exists (GET /items/fiscal_information/{SKU})
        4. If 200: log exists, skip to verification
        5. If 404: register new fiscal data (POST /items/fiscal_information)
        6. Verify invoice readiness (GET /can_invoice/items/{ITEM_ID})

        Args:
            item_id: Mercado Livre item ID (e.g., MLB1234567890)
            fiscal_data: Fiscal data to submit

        Returns:
            FiscalSubmissionResult with success status and details
        """
        sku = fiscal_data.sku
        logger.info(f"Starting fiscal data workflow for item {item_id}, SKU: {sku}")

        # Validate fiscal data before submission
        if not fiscal_data.is_valid:
            missing = fiscal_data.get_missing_fields()
            error_msg = f"Invalid fiscal data for {item_id}: missing {missing}"
            logger.error(error_msg)
            return FiscalSubmissionResult(
                success=False,
                item_id=item_id,
                sku=sku,
                status=FiscalSubmissionStatus.FAILED,
                fiscal_data=fiscal_data,
                error_message=error_msg,
                error_code="INVALID_FISCAL_DATA",
            )

        # Step 1: Wait for item to be ready for fiscal data
        try:
            is_ready, fiscal_info_response, wait_retries = self._wait_for_fiscal_data_ready(
                item_id, sku
            )

            if not is_ready:
                error_msg = (
                    f"Item {item_id} (SKU: {sku}) not ready for fiscal data submission "
                    f"after {wait_retries} wait cycles"
                )
                logger.error(error_msg)
                return FiscalSubmissionResult(
                    success=False,
                    item_id=item_id,
                    sku=sku,
                    status=FiscalSubmissionStatus.FAILED,
                    fiscal_data=fiscal_data,
                    response=fiscal_info_response,
                    error_message=error_msg,
                    error_code="NOT_READY_FOR_FISCAL_DATA",
                    retry_count=wait_retries,
                )

            logger.info(
                f"Item {item_id} (SKU: {sku}) is ready for fiscal data submission "
                f"(fiscal_information returned data)"
            )

        except Exception as e:
            error_msg = f"Failed to verify item readiness for fiscal data: {str(e)}"
            logger.error(f"{error_msg} for SKU {sku} (item {item_id})")
            return FiscalSubmissionResult(
                success=False,
                item_id=item_id,
                sku=sku,
                status=FiscalSubmissionStatus.FAILED,
                fiscal_data=fiscal_data,
                error_message=error_msg,
                error_code="FISCAL_INFO_CHECK_ERROR",
            )

        # Step 2: Check if fiscal data exists
        check_exists_retry_count = 0
        try:
            (exists, _), check_exists_retry_count = self._execute_with_retry(
                lambda: self.api_client.check_fiscal_data_exists(sku),
                "Check fiscal data exists",
                sku,
                item_id,
            )

            if exists:
                logger.info(
                    f"Fiscal data already exists for SKU {sku} (item {item_id}), "
                    f"skipping registration"
                )
                # Skip to verification
                return self._verify_invoice_readiness(
                    item_id,
                    sku,
                    fiscal_data,
                    FiscalSubmissionStatus.ALREADY_EXISTS,
                    wait_retries + check_exists_retry_count,
                )

        except Exception as e:
            error_msg = f"Failed to check fiscal data existence: {str(e)}"
            logger.error(f"{error_msg} for SKU {sku} (item {item_id})")
            return FiscalSubmissionResult(
                success=False,
                item_id=item_id,
                sku=sku,
                status=FiscalSubmissionStatus.FAILED,
                fiscal_data=fiscal_data,
                error_message=error_msg,
                error_code="CHECK_EXISTS_ERROR",
                retry_count=wait_retries + check_exists_retry_count,
            )

        # Step 3: Register new fiscal data
        registration_retry_count = 0
        try:
            payload = fiscal_data.to_api_payload()
            logger.info(f"Registering fiscal data for SKU {sku} (item {item_id})")
            logger.debug(f"Fiscal payload: {payload}")

            _, registration_retry_count = self._execute_with_retry(
                lambda: self.api_client.register_fiscal_data(payload),
                "Register fiscal data",
                sku,
                item_id,
            )

            logger.info(f"Successfully registered fiscal data for SKU {sku} (item {item_id})")

        except Exception as e:
            error_msg = f"Failed to register fiscal data: {str(e)}"
            error_code = self._extract_error_code(e)
            # Try to extract response body for more details on 400 errors
            error_detail = None
            try:
                if hasattr(e, "response") and e.response is not None:
                    error_detail = e.response.json()
                    error_msg = f"{error_msg} - Response: {error_detail}"
            except Exception:
                pass
            logger.error(f"{error_msg} for SKU {sku} (item {item_id})")
            return FiscalSubmissionResult(
                success=False,
                item_id=item_id,
                sku=sku,
                status=FiscalSubmissionStatus.FAILED,
                fiscal_data=fiscal_data,
                response=error_detail,
                error_message=error_msg,
                error_code=error_code or "REGISTER_ERROR",
                retry_count=wait_retries + check_exists_retry_count + registration_retry_count,
            )

        # Step 4: Verify invoice readiness
        return self._verify_invoice_readiness(
            item_id,
            sku,
            fiscal_data,
            FiscalSubmissionStatus.REGISTERED,
            wait_retries + check_exists_retry_count + registration_retry_count,
        )

    def _verify_invoice_readiness(
        self,
        item_id: str,
        sku: str,
        fiscal_data: FiscalData,
        previous_status: FiscalSubmissionStatus,
        previous_retry_count: int = 0,
    ) -> FiscalSubmissionResult:
        """Verify invoice readiness for an item.

        Args:
            item_id: Mercado Livre item ID
            sku: Product SKU
            fiscal_data: Fiscal data
            previous_status: Status from previous step
            previous_retry_count: Retry count from previous operations

        Returns:
            FiscalSubmissionResult
        """
        try:
            (is_ready, response), retry_count = self._execute_with_retry(
                lambda: self.api_client.verify_invoice_readiness(item_id),
                "Verify invoice readiness",
                sku,
                item_id,
            )

            total_retry_count = previous_retry_count + retry_count

            if is_ready:
                logger.info(f"Invoice readiness verified for item {item_id} (SKU: {sku})")
                return FiscalSubmissionResult(
                    success=True,
                    item_id=item_id,
                    sku=sku,
                    status=FiscalSubmissionStatus.VERIFIED,
                    fiscal_data=fiscal_data,
                    response=response,
                    retry_count=total_retry_count,
                )
            else:
                logger.warning(
                    f"Item {item_id} (SKU: {sku}) is not ready for invoicing: {response}"
                )
                return FiscalSubmissionResult(
                    success=False,
                    item_id=item_id,
                    sku=sku,
                    status=FiscalSubmissionStatus.FAILED,
                    fiscal_data=fiscal_data,
                    response=response,
                    error_message="Item not ready for invoice generation",
                    error_code="NOT_INVOICE_READY",
                    retry_count=total_retry_count,
                )

        except Exception as e:
            error_msg = f"Failed to verify invoice readiness: {str(e)}"
            logger.error(f"{error_msg} for item {item_id} (SKU: {sku})")
            return FiscalSubmissionResult(
                success=False,
                item_id=item_id,
                sku=sku,
                status=FiscalSubmissionStatus.FAILED,
                fiscal_data=fiscal_data,
                error_message=error_msg,
                error_code="VERIFY_ERROR",
                retry_count=previous_retry_count,
            )

    def _extract_error_code(self, exception: Exception) -> str | None:
        """Extract error code from API exception."""
        response = getattr(exception, "response", None)
        if response is None:
            return None

        try:
            error_detail = response.json()
            if isinstance(error_detail, dict):
                causes = error_detail.get("cause", [])
                if isinstance(causes, list) and len(causes) > 0:
                    first_cause = causes[0]
                    if isinstance(first_cause, dict):
                        return first_cause.get("code")
        except Exception:
            pass

        return None

    def submit_fiscal_data_batch(
        self, items: list[tuple[str, FiscalData]]
    ) -> list[FiscalSubmissionResult]:
        """Submit fiscal data for multiple items.

        Args:
            items: List of (item_id, fiscal_data) tuples

        Returns:
            List of FiscalSubmissionResult for each submission
        """
        results: list[FiscalSubmissionResult] = []
        total = len(items)

        logger.info(f"Starting batch fiscal data submission for {total} items")

        for index, (item_id, fiscal_data) in enumerate(items, 1):
            logger.info(f"Processing item {index}/{total}: {item_id}")
            result = self.submit_fiscal_data_workflow(item_id, fiscal_data)
            results.append(result)

            if result.success:
                logger.info(f"Successfully processed {item_id}")
            else:
                logger.error(f"Failed to process {item_id}: {result.error_message}")

        success_count = sum(1 for r in results if r.success)
        logger.info(f"Batch submission complete: {success_count}/{total} successful")

        return results

    def validate_fiscal_data(self, fiscal_data: FiscalData) -> tuple[bool, list[str]]:
        """Validate fiscal data without submitting.

        Args:
            fiscal_data: Fiscal data to validate

        Returns:
            Tuple of (is_valid, list_of_missing_fields)
        """
        is_valid = fiscal_data.is_valid
        missing = fiscal_data.get_missing_fields()

        if not is_valid:
            logger.warning(f"Fiscal data validation failed: missing {missing}")

        return is_valid, missing

    def check_fiscal_data_exists(
        self, sku: str, item_id: str = ""
    ) -> tuple[bool, dict[str, Any] | None, int]:
        """Check if fiscal data exists for a SKU.

        Args:
            sku: Product SKU
            item_id: Item ID for logging context

        Returns:
            Tuple of (exists, response_data, retry_count)
        """
        try:
            (exists, data), retry_count = self._execute_with_retry(
                lambda: self.api_client.check_fiscal_data_exists(sku),
                "Check fiscal data exists",
                sku,
                item_id or sku,
            )
            return exists, data, retry_count
        except Exception as e:
            logger.error(f"Failed to check fiscal data for SKU {sku}: {e}")
            raise

    def register_fiscal_data(
        self, fiscal_data: FiscalData, item_id: str = ""
    ) -> tuple[dict[str, Any], int]:
        """Register fiscal data for a product.

        Args:
            fiscal_data: Fiscal data to register
            item_id: Item ID for logging context

        Returns:
            Tuple of (response_data, retry_count)
        """
        if not fiscal_data.is_valid:
            missing = fiscal_data.get_missing_fields()
            raise ValueError(f"Invalid fiscal data: missing {missing}")

        payload = fiscal_data.to_api_payload()
        sku = fiscal_data.sku

        try:
            response, retry_count = self._execute_with_retry(
                lambda: self.api_client.register_fiscal_data(payload),
                "Register fiscal data",
                sku,
                item_id or sku,
            )
            return response, retry_count
        except Exception as e:
            logger.error(f"Failed to register fiscal data for SKU {sku}: {e}")
            raise

    def verify_invoice_readiness(
        self, item_id: str, sku: str = ""
    ) -> tuple[bool, dict[str, Any], int]:
        """Verify if an item is ready for invoice generation.

        Args:
            item_id: Mercado Livre item ID
            sku: SKU for logging context

        Returns:
            Tuple of (is_ready, response_data, retry_count)
        """
        try:
            (is_ready, response), retry_count = self._execute_with_retry(
                lambda: self.api_client.verify_invoice_readiness(item_id),
                "Verify invoice readiness",
                sku or item_id,
                item_id,
            )
            return is_ready, response, retry_count
        except Exception as e:
            logger.error(f"Failed to verify invoice readiness for {item_id}: {e}")
            raise
