"""Tests for category handling in publish flow."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

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
        category_data: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self.find_result = find_result
        self.predictor_result = predictor_result
        self.title_result = title_result
        self.leaf_map = leaf_map or {}
        self.listing_allowed = listing_allowed or {}
        self.category_data = category_data or {}
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

    def get_category_data(self, category_id: str) -> dict[str, Any]:
        return self.category_data.get(
            category_id,
            {
                "id": category_id,
                "path_from_root": [{"id": category_id, "name": f"Category {category_id}"}],
            },
        )


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
    assert resolver.find_calls == 0
    assert resolver.predictor_calls == [("Nao encontrada", ["Notebook Gamer"], "MLB")]
    assert resolver.title_calls == []
    assert resolver.resolve_calls == ["MLB1000"]
    assert use_case._publish_one.call_count == 1
    assert use_case._publish_one.call_args.args[1] == "MLB1001"
    item_result = result["item_results"][0]
    assert item_result["resolution_strategy"] == "predictor_path_match"
    assert item_result["category_input"] == "Nao encontrada"
    assert item_result["category_resolved_id"] == "MLB1001"
    assert item_result["category_path"] == [{"id": "MLB1001", "name": "Category MLB1001"}]
    assert item_result["category_resolution_decision"]["predictor_attempted"] is True
    assert item_result["category_resolution_decision"]["predictor_matched"] is True
    assert item_result["category_resolution_decision"]["fallback_attempted"] is False
    assert result["category_resolution"]["strategy_counts"]["predictor_path_match"] == 1
    assert result["category_resolution"]["fallback_counts"] == {
        "attempted": 0,
        "resolved": 0,
        "unresolved": 0,
    }
    assert result["category_resolution"]["predictor_counts"] == {
        "attempted": 1,
        "matched": 1,
        "unmatched": 0,
    }


def test_execute_fails_fast_when_category_is_not_allowed_for_listing() -> None:
    resolver = _CategoryFlowResolver(
        find_result=None,
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

    result = use_case.execute([_build_product()], "MLB2000")

    assert result["success"] is False
    assert result["published"] == 0
    assert result["failed"] == 1
    assert result["errors"] == ["Category not available for listing: MLB2000"]
    assert result["item_results"][0]["status"] == "failed"
    assert result["item_results"][0]["resolution_strategy"] == "direct_id"
    assert result["item_results"][0]["category_input"] == "MLB2000"
    assert result["item_results"][0]["category_resolved_id"] == "MLB2000"
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
    item_result = result["item_results"][0]
    assert item_result["resolution_strategy"] == "direct_id"
    assert item_result["category_input"] == "MLB2000"
    assert item_result["category_resolved_id"] == "MLB2000"


def test_execute_accepts_direct_category_id_with_surrounding_whitespace() -> None:
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

    result = use_case.execute([_build_product()], "  MLB2000  ")

    assert result["success"] is True
    assert resolver.find_calls == 0
    assert resolver.predictor_calls == []
    assert resolver.title_calls == []
    assert resolver.resolve_calls == ["MLB2000"]
    assert use_case._publish_one.call_args.args[1] == "MLB2000"
    item_result = result["item_results"][0]
    assert item_result["resolution_strategy"] == "direct_id"
    assert item_result["category_input"] == "MLB2000"
    assert item_result["category_resolved_id"] == "MLB2000"


def test_execute_returns_unresolved_when_predictor_does_not_match() -> None:
    resolver = _CategoryFlowResolver(
        find_result=None,
        predictor_result=None,
    )
    use_case = PublishProductUseCase(
        category_resolver=resolver,  # type: ignore[arg-type]
        publisher=MagicMock(),
        image_uploader=MagicMock(),
        enable_feedback=False,
        enable_fiscal_submission=False,
    )
    use_case._publish_one = MagicMock(return_value=True)  # type: ignore[method-assign]

    result = use_case.execute([_build_product("Notebook Gamer")], "Nao encontrada")

    assert result["success"] is False
    assert resolver.predictor_calls == [("Nao encontrada", ["Notebook Gamer"], "MLB")]
    assert resolver.find_calls == 0
    assert resolver.title_calls == []
    assert use_case._publish_one.call_count == 0
    item_result = result["item_results"][0]
    assert item_result["resolution_strategy"] == "unresolved"
    assert item_result["category_resolved_id"] is None
    assert item_result["category_resolution_decision"]["predictor_attempted"] is True
    assert item_result["category_resolution_decision"]["predictor_matched"] is False
    assert item_result["category_resolution_decision"]["fallback_reason"] == "predictor_no_match"
    assert result["category_resolution"]["strategy_counts"]["unresolved"] == 1
    assert result["category_resolution"]["predictor_counts"] == {
        "attempted": 1,
        "matched": 0,
        "unmatched": 1,
    }


def test_execute_includes_unresolved_metadata_when_category_not_found() -> None:
    resolver = _CategoryFlowResolver(find_result=None, predictor_result=None, title_result=None)
    use_case = PublishProductUseCase(
        category_resolver=resolver,  # type: ignore[arg-type]
        publisher=MagicMock(),
        image_uploader=MagicMock(),
        enable_feedback=False,
        enable_fiscal_submission=False,
    )
    use_case._publish_one = MagicMock(return_value=True)  # type: ignore[method-assign]

    result = use_case.execute([_build_product("Notebook Gamer")], "Nao encontrada")

    assert result["success"] is False
    assert result["errors"] == ["Category not found: Nao encontrada"]
    assert resolver.find_calls == 0
    assert resolver.title_calls == []
    item_result = result["item_results"][0]
    assert item_result["resolution_strategy"] == "unresolved"
    assert item_result["category_input"] == "Nao encontrada"
    assert item_result["category_resolved_id"] is None
    assert item_result["category_path"] == []


def test_execute_records_name_match_fallback_observability_when_titles_are_missing() -> None:
    resolver = _CategoryFlowResolver(find_result="MLB3000")
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

    result = use_case.execute([_build_product("")], "Categoria sem titulo")

    assert result["success"] is True
    item_result = result["item_results"][0]
    assert item_result["resolution_strategy"] == "name_match"
    assert item_result["category_resolution_decision"]["predictor_attempted"] is False
    assert item_result["category_resolution_decision"]["fallback_attempted"] is True
    assert (
        item_result["category_resolution_decision"]["fallback_reason"]
        == "missing_titles_for_predictor"
    )
    assert result["category_resolution"]["strategy_counts"]["name_match"] == 1
    assert result["category_resolution"]["fallback_counts"] == {
        "attempted": 1,
        "resolved": 1,
        "unresolved": 0,
    }


@pytest.mark.parametrize(
    (
        "category_input",
        "title",
        "resolver_kwargs",
        "expected_strategy",
        "expected_category",
    ),
    [
        (
            "MLB1743",
            "Livro de Python",
            {"find_result": "IGNORED"},
            "direct_id",
            "MLB1743",
        ),
        (
            "Celulares e Smartphones",
            "Smartphone Android",
            {"find_result": None, "predictor_result": "MLB1055"},
            "predictor_path_match",
            "MLB1055",
        ),
        (
            "Moda sem Match",
            "Camiseta Dry Fit",
            {
                "find_result": None,
                "predictor_result": "MLB1430",
                "leaf_map": {"MLB1430": "MLB1431"},
            },
            "predictor_path_match",
            "MLB1431",
        ),
        (
            "Categoria desconhecida",
            "Bicicleta Aro 29",
            {
                "find_result": None,
                "predictor_result": None,
            },
            "unresolved",
            None,
        ),
    ],
)
def test_execute_resolution_strategy_matrix(
    category_input: str,
    title: str,
    resolver_kwargs: dict[str, Any],
    expected_strategy: str,
    expected_category: str | None,
) -> None:
    resolver = _CategoryFlowResolver(**resolver_kwargs)
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

    result = use_case.execute([_build_product(title)], category_input)

    if expected_category is None:
        assert result["success"] is False
        assert result["published"] == 0
        assert result["errors"] == [f"Category not found: {category_input}"]
    else:
        assert result["success"] is True
        assert result["published"] == 1

    item_result = result["item_results"][0]
    assert item_result["resolution_strategy"] == expected_strategy
    assert item_result["category_input"] == category_input
    assert item_result["category_resolved_id"] == expected_category
