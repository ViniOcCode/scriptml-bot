"""Tests for PublishJsonUseCase."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import requests

from mercadolivre_upload.adapters.json_payload_reader import (
    InvalidPayloadError,
    JsonPayloadReader,
    ReadPayloadResult,
)
from mercadolivre_upload.application.publish_json_use_case import (
    PublishJsonUseCase,
)
from mercadolivre_upload.application.validators.seller_policy import (
    BatchConfig,
    CategoriesConfig,
    ListingConfig,
    PricingConfig,
    SellerConfig,
    SellerPolicyValidator,
)


def _make_seller_config(
    allowed_types: list[str] | None = None,
    min_price: float = 5.0,
    max_price: float = 9999.0,
    blocked: list[str] | None = None,
    overrides: dict[str, str] | None = None,
    human_review_required: bool = True,
) -> SellerConfig:
    return SellerConfig(
        listing=ListingConfig(
            allowed_types=allowed_types or ["gold_special", "gold_pro"],
            default_type="gold_special",
        ),
        pricing=PricingConfig(min_price=min_price, max_price=max_price),
        categories=CategoriesConfig(blocked=blocked or [], overrides=overrides or {}),
        batch=BatchConfig(human_review_required=human_review_required),
    )


def _make_read_result(
    *,
    description: str | None = "Descrição do produto",
    sku: str | None = "ABC-001",
    category_id: str = "MLB271599",
    ai_suggested: bool = False,
    listing_type_id: str = "gold_special",
    price: float = 50.0,
) -> ReadPayloadResult:
    payload = {
        "title": "Produto Teste",
        "category_id": category_id,
        "price": price,
        "currency_id": "BRL",
        "available_quantity": 10,
        "buying_mode": "buy_it_now",
        "listing_type_id": listing_type_id,
        "condition": "new",
        "pictures": [{"source": "https://cdn.ml.com/img.jpg"}],
    }
    return ReadPayloadResult(
        payload=payload,
        description=description,
        sku=sku,
        category_id=category_id,
        ai_suggested=ai_suggested,
    )


def _make_read_result_with_variations(
    *,
    variation_prices: list[float],
    listing_type_id: str = "gold_special",
) -> ReadPayloadResult:
    """Build a ReadPayloadResult whose price lives in variations, not at root."""
    payload: dict[str, Any] = {
        "title": "Produto com Variações",
        "category_id": "MLB271599",
        "currency_id": "BRL",
        "buying_mode": "buy_it_now",
        "listing_type_id": listing_type_id,
        "condition": "new",
        "pictures": [{"source": "https://cdn.ml.com/img.jpg"}],
        "variations": [
            {"price": p, "available_quantity": 5, "attribute_combinations": []}
            for p in variation_prices
        ],
    }
    return ReadPayloadResult(
        payload=payload,
        description=None,
        sku="VAR-001",
        category_id="MLB271599",
        ai_suggested=False,
    )


def _make_use_case(
    config: SellerConfig | None = None,
) -> tuple[PublishJsonUseCase, MagicMock, MagicMock]:
    reader = MagicMock(spec=JsonPayloadReader)
    cfg = config or _make_seller_config()
    policy = SellerPolicyValidator(cfg)
    publisher = MagicMock()
    publisher.create_item.return_value = {"id": "MLB987654321"}
    use_case = PublishJsonUseCase(reader=reader, policy=policy, publisher=publisher)
    return use_case, reader, publisher


class TestPublishJsonUseCase:
    def test_publish_sucesso(self, tmp_path: Path) -> None:
        use_case, reader, publisher = _make_use_case()
        reader.read.return_value = _make_read_result()

        result = use_case.execute(tmp_path / "payload.json")

        assert result.status == "published"
        assert result.item_id == "MLB987654321"
        assert result.sku == "ABC-001"
        publisher.create_item.assert_called_once()
        publisher.create_item_description.assert_called_once_with(
            "MLB987654321", "Descrição do produto"
        )

    def test_publish_dry_run(self, tmp_path: Path) -> None:
        use_case, reader, publisher = _make_use_case()
        reader.read.return_value = _make_read_result()

        result = use_case.execute(tmp_path / "payload.json", dry_run=True)

        assert result.status == "skipped"
        assert result.item_id is None
        publisher.create_item.assert_not_called()
        publisher.create_item_description.assert_not_called()

    def test_publish_schema_invalido(self, tmp_path: Path) -> None:
        use_case, reader, publisher = _make_use_case()
        reader.read.side_effect = InvalidPayloadError("campos ausentes: ['title']")

        result = use_case.execute(tmp_path / "payload.json")

        assert result.status == "failed"
        assert result.error is not None
        assert result.sku is None
        publisher.create_item.assert_not_called()

    def test_publish_policy_error(self, tmp_path: Path) -> None:
        use_case, reader, publisher = _make_use_case()
        reader.read.return_value = _make_read_result(listing_type_id="bronze")

        result = use_case.execute(tmp_path / "payload.json")

        assert result.status == "failed"
        assert result.error is not None
        assert "bronze" in result.error or "não é permitido" in result.error
        publisher.create_item.assert_not_called()

    def test_publish_policy_warning(self, tmp_path: Path) -> None:
        config = _make_seller_config(max_price=9999.0)
        use_case, reader, publisher = _make_use_case(config)
        reader.read.return_value = _make_read_result(price=10001.0)

        result = use_case.execute(tmp_path / "payload.json")

        assert result.status == "published"
        assert len(result.warnings) > 0

    def test_publish_override_aplicado(self, tmp_path: Path) -> None:
        config = _make_seller_config(
            allowed_types=["gold_pro"],
            overrides={"MLB271599": "gold_pro"},
        )
        use_case, reader, publisher = _make_use_case(config)
        reader.read.return_value = _make_read_result(listing_type_id="gold_special")

        result = use_case.execute(tmp_path / "payload.json")

        assert result.status == "published"
        call_payload = publisher.create_item.call_args[0][0]
        assert call_payload["listing_type_id"] == "gold_pro"

    def test_publish_description_postada(self, tmp_path: Path) -> None:
        use_case, reader, publisher = _make_use_case()
        reader.read.return_value = _make_read_result(description="Texto especial")

        use_case.execute(tmp_path / "payload.json")

        publisher.create_item_description.assert_called_once_with("MLB987654321", "Texto especial")

    def test_publish_sem_description(self, tmp_path: Path) -> None:
        use_case, reader, publisher = _make_use_case()
        reader.read.return_value = _make_read_result(description=None)

        use_case.execute(tmp_path / "payload.json")

        publisher.create_item_description.assert_not_called()

    def test_publish_api_error_retorna_failed(self, tmp_path: Path) -> None:
        use_case, reader, publisher = _make_use_case()
        reader.read.return_value = _make_read_result()
        publisher.create_item.side_effect = RuntimeError("API offline")

        result = use_case.execute(tmp_path / "payload.json")

        assert result.status == "failed"
        assert "API offline" in (result.error or "")


class TestSellerPolicyVariations:
    """Policy price-range checks must work for variation payloads (no root price)."""

    def test_variacao_preco_valido_nao_bloqueia(self) -> None:
        config = _make_seller_config(min_price=5.0, max_price=9999.0)
        policy = SellerPolicyValidator(config)
        result = _make_read_result_with_variations(variation_prices=[59.90, 79.90])
        violations = policy.validate(result.payload)
        assert not violations.has_errors

    def test_variacao_preco_minimo_abaixo_bloqueia(self) -> None:
        config = _make_seller_config(min_price=5.0, max_price=9999.0)
        policy = SellerPolicyValidator(config)
        result = _make_read_result_with_variations(variation_prices=[2.00, 59.90])
        violations = policy.validate(result.payload)
        assert violations.has_errors
        assert any(v.field == "price" for v in violations.violations)

    def test_variacao_sem_preco_em_nenhum_lugar_bloqueia(self) -> None:
        """Empty variations list → effective price 0.0 → always below min."""
        config = _make_seller_config(min_price=5.0, max_price=9999.0)
        policy = SellerPolicyValidator(config)
        result = _make_read_result_with_variations(variation_prices=[])
        violations = policy.validate(result.payload)
        assert violations.has_errors


class TestPublishJsonApiErrors:
    """PublishJsonUseCase must surface ML API cause codes in PublishJsonResult.error."""

    def test_400_with_ml_causes_formats_error_field(self, tmp_path: Path) -> None:
        """MLApiError causes must be formatted into result.error as [code] message."""
        from mercadolivre_upload.api.exceptions import MLApiError

        ml_cause = {
            "cause_id": 147,
            "type": "error",
            "code": "item.attributes.missing_required",
            "references": ["item.attributes"],
            "message": "The attributes [BRAND] are required for category MLB437616",
        }
        api_error = MLApiError(
            "400 Client Error",
            response_body={"error": "validation_error", "status": 400, "cause": [ml_cause]},
        )

        use_case, reader, publisher = _make_use_case()
        reader.read.return_value = _make_read_result()
        publisher.create_item.side_effect = api_error

        result = use_case.execute(tmp_path / "payload.json")

        assert result.status == "failed"
        assert "item.attributes.missing_required" in (result.error or "")
        assert "BRAND" in (result.error or "")

    def test_400_without_ml_body_falls_back_to_http_error_str(self, tmp_path: Path) -> None:
        """Plain HTTPError (no ML body) must still produce a failed result with error string."""
        plain_error = requests.HTTPError(
            "400 Client Error: Bad Request for url: https://api.mercadolibre.com/items"
        )

        use_case, reader, publisher = _make_use_case()
        reader.read.return_value = _make_read_result()
        publisher.create_item.side_effect = plain_error

        result = use_case.execute(tmp_path / "payload.json")

        assert result.status == "failed"
        assert "400" in (result.error or "")
