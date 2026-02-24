"""Tests for fiscal submission workflow behavior."""

from unittest.mock import MagicMock, patch

import requests

from mercadolivre_upload.domain.fiscal.data import FiscalData
from mercadolivre_upload.domain.fiscal.service import (
    FiscalService,
    FiscalSubmissionResult,
    FiscalSubmissionStatus,
)


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


def test_submit_workflow_skips_registration_when_fiscal_data_already_exists():
    api_client = MagicMock()
    api_client.check_fiscal_data_exists.side_effect = [
        (True, {"sku": "SKU-123"}),
        (True, {"sku": "SKU-123"}),
    ]
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
    api_client.register_fiscal_data.assert_not_called()
    api_client.link_fiscal_sku_to_item.assert_called_once_with(sku="SKU-123", item_id="MLB123")


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


def test_submit_workflow_fails_fast_for_invalid_fiscal_data():
    api_client = MagicMock()
    service = FiscalService(api_client=api_client)
    invalid_fiscal_data = FiscalData(
        sku="SKU-123",
        title="Produto Teste",
        type="single",
        measurement_unit="UN",
        cost=10.0,
        ncm="",
        origin_type="reseller",
        origin_detail="2",
    )

    result = service.submit_fiscal_data_workflow("MLB123", invalid_fiscal_data)

    assert result.success is False
    assert result.status == FiscalSubmissionStatus.FAILED
    assert result.error_code == "INVALID_FISCAL_DATA"
    api_client.check_fiscal_data_exists.assert_not_called()
    api_client.register_fiscal_data.assert_not_called()
    api_client.link_fiscal_sku_to_item.assert_not_called()
    api_client.verify_invoice_readiness.assert_not_called()


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


def test_fiscal_data_treats_measurement_unit_as_optional_for_mlb_payload():
    with patch(
        "mercadolivre_upload.domain.fiscal.data._load_fiscal_defaults",
        return_value={"type": "single", "origin_type": "reseller", "tax_payer_type": "company"},
    ):
        fiscal_data = FiscalData(
            sku="SKU-123",
            title="Produto Teste",
            cost=10.0,
            ncm="39263000",
            origin_type="reseller",
            origin_detail="2",
            measurement_unit="",
        )

    payload = fiscal_data.to_api_payload()

    assert fiscal_data.is_valid is True
    assert "measurement_unit" not in fiscal_data.get_missing_fields()
    assert "measurement_unit" not in payload


def test_fiscal_data_uses_kg_weights_without_double_conversion():
    fiscal_data = FiscalData(
        sku="SKU-123",
        title="Produto Teste",
        type="single",
        measurement_unit="UN",
        cost=10.0,
        ncm="39263000",
        origin_type="reseller",
        origin_detail="2",
        net_weight="1,25",
        gross_weight=2,
    )

    payload = fiscal_data.to_api_payload()

    assert payload["tax_information"]["net_weight"] == 1.25
    assert payload["tax_information"]["gross_weight"] == 2.0


def test_fiscal_data_does_not_mark_optional_nan_fields_as_present():
    fiscal_data = FiscalData(
        sku="SKU-123",
        title="Produto Teste",
        type="single",
        measurement_unit="UN",
        cost=10.0,
        ncm="39263000",
        origin_type="reseller",
        origin_detail="2",
        cfop=float("nan"),
        ean=float("nan"),
    )

    tax_info = fiscal_data.to_api_payload()["tax_information"]

    assert "cfop" not in tax_info
    assert "ean" not in tax_info


def test_fiscal_data_requires_positive_cost():
    fiscal_data = FiscalData(
        sku="SKU-123",
        title="Produto Teste",
        type="single",
        measurement_unit="UN",
        cost=0.0,
        ncm="39263000",
        origin_type="reseller",
        origin_detail="2",
    )

    assert fiscal_data.is_valid is False
    assert "cost" in fiscal_data.get_missing_fields()


def test_submit_batch_continues_when_one_item_raises_unexpected_error():
    api_client = MagicMock()
    service = FiscalService(api_client=api_client)
    fiscal_data = _build_valid_fiscal_data()

    success_result = FiscalSubmissionResult(
        success=True,
        item_id="MLB1",
        sku=fiscal_data.sku,
        status=FiscalSubmissionStatus.VERIFIED,
        fiscal_data=fiscal_data,
    )
    second_item = FiscalData(**{**fiscal_data.to_dict(), "sku": "SKU-456"})
    third_item = FiscalData(**{**fiscal_data.to_dict(), "sku": "SKU-789"})

    service.submit_fiscal_data_workflow = MagicMock(  # type: ignore[method-assign]
        side_effect=[
            success_result,
            RuntimeError("boom"),
            FiscalSubmissionResult(
                success=True,
                item_id="MLB3",
                sku=third_item.sku,
                status=FiscalSubmissionStatus.PENDING_VERIFICATION,
                fiscal_data=third_item,
            ),
        ]
    )

    results = service.submit_fiscal_data_batch(
        [("MLB1", fiscal_data), ("MLB2", second_item), ("MLB3", third_item)]
    )

    assert len(results) == 3
    assert results[0].success is True
    assert results[1].success is False
    assert results[1].error_code == "BATCH_ITEM_ERROR"
    assert "Unexpected fiscal workflow error" in (results[1].error_message or "")
    assert results[2].success is True
