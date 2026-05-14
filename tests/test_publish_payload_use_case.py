"""Tests for PublishPayloadUseCase."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import requests

from mercadolivre_upload.adapters.json_payload_reader import (
    InvalidPayloadError,
    JsonPayloadReader,
    ReadPayloadResult,
)
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
        sku=sku,
        category_id=category_id,
        ai_suggested=ai_suggested,
        fiscal_items=fiscal_items or [],
        publish_item_skus=publish_item_skus or [],
    )


def _make_user_products_read_result(
    *,
    description: str | None = "Descrição do produto",
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
        sku=sku,
        category_id="MLB271599",
        ai_suggested=ai_suggested,
        upload_mode="user_products",
        fiscal_items=fiscal_items or [],
        publish_item_skus=publish_item_skus or [],
    )


def _make_user_products_payload_array_read_result(
    *,
    description: str | None = "Descrição do produto",
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
        sku=sku,
        category_id="MLB271599",
        ai_suggested=ai_suggested,
        upload_mode="user_products",
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

        assert result.status == "published"
        assert result.item_id == "MLB987654321"
        assert result.sku == "ABC-001"
        publisher.create_item.assert_called_once()
        publisher.create_item_description.assert_called_once_with(
            "MLB987654321", "Descrição do produto"
        )

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

    def test_publish_continues_when_validation_has_only_warning_causes(self, tmp_path: Path) -> None:
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
        assert any("item.shipping.mandatory_free_shipping" in warning for warning in result.warnings)
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
            {"id": "MLB1", "user_product_id": "MLBU123"},
            {"id": "MLB2", "user_product_id": "MLBU123"},
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
            {"id": "MLB1", "user_product_id": "MLBU123"},
            {"id": "MLB2", "user_product_id": "MLBU123"},
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
            {"id": "MLB1", "user_product_id": "MLBU123"},
            {"id": "MLB2", "user_product_id": "MLBU123"},
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
            {"id": "MLB1", "user_product_id": "MLBU123"},
            {"id": "MLB2", "user_product_id": "MLBU123"},
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
        assert second_payload["user_product_id"] == "MLBU123"
        publisher.create_item_description.assert_called_once_with("MLB1", "Descrição do produto")

    def test_publish_user_products_payload_array_sends_separate_requests(
        self, tmp_path: Path
    ) -> None:
        use_case, reader, publisher = _make_use_case()
        reader.read.return_value = _make_user_products_payload_array_read_result(
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
                },
            ]
        )
        publisher.create_user_product_item.side_effect = [
            {"id": "MLB1", "user_product_id": "MLBU123"},
            {"id": "MLB2", "user_product_id": "MLBU123"},
        ]

        result = use_case.execute(tmp_path / "payload.json")

        assert result.status == "published"
        assert publisher.create_user_product_item.call_count == 2
        first_payload = publisher.create_user_product_item.call_args_list[0].args[0]
        second_payload = publisher.create_user_product_item.call_args_list[1].args[0]
        assert "items" not in first_payload
        assert "payload" not in first_payload
        assert first_payload["family_name"] == "Linha Alpha"
        assert second_payload["user_product_id"] == "MLBU123"

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

    def test_publish_user_products_missing_user_product_id_fails_after_first_item(
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
        publisher.create_user_product_item.return_value = {"id": "MLB1"}

        result = use_case.execute(tmp_path / "payload.json")

        assert result.status == "failed"
        assert result.item_id == "MLB1"
        assert result.item_ids == ["MLB1"]
        assert "user_product_id" in (result.error or "")


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

    def test_publish_inactive_update_failure_is_warn_only(self, tmp_path: Path) -> None:
        """If update_item raises, result is still 'published' — warn-only, not a failure."""
        use_case, reader, publisher = _make_use_case(publish_inactive=True)
        reader.read.return_value = _make_read_result()
        publisher.update_item.side_effect = RuntimeError("pause failed")

        result = use_case.execute(tmp_path / "payload.json")

        assert result.status == "published"
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

    def test_publication_ready_none_proceeds_compat(self, tmp_path: Path) -> None:
        """publication_ready=None (absent) must NOT block — backward compat."""
        use_case, reader, publisher = _make_use_case()
        reader.read.return_value = _make_read_result()  # publication_ready defaults to None

        result = use_case.execute(tmp_path / "payload.json")

        assert result.status == "published"
        publisher.create_item.assert_called_once()


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
