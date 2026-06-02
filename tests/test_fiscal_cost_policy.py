"""Regression tests: fiscal cost (Custo unitário) is optional and never inferred from price."""

from unittest.mock import MagicMock, patch

from mercadolivre_upload.application.publish_payload_use_case import _build_fiscal_data
from mercadolivre_upload.domain.fiscal.data import FiscalData
from mercadolivre_upload.domain.fiscal.field_policy import (
    fiscal_cost_for_api_payload,
    load_optional_fiscal_fields,
    load_required_fiscal_fields,
    normalize_fiscal_cost,
)
from mercadolivre_upload.domain.fiscal.service import FiscalService


def _complete_fiscal_item(**overrides: object) -> dict:
    item = {
        "sku": "SKU-FISCAL",
        "type": "single",
        "measurement_unit": "UN",
        "tax_information": {
            "ncm": "90183929",
            "origin_type": "reseller",
            "origin_detail": "0",
        },
    }
    item.update(overrides)
    return item


def _complete_fiscal_data(**overrides: object) -> FiscalData:
    payload = {
        "sku": "SKU-FISCAL",
        "title": "Produto fiscal",
        "type": "single",
        "measurement_unit": "UN",
        "ncm": "90183929",
        "origin_type": "reseller",
        "origin_detail": "0",
    }
    payload.update(overrides)
    return FiscalData(**payload)


def test_cost_is_optional_in_config_policy() -> None:
    assert "cost" in load_optional_fiscal_fields()
    assert "cost" not in load_required_fiscal_fields()


def test_fiscal_data_valid_without_cost() -> None:
    fiscal = _complete_fiscal_data()
    assert fiscal.cost is None
    assert "cost" not in fiscal.get_missing_fields()
    assert fiscal.is_valid is True


def test_fiscal_data_valid_with_cost_none() -> None:
    fiscal = _complete_fiscal_data(cost=None)
    assert "cost" not in fiscal.get_missing_fields()
    assert fiscal.is_valid is True


def test_fiscal_data_valid_with_cost_zero_treated_as_unset() -> None:
    fiscal = _complete_fiscal_data(cost=0.0)
    assert fiscal.cost is None
    assert "cost" not in fiscal.get_missing_fields()
    assert fiscal.is_valid is True


def test_build_fiscal_data_does_not_use_item_price_when_cost_missing() -> None:
    fiscal = _build_fiscal_data(
        fiscal_item=_complete_fiscal_item(),
        publish_payload={"price": 199.9, "title": "Anúncio"},
        fallback_sku=None,
    )
    assert fiscal.cost is None
    assert "cost" not in fiscal.get_missing_fields()


def test_build_fiscal_data_does_not_use_item_price_when_cost_null() -> None:
    fiscal = _build_fiscal_data(
        fiscal_item=_complete_fiscal_item(cost=None),
        publish_payload={"price": 199.9, "title": "Anúncio"},
        fallback_sku=None,
    )
    assert fiscal.cost is None
    assert "cost" not in fiscal.to_api_payload()


def test_to_api_payload_omits_cost_when_unset() -> None:
    fiscal = _complete_fiscal_data()
    body = fiscal.to_api_payload()
    assert "cost" not in body


def test_to_api_payload_includes_explicit_positive_cost_only() -> None:
    fiscal = _complete_fiscal_data(cost=42.5)
    body = fiscal.to_api_payload()
    assert body["cost"] == 42.5


def test_normalize_fiscal_cost_never_returns_price_like_fallback() -> None:
    assert normalize_fiscal_cost(None) is None
    assert normalize_fiscal_cost(0) is None
    assert normalize_fiscal_cost(15.0) == 15.0
    assert fiscal_cost_for_api_payload(199.9) == 199.9


def test_missing_ncm_still_fails_validation() -> None:
    fiscal = _complete_fiscal_data(ncm="")
    assert fiscal.is_valid is False
    assert "ncm" in fiscal.get_missing_fields()


def test_fiscal_service_workflow_accepts_missing_cost() -> None:
    fiscal = _complete_fiscal_data()
    api_client = MagicMock()
    api_client.check_fiscal_data_exists.return_value = (False, None)
    api_client.register_fiscal_data.return_value = {"ok": True}
    api_client.link_fiscal_sku_to_item.return_value = {"ok": True}
    api_client.verify_invoice_readiness.return_value = (True, {"status": True})

    service = FiscalService(api_client)
    captured: dict = {}

    def _register(payload: dict) -> dict:
        captured["body"] = payload
        return {"ok": True}

    api_client.register_fiscal_data.side_effect = _register

    with patch.object(service, "_wait_for_invoice_readiness", return_value=(True, {}, 0)):
        result = service.submit_fiscal_data_workflow("MLB0000000001", fiscal)

    assert result.success is True
    assert "cost" not in captured["body"]
    assert "cost" not in fiscal.get_missing_fields()
