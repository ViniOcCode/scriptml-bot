"""Fiscal service for managing tax information submission.

This service handles post-publication fiscal workflow:
1. Check fiscal data by SKU
2. Register new fiscal data by SKU when missing
3. Link fiscal SKU to the published item
4. Verify invoice readiness for the item
"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol

from .data import FiscalData
from .retry import RetryConfig, execute_with_retry, extract_response_detail, extract_status_code
from .workflow_steps import (
    wait_for_fiscal_data_ready,
    wait_for_invoice_readiness,
    wait_for_sku_link,
)

logger = logging.getLogger(__name__)


class FiscalSubmissionStatus(Enum):
    """Status of fiscal data submission."""

    ALREADY_EXISTS = "already_exists"
    REGISTERED = "registered"
    VERIFIED = "verified"
    PENDING_VERIFICATION = "pending_verification"
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

    def link_fiscal_sku_to_item(
        self, sku: str, item_id: str, variation_id: str | None = None
    ) -> dict[str, Any]:
        """Link a registered fiscal SKU to a published item."""
        ...

    def verify_invoice_readiness(self, item_id: str) -> tuple[bool, dict[str, Any]]:
        """Verify if item is ready for invoice generation.

        Args:
            item_id: Mercado Livre item ID

        Returns:
            Tuple of (is_ready, response_data)
        """
        ...


class FiscalService:
    """Service for managing fiscal data submission.

    This service orchestrates the complete workflow for fiscal information:
    1. Check if fiscal data already exists by SKU
    2. Register fiscal data by SKU when missing
    3. Link SKU to the published item
    4. Poll invoice readiness for verification

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
        """Execute an operation with retry logic."""
        return execute_with_retry(
            operation,
            operation_name=operation_name,
            sku=sku,
            item_id=item_id,
            retry_config=self.retry_config,
            sleep_fn=time.sleep,
            logger_instance=logger,
            status_code_extractor=self._extract_status_code,
        )

    def _extract_status_code(self, exception: Exception) -> int:
        """Extract HTTP status code from exception."""
        return extract_status_code(exception)

    @staticmethod
    def _extract_response_detail(exception: Exception) -> dict[str, Any] | None:
        """Extract JSON response body from API exception when available."""
        return extract_response_detail(exception)

    def _wait_for_fiscal_data_ready(
        self, item_id: str, sku: str
    ) -> tuple[bool, dict[str, Any] | None, int]:
        """Wait for item to be ready for fiscal data submission."""
        return wait_for_fiscal_data_ready(
            api_client=self.api_client,
            item_id=item_id,
            sku=sku,
            max_retries=self.can_invoice_max_retries,
            wait_delay=self.can_invoice_wait_delay,
            sleep_fn=time.sleep,
            logger_instance=logger,
        )

    def _wait_for_sku_link(
        self,
        item_id: str,
        sku: str,
        variation_id: str | None = None,
    ) -> tuple[dict[str, Any] | None, int]:
        """Wait until SKU can be linked to the published item."""
        retryable_statuses = self.retry_config.retryable_status_codes | {404}
        return wait_for_sku_link(
            api_client=self.api_client,
            item_id=item_id,
            sku=sku,
            variation_id=variation_id,
            max_retries=self.can_invoice_max_retries,
            wait_delay=self.can_invoice_wait_delay,
            retryable_statuses=retryable_statuses,
            status_code_extractor=self._extract_status_code,
            response_detail_extractor=self._extract_response_detail,
            sleep_fn=time.sleep,
            logger_instance=logger,
        )

    def _wait_for_invoice_readiness(
        self, item_id: str, sku: str
    ) -> tuple[bool, dict[str, Any] | None, int]:
        """Poll can_invoice endpoint until ready or timeout."""
        return wait_for_invoice_readiness(
            item_id=item_id,
            sku=sku,
            max_retries=self.can_invoice_max_retries,
            wait_delay=self.can_invoice_wait_delay,
            verify_invoice_operation=lambda: self.api_client.verify_invoice_readiness(item_id),
            execute_with_retry=lambda operation: self._execute_with_retry(
                operation,
                "Verify invoice readiness",
                sku,
                item_id,
            ),
            retryable_status_codes=self.retry_config.retryable_status_codes,
            status_code_extractor=self._extract_status_code,
            sleep_fn=time.sleep,
            logger_instance=logger,
        )

    def submit_fiscal_data_workflow(
        self,
        item_id: str,
        fiscal_data: FiscalData,
        variation_id: str | None = None,
    ) -> FiscalSubmissionResult:
        """Execute complete fiscal data submission workflow.

        Workflow:
        1. Validate fiscal payload (required + conditional rules)
        2. Check fiscal data existence (GET /items/fiscal_information/{SKU})
        3. Register fiscal data when missing (POST /items/fiscal_information)
        4. Link SKU to item (POST /items/fiscal_information/items)
        5. Poll invoice readiness (GET /can_invoice/items/{ITEM_ID})
        """
        sku = fiscal_data.sku
        logger.info(f"Starting fiscal data workflow for item {item_id}, SKU: {sku}")

        missing_fields = fiscal_data.get_missing_fields()
        validation_errors = fiscal_data.get_validation_errors()
        if missing_fields or validation_errors:
            error_msg = (
                f"Invalid fiscal data for {item_id}: "
                f"missing={missing_fields}, validation_errors={validation_errors}"
            )
            logger.error(error_msg)
            return FiscalSubmissionResult(
                success=False,
                item_id=item_id,
                sku=sku,
                status=FiscalSubmissionStatus.SKIPPED,
                fiscal_data=fiscal_data,
                response={
                    "missing_fields": missing_fields,
                    "validation_errors": validation_errors,
                },
                error_message=error_msg,
                error_code="INVALID_FISCAL_DATA",
            )

        check_exists_retry_count = 0
        registration_retry_count = 0
        fiscal_status = FiscalSubmissionStatus.ALREADY_EXISTS

        try:
            (exists, _), check_exists_retry_count = self._execute_with_retry(
                lambda: self.api_client.check_fiscal_data_exists(sku),
                "Check fiscal data exists",
                sku,
                item_id,
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
                retry_count=check_exists_retry_count,
            )

        if not exists:
            fiscal_status = FiscalSubmissionStatus.REGISTERED
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
                error_detail = self._extract_response_detail(e)
                if error_detail is not None:
                    error_msg = f"{error_msg} - Response: {error_detail}"
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
                    retry_count=check_exists_retry_count + registration_retry_count,
                )
        else:
            logger.info(f"Fiscal data already exists for SKU {sku} (item {item_id})")

        total_retry_count = check_exists_retry_count + registration_retry_count

        link_retry_count = 0
        try:
            _, link_retry_count = self._wait_for_sku_link(
                item_id=item_id,
                sku=sku,
                variation_id=variation_id,
            )
            total_retry_count += link_retry_count
        except Exception as e:
            error_msg = f"Failed to link SKU to item: {str(e)}"
            error_detail = self._extract_response_detail(e)
            if error_detail is not None:
                error_msg = f"{error_msg} - Response: {error_detail}"
            logger.error(f"{error_msg} for SKU {sku} (item {item_id})")
            return FiscalSubmissionResult(
                success=False,
                item_id=item_id,
                sku=sku,
                status=FiscalSubmissionStatus.FAILED,
                fiscal_data=fiscal_data,
                response=error_detail,
                error_message=error_msg,
                error_code="SKU_ITEM_LINK_ERROR",
                retry_count=total_retry_count,
            )

        return self._verify_invoice_readiness(
            item_id,
            sku,
            fiscal_data,
            fiscal_status,
            total_retry_count,
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
            is_ready, response, retry_count = self._wait_for_invoice_readiness(item_id, sku)

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

            logger.warning(
                f"Invoice readiness still pending for item {item_id} (SKU: {sku}): {response}"
            )
            return FiscalSubmissionResult(
                success=True,
                item_id=item_id,
                sku=sku,
                status=FiscalSubmissionStatus.PENDING_VERIFICATION,
                fiscal_data=fiscal_data,
                response=response,
                error_message="Invoice readiness pending verification",
                error_code="INVOICE_PENDING",
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
        except ValueError as exc:
            logger.debug("Unable to decode fiscal error payload: %s", exc)

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
            try:
                result = self.submit_fiscal_data_workflow(item_id, fiscal_data)
            except Exception as e:
                logger.exception(
                    "Unexpected fiscal workflow error for item %s (SKU: %s): %s",
                    item_id,
                    fiscal_data.sku,
                    e,
                )
                result = FiscalSubmissionResult(
                    success=False,
                    item_id=item_id,
                    sku=fiscal_data.sku,
                    status=FiscalSubmissionStatus.FAILED,
                    fiscal_data=fiscal_data,
                    error_message=f"Unexpected fiscal workflow error: {e}",
                    error_code="BATCH_ITEM_ERROR",
                )
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
