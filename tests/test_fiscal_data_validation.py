"""Focused tests for fiscal conditional validation rules."""

from mercadolivre_upload.domain.fiscal.data import FiscalData


def _base_fiscal(**overrides) -> FiscalData:
    payload = {
        "sku": "SKU-VALID",
        "title": "Produto",
        "type": "single",
        "measurement_unit": "UN",
        "cost": 10.0,
        "ncm": "39263000",
        "origin_type": "reseller",
        "origin_detail": "2",
    }
    payload.update(overrides)
    return FiscalData(**payload)


def test_fci_is_required_for_origin_detail_3_5_8() -> None:
    fiscal = _base_fiscal(origin_detail="3", fci=None)
    assert fiscal.is_valid is False
    assert "FCI é obrigatório quando origin_detail for 3, 5 ou 8" in fiscal.get_validation_errors()


def test_anvisa_isento_requires_exemption_reason() -> None:
    fiscal = _base_fiscal(med_anvisa_code="ISENTO", med_exemption_reason=None)
    assert fiscal.is_valid is False
    assert (
        "med_exemption_reason é obrigatório quando med_anvisa_code for ISENTO"
        in fiscal.get_validation_errors()
    )


def test_anvisa_numeric_forbids_exemption_reason() -> None:
    fiscal = _base_fiscal(med_anvisa_code="1234567890123", med_exemption_reason="qualquer")
    assert fiscal.is_valid is False
    assert (
        "med_exemption_reason só deve ser enviado com med_anvisa_code=ISENTO"
        in fiscal.get_validation_errors()
    )


def test_csosn_and_tax_rule_id_are_mutually_exclusive() -> None:
    fiscal = _base_fiscal(csosn="102", tax_rule_id=123)
    assert fiscal.is_valid is False
    assert "csosn e tax_rule_id não podem ser enviados juntos" in fiscal.get_validation_errors()
