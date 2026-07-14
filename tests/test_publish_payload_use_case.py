"""Tests for PublishPayloadUseCase."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, Mock

import pytest
import requests

from mercadolivre_upload.adapters.json_payload_reader import (
    InvalidPayloadError,
    JsonPayloadReader,
    ReadPayloadResult,
)
from mercadolivre_upload.api.client import MLApiClient
from mercadolivre_upload.api.exceptions import MLApiError
from mercadolivre_upload.application.publish_payload_use_case import (
    PublishPayloadUseCase,
)
from mercadolivre_upload.application.validators.seller_policy import (
    BatchConfig,
    CategoriesConfig,
    ListingConfig,
    PricingConfig,
    SellerConfig,
    SellerPolicyValidator,
)
from mercadolivre_upload.contracts.publication import PublicationOutcome


def _grouped_up_response(**fields: Any) -> dict[str, Any]:
    return {"family_id": "FAM-1", **fields}


def _make_seller_config(
    allowed_types: list[str] | None = None,
    min_price: float = 5.0,
    max_price: float = 9999.0,
    blocked: list[str] | None = None,
    overrides: dict[str, str] | None = None,
    human_review_required: bool = True,
    min_ai_confidence: float = 0.0,
) -> SellerConfig:
    return SellerConfig(
        listing=ListingConfig(
            allowed_types=allowed_types or ["gold_special", "gold_pro"],
            default_type="gold_special",
        ),
        pricing=PricingConfig(min_price=min_price, max_price=max_price),
        categories=CategoriesConfig(blocked=blocked or [], overrides=overrides or {}),
        batch=BatchConfig(
            human_review_required=human_review_required,
            min_ai_confidence=min_ai_confidence,
        ),
    )


def _make_read_result(
    *,
    description: str | None = "Descrição do produto",
    description_by_sku: dict[str, str] | None = None,
    sku: str | None = "ABC-001",
    category_id: str = "MLB271599",
    ai_suggested: bool = False,
    listing_type_id: str = "gold_special",
    price: float = 50.0,
    fiscal_items: list[dict[str, Any]] | None = None,
    publish_item_skus: list[str] | None = None,
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
        description_by_sku=description_by_sku or {},
        sku=sku,
        category_id=category_id,
        ai_suggested=ai_suggested,
        publication_ready=True,
        fiscal_items=fiscal_items or [],
        publish_item_skus=publish_item_skus or [],
    )


def _make_user_products_read_result(
    *,
    description: str | None = "Descrição do produto",
    description_by_sku: dict[str, str] | None = None,
    sku: str | None = "ABC-001",
    family_name: str = "Linha Alpha",
    items: list[dict[str, Any]] | None = None,
    ai_suggested: bool = False,
    fiscal_items: list[dict[str, Any]] | None = None,
    publish_item_skus: list[str] | None = None,
) -> ReadPayloadResult:
    payload_items = items or [
        {
            "category_id": "MLB271599",
            "price": 50.0,
            "currency_id": "BRL",
            "available_quantity": 10,
            "buying_mode": "buy_it_now",
            "listing_type_id": "gold_special",
            "condition": "new",
            "pictures": [{"source": "https://cdn.ml.com/img.jpg"}],
            "attributes": [{"id": "BRAND", "value_name": "Marca"}],
        }
    ]
    return ReadPayloadResult(
        payload={
            "family_name": family_name,
            "items": payload_items,
        },
        description=description,
        description_by_sku=description_by_sku or {},
        sku=sku,
        category_id="MLB271599",
        ai_suggested=ai_suggested,
        upload_mode="user_products",
        publication_ready=True,
        fiscal_items=fiscal_items or [],
        publish_item_skus=publish_item_skus or [],
    )


def _make_user_products_payload_array_read_result(
    *,
    description: str | None = "Descrição do produto",
    description_by_sku: dict[str, str] | None = None,
    sku: str | None = "ABC-001",
    entries: list[dict[str, Any]] | None = None,
    ai_suggested: bool = False,
) -> ReadPayloadResult:
    payload_entries = entries or [
        {
            "family_name": "Linha Alpha",
            "category_id": "MLB271599",
            "price": 50.0,
            "currency_id": "BRL",
            "available_quantity": 10,
            "buying_mode": "buy_it_now",
            "listing_type_id": "gold_special",
            "condition": "new",
            "pictures": [{"source": "https://cdn.ml.com/img.jpg"}],
            "attributes": [{"id": "BRAND", "value_name": "Marca"}],
        }
    ]
    return ReadPayloadResult(
        payload={"payload": payload_entries},
        description=description,
        description_by_sku=description_by_sku or {},
        sku=sku,
        category_id="MLB271599",
        ai_suggested=ai_suggested,
        upload_mode="user_products",
        publication_ready=True,
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
        publication_ready=True,
    )


def _make_use_case(
    config: SellerConfig | None = None,
    fiscal_service: Any | None = None,
    publish_inactive: bool = False,
) -> tuple[PublishPayloadUseCase, MagicMock, MagicMock]:
    reader = MagicMock(spec=JsonPayloadReader)
    cfg = config or _make_seller_config()
    policy = SellerPolicyValidator(cfg)
    publisher = MagicMock()
    publisher.validate_item.return_value = {}
    publisher.validate_user_product_item.return_value = {}
    publisher.create_item.return_value = {"id": "MLB987654321"}
    publisher.create_user_product_item.return_value = {
        "id": "MLB987654321",
        "user_product_id": "MLBU123456",
    }
    publisher.get_user_product.side_effect = lambda user_product_id: {
        "id": user_product_id,
        "family_id": "FAM-1",
    }
    use_case = PublishPayloadUseCase(
        reader=reader,
        policy=policy,
        publisher=publisher,
        fiscal_service=fiscal_service,
        publish_inactive=publish_inactive,
    )
    return use_case, reader, publisher


class TestPublishPayloadUseCase:
    def test_publish_sucesso(self, tmp_path: Path) -> None:
        use_case, reader, publisher = _make_use_case()
        reader.read.return_value = _make_read_result()

        result = use_case.execute(tmp_path / "payload.json")

        assert isinstance(result, PublicationOutcome)
        assert result.status == "published"
        assert result.side_effect_state == "confirmed"
        assert result.reconciliation_required is False
        assert result.item_id == "MLB987654321"
        assert result.sku == "ABC-001"
        publisher.create_item.assert_called_once()
        publisher.create_item_description.assert_called_once_with(
            "MLB987654321", "Descrição do produto"
        )

    def test_pause_failure_is_not_reported_as_success(self, tmp_path: Path) -> None:
        use_case, reader, publisher = _make_use_case(publish_inactive=True)
        reader.read.return_value = _make_read_result()
        publisher.update_item.side_effect = RuntimeError("pause rejected")

        result = use_case.execute(tmp_path / "payload.json")

        assert result.status == "failed"
        assert result.side_effect_state == "partial"
        assert result.reconciliation_required is True
        assert result.item_ids == ["MLB987654321"]
        assert any(phase.name == "pause" and phase.status == "failed" for phase in result.phases)

    def test_pause_http_503_is_unknown_and_not_retried(self, tmp_path: Path) -> None:
        use_case, reader, publisher = _make_use_case(publish_inactive=True)
        reader.read.return_value = _make_read_result()
        publisher.update_item.side_effect = requests.HTTPError(
            "503 Service Unavailable",
            response=Mock(status_code=503),
        )

        result = use_case.execute(tmp_path / "payload.json")

        assert result.status == "unknown"
        assert result.side_effect_state == "partial"
        assert result.reconciliation_required is True
        assert publisher.update_item.call_count == 1

    def test_description_timeout_is_unknown_and_is_not_retried(
        self,
        tmp_path: Path,
    ) -> None:
        use_case, reader, publisher = _make_use_case()
        reader.read.return_value = _make_read_result()
        publisher.create_item_description.side_effect = requests.Timeout("timed out")

        result = use_case.execute(tmp_path / "payload.json")

        assert result.status == "unknown"
        assert result.side_effect_state == "partial"
        assert result.reconciliation_required is True
        assert publisher.create_item_description.call_count == 1
        assert any(
            phase.name == "description" and phase.status == "unknown" for phase in result.phases
        )

    def test_description_connection_error_is_unknown_and_not_retried(
        self,
        tmp_path: Path,
    ) -> None:
        use_case, reader, publisher = _make_use_case()
        reader.read.return_value = _make_read_result()
        publisher.create_item_description.side_effect = requests.ConnectionError(
            "connection dropped after send"
        )

        result = use_case.execute(tmp_path / "payload.json")

        assert result.status == "unknown"
        assert result.side_effect_state == "partial"
        assert result.reconciliation_required is True
        assert publisher.create_item_description.call_count == 1

    def test_item_creation_timeout_requires_reconciliation(self, tmp_path: Path) -> None:
        use_case, reader, publisher = _make_use_case()
        reader.read.return_value = _make_read_result(description=None)
        publisher.create_item.side_effect = requests.Timeout("timed out")

        result = use_case.execute(tmp_path / "payload.json")

        assert result.status == "unknown"
        assert result.side_effect_state == "unknown"
        assert result.reconciliation_required is True
        assert result.item_ids == []
        assert publisher.create_item.call_count == 1
        assert any(
            phase.name == "item_creation" and phase.status == "unknown" for phase in result.phases
        )

    @pytest.mark.parametrize(
        "transport_error",
        [
            requests.ConnectionError("connection dropped after send"),
            requests.HTTPError(
                "503 Service Unavailable",
                response=Mock(status_code=503),
            ),
        ],
    )
    def test_item_creation_ambiguous_transport_failure_requires_reconciliation(
        self,
        tmp_path: Path,
        transport_error: requests.RequestException,
    ) -> None:
        use_case, reader, publisher = _make_use_case()
        reader.read.return_value = _make_read_result(description=None)
        publisher.create_item.side_effect = transport_error

        result = use_case.execute(tmp_path / "payload.json")

        assert result.status == "unknown"
        assert result.side_effect_state == "unknown"
        assert result.reconciliation_required is True
        assert publisher.create_item.call_count == 1

    def test_item_creation_http_422_is_a_definitive_failure(self, tmp_path: Path) -> None:
        use_case, reader, publisher = _make_use_case()
        reader.read.return_value = _make_read_result(description=None)
        publisher.create_item.side_effect = requests.HTTPError(
            "422 Unprocessable Entity",
            response=Mock(status_code=422),
        )

        result = use_case.execute(tmp_path / "payload.json")

        assert result.status == "failed"
        assert result.side_effect_state == "none"
        assert result.reconciliation_required is False
        assert publisher.create_item.call_count == 1

    @pytest.mark.parametrize("status_code", [200, 201])
    def test_item_creation_non_json_success_requires_reconciliation(
        self,
        tmp_path: Path,
        status_code: int,
    ) -> None:
        use_case, reader, publisher = _make_use_case()
        reader.read.return_value = _make_read_result(description=None)
        publisher.create_item.side_effect = MLApiError(
            "POST /items returned non-JSON success response",
            response=Mock(status_code=status_code),
        )

        result = use_case.execute(tmp_path / "payload.json")

        assert result.status == "unknown"
        assert result.side_effect_state == "unknown"
        assert result.reconciliation_required is True
        assert publisher.create_item.call_count == 1

    def test_publish_fails_when_api_validation_returns_error(self, tmp_path: Path) -> None:
        use_case, reader, publisher = _make_use_case()
        reader.read.return_value = _make_read_result()
        publisher.validate_item.return_value = {
            "cause": [{"type": "error", "code": "item.title.required", "message": "titulo"}]
        }

        result = use_case.execute(tmp_path / "payload.json")

        assert result.status == "failed"
        assert result.error is not None
        assert "item.title.required" in result.error
        publisher.create_item.assert_not_called()

    def test_publish_continues_when_validation_has_only_warning_causes(
        self, tmp_path: Path
    ) -> None:
        use_case, reader, publisher = _make_use_case()
        reader.read.return_value = _make_read_result()
        publisher.validate_item.return_value = {
            "error": "validation_error",
            "status": 400,
            "cause": [
                {
                    "code": "shipping.lost_me1_by_user",
                    "type": "warning",
                    "department": "shipping",
                    "message": "User has not mode me1",
                    "references": ["item.shipping.mode"],
                }
            ],
        }

        result = use_case.execute(tmp_path / "payload.json")

        assert result.status == "published"
        assert result.item_id == "MLB987654321"
        assert result.validation_status == "validation_passed_with_warnings"
        assert result.validation_report is not None
        assert result.validation_report["warnings"][0]["code"] == "shipping.lost_me1_by_user"
        assert any("shipping.lost_me1_by_user" in warning for warning in result.warnings)
        publisher.create_item.assert_called_once()

    def test_publish_continues_when_validation_has_mandatory_free_shipping_warning(
        self, tmp_path: Path
    ) -> None:
        use_case, reader, publisher = _make_use_case()
        reader.read.return_value = _make_read_result()
        publisher.validate_item.return_value = {
            "error": "validation_error",
            "status": 400,
            "cause": [
                {
                    "code": "item.shipping.mandatory_free_shipping",
                    "type": "warning",
                    "department": "shipping",
                    "message": "Mandatory free shipping added",
                    "references": ["item.shipping.free_shipping"],
                }
            ],
        }

        result = use_case.execute(tmp_path / "payload.json")

        assert result.status == "published"
        assert result.item_id == "MLB987654321"
        assert result.validation_status == "validation_passed_with_warnings"
        assert any(
            "item.shipping.mandatory_free_shipping" in warning for warning in result.warnings
        )
        publisher.create_item.assert_called_once()

    def test_publish_blocks_when_validation_has_warning_and_error(self, tmp_path: Path) -> None:
        use_case, reader, publisher = _make_use_case()
        reader.read.return_value = _make_read_result()
        publisher.validate_item.return_value = {
            "error": "validation_error",
            "status": 400,
            "cause": [
                {"code": "shipping.lost_me1_by_user", "type": "warning", "message": "warn"},
                {"code": "item.title.required", "type": "error", "message": "titulo"},
            ],
        }

        result = use_case.execute(tmp_path / "payload.json")

        assert result.status == "failed"
        assert result.validation_status == "validation_failed"
        assert result.validation_report is not None
        assert result.validation_report["warnings"][0]["code"] == "shipping.lost_me1_by_user"
        assert result.validation_report["errors"][0]["code"] == "item.title.required"
        assert "item.title.required" in (result.error or "")
        assert any("shipping.lost_me1_by_user" in warning for warning in result.warnings)
        publisher.create_item.assert_not_called()

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

    def test_publish_submete_fiscal_quando_presente(self, tmp_path: Path) -> None:
        fiscal_service = MagicMock()
        fiscal_service.submit_fiscal_data_workflow.return_value = SimpleNamespace(
            success=True,
            error_message=None,
        )
        use_case, reader, _publisher = _make_use_case(fiscal_service=fiscal_service)
        reader.read.return_value = _make_read_result(
            fiscal_items=[
                {
                    "sku": "ABC-001",
                    "type": "single",
                    "measurement_unit": "UN",
                    "cost": 50.0,
                    "tax_information": {
                        "ncm": "9018.39.29",
                        "origin_type": "reseller",
                        "origin_detail": "0",
                        "csosn": "102",
                    },
                }
            ]
        )

        result = use_case.execute(tmp_path / "payload.json")

        assert result.status == "published"
        fiscal_service.submit_fiscal_data_workflow.assert_called_once()
        call_args = fiscal_service.submit_fiscal_data_workflow.call_args[0]
        assert call_args[0] == "MLB987654321"
        fiscal_data = call_args[1]
        assert fiscal_data.sku == "ABC-001"
        assert fiscal_data.ncm == "90183929"
        assert fiscal_data.origin_type == "reseller"
        assert result.fiscal_status == "submitted"
        assert result.fiscal_report[0]["item_id"] == "MLB987654321"
        assert result.fiscal_report[0]["raw_origin_type"] == "reseller"
        assert result.fiscal_report[0]["normalized_origin_type"] == "reseller"
        assert result.fiscal_report[0]["raw_origin_detail"] == "0"
        assert result.fiscal_report[0]["normalized_origin_detail"] == "0"

    def test_publish_fiscal_com_falha_bloqueia_resultado(self, tmp_path: Path) -> None:
        fiscal_service = MagicMock()
        fiscal_service.submit_fiscal_data_workflow.return_value = SimpleNamespace(
            success=False,
            error_message="sku não encontrado",
            response={"error_code": "10086"},
            status=SimpleNamespace(value="failed"),
        )
        use_case, reader, _publisher = _make_use_case(fiscal_service=fiscal_service)
        reader.read.return_value = _make_read_result(
            fiscal_items=[
                {
                    "sku": "ABC-001",
                    "type": "single",
                    "measurement_unit": "UN",
                    "cost": 50.0,
                    "tax_information": {
                        "ncm": "9018.39.29",
                        "origin_type": "reseller",
                        "origin_detail": "0",
                    },
                }
            ]
        )

        result = use_case.execute(tmp_path / "payload.json")

        assert result.status == "failed"
        assert "fiscal[1]" in (result.error or "")
        assert "sku não encontrado" in (result.error or "")
        assert result.item_id == "MLB987654321"
        assert result.fiscal_status == "failed"
        assert result.fiscal_report[0]["published_item_exists"] is True
        assert result.fiscal_report[0]["api_response"] == {"error_code": "10086"}
        assert result.fiscal_report[0]["final_fiscal_status"] == "failed"

    def test_publish_fiscal_up_mapeia_por_sku_independente_da_ordem(self, tmp_path: Path) -> None:
        fiscal_service = MagicMock()
        fiscal_service.submit_fiscal_data_workflow.return_value = SimpleNamespace(
            success=True,
            error_message=None,
        )
        use_case, reader, publisher = _make_use_case(fiscal_service=fiscal_service)
        reader.read.return_value = _make_user_products_read_result(
            items=[
                {
                    "category_id": "MLB271599",
                    "price": 50.0,
                    "currency_id": "BRL",
                    "available_quantity": 10,
                    "buying_mode": "buy_it_now",
                    "listing_type_id": "gold_special",
                    "condition": "new",
                    "pictures": [{"source": "https://cdn.ml.com/img-1.jpg"}],
                    "attributes": [{"id": "SELLER_SKU", "value_name": "SKU-A"}],
                },
                {
                    "category_id": "MLB271599",
                    "price": 60.0,
                    "currency_id": "BRL",
                    "available_quantity": 5,
                    "buying_mode": "buy_it_now",
                    "listing_type_id": "gold_special",
                    "condition": "new",
                    "pictures": [{"source": "https://cdn.ml.com/img-2.jpg"}],
                    "attributes": [{"id": "SELLER_SKU", "value_name": "SKU-B"}],
                },
            ],
            fiscal_items=[
                {
                    "sku": "SKU-B",
                    "type": "single",
                    "measurement_unit": "UN",
                    "cost": 60.0,
                    "tax_information": {
                        "ncm": "9018.39.29",
                        "origin_type": "reseller",
                        "origin_detail": "0",
                    },
                },
                {
                    "sku": "SKU-A",
                    "type": "single",
                    "measurement_unit": "UN",
                    "cost": 50.0,
                    "tax_information": {
                        "ncm": "9018.39.29",
                        "origin_type": "reseller",
                        "origin_detail": "0",
                    },
                },
            ],
        )
        publisher.create_user_product_item.side_effect = [
            _grouped_up_response(id="MLB1", user_product_id="MLBU123"),
            _grouped_up_response(id="MLB2", user_product_id="MLBU123"),
        ]

        result = use_case.execute(tmp_path / "payload.json")

        assert result.status == "published"
        assert fiscal_service.submit_fiscal_data_workflow.call_count == 2
        first_call = fiscal_service.submit_fiscal_data_workflow.call_args_list[0].args
        second_call = fiscal_service.submit_fiscal_data_workflow.call_args_list[1].args
        assert first_call[0] == "MLB2"
        assert first_call[1].sku == "SKU-B"
        assert second_call[0] == "MLB1"
        assert second_call[1].sku == "SKU-A"

    def test_publish_fiscal_up_mapeia_por_traceability_publish_item_skus(
        self, tmp_path: Path
    ) -> None:
        fiscal_service = MagicMock()
        fiscal_service.submit_fiscal_data_workflow.return_value = SimpleNamespace(
            success=True,
            error_message=None,
        )
        use_case, reader, publisher = _make_use_case(fiscal_service=fiscal_service)
        reader.read.return_value = _make_user_products_read_result(
            items=[
                {
                    "category_id": "MLB271599",
                    "price": 50.0,
                    "currency_id": "BRL",
                    "available_quantity": 10,
                    "buying_mode": "buy_it_now",
                    "listing_type_id": "gold_special",
                    "condition": "new",
                    "pictures": [{"source": "https://cdn.ml.com/img-1.jpg"}],
                    "attributes": [{"id": "BRAND", "value_name": "Marca"}],
                },
                {
                    "category_id": "MLB271599",
                    "price": 60.0,
                    "currency_id": "BRL",
                    "available_quantity": 5,
                    "buying_mode": "buy_it_now",
                    "listing_type_id": "gold_special",
                    "condition": "new",
                    "pictures": [{"source": "https://cdn.ml.com/img-2.jpg"}],
                    "attributes": [{"id": "BRAND", "value_name": "Marca"}],
                },
            ],
            fiscal_items=[
                {
                    "sku": "SKU-B",
                    "type": "single",
                    "measurement_unit": "UN",
                    "cost": 60.0,
                    "tax_information": {
                        "ncm": "9018.39.29",
                        "origin_type": "reseller",
                        "origin_detail": "0",
                    },
                },
                {
                    "sku": "SKU-A",
                    "type": "single",
                    "measurement_unit": "UN",
                    "cost": 50.0,
                    "tax_information": {
                        "ncm": "9018.39.29",
                        "origin_type": "reseller",
                        "origin_detail": "0",
                    },
                },
            ],
            publish_item_skus=["SKU-A", "SKU-B"],
        )
        publisher.create_user_product_item.side_effect = [
            _grouped_up_response(id="MLB1", user_product_id="MLBU123"),
            _grouped_up_response(id="MLB2", user_product_id="MLBU123"),
        ]

        result = use_case.execute(tmp_path / "payload.json")

        assert result.status == "published"
        assert fiscal_service.submit_fiscal_data_workflow.call_count == 2
        first_call = fiscal_service.submit_fiscal_data_workflow.call_args_list[0].args
        second_call = fiscal_service.submit_fiscal_data_workflow.call_args_list[1].args
        assert first_call[0] == "MLB2"
        assert first_call[1].sku == "SKU-B"
        assert second_call[0] == "MLB1"
        assert second_call[1].sku == "SKU-A"

    def test_publish_fiscal_legacy_variations_envia_todos_os_skus(self, tmp_path: Path) -> None:
        fiscal_service = MagicMock()
        fiscal_service.submit_fiscal_data_workflow.return_value = SimpleNamespace(
            success=True,
            error_message=None,
        )
        use_case, reader, _publisher = _make_use_case(fiscal_service=fiscal_service)
        read_result = _make_read_result(
            sku="SKU-FAMILIA",
            fiscal_items=[
                {
                    "sku": "SKU-VAR-A",
                    "type": "single",
                    "measurement_unit": "UN",
                    "cost": 50.0,
                    "tax_information": {
                        "ncm": "9018.39.29",
                        "origin_type": "reseller",
                        "origin_detail": "0",
                    },
                },
                {
                    "sku": "SKU-VAR-B",
                    "type": "single",
                    "measurement_unit": "UN",
                    "cost": 60.0,
                    "tax_information": {
                        "ncm": "9018.39.29",
                        "origin_type": "reseller",
                        "origin_detail": "0",
                    },
                },
            ],
        )
        read_result.payload["variations"] = [
            {"price": 50.0, "available_quantity": 5, "attribute_combinations": []},
            {"price": 60.0, "available_quantity": 5, "attribute_combinations": []},
        ]
        reader.read.return_value = read_result

        result = use_case.execute(tmp_path / "payload.json")

        assert result.status == "published"
        assert fiscal_service.submit_fiscal_data_workflow.call_count == 2
        calls = fiscal_service.submit_fiscal_data_workflow.call_args_list
        assert calls[0].args[0] == "MLB987654321"
        assert calls[1].args[0] == "MLB987654321"
        submitted_skus = {calls[0].args[1].sku, calls[1].args[1].sku}
        assert submitted_skus == {"SKU-VAR-A", "SKU-VAR-B"}

    def test_publish_fiscal_legacy_variation_repasse_variation_id_quando_disponivel(
        self, tmp_path: Path
    ) -> None:
        fiscal_service = MagicMock()
        fiscal_service.submit_fiscal_data_workflow.return_value = SimpleNamespace(
            success=True,
            error_message=None,
        )
        use_case, reader, publisher = _make_use_case(fiscal_service=fiscal_service)
        read_result = _make_read_result(
            sku="SKU-BASE",
            fiscal_items=[
                {
                    "sku": "SKU-VAR-A",
                    "type": "single",
                    "measurement_unit": "UN",
                    "cost": 50.0,
                    "tax_information": {
                        "ncm": "9018.39.29",
                        "origin_type": "reseller",
                        "origin_detail": "0",
                    },
                }
            ],
        )
        read_result.payload["variations"] = [
            {"price": 50.0, "available_quantity": 5, "attribute_combinations": []}
        ]
        reader.read.return_value = read_result
        publisher.create_item.return_value = {
            "id": "MLB987654321",
            "variations": [
                {
                    "id": 111,
                    "attributes": [{"id": "SELLER_SKU", "value_name": "SKU-VAR-A"}],
                }
            ],
        }

        result = use_case.execute(tmp_path / "payload.json")

        assert result.status == "published"
        fiscal_service.submit_fiscal_data_workflow.assert_called_once()
        call = fiscal_service.submit_fiscal_data_workflow.call_args
        assert call.args[0] == "MLB987654321"
        assert call.args[1].sku == "SKU-VAR-A"
        assert call.kwargs["variation_id"] == "111"

    def test_publish_fiscal_sem_service_falha_quando_payload_exige(self, tmp_path: Path) -> None:
        use_case, reader, _publisher = _make_use_case(fiscal_service=None)
        reader.read.return_value = _make_read_result(
            fiscal_items=[
                {
                    "sku": "ABC-001",
                    "type": "single",
                    "measurement_unit": "UN",
                    "cost": 50.0,
                    "tax_information": {
                        "ncm": "9018.39.29",
                        "origin_type": "reseller",
                        "origin_detail": "0",
                    },
                }
            ]
        )

        result = use_case.execute(tmp_path / "payload.json")

        assert result.status == "failed"
        assert "fiscal:" in (result.error or "").lower()
        assert "fiscalservice" in (result.error or "").lower()

    def test_publish_fiscal_up_sku_nao_mapeado_falha(self, tmp_path: Path) -> None:
        fiscal_service = MagicMock()
        fiscal_service.submit_fiscal_data_workflow.return_value = SimpleNamespace(
            success=True,
            error_message=None,
        )
        use_case, reader, publisher = _make_use_case(fiscal_service=fiscal_service)
        reader.read.return_value = _make_user_products_read_result(
            items=[
                {
                    "category_id": "MLB271599",
                    "price": 50.0,
                    "currency_id": "BRL",
                    "available_quantity": 10,
                    "buying_mode": "buy_it_now",
                    "listing_type_id": "gold_special",
                    "condition": "new",
                    "pictures": [{"source": "https://cdn.ml.com/img-1.jpg"}],
                    "attributes": [{"id": "SELLER_SKU", "value_name": "SKU-A"}],
                },
                {
                    "category_id": "MLB271599",
                    "price": 60.0,
                    "currency_id": "BRL",
                    "available_quantity": 5,
                    "buying_mode": "buy_it_now",
                    "listing_type_id": "gold_special",
                    "condition": "new",
                    "pictures": [{"source": "https://cdn.ml.com/img-2.jpg"}],
                    "attributes": [{"id": "SELLER_SKU", "value_name": "SKU-B"}],
                },
            ],
            fiscal_items=[
                {
                    "sku": "SKU-A",
                    "type": "single",
                    "measurement_unit": "UN",
                    "cost": 50.0,
                    "tax_information": {
                        "ncm": "9018.39.29",
                        "origin_type": "reseller",
                        "origin_detail": "0",
                    },
                },
                {
                    "sku": "SKU-C",
                    "type": "single",
                    "measurement_unit": "UN",
                    "cost": 70.0,
                    "tax_information": {
                        "ncm": "9018.39.29",
                        "origin_type": "reseller",
                        "origin_detail": "0",
                    },
                },
            ],
        )
        publisher.create_user_product_item.side_effect = [
            _grouped_up_response(id="MLB1", user_product_id="MLBU123"),
            _grouped_up_response(id="MLB2", user_product_id="MLBU123"),
        ]

        result = use_case.execute(tmp_path / "payload.json")

        assert result.status == "failed"
        assert "sku 'SKU-C'" in (result.error or "")

    def test_publish_api_error_retorna_failed(self, tmp_path: Path) -> None:
        use_case, reader, publisher = _make_use_case()
        reader.read.return_value = _make_read_result()
        publisher.create_item.side_effect = RuntimeError("API offline")

        result = use_case.execute(tmp_path / "payload.json")

        assert result.status == "failed"
        assert "API offline" in (result.error or "")

    def test_publish_user_products_multiple_items(self, tmp_path: Path) -> None:
        use_case, reader, publisher = _make_use_case()
        reader.read.return_value = _make_user_products_read_result(
            items=[
                {
                    "category_id": "MLB271599",
                    "price": 50.0,
                    "currency_id": "BRL",
                    "available_quantity": 10,
                    "buying_mode": "buy_it_now",
                    "listing_type_id": "gold_special",
                    "condition": "new",
                    "pictures": [{"source": "https://cdn.ml.com/img-1.jpg"}],
                    "attributes": [{"id": "BRAND", "value_name": "Marca"}],
                },
                {
                    "category_id": "MLB271599",
                    "price": 60.0,
                    "currency_id": "BRL",
                    "available_quantity": 5,
                    "buying_mode": "buy_it_now",
                    "listing_type_id": "gold_special",
                    "condition": "new",
                    "pictures": [{"source": "https://cdn.ml.com/img-2.jpg"}],
                    "attributes": [{"id": "BRAND", "value_name": "Marca"}],
                },
            ]
        )
        publisher.create_user_product_item.side_effect = [
            {"id": "MLB1", "user_product_id": "MLBU123", "family_id": "FAM-1"},
            {"id": "MLB2", "user_product_id": "MLBU456", "family_id": "FAM-1"},
        ]

        result = use_case.execute(tmp_path / "payload.json")

        assert result.status == "published"
        assert result.item_id == "MLB1"
        assert result.item_ids == ["MLB1", "MLB2"]
        assert result.user_product_id == "MLBU123"
        publisher.create_item.assert_not_called()
        assert publisher.create_user_product_item.call_count == 2
        first_payload = publisher.create_user_product_item.call_args_list[0].args[0]
        second_payload = publisher.create_user_product_item.call_args_list[1].args[0]
        assert first_payload["family_name"] == "Linha Alpha"
        assert "user_product_id" not in first_payload
        assert second_payload["family_name"] == "Linha Alpha"
        assert "user_product_id" not in second_payload
        assert result.publish_endpoints == ["/items", "/items"]
        assert [call.args for call in publisher.create_item_description.call_args_list] == [
            ("MLB1", "Descrição do produto"),
            ("MLB2", "Descrição do produto"),
        ]

    def test_publish_user_products_api_error_reports_sanitized_shipping_path(
        self, tmp_path: Path
    ) -> None:
        use_case, reader, publisher = _make_use_case()
        reader.read.return_value = _make_user_products_read_result(
            items=[
                {
                    "category_id": "MLB271599",
                    "price": 50.0,
                    "currency_id": "BRL",
                    "available_quantity": 10,
                    "buying_mode": "buy_it_now",
                    "listing_type_id": "gold_special",
                    "condition": "new",
                    "shipping": {"mode": "me2", "free_shipping": True, "local_pick_up": False},
                }
            ]
        )
        publisher.last_user_product_sanitization = {
            "endpoint": "/user-products/{user_product_id}/items",
            "removed_fields": ["shipping.local_pick_up"],
        }
        publisher.create_user_product_item.side_effect = MLApiError(
            "bad request",
            response_body={
                "status": 400,
                "message": "Validation error",
                "cause": [
                    {
                        "type": "error",
                        "code": "item.shipping.invalid_field",
                        "references": ["item.shipping.local_pick_up"],
                        "message": "Request body contains invalid fields [local_pick_up]",
                    }
                ],
            },
        )

        result = use_case.execute(tmp_path / "payload.json")

        assert result.status == "failed"
        assert "item.shipping.invalid_field" in (result.error or "")
        assert "references=item.shipping.local_pick_up" in (result.error or "")
        assert (
            'sanitized={"endpoint": "/user-products/{user_product_id}/items", '
            '"removed_fields": ["shipping.local_pick_up"]}' in (result.error or "")
        )

    def test_publish_user_products_payload_array_sends_separate_requests(
        self, tmp_path: Path
    ) -> None:
        use_case, reader, publisher = _make_use_case()
        entries = [
            {
                "family_name": "Linha Alpha",
                "category_id": "MLB271599",
                "price": 50.0,
                "currency_id": "BRL",
                "available_quantity": 10,
                "buying_mode": "buy_it_now",
                "listing_type_id": "gold_special",
                "condition": "new",
                "pictures": [{"source": "https://cdn.ml.com/img-1.jpg"}],
                "attributes": [{"id": "SELLER_SKU", "value_name": "SKU-A"}],
                "shipping": {"mode": "me2", "free_shipping": True, "local_pick_up": True},
                "sale_terms": [{"id": "WARRANTY_TYPE", "value_name": "Garantia do vendedor"}],
            },
            {
                "family_name": "Linha Alpha",
                "category_id": "MLB271599",
                "price": 60.0,
                "currency_id": "BRL",
                "available_quantity": 5,
                "buying_mode": "buy_it_now",
                "listing_type_id": "gold_special",
                "condition": "new",
                "pictures": [{"source": "https://cdn.ml.com/img-2.jpg"}],
                "attributes": [{"id": "SELLER_SKU", "value_name": "SKU-B"}],
                "shipping": {"mode": "me2", "free_shipping": False, "local_pick_up": True},
                "sale_terms": [{"id": "WARRANTY_TYPE", "value_name": "Garantia do vendedor"}],
            },
        ]
        reader.read.return_value = _make_user_products_payload_array_read_result(
            description="Descrição compartilhada",
            description_by_sku={
                "SKU-A": "Descrição SKU A",
                "SKU-B": "Descrição SKU B",
            },
            entries=entries,
        )
        publisher.create_user_product_item.side_effect = [
            _grouped_up_response(id="MLB1", user_product_id="MLBU123"),
            _grouped_up_response(id="MLB2", user_product_id="MLBU123"),
        ]

        result = use_case.execute(tmp_path / "payload.json")

        assert result.status == "published"
        assert publisher.validate_user_product_item.call_count == 2
        assert publisher.create_user_product_item.call_count == 2
        first_validation_payload = publisher.validate_user_product_item.call_args_list[0].args[0]
        second_validation_payload = publisher.validate_user_product_item.call_args_list[1].args[0]
        first_payload = publisher.create_user_product_item.call_args_list[0].args[0]
        second_payload = publisher.create_user_product_item.call_args_list[1].args[0]
        assert first_validation_payload == first_payload
        assert second_validation_payload == second_payload
        assert "items" not in first_payload
        assert "payload" not in first_payload
        assert "description_by_sku" not in first_payload
        assert "description_by_sku" not in second_payload
        assert first_payload["family_name"] == "Linha Alpha"
        assert second_payload["family_name"] == "Linha Alpha"
        assert "user_product_id" not in second_payload
        for source, created in zip(entries, [first_payload, second_payload], strict=True):
            assert created["pictures"] == source["pictures"]
            assert created["attributes"] == source["attributes"]
            assert created["available_quantity"] == source["available_quantity"]
            assert created["shipping"] == source["shipping"]
            assert created["sale_terms"] == source["sale_terms"]
            assert created["listing_type_id"] == source["listing_type_id"]
            assert created["shipping"]["local_pick_up"] is True
        assert result.publish_endpoints == ["/items", "/items"]
        assert [call.args for call in publisher.create_item_description.call_args_list] == [
            ("MLB1", "Descrição SKU A"),
            ("MLB2", "Descrição SKU B"),
        ]

    def test_publish_user_products_payload_array_uses_items_endpoint_with_api_client(
        self, tmp_path: Path
    ) -> None:
        reader = MagicMock(spec=JsonPayloadReader)
        policy = SellerPolicyValidator(_make_seller_config())
        publisher = MLApiClient(http_client=MagicMock())
        publisher.post = MagicMock(
            side_effect=[
                {},
                {},
                {"id": "MLB1", "user_product_id": "MLBU123", "family_id": "FAM-1"},
                {"id": "MLB2", "user_product_id": "MLBU123", "family_id": "FAM-1"},
            ]
        )
        use_case = PublishPayloadUseCase(reader=reader, policy=policy, publisher=publisher)
        reader.read.return_value = _make_user_products_payload_array_read_result(
            description=None,
            entries=[
                {
                    "family_name": "Linha Alpha",
                    "category_id": "MLB271599",
                    "price": 50.0,
                    "currency_id": "BRL",
                    "available_quantity": 10,
                    "buying_mode": "buy_it_now",
                    "listing_type_id": "gold_special",
                    "condition": "new",
                    "pictures": [{"source": "https://cdn.ml.com/img-1.jpg"}],
                    "attributes": [{"id": "SELLER_SKU", "value_name": "SKU-A"}],
                    "shipping": {"mode": "me2", "free_shipping": True, "local_pick_up": True},
                    "sale_terms": [{"id": "WARRANTY_TYPE", "value_name": "Garantia do vendedor"}],
                },
                {
                    "family_name": "Linha Alpha",
                    "category_id": "MLB271599",
                    "price": 60.0,
                    "currency_id": "BRL",
                    "available_quantity": 5,
                    "buying_mode": "buy_it_now",
                    "listing_type_id": "gold_special",
                    "condition": "new",
                    "pictures": [{"source": "https://cdn.ml.com/img-2.jpg"}],
                    "attributes": [{"id": "SELLER_SKU", "value_name": "SKU-B"}],
                    "shipping": {"mode": "me2", "free_shipping": False, "local_pick_up": True},
                    "sale_terms": [{"id": "WARRANTY_TYPE", "value_name": "Garantia do vendedor"}],
                },
            ],
        )

        result = use_case.execute(tmp_path / "payload.json")

        assert result.status == "published"
        assert result.publish_endpoints == ["/items", "/items"]
        assert [call.args[0] for call in publisher.post.call_args_list] == [
            "/items/validate",
            "/items/validate",
            "/items",
            "/items",
        ]
        first_post_body = publisher.post.call_args_list[2].kwargs["json"]
        second_post_body = publisher.post.call_args_list[3].kwargs["json"]
        assert first_post_body["family_name"] == "Linha Alpha"
        assert second_post_body["family_name"] == "Linha Alpha"
        assert first_post_body["shipping"]["local_pick_up"] is True
        assert second_post_body["shipping"]["local_pick_up"] is True

    def test_publish_user_products_continues_when_validation_has_only_warning(
        self, tmp_path: Path
    ) -> None:
        use_case, reader, publisher = _make_use_case()
        reader.read.return_value = _make_user_products_read_result()
        publisher.validate_user_product_item.return_value = {
            "error": "validation_error",
            "status": 400,
            "cause": [
                {
                    "type": "warning",
                    "code": "shipping.lost_me1_by_user",
                    "message": "warn",
                    "department": "shipping",
                }
            ],
        }

        result = use_case.execute(tmp_path / "payload.json")

        assert result.status == "published"
        assert result.validation_status == "validation_passed_with_warnings"
        assert result.validation_report is not None
        assert result.validation_report["warnings"][0]["code"] == "shipping.lost_me1_by_user"
        publisher.create_user_product_item.assert_called_once()

    def test_publish_user_products_blocks_when_validation_has_warning_and_error(
        self, tmp_path: Path
    ) -> None:
        use_case, reader, publisher = _make_use_case()
        reader.read.return_value = _make_user_products_read_result()
        publisher.validate_user_product_item.return_value = {
            "error": "validation_error",
            "status": 400,
            "cause": [
                {"type": "warning", "code": "shipping.lost_me1_by_user", "message": "warn"},
                {"type": "error", "code": "item.title.required", "message": "erro"},
            ],
        }

        result = use_case.execute(tmp_path / "payload.json")

        assert result.status == "failed"
        assert result.validation_status == "validation_failed"
        assert "item.title.required" in (result.error or "")
        publisher.create_user_product_item.assert_not_called()

    def test_publish_user_products_multiple_items_does_not_require_first_user_product_id(
        self, tmp_path: Path
    ) -> None:
        use_case, reader, publisher = _make_use_case()
        reader.read.return_value = _make_user_products_read_result(
            items=[
                {
                    "category_id": "MLB271599",
                    "price": 50.0,
                    "currency_id": "BRL",
                    "available_quantity": 10,
                    "buying_mode": "buy_it_now",
                    "listing_type_id": "gold_special",
                    "condition": "new",
                    "pictures": [{"source": "https://cdn.ml.com/img-1.jpg"}],
                    "attributes": [{"id": "BRAND", "value_name": "Marca"}],
                },
                {
                    "category_id": "MLB271599",
                    "price": 60.0,
                    "currency_id": "BRL",
                    "available_quantity": 5,
                    "buying_mode": "buy_it_now",
                    "listing_type_id": "gold_special",
                    "condition": "new",
                    "pictures": [{"source": "https://cdn.ml.com/img-2.jpg"}],
                    "attributes": [{"id": "BRAND", "value_name": "Marca"}],
                },
            ]
        )
        publisher.create_user_product_item.return_value = _grouped_up_response(id="MLB1")

        result = use_case.execute(tmp_path / "payload.json")

        assert result.status == "published"
        assert result.item_id == "MLB1"
        assert result.item_ids == ["MLB1", "MLB1"]
        assert result.user_product_id is None
        assert result.publish_endpoints == ["/items", "/items"]

    def test_publish_existing_user_product_mode_reuses_first_user_product_id(
        self, tmp_path: Path
    ) -> None:
        use_case, reader, publisher = _make_use_case()
        reader.read.return_value = _make_user_products_payload_array_read_result(
            description=None,
            entries=[
                {
                    "target": "existing_user_product_selling_condition",
                    "price": 50.0,
                    "category_id": "MLB271599",
                    "currency_id": "BRL",
                    "buying_mode": "buy_it_now",
                    "listing_type_id": "gold_special",
                },
                {
                    "target": "existing_user_product_selling_condition",
                    "price": 60.0,
                    "category_id": "MLB271599",
                    "currency_id": "BRL",
                    "buying_mode": "buy_it_now",
                    "listing_type_id": "gold_special",
                },
            ],
        )
        publisher.create_user_product_item.side_effect = [
            _grouped_up_response(id="MLB1", user_product_id="MLBU123"),
            _grouped_up_response(id="MLB2"),
        ]

        result = use_case.execute(tmp_path / "payload.json")

        assert result.status == "published"
        assert result.user_product_id == "MLBU123"
        assert result.publish_endpoints == [
            "/user-products/{user_product_id}/items",
            "/user-products/{user_product_id}/items",
        ]
        first_payload = publisher.create_user_product_item.call_args_list[0].args[0]
        second_payload = publisher.create_user_product_item.call_args_list[1].args[0]
        assert "user_product_id" not in first_payload
        assert second_payload["user_product_id"] == "MLBU123"


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


class TestPublishPayloadApiErrors:
    """PublishPayloadUseCase must surface ML API cause codes in PublishPayloadResult.error."""

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
        assert '"error": "validation_error"' in (result.error or "")
        assert '"references": ["item.attributes"]' in (result.error or "")

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


class TestPublishInactiveFlag:
    """PublishPayloadUseCase must pause items after creation when publish_inactive=True."""

    def test_publish_inactive_true_calls_update_item(self, tmp_path: Path) -> None:
        """publish_inactive=True triggers update_item({status: paused}) after creation."""
        use_case, reader, publisher = _make_use_case(publish_inactive=True)
        reader.read.return_value = _make_read_result()

        result = use_case.execute(tmp_path / "payload.json")

        assert result.status == "published"
        publisher.update_item.assert_called_once_with("MLB987654321", {"status": "paused"})

    def test_publish_inactive_false_does_not_call_update_item(self, tmp_path: Path) -> None:
        """Default (False) never calls update_item."""
        use_case, reader, publisher = _make_use_case(publish_inactive=False)
        reader.read.return_value = _make_read_result()

        result = use_case.execute(tmp_path / "payload.json")

        assert result.status == "published"
        publisher.update_item.assert_not_called()

    def test_publish_inactive_update_failure_requires_reconciliation(self, tmp_path: Path) -> None:
        """A created item that could not be paused is never complete success."""
        use_case, reader, publisher = _make_use_case(publish_inactive=True)
        reader.read.return_value = _make_read_result()
        publisher.update_item.side_effect = RuntimeError("pause failed")

        result = use_case.execute(tmp_path / "payload.json")

        assert result.status == "failed"
        assert result.side_effect_state == "partial"
        assert result.reconciliation_required is True
        assert result.item_id == "MLB987654321"
        publisher.update_item.assert_called_once_with("MLB987654321", {"status": "paused"})


class TestPublicationReadyGate:
    def test_publication_ready_false_blocks_publish(self, tmp_path: Path) -> None:
        """publication_ready=False must block publish and surface blocking_reasons."""
        use_case, reader, publisher = _make_use_case()
        read_result = replace(
            _make_read_result(),
            publication_ready=False,
            blocking_reasons=["fiscal not resolved"],
        )
        reader.read.return_value = read_result

        result = use_case.execute(tmp_path / "payload.json")

        assert result.status == "failed"
        assert "fiscal not resolved" in (result.error or "")
        publisher.create_item.assert_not_called()

    def test_publication_ready_true_proceeds(self, tmp_path: Path) -> None:
        """publication_ready=True proceeds through the full publish flow."""
        use_case, reader, publisher = _make_use_case()
        read_result = replace(_make_read_result(), publication_ready=True)
        reader.read.return_value = read_result

        result = use_case.execute(tmp_path / "payload.json")

        assert result.status == "published"
        publisher.create_item.assert_called_once()

    def test_publication_ready_none_is_rejected(self, tmp_path: Path) -> None:
        """The publisher requires an explicit positive readiness decision."""
        use_case, reader, publisher = _make_use_case()
        reader.read.return_value = replace(_make_read_result(), publication_ready=None)

        result = use_case.execute(tmp_path / "payload.json")

        assert result.status == "failed"
        assert "publication_ready" in (result.error or "")
        publisher.create_item.assert_not_called()


class TestLowConfidenceGate:
    def test_low_confidence_ai_category_blocked(self, tmp_path: Path) -> None:
        """category_confidence below min_ai_confidence must block publish."""
        config = _make_seller_config(human_review_required=False, min_ai_confidence=0.70)
        use_case, reader, publisher = _make_use_case(config)
        read_result = replace(_make_read_result(ai_suggested=True), category_confidence=0.45)
        reader.read.return_value = read_result

        result = use_case.execute(tmp_path / "payload.json")

        assert result.status == "failed"
        assert result.error is not None
        assert (
            "0.45" in (result.error or "")
            or "45.0%" in (result.error or "")
            or "Confiança" in (result.error or "")
        )
        publisher.create_item.assert_not_called()


class TestFiscalWarningGate:
    def test_reviewed_fiscal_false_with_publication_ready_adds_warning(
        self, tmp_path: Path
    ) -> None:
        """publication_ready=True with reviewed_fiscal=False emits a warning but still publishes."""
        mock_fiscal_service = MagicMock()
        mock_fiscal_service.submit_fiscal_data_workflow.return_value = MagicMock(success=True)
        use_case, reader, publisher = _make_use_case(fiscal_service=mock_fiscal_service)
        read_result = replace(
            _make_read_result(fiscal_items=[{"sku": "ABC-001", "type": "single"}]),
            publication_ready=True,
            reviewed_fiscal=False,
        )
        reader.read.return_value = read_result

        result = use_case.execute(tmp_path / "payload.json")

        assert result.status == "published"
        assert any("fiscal" in w.lower() for w in result.warnings)

    def test_reviewed_fiscal_true_no_extra_warning(self, tmp_path: Path) -> None:
        """publication_ready=True with reviewed_fiscal=True produces no fiscal warning."""
        use_case, reader, publisher = _make_use_case()
        read_result = replace(_make_read_result(), publication_ready=True, reviewed_fiscal=True)
        reader.read.return_value = read_result

        result = use_case.execute(tmp_path / "payload.json")

        assert result.status == "published"
        assert not any("fiscal" in w.lower() for w in result.warnings)

    def test_reviewed_fiscal_none_no_extra_warning(self, tmp_path: Path) -> None:
        """reviewed_fiscal=None (absent) must not produce fiscal warning — backward compat."""
        use_case, reader, publisher = _make_use_case()
        reader.read.return_value = _make_read_result()  # reviewed_fiscal defaults to None

        result = use_case.execute(tmp_path / "payload.json")

        assert result.status == "published"
        assert not any("fiscal" in w.lower() for w in result.warnings)


class TestUserProductsGroupingVerification:
    def test_publish_user_products_reports_not_grouped_when_grouping_ids_absent(
        self, tmp_path: Path
    ) -> None:
        use_case, reader, publisher = _make_use_case()
        reader.read.return_value = _make_user_products_read_result(
            items=[
                {
                    "category_id": "MLB271599",
                    "price": 50.0,
                    "currency_id": "BRL",
                    "available_quantity": 10,
                    "buying_mode": "buy_it_now",
                    "listing_type_id": "gold_special",
                    "condition": "new",
                    "pictures": [{"source": "https://cdn.ml.com/img-1.jpg"}],
                },
                {
                    "category_id": "MLB271599",
                    "price": 60.0,
                    "currency_id": "BRL",
                    "available_quantity": 5,
                    "buying_mode": "buy_it_now",
                    "listing_type_id": "gold_special",
                    "condition": "new",
                    "pictures": [{"source": "https://cdn.ml.com/img-2.jpg"}],
                },
            ]
        )
        publisher.create_user_product_item.side_effect = [
            {"id": "MLB1", "user_product_id": "MLBU123"},
            {"id": "MLB2", "user_product_id": "MLBU456"},
        ]
        publisher.get_user_product.side_effect = [
            {"id": "MLBU123"},
            {"id": "MLBU456"},
        ]

        result = use_case.execute(tmp_path / "payload.json")

        assert result.status == "published_but_not_grouped"
        assert "missing_family_id_for_multi_item_user_products_publish" in result.warnings

    def test_publish_user_products_reports_not_grouped_when_grouping_ids_diverge(
        self, tmp_path: Path
    ) -> None:
        use_case, reader, publisher = _make_use_case()
        reader.read.return_value = _make_user_products_read_result(
            items=[
                {
                    "category_id": "MLB271599",
                    "price": 50.0,
                    "currency_id": "BRL",
                    "available_quantity": 10,
                    "buying_mode": "buy_it_now",
                    "listing_type_id": "gold_special",
                    "condition": "new",
                    "pictures": [{"source": "https://cdn.ml.com/img-1.jpg"}],
                },
                {
                    "category_id": "MLB271599",
                    "price": 60.0,
                    "currency_id": "BRL",
                    "available_quantity": 5,
                    "buying_mode": "buy_it_now",
                    "listing_type_id": "gold_special",
                    "condition": "new",
                    "pictures": [{"source": "https://cdn.ml.com/img-2.jpg"}],
                },
            ]
        )
        publisher.create_user_product_item.side_effect = [
            {"id": "MLB1", "user_product_id": "MLBU123"},
            {"id": "MLB2", "user_product_id": "MLBU456"},
        ]
        publisher.get_user_product.side_effect = lambda user_product_id: {
            "id": user_product_id,
            "family_id": "FAM-1" if user_product_id == "MLBU123" else "FAM-2",
        }

        result = use_case.execute(tmp_path / "payload.json")

        assert result.status == "published_but_not_grouped"
        assert "divergent_family_id_across_user_product_items" in result.warnings

    def test_publish_user_products_allows_different_user_product_id_with_consistent_family_id(
        self, tmp_path: Path
    ) -> None:
        use_case, reader, publisher = _make_use_case()
        reader.read.return_value = _make_user_products_read_result(
            items=[
                {
                    "category_id": "MLB271599",
                    "price": 50.0,
                    "currency_id": "BRL",
                    "available_quantity": 10,
                    "buying_mode": "buy_it_now",
                    "listing_type_id": "gold_special",
                    "condition": "new",
                    "pictures": [{"source": "https://cdn.ml.com/img-1.jpg"}],
                },
                {
                    "category_id": "MLB271599",
                    "price": 60.0,
                    "currency_id": "BRL",
                    "available_quantity": 5,
                    "buying_mode": "buy_it_now",
                    "listing_type_id": "gold_special",
                    "condition": "new",
                    "pictures": [{"source": "https://cdn.ml.com/img-2.jpg"}],
                },
            ]
        )
        publisher.create_user_product_item.side_effect = [
            {"id": "MLB1", "user_product_id": "MLBU123", "family_id": "FAM-1"},
            {"id": "MLB2", "user_product_id": "MLBU999", "family_id": "FAM-1"},
        ]

        result = use_case.execute(tmp_path / "payload.json")

        assert result.status == "published"
        assert result.user_product_id == "MLBU123"

    def test_publish_user_products_reports_not_grouped_when_only_one_item_has_family_id(
        self, tmp_path: Path
    ) -> None:
        use_case, reader, publisher = _make_use_case()
        reader.read.return_value = _make_user_products_read_result(
            items=[
                {
                    "category_id": "MLB271599",
                    "price": 50.0,
                    "currency_id": "BRL",
                    "available_quantity": 10,
                    "buying_mode": "buy_it_now",
                    "listing_type_id": "gold_special",
                    "condition": "new",
                    "pictures": [{"source": "https://cdn.ml.com/img-1.jpg"}],
                },
                {
                    "category_id": "MLB271599",
                    "price": 60.0,
                    "currency_id": "BRL",
                    "available_quantity": 5,
                    "buying_mode": "buy_it_now",
                    "listing_type_id": "gold_special",
                    "condition": "new",
                    "pictures": [{"source": "https://cdn.ml.com/img-2.jpg"}],
                },
            ]
        )
        publisher.create_user_product_item.side_effect = [
            {"id": "MLB1", "user_product_id": "MLBU123", "family_id": "FAM-1"},
            {"id": "MLB2", "user_product_id": "MLBU456"},
        ]
        publisher.get_user_product.side_effect = lambda user_product_id: {
            "id": user_product_id,
            "family_id": "FAM-1" if user_product_id == "MLBU123" else None,
        }

        result = use_case.execute(tmp_path / "payload.json")

        assert result.status == "published_but_not_grouped"
        assert "missing_family_id_for_multi_item_user_products_publish" in result.warnings

    def test_publish_user_products_resolves_family_id_via_get_user_product(
        self, tmp_path: Path
    ) -> None:
        use_case, reader, publisher = _make_use_case()
        reader.read.return_value = _make_user_products_read_result(
            items=[
                {
                    "category_id": "MLB271599",
                    "price": 50.0,
                    "currency_id": "BRL",
                    "available_quantity": 10,
                    "buying_mode": "buy_it_now",
                    "listing_type_id": "gold_special",
                    "condition": "new",
                    "pictures": [{"source": "https://cdn.ml.com/img-1.jpg"}],
                },
                {
                    "category_id": "MLB271599",
                    "price": 60.0,
                    "currency_id": "BRL",
                    "available_quantity": 5,
                    "buying_mode": "buy_it_now",
                    "listing_type_id": "gold_special",
                    "condition": "new",
                    "pictures": [{"source": "https://cdn.ml.com/img-2.jpg"}],
                },
            ]
        )
        publisher.create_user_product_item.side_effect = [
            {"id": "MLB1", "user_product_id": "MLBU123"},
            {"id": "MLB2", "user_product_id": "MLBU456"},
        ]
        publisher.get_user_product.side_effect = lambda user_product_id: {
            "id": user_product_id,
            "family_id": "FAM-1",
        }

        result = use_case.execute(tmp_path / "payload.json")

        assert result.status == "published"
        assert publisher.get_user_product.call_count == 2
