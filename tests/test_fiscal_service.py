"""Tests for fiscal submission workflow behavior."""

from unittest.mock import MagicMock, patch

import requests

from mercadolivre_upload.domain.fiscal.data import FiscalData
from mercadolivre_upload.domain.fiscal.service import FiscalService, FiscalSubmissionStatus


def _build_valid_fiscal_data() -> FiscalData:
    return FiscalData(
        sku="SKU-123",
        title="Produto Teste",
        type="single",
        measurement_unit="UN",
        cost=10.0,
        ncm="39263000",
        origin_type="reseller",
        origin_detail="2",
    )


def test_submit_workflow_marks_pending_when_invoice_not_ready():
    api_client = MagicMock()
    api_client.check_fiscal_data_exists.side_effect = [(False, None), (False, None)]
    api_client.register_fiscal_data.return_value = {"sku": "SKU-123"}
    api_client.link_fiscal_sku_to_item.return_value = {"status": "active"}
    api_client.verify_invoice_readiness.return_value = (
        False,
        {"item_id": "MLB123", "status": False},
    )

    service = FiscalService(
        api_client=api_client, can_invoice_wait_delay=0.0, can_invoice_max_retries=2
    )
    fiscal_data = _build_valid_fiscal_data()

    with patch("mercadolivre_upload.domain.fiscal.service.time.sleep") as sleep_mock:
        result = service.submit_fiscal_data_workflow("MLB123", fiscal_data)

    assert result.success is True
    assert result.status == FiscalSubmissionStatus.PENDING_VERIFICATION
    assert result.error_code == "INVOICE_PENDING"
    assert api_client.verify_invoice_readiness.call_count == 3
    assert sleep_mock.call_count == 2


def test_submit_workflow_links_sku_after_registering_fiscal_data():
    api_client = MagicMock()
    api_client.check_fiscal_data_exists.side_effect = [(False, None), (False, None)]
    api_client.register_fiscal_data.return_value = {"sku": "SKU-123"}
    api_client.link_fiscal_sku_to_item.return_value = {"status": "active"}
    api_client.verify_invoice_readiness.return_value = (
        True,
        {"item_id": "MLB123", "status": True},
    )

    service = FiscalService(
        api_client=api_client, can_invoice_wait_delay=0.0, can_invoice_max_retries=0
    )
    fiscal_data = _build_valid_fiscal_data()
    result = service.submit_fiscal_data_workflow("MLB123", fiscal_data)

    assert result.success is True
    assert result.status == FiscalSubmissionStatus.VERIFIED
    api_client.link_fiscal_sku_to_item.assert_called_once_with(sku="SKU-123", item_id="MLB123")

    register_index = next(
        i for i, call in enumerate(api_client.mock_calls) if call[0] == "register_fiscal_data"
    )
    link_index = next(
        i for i, call in enumerate(api_client.mock_calls) if call[0] == "link_fiscal_sku_to_item"
    )
    assert register_index < link_index


def test_submit_workflow_retries_sku_link_when_item_not_ready():
    link_error = requests.HTTPError("Item not found")
    link_error.response = MagicMock(status_code=404)  # type: ignore[attr-defined]
    link_error.response.json.return_value = {"error_code": "10095"}  # type: ignore[attr-defined]

    api_client = MagicMock()
    api_client.check_fiscal_data_exists.side_effect = [(False, None), (False, None)]
    api_client.register_fiscal_data.return_value = {"sku": "SKU-123"}
    api_client.link_fiscal_sku_to_item.side_effect = [link_error, {"status": "active"}]
    api_client.verify_invoice_readiness.return_value = (
        True,
        {"item_id": "MLB123", "status": True},
    )

    service = FiscalService(
        api_client=api_client, can_invoice_wait_delay=0.0, can_invoice_max_retries=2
    )
    fiscal_data = _build_valid_fiscal_data()

    with patch("mercadolivre_upload.domain.fiscal.service.time.sleep") as sleep_mock:
        result = service.submit_fiscal_data_workflow("MLB123", fiscal_data)

    assert result.success is True
    assert result.status == FiscalSubmissionStatus.VERIFIED
    assert api_client.link_fiscal_sku_to_item.call_count == 2
    assert sleep_mock.call_count >= 1


def test_extract_error_code_returns_first_cause_code():
    api_client = MagicMock()
    service = FiscalService(api_client=api_client)

    response = MagicMock()
    response.json.return_value = {"cause": [{"code": "10095"}]}
    exc = Exception("API error")
    exc.response = response  # type: ignore[attr-defined]

    assert service._extract_error_code(exc) == "10095"


def test_extract_error_code_returns_none_for_invalid_json():
    api_client = MagicMock()
    service = FiscalService(api_client=api_client)

    response = MagicMock()
    response.json.side_effect = ValueError("not json")
    exc = Exception("API error")
    exc.response = response  # type: ignore[attr-defined]

    assert service._extract_error_code(exc) is None
