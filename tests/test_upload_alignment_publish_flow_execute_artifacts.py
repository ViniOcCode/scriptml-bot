"""Publish flow tests for execute artifacts and payload normalization."""

from __future__ import annotations

from typing import Any

import pytest

from mercadolivre_upload.application.attribute_builder import AttributeBuilderService
from mercadolivre_upload.application.publish_product import PublishProductUseCase
from mercadolivre_upload.domain.attribute_metadata import AttributeMeta
from mercadolivre_upload.domain.cache_attribute_mapper import CachedAttributeMapper
from tests.support.upload_alignment import (
    _FakeCategoryResolver,
    _FakeImageUploader,
    _FakePublisher,
    _FixedShippingResolver,
    _StaticAttributeCache,
)


def test_publish_attribute_normalization_uses_attribute_id_for_weights() -> None:
    use_case = object.__new__(PublishProductUseCase)
    use_case.config = {}

    item = {
        "attributes": [
            {"id": "WEIGHT", "value_name": "0,220"},
            {"id": "WIDTH", "value_name": "23"},
            {"id": "SELLER_PACKAGE_WEIGHT", "value_name": "214"},
        ]
    }

    PublishProductUseCase._normalize_item_attributes(use_case, item)

    values = {a["id"]: a["value_name"] for a in item["attributes"]}
    assert values["WEIGHT"] == "0.220 kg"
    assert values["WIDTH"] == "23 cm"
    assert values["SELLER_PACKAGE_WEIGHT"] == "214 g"


def test_publish_attribute_normalization_skips_non_dict_attributes() -> None:
    use_case = object.__new__(PublishProductUseCase)
    use_case.config = {}

    item = {
        "attributes": [
            {"id": "WIDTH", "value_name": "23"},
            "invalid-attribute",
            None,
        ]
    }

    PublishProductUseCase._normalize_item_attributes(use_case, item)

    assert item["attributes"][0]["value_name"] == "23 cm"
    assert item["attributes"][1] == "invalid-attribute"
    assert item["attributes"][2] is None


def test_build_product_reads_descricao_header() -> None:
    use_case = object.__new__(PublishProductUseCase)
    product = PublishProductUseCase._build_product_from_dict(
        use_case,
        {
            "Título": "Meu livro",
            "Preço": 29.9,
            "Estoque": 2,
            "Condição": "Novo",
            "SKU": "SKU-ABC",
            "Descrição": "Descrição vinda da planilha",
        },
    )

    assert product.description == "Descrição vinda da planilha"


@pytest.mark.parametrize(
    ("row", "expected"),
    [
        (
            {
                "Título do anúncio": "Notebook Gamer",
                "Preço": "4999,90",
                "Estoque disponível": "2",
                "Condição": "Novo",
                "Código interno": "SKU-NOTE-01",
                "Descrição": "Linha premium",
            },
            {
                "sku": "SKU-NOTE-01",
                "title": "Notebook gamer",
                "price": 4999.9,
                "quantity": 2,
                "condition": "new",
                "description": "Linha premium",
            },
        ),
        (
            {
                "Title": "Camiseta Dry Fit",
                "Price": "79.5",
                "Stock": "12",
                "Condition": "used",
                "Code": "SKU-CAM-12",
            },
            {
                "sku": "SKU-CAM-12",
                "title": "Camiseta dry fit",
                "price": 79.5,
                "quantity": 12,
                "condition": "used",
                "description": "",
            },
        ),
        (
            {
                "Título do livro": "Título incorreto",
                "Título do anúncio": "Fone Bluetooth",
                "Preço unitário": "129,99",
                "Quantidade em estoque": "7",
                "Condição": "1",
                "SKU": "SKU-FONE-7",
                "Descrição completa": "Com cancelamento de ruído",
                "Varia por: Cor": "Preto, Branco",
            },
            {
                "sku": "SKU-FONE-7",
                "title": "Fone bluetooth",
                "price": 129.99,
                "quantity": 7,
                "condition": "used",
                "description": "Com cancelamento de ruído",
            },
        ),
    ],
)
def test_build_product_handles_messy_header_variants_matrix(
    row: dict[str, Any], expected: dict[str, Any]
) -> None:
    use_case = object.__new__(PublishProductUseCase)

    product = PublishProductUseCase._build_product_from_dict(use_case, row)

    assert product.sku == expected["sku"]
    assert product.title == expected["title"]
    assert product.price == expected["price"]
    assert product.available_quantity == expected["quantity"]
    assert product.condition == expected["condition"]
    assert product.description == expected["description"]
    if "Varia por: Cor" in row:
        assert product.attributes["Varia por: Cor"] == "Preto, Branco"


