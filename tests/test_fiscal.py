"""Unit tests for fiscal data submission module."""

import unittest
from unittest.mock import MagicMock, patch

import requests

from mercadolivre_upload.domain.fiscal.data import FiscalData
from mercadolivre_upload.domain.fiscal.service import (
    FiscalService,
    RetryConfig,
    FiscalSubmissionStatus,
    FiscalSubmissionResult,
)


class TestFiscalData(unittest.TestCase):
    """Tests for FiscalData model."""

    def test_fiscal_data_creation(self):
        """Test basic FiscalData creation."""
        data = FiscalData(
            sku="SKU123",
            title="Test Product",
            cost=100.0,
            ncm="39263000",
            origin_type="reseller",
            origin_detail="2",
        )

        self.assertEqual(data.sku, "SKU123")
        self.assertEqual(data.title, "Test Product")
        self.assertEqual(data.cost, 100.0)
        self.assertEqual(data.ncm, "39263000")
        self.assertEqual(data.origin_type, "reseller")
        self.assertEqual(data.origin_detail, "2")
        self.assertEqual(data.type, "single")
        self.assertEqual(data.measurement_unit, "UN")

    def test_fiscal_data_validation_valid(self):
        """Test validation with valid data."""
        data = FiscalData(
            sku="SKU123",
            title="Test Product",
            cost=100.0,
            ncm="39263000",
            origin_type="reseller",
            origin_detail="2",
        )

        self.assertTrue(data.is_valid)
        self.assertEqual(data.get_missing_fields(), [])

    def test_fiscal_data_validation_invalid(self):
        """Test validation with invalid data."""
        data = FiscalData(
            sku="",
            title="",
            cost=0.0,
            ncm="",
            origin_type="",
            origin_detail="",
        )

        self.assertFalse(data.is_valid)
        missing = data.get_missing_fields()
        self.assertIn("sku", missing)
        self.assertIn("title", missing)
        self.assertIn("cost", missing)
        self.assertIn("ncm", missing)
        self.assertIn("origin_type", missing)
        self.assertIn("origin_detail", missing)

    def test_fiscal_data_to_api_payload(self):
        """Test conversion to API payload."""
        data = FiscalData(
            sku="SKU123",
            title="Test Product",
            cost=100.0,
            ncm="39263000",
            origin_type="reseller",
            origin_detail="2",
            cest="1234567",
            csosn="500",
            ean="7891234567890",
        )

        payload = data.to_api_payload()

        self.assertEqual(payload["sku"], "SKU123")
        self.assertEqual(payload["title"], "Test Product")
        self.assertEqual(payload["type"], "single")
        self.assertEqual(payload["measurement_unit"], "UN")
        self.assertEqual(payload["cost"], 100.0)
        self.assertEqual(payload["tax_information"]["ncm"], "39263000")
        self.assertEqual(payload["tax_information"]["origin_type"], "reseller")
        self.assertEqual(payload["tax_information"]["origin_detail"], "2")
        self.assertEqual(payload["tax_information"]["cest"], "1234567")
        self.assertEqual(payload["tax_information"]["csosn"], "500")
        self.assertEqual(payload["tax_information"]["ean"], "7891234567890")

    def test_fiscal_data_from_spreadsheet_row(self):
        """Test creation from spreadsheet row."""
        data = FiscalData.from_spreadsheet_row(
            sku="SKU123",
            title="Test Product",
            cost=100.0,
            ncm="39263000",
            origin="2",
            cfop="5102",
            cest="1234567",
        )

        self.assertEqual(data.sku, "SKU123")
        self.assertEqual(data.origin_detail, "2")
        self.assertEqual(data.cfop, "5102")
        self.assertEqual(data.cest, "1234567")
        self.assertEqual(data.origin_type, "reseller")


class TestRetryConfig(unittest.TestCase):
    """Tests for RetryConfig."""

    def test_default_config(self):
        """Test default retry configuration."""
        config = RetryConfig()

        self.assertEqual(config.max_retries, 3)
        self.assertEqual(config.base_delay, 1.0)
        self.assertEqual(config.max_delay, 60.0)
        self.assertEqual(config.exponential_base, 2.0)
        self.assertEqual(config.retryable_status_codes, {429, 500, 502, 503, 504})

    def test_custom_config(self):
        """Test custom retry configuration."""
        config = RetryConfig(
            max_retries=5,
            base_delay=2.0,
            max_delay=30.0,
            exponential_base=3.0,
        )

        self.assertEqual(config.max_retries, 5)
        self.assertEqual(config.base_delay, 2.0)
        self.assertEqual(config.max_delay, 30.0)
        self.assertEqual(config.exponential_base, 3.0)

    def test_get_delay_exponential_backoff(self):
        """Test exponential backoff delay calculation."""
        config = RetryConfig(base_delay=1.0, exponential_base=2.0)

        self.assertEqual(config.get_delay(0), 1.0)
        self.assertEqual(config.get_delay(1), 2.0)
        self.assertEqual(config.get_delay(2), 4.0)
        self.assertEqual(config.get_delay(3), 8.0)

    def test_get_delay_max_cap(self):
        """Test delay max cap."""
        config = RetryConfig(base_delay=1.0, max_delay=10.0)

        self.assertEqual(config.get_delay(10), 10.0)


