"""Tests for category handling in publish flow."""

from __future__ import annotations

from unittest.mock import MagicMock

from mercadolivre_upload.application.publish_product import PublishProductUseCase
from mercadolivre_upload.domain.fiscal.data import FiscalData
from mercadolivre_upload.domain.product.model import Product


class _CategoryFlowResolver:
    def __init__(
        self,
        *,
        find_result: str | None,
        predictor_result: str | None = None,
        title_result: str | None = None,
        leaf_map: dict[str, str] | None = None,
        listing_allowed: dict[str, bool] | None = None,
    ) -> None:
        self.find_result = find_result
        self.predictor_result = predictor_result
        self.title_result = title_result
        self.leaf_map = leaf_map or {}
        self.listing_allowed = listing_allowed or {}
        self.find_calls = 0
        self.predictor_calls: list[tuple[str, list[str], str]] = []
        self.title_calls: list[tuple[str, str]] = []
        self.resolve_calls: list[str] = []

    def find_category(self, _name: str, _site_id: str = "MLB") -> str | None:
        self.find_calls += 1
        return self.find_result

    def find_category_with_predictor(
        self,
        category_name: str,
        product_titles: list[str],
        site_id: str = "MLB",
    ) -> str | None:
        self.predictor_calls.append((category_name, product_titles, site_id))
        return self.predictor_result

    def predict_category_from_title(self, title: str, site_id: str = "MLB") -> str | None:
        self.title_calls.append((title, site_id))
        return self.title_result

    def resolve_to_leaf(self, category_id: str) -> str:
        self.resolve_calls.append(category_id)
        return self.leaf_map.get(category_id, category_id)

    def is_listing_allowed(self, category_id: str) -> bool:
        return self.listing_allowed.get(category_id, True)


def _build_product(title: str = "Produto teste") -> Product:
    return Product(
        sku="SKU-1",
        title=title,
        description="Desc",
        price=10.0,
        available_quantity=1,
        condition="new",
        fiscal=FiscalData(sku="SKU-1", title=title),
        attributes={},
    )


def test_execute_uses_predictor_and_resolves_to_leaf_before_publishing() -> None:
    resolver = _CategoryFlowResolver(
        find_result=None,
        predictor_result="MLB1000",
        leaf_map={"MLB1000": "MLB1001"},
    )
    use_case = PublishProductUseCase(
        category_resolver=resolver,  # type: ignore[arg-type]
        publisher=MagicMock(),
        image_uploader=MagicMock(),
        enable_feedback=False,
        enable_fiscal_submission=False,
    )

    def _publish(_product: Product, _category_id: str) -> bool:
        use_case.published += 1
        return True

    use_case._publish_one = MagicMock(side_effect=_publish)  # type: ignore[method-assign]

    result = use_case.execute([_build_product("Notebook Gamer")], "Nao encontrada")

    assert result["success"] is True
    assert result["published"] == 1
    assert resolver.predictor_calls == [("Nao encontrada", ["Notebook Gamer"], "MLB")]
    assert resolver.title_calls == []
    assert resolver.resolve_calls == ["MLB1000"]
    assert use_case._publish_one.call_count == 1
    assert use_case._publish_one.call_args.args[1] == "MLB1001"


def test_execute_fails_fast_when_category_is_not_allowed_for_listing() -> None:
    resolver = _CategoryFlowResolver(
        find_result="MLB2000",
        listing_allowed={"MLB2000": False},
    )
    use_case = PublishProductUseCase(
        category_resolver=resolver,  # type: ignore[arg-type]
        publisher=MagicMock(),
        image_uploader=MagicMock(),
        enable_feedback=False,
        enable_fiscal_submission=False,
    )
    use_case._publish_one = MagicMock(return_value=True)  # type: ignore[method-assign]

    result = use_case.execute([_build_product()], "Eletronicos")

    assert result["success"] is False
    assert result["published"] == 0
    assert result["failed"] == 1
    assert result["errors"] == ["Category not available for listing: MLB2000"]
    assert result["item_results"][0]["status"] == "failed"
    assert use_case._publish_one.call_count == 0


def test_execute_accepts_direct_category_id_without_name_lookup() -> None:
    resolver = _CategoryFlowResolver(find_result="UNUSED")
    use_case = PublishProductUseCase(
        category_resolver=resolver,  # type: ignore[arg-type]
        publisher=MagicMock(),
        image_uploader=MagicMock(),
        enable_feedback=False,
        enable_fiscal_submission=False,
    )

    def _publish(_product: Product, _category_id: str) -> bool:
        use_case.published += 1
        return True

    use_case._publish_one = MagicMock(side_effect=_publish)  # type: ignore[method-assign]

    result = use_case.execute([_build_product()], "MLB2000")

    assert result["success"] is True
    assert resolver.find_calls == 0
    assert resolver.predictor_calls == []
    assert resolver.title_calls == []
    assert resolver.resolve_calls == ["MLB2000"]
    assert use_case._publish_one.call_args.args[1] == "MLB2000"
