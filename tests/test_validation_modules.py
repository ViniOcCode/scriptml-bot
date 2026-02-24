"""Tests for base and extended validation modules."""

from __future__ import annotations

import sys
import types

from mercadolivre_upload.domain.validation.base import (
    BaseValidator,
    LengthRule,
    RangeRule,
    RequiredFieldRule,
    ValidationSeverity,
    create_validator,
)
from mercadolivre_upload.domain.validation.extended_validators import (
    CategoryValidator,
    ExtendedValidationSuite,
    ImageValidator,
    PriceValidator,
    StockValidator,
    TitleValidator,
)


class _DummyValidator(BaseValidator):
    def validate(self, data):
        self._clear_results()
        return self._apply_rules(data)


def test_base_rules_and_result_accumulators() -> None:
    validator = _DummyValidator()
    validator.add_rule(RequiredFieldRule("title"))
    validator.add_rule(
        LengthRule("title", min_length=3, max_length=8, severity=ValidationSeverity.WARNING)
    )
    validator.add_rule(RangeRule("price", min_value=1.0, max_value=10.0))

    results = validator.validate({"title": "ab", "price": 0.5})
    assert len(results) == 2
    assert validator.has_errors() is True
    assert validator.has_warnings() is True
    assert len(validator.get_errors()) == 1
    assert len(validator.get_warnings()) == 1

    validator.clear_rules()
    assert validator.validate({"title": "abc", "price": 5}) == []


def test_required_length_and_range_rules_individual_paths() -> None:
    assert RequiredFieldRule("sku").validate({"sku": ""}) is not None
    assert RequiredFieldRule("sku").validate({}) is not None
    assert RequiredFieldRule("sku").validate({"sku": "ok"}) is None

    assert LengthRule("name", max_length=2).validate({"name": "abcd"}) is not None
    assert LengthRule("name", min_length=4).validate({"name": "ab"}) is not None

    assert RangeRule("qty", min_value=1).validate({"qty": None}) is not None
    assert RangeRule("qty", min_value=1).validate({"qty": "x"}) is not None
    assert RangeRule("qty", min_value=1).validate({"qty": 0}) is not None
    assert RangeRule("qty", max_value=1).validate({"qty": 2}) is not None
    assert RangeRule("qty", min_value=1, max_value=2).validate({"qty": 1.5}) is None


def test_create_validator_factory_with_injected_product_validator(monkeypatch) -> None:
    module_name = "mercadolivre_upload.domain.validation.product_validator"
    fake_module = types.ModuleType(module_name)

    class ProductValidator(BaseValidator):
        def validate(self, data):
            self._clear_results()
            return self._apply_rules(data)

    fake_module.ProductValidator = ProductValidator
    monkeypatch.setitem(sys.modules, module_name, fake_module)

    validator = create_validator([RequiredFieldRule("sku")])
    results = validator.validate({})
    assert results
    assert results[0].field == "sku"


def test_price_and_title_validators_cover_common_edges() -> None:
    price_validator = PriceValidator()

    assert price_validator.validate({"price": "abc"})[0].is_error()
    assert any(r.is_error() for r in price_validator.validate({"price": -10}))
    assert any(r.is_error() for r in price_validator.validate({"price": 0}))
    low_results = price_validator.validate({"price": 0.10})
    assert any(r.is_warning() for r in low_results)
    assert any("chamativo" in r.message for r in low_results)
    assert any(r.is_error() for r in price_validator.validate({"price": 100_000_001}))

    title_validator = TitleValidator()
    assert title_validator.validate({"title": 123})[0].is_error()
    assert any(r.is_error() for r in title_validator.validate({"title": "abc"}))
    assert any(r.is_error() for r in title_validator.validate({"title": "x" * 70}))
    flagged = title_validator.validate({"title": " promo whatsapp "})
    assert any("proibida" in r.message for r in flagged)
    assert any(r.is_warning() for r in flagged)


def test_image_category_stock_and_suite_validators(monkeypatch) -> None:
    image_validator = ImageValidator()
    assert image_validator.validate({"pictures": []})[0].is_warning()

    too_many = image_validator.validate(
        {"pictures": [f"https://example.com/{idx}.jpg" for idx in range(13)]}
    )
    assert any(r.is_error() for r in too_many)

    mixed = image_validator.validate(
        {
            "pictures": [
                {"source": "ftp://example.com/a.bmp"},
                {"url": "http://example.com/noext"},
                {},
            ]
        }
    )
    assert len(mixed) >= 3

    from mercadolivre_upload.domain.validation import extended_validators as ev_module

    def _raise(_url: str):
        raise ValueError("bad url")

    monkeypatch.setattr(ev_module, "urlparse", _raise)
    invalid_url_results = image_validator._validate_image_url(
        "http://example.com/a.jpg", "pictures[0]"
    )
    assert any("URL de imagem inválida" in r.message for r in invalid_url_results)

    category_validator = CategoryValidator()
    assert category_validator.validate({"category_id": None})[0].is_error()
    assert category_validator.validate({"category_id": 1})[0].is_error()
    assert category_validator.validate({"category_id": "ABC"})[0].is_error()
    assert category_validator.validate({"category_id": "MLB123"}) == []
    assert category_validator.validate({"category_id": "MLM123"}) == []

    stock_validator = StockValidator()
    assert stock_validator.validate({})[0].is_error()
    assert stock_validator.validate({"available_quantity": "x"})[0].is_error()
    assert any(r.is_error() for r in stock_validator.validate({"available_quantity": -1}))
    assert any(r.is_warning() for r in stock_validator.validate({"available_quantity": 0}))
    assert any(r.is_error() for r in stock_validator.validate({"available_quantity": 10000}))

    suite = ExtendedValidationSuite()
    data = {
        "price": 0.10,
        "title": " promo ",
        "pictures": [],
        "category_id": "BAD",
        "available_quantity": 0,
    }
    assert suite.has_errors(data) is True
    assert suite.get_errors(data)
    assert suite.get_warnings(data)