class TestFiscalService(unittest.TestCase):
    """Tests for FiscalService."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_api = MagicMock()
        # Use zero wait delay for tests to avoid long waits
        self.service = FiscalService(
            self.mock_api,
            can_invoice_wait_delay=0.0,
            can_invoice_max_retries=0
        )
        self.valid_fiscal_data = FiscalData(
            sku="SKU123",
            title="Test Product",
            cost=100.0,
            ncm="39263000",
            origin_type="reseller",
            origin_detail="2",
        )

    def test_submit_fiscal_data_workflow_already_exists(self):
        """Test workflow when fiscal data already exists."""
        # Mock API responses - can_invoice must return True first
        self.mock_api.verify_invoice_readiness.return_value = (True, {"status": True})
        self.mock_api.check_fiscal_data_exists.return_value = (True, {"id": "123"})

        result = self.service.submit_fiscal_data_workflow(
            "MLB123456", self.valid_fiscal_data
        )

        self.assertTrue(result.success)
        self.assertEqual(result.status, FiscalSubmissionStatus.VERIFIED)
        self.assertEqual(result.item_id, "MLB123456")
        self.assertEqual(result.sku, "SKU123")

        # Verify API calls - can_invoice is called first now
        self.mock_api.verify_invoice_readiness.assert_called_with("MLB123456")
        self.mock_api.check_fiscal_data_exists.assert_called_once_with("SKU123")
        self.mock_api.register_fiscal_data.assert_not_called()

    def test_submit_fiscal_data_workflow_register_new(self):
        """Test workflow when registering new fiscal data."""
        # Mock API responses - can_invoice must return True first
        self.mock_api.verify_invoice_readiness.return_value = (True, {"status": True})
        self.mock_api.check_fiscal_data_exists.return_value = (False, None)
        self.mock_api.register_fiscal_data.return_value = {"id": "456"}

        result = self.service.submit_fiscal_data_workflow(
            "MLB123456", self.valid_fiscal_data
        )

        self.assertTrue(result.success)
        self.assertEqual(result.status, FiscalSubmissionStatus.VERIFIED)

        # Verify API calls - can_invoice is called first, then at the end
        self.mock_api.verify_invoice_readiness.assert_called_with("MLB123456")
        self.mock_api.check_fiscal_data_exists.assert_called_once_with("SKU123")
        self.mock_api.register_fiscal_data.assert_called_once()

    def test_submit_fiscal_data_workflow_register_new_with_retry(self):
        """Test workflow with retry during registration."""
        # Create mock response with retryable status code
        mock_response = MagicMock()
        mock_response.status_code = 503

        error = requests.HTTPError("Service Unavailable")
        error.response = mock_response

        # Mock API responses - can_invoice returns True, check exists returns False,
        # register fails once then succeeds
        self.mock_api.verify_invoice_readiness.return_value = (True, {"status": True})
        self.mock_api.check_fiscal_data_exists.return_value = (False, None)
        self.mock_api.register_fiscal_data.side_effect = [error, {"id": "456"}]

        with patch("time.sleep") as mock_sleep:
            result = self.service.submit_fiscal_data_workflow(
                "MLB123456", self.valid_fiscal_data
            )

        self.assertTrue(result.success)
        self.assertEqual(result.status, FiscalSubmissionStatus.VERIFIED)
        self.assertEqual(self.mock_api.register_fiscal_data.call_count, 2)
        mock_sleep.assert_called()

    def test_submit_fiscal_data_workflow_invalid_data(self):
        """Test workflow with invalid fiscal data."""
        invalid_data = FiscalData(
            sku="",
            title="",
            cost=0.0,
            ncm="",
            origin_type="",
            origin_detail="",
        )

        result = self.service.submit_fiscal_data_workflow("MLB123456", invalid_data)

        self.assertFalse(result.success)
        self.assertEqual(result.status, FiscalSubmissionStatus.FAILED)
        self.assertEqual(result.error_code, "INVALID_FISCAL_DATA")
        self.mock_api.check_fiscal_data_exists.assert_not_called()

    def test_submit_fiscal_data_workflow_not_invoice_ready(self):
        """Test workflow when item is not invoice ready."""
        # First can_invoice check returns True (to proceed with fiscal data)
        # Final verify_invoice_readiness returns False
        self.mock_api.verify_invoice_readiness.side_effect = [
            (True, {"status": True}),  # First check - ready for fiscal data
            (False, {"status": False, "reason": "missing_data"}),  # Final check
        ]
        self.mock_api.check_fiscal_data_exists.return_value = (False, None)
        self.mock_api.register_fiscal_data.return_value = {"id": "456"}

        result = self.service.submit_fiscal_data_workflow(
            "MLB123456", self.valid_fiscal_data
        )

        self.assertFalse(result.success)
        self.assertEqual(result.status, FiscalSubmissionStatus.FAILED)
        self.assertEqual(result.error_code, "NOT_INVOICE_READY")

    def test_submit_fiscal_data_workflow_check_exists_error(self):
        """Test workflow when check exists fails."""
        # can_invoice returns True first, then check_exists fails
        self.mock_api.verify_invoice_readiness.return_value = (True, {"status": True})
        self.mock_api.check_fiscal_data_exists.side_effect = requests.HTTPError(
            "Server Error"
        )

        result = self.service.submit_fiscal_data_workflow(
            "MLB123456", self.valid_fiscal_data
        )

        self.assertFalse(result.success)
        self.assertEqual(result.status, FiscalSubmissionStatus.FAILED)
        self.assertEqual(result.error_code, "CHECK_EXISTS_ERROR")

    def test_submit_fiscal_data_workflow_register_error(self):
        """Test workflow when registration fails."""
        # can_invoice returns True first, then registration fails
        self.mock_api.verify_invoice_readiness.return_value = (True, {"status": True})
        self.mock_api.check_fiscal_data_exists.return_value = (False, None)
        self.mock_api.register_fiscal_data.side_effect = requests.HTTPError(
            "Bad Request"
        )

        result = self.service.submit_fiscal_data_workflow(
            "MLB123456", self.valid_fiscal_data
        )

        self.assertFalse(result.success)
        self.assertEqual(result.status, FiscalSubmissionStatus.FAILED)

    def test_retry_logic_transient_error(self):
        """Test retry logic for transient errors."""
        # Create mock response with status code
        mock_response = MagicMock()
        mock_response.status_code = 503

        # Create exception with response
        error = requests.HTTPError("Service Unavailable")
        error.response = mock_response

        # can_invoice returns True, then check_exists fails twice, then succeeds
        self.mock_api.verify_invoice_readiness.return_value = (True, {"status": True})
        self.mock_api.check_fiscal_data_exists.side_effect = [
            error,
            error,
            (True, {"id": "123"}),
        ]

        with patch("time.sleep") as mock_sleep:
            result = self.service.submit_fiscal_data_workflow(
                "MLB123456", self.valid_fiscal_data
            )

        self.assertTrue(result.success)
        # Retry count is from check_exists retry logic
        self.assertEqual(self.mock_api.check_fiscal_data_exists.call_count, 3)
        mock_sleep.assert_called()

    def test_retry_logic_non_retryable_error(self):
        """Test that non-retryable errors are not retried."""
        mock_response = MagicMock()
        mock_response.status_code = 400

        error = requests.HTTPError("Bad Request")
        error.response = mock_response

        # can_invoice returns True, then check_exists fails with non-retryable error
        self.mock_api.verify_invoice_readiness.return_value = (True, {"status": True})
        self.mock_api.check_fiscal_data_exists.side_effect = error

        with patch("time.sleep") as mock_sleep:
            result = self.service.submit_fiscal_data_workflow(
                "MLB123456", self.valid_fiscal_data
            )

        self.assertFalse(result.success)
        self.mock_api.check_fiscal_data_exists.assert_called_once()
        mock_sleep.assert_not_called()

    def test_submit_fiscal_data_batch(self):
        """Test batch submission."""
        items = [
            ("MLB123", self.valid_fiscal_data),
            ("MLB456", FiscalData(
                sku="SKU456",
                title="Product 2",
                cost=200.0,
                ncm="39263000",
                origin_type="manufacturer",
                origin_detail="1",
            )),
        ]

        # can_invoice returns True for both items
        self.mock_api.verify_invoice_readiness.return_value = (True, {"status": True})
        self.mock_api.check_fiscal_data_exists.return_value = (True, {"id": "123"})

        results = self.service.submit_fiscal_data_batch(items)

        self.assertEqual(len(results), 2)
        self.assertTrue(all(r.success for r in results))

    def test_validate_fiscal_data(self):
        """Test validation without submission."""
        is_valid, missing = self.service.validate_fiscal_data(self.valid_fiscal_data)

        self.assertTrue(is_valid)
        self.assertEqual(missing, [])

        invalid_data = FiscalData(
            sku="",
            title="Test",
            cost=100.0,
            ncm="39263000",
            origin_type="reseller",
            origin_detail="2",
        )

        is_valid, missing = self.service.validate_fiscal_data(invalid_data)
        self.assertFalse(is_valid)
        self.assertIn("sku", missing)

    def test_check_fiscal_data_exists_method(self):
        """Test standalone check exists method."""
        self.mock_api.check_fiscal_data_exists.return_value = (True, {"id": "123"})

        exists, data, retry_count = self.service.check_fiscal_data_exists(
            "SKU123", "MLB123"
        )

        self.assertTrue(exists)
        self.assertEqual(data, {"id": "123"})
        self.assertEqual(retry_count, 0)

    def test_register_fiscal_data_method(self):
        """Test standalone register method."""
        self.mock_api.register_fiscal_data.return_value = {"id": "456"}

        response, retry_count = self.service.register_fiscal_data(
            self.valid_fiscal_data, "MLB123"
        )

        self.assertEqual(response, {"id": "456"})
        self.assertEqual(retry_count, 0)

    def test_verify_invoice_readiness_method(self):
        """Test standalone verify method."""
        self.mock_api.verify_invoice_readiness.return_value = (
            True,
            {"status": True},
        )

        is_ready, response, retry_count = self.service.verify_invoice_readiness(
            "MLB123", "SKU123"
        )

        self.assertTrue(is_ready)
        self.assertEqual(response, {"status": True})
        self.assertEqual(retry_count, 0)

    def test_register_fiscal_data_invalid_data_raises(self):
        """Test that register raises on invalid data."""
        invalid_data = FiscalData(
            sku="",
            title="",
            cost=0.0,
            ncm="",
            origin_type="",
            origin_detail="",
        )

        with self.assertRaises(ValueError) as context:
            self.service.register_fiscal_data(invalid_data)

        self.assertIn("Invalid fiscal data", str(context.exception))


class TestMLApiClientFiscalEndpoints(unittest.TestCase):
    """Tests for MLApiClient fiscal endpoints."""

    def setUp(self):
        """Set up test fixtures."""
        from mercadolivre_upload.api.client import MLApiClient

        self.client = MLApiClient()
        self.client.session = MagicMock()

    def test_check_fiscal_data_exists_found(self):
        """Test check exists when data exists."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"sku": "SKU123", "title": "Test"}
        self.client.session.get.return_value = mock_response

        exists, data = self.client.check_fiscal_data_exists("SKU123")

        self.assertTrue(exists)
        self.assertEqual(data, {"sku": "SKU123", "title": "Test"})

    def test_check_fiscal_data_exists_not_found(self):
        """Test check exists when data not found."""
        mock_response = MagicMock()
        mock_response.status_code = 404

        error = requests.HTTPError("Not Found")
        error.response = mock_response
        self.client.session.get.side_effect = error

        exists, data = self.client.check_fiscal_data_exists("SKU123")

        self.assertFalse(exists)
        self.assertIsNone(data)

    def test_check_fiscal_data_exists_other_error_raises(self):
        """Test check exists raises on non-404 errors."""
        mock_response = MagicMock()
        mock_response.status_code = 500

        error = requests.HTTPError("Server Error")
        error.response = mock_response
        self.client.session.get.side_effect = error

        with self.assertRaises(requests.HTTPError):
            self.client.check_fiscal_data_exists("SKU123")

    def test_register_fiscal_data(self):
        """Test register fiscal data."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"id": "123", "status": "created"}
        self.client.session.post.return_value = mock_response

        payload = {
            "sku": "SKU123",
            "title": "Test",
            "type": "single",
            "measurement_unit": "UN",
            "cost": 100.0,
            "tax_information": {"ncm": "39263000"},
        }

        result = self.client.register_fiscal_data(payload)

        self.assertEqual(result, {"id": "123", "status": "created"})

    def test_verify_invoice_readiness_ready(self):
        """Test verify when ready."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"status": True, "item_id": "MLB123"}
        self.client.session.get.return_value = mock_response

        is_ready, data = self.client.verify_invoice_readiness("MLB123")

        self.assertTrue(is_ready)
        self.assertEqual(data, {"status": True, "item_id": "MLB123"})

    def test_verify_invoice_readiness_not_ready(self):
        """Test verify when not ready."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"status": False, "reason": "missing_data"}
        self.client.session.get.return_value = mock_response

        is_ready, data = self.client.verify_invoice_readiness("MLB123")

        self.assertFalse(is_ready)
        self.assertEqual(data, {"status": False, "reason": "missing_data"})


if __name__ == "__main__":
    unittest.main()