def test_execute_variation_heavy_row_surfaces_preflight_artifacts() -> None:
    class _ResolverWithExecute(_FakeCategoryResolver):
        def resolve_to_leaf(self, category_id: str) -> str:
            return category_id

        def find_category(self, _name: str) -> str | None:
            return None

        def find_category_with_predictor(
            self,
            _category_name: str,
            _product_titles: list[str],
            _site_id: str = "MLB",
        ) -> str | None:
            return None

        def predict_category_from_title(self, _title: str, _site_id: str = "MLB") -> str | None:
            return None

        def is_listing_allowed(self, _category_id: str) -> bool:
            return True

    class _WarningPublisher(_FakePublisher):
        def validate_item(self, item: dict[str, Any]) -> dict[str, Any]:
            self.validated_items.append(item)
            return {
                "cause": [
                    {
                        "type": "warning",
                        "code": "item.title.normalized",
                        "message": "Title normalized for publish matrix",
                    }
                ]
            }

    class _DiagnosticImageUploader(_FakeImageUploader):
        def diagnose_images(
            self,
            *,
            sku: str,
            category_id: str,
            title: str | None,
            picture_urls: list[str],
            picture_ids: list[str] | None = None,
        ) -> dict[str, Any]:
            del sku, category_id, title, picture_ids
            return {
                "status": "passed",
                "available": True,
                "checked": len(picture_urls),
                "issues": [],
                "results": [],
            }

    resolver = _ResolverWithExecute(
        [
            AttributeMeta(id="COLOR", name="Cor", value_type="string", required=False),
            AttributeMeta(id="GTIN", name="GTIN", value_type="string", required=False),
        ]
    )
    publisher = _WarningPublisher(listing_types=[{"id": "gold_special"}], sale_terms=[])
    use_case = PublishProductUseCase(
        category_resolver=resolver,  # type: ignore[arg-type]
        publisher=publisher,  # type: ignore[arg-type]
        image_uploader=_DiagnosticImageUploader(),  # type: ignore[arg-type]
        shipping_resolver=_FixedShippingResolver("me2"),  # type: ignore[arg-type]
        fiscal_service=None,
        clip_uploader=None,
        config={
            "core_item_fields": {
                "defaults": {
                    "currency_id": "BRL",
                    "buying_mode": "buy_it_now",
                    "listing_type_id": "gold_special",
                    "sale_terms": [],
                }
            },
            "shipping": {
                "default_mode": "me2",
                "modes": {
                    "me2": {
                        "local_pick_up": False,
                        "logistic_type": "drop_off",
                        "methods": [],
                        "tags": [],
                        "dimensions": None,
                        "free_shipping": False,
                        "store_pick_up": False,
                    }
                },
            },
        },
        dry_run=False,
        validation_only=True,
        min_attribute_score=0,
        enable_feedback=False,
        enable_fiscal_submission=False,
    )

    cache_mapper = CachedAttributeMapper(
        _StaticAttributeCache(
            [
                {
                    "id": "COLOR",
                    "name": "Cor",
                    "value_type": "string",
                    "values": [
                        {"id": "1", "name": "Azul"},
                        {"id": "2", "name": "Verde"},
                    ],
                }
            ]
        ),
        "MLB123",
    )
    use_case._attribute_builder.set_cache_mapper(cache_mapper)  # type: ignore[attr-defined]

    row = {
        "Título do anúncio": "Camiseta Esportiva",
        "Preço de venda": "59,90",
        "Estoque atual": "4",
        "Condição": "Novo",
        "Código interno": "SKU-CAM-1",
        "Descrição completa": "Tecido dry fit",
        "Varia por: Cor": "Azul, Verde",
        "EAN / GTIN": "7891234567895",
    }

    result = use_case.execute([row], "MLB123")

    assert result["success"] is True
    assert result["validated"] == 1
    item_result = result["item_results"][0]
    assert item_result["resolution_strategy"] == "direct_id"
    assert item_result["category_resolved_id"] == "MLB123"
    assert item_result["identifier_gate"]["checked"] is True
    assert item_result["image_diagnostics"]["status"] == "passed"
    assert item_result["shipping_policy"]["decision"]["selected_mode"] == "me2"
    assert item_result["validation_decision"]["action"] == "allow"

    validated_item = publisher.validated_items[0]
    variation_values = sorted(
        variation["attribute_combinations"][0]["value_name"]
        for variation in validated_item["variations"]
    )
    assert variation_values == ["Azul", "Verde"]


def test_gtin_source_priority_scores_universal_code_higher_than_isbn() -> None:
    resolver = _FakeCategoryResolver(
        [
            AttributeMeta(id="GTIN", name="GTIN", value_type="string", required=False),
        ]
    )
    service = AttributeBuilderService(
        category_resolver=resolver,
        config={
            "gtin_source_priority": [
                "Código de produtos universal",
                "EAN / GTIN",
                "ISBN",
                "IBSN",
            ]
        },
        min_attribute_score=0,
    )
    meta = resolver.get_attribute_metadata("MLB123")[0]

    universal_score = service._score_attribute_payload(
        {
            "id": "GTIN",
            "value_name": "1234567890123",
            "_source_column": "Código de produtos universal",
        },
        meta,
    )
    isbn_score = service._score_attribute_payload(
        {"id": "GTIN", "value_name": "1234567890123", "_source_column": "ISBN"},
        meta,
    )

    assert universal_score > isbn_score
