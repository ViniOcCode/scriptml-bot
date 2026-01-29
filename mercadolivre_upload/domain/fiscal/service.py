"""Fiscal service for managing tax information submission.

This service handles the post-publication submission of fiscal data
to Mercado Livre's fiscal information endpoint.
"""

import logging
from dataclasses import dataclass
from typing import Any, Optional, Protocol

from .data import FiscalData

logger = logging.getLogger(__name__)


@dataclass
class FiscalSubmissionResult:
    """Result of fiscal data submission."""

    success: bool
    item_id: str
    fiscal_data: FiscalData
    response: Optional[dict[str, Any]] = None
    error_message: Optional[str] = None
    error_code: Optional[str] = None


class FiscalApiPort(Protocol):
    """Port for fiscal API operations."""

    def submit_fiscal_info(self, item_id: str, fiscal_data: dict[str, Any]) -> dict[str, Any]:
        """Submit fiscal information for an item.

        Args:
            item_id: Mercado Livre item ID (e.g., MLB1234567890)
            fiscal_data: Fiscal data payload

        Returns:
            API response
        """
        ...


class FiscalService:
    """Service for managing fiscal data submission.

    This service orchestrates the submission of fiscal information to Mercado Livre
    after an item has been successfully published.
    """

    def __init__(self, api_client: FiscalApiPort):
        """Initialize fiscal service.

        Args:
            api_client: API client implementing FiscalApiPort
        """
        self.api_client = api_client

    def submit_fiscal_data(
        self,
        item_id: str,
        fiscal_data: FiscalData
    ) -> FiscalSubmissionResult:
        """Submit fiscal data for a published item.

        Args:
            item_id: Mercado Livre item ID (e.g., MLB1234567890)
            fiscal_data: Fiscal data to submit

        Returns:
            FiscalSubmissionResult with success status and details
        """
        # Validate fiscal data before submission
        if not fiscal_data.is_valid:
            missing = fiscal_data.get_missing_fields()
            error_msg = f"Invalid fiscal data for {item_id}: missing {missing}"
            logger.error(error_msg)
            return FiscalSubmissionResult(
                success=False,
                item_id=item_id,
                fiscal_data=fiscal_data,
                error_message=error_msg,
                error_code="INVALID_FISCAL_DATA"
            )

        # Build API payload
        payload = fiscal_data.to_api_payload()
        logger.info(f"Submitting fiscal data for item {item_id}, SKU: {fiscal_data.sku}")
        logger.debug(f"Fiscal payload for {item_id}: {payload}")

        try:
            # Submit to API
            response = self.api_client.submit_fiscal_info(item_id, payload)
            logger.info(f"Successfully submitted fiscal data for {item_id}")

            return FiscalSubmissionResult(
                success=True,
                item_id=item_id,
                fiscal_data=fiscal_data,
                response=response
            )

        except Exception as e:
            error_msg = str(e)
            error_code: str = "API_ERROR"

            # Try to extract error details from exception
            response = getattr(e, 'response', None)
            if response is not None:
                try:
                    error_detail = response.json()
                    error_msg = f"{error_msg} - {error_detail}"

                    # Extract specific error codes if available
                    if isinstance(error_detail, dict):
                        causes_value: Any = error_detail.get("cause", [])
                        if isinstance(causes_value, list) and len(causes_value) > 0:
                            first_cause: Any = causes_value[0]
                            if isinstance(first_cause, dict):
                                code_value: Any = first_cause.get("code")
                                if code_value is not None:
                                    error_code = str(code_value)
                except Exception:
                    text = getattr(response, 'text', '')
                    error_msg = f"{error_msg} - {text[:200]}"

            logger.error(f"Failed to submit fiscal data for {item_id}: {error_msg}")

            return FiscalSubmissionResult(
                success=False,
                item_id=item_id,
                fiscal_data=fiscal_data,
                error_message=error_msg,
                error_code=error_code
            )

    def submit_fiscal_data_batch(
        self,
        items: list[tuple[str, FiscalData]]
    ) -> list[FiscalSubmissionResult]:
        """Submit fiscal data for multiple items.

        Args:
            items: List of (item_id, fiscal_data) tuples

        Returns:
            List of FiscalSubmissionResult for each submission
        """
        results: list[FiscalSubmissionResult] = []

        for item_id, fiscal_data in items:
            result = self.submit_fiscal_data(item_id, fiscal_data)
            results.append(result)

        return results

    def validate_fiscal_data(
        self,
        fiscal_data: FiscalData
    ) -> tuple[bool, list[str]]:
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
