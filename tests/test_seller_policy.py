"""Tests for SellerPolicyValidator."""

from __future__ import annotations

from pathlib import Path

from mercadolivre_upload.application.validators.seller_policy import (
    BatchConfig,
    CategoriesConfig,
    ListingConfig,
    PolicyResult,
    PolicyViolation,
    PricingConfig,
    SellerConfig,
    SellerPolicyValidator,
    load_seller_config,
)


def _make_config(
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


def _make_payload(**overrides: object) -> dict:
    base: dict = {
        "title": "Produto",
        "category_id": "MLB271599",
        "price": 50.0,
        "listing_type_id": "gold_special",
        "pictures": [{"source": "https://cdn.ml.com/img.jpg"}],
    }
    base.update(overrides)
    return base


class TestSellerPolicyValidator:
    def test_listing_type_permitido(self) -> None:
        config = _make_config(allowed_types=["gold_special"])
        validator = SellerPolicyValidator(config)
        result = validator.validate(_make_payload(listing_type_id="gold_special"))
        assert not result.has_errors

    def test_listing_type_bloqueado(self) -> None:
        config = _make_config(allowed_types=["gold_special"])
        validator = SellerPolicyValidator(config)
        result = validator.validate(_make_payload(listing_type_id="bronze"))
        assert result.has_errors
        assert any(v.field == "listing_type_id" for v in result.violations)

    def test_preco_minimo(self) -> None:
        config = _make_config(min_price=5.0)
        validator = SellerPolicyValidator(config)
        result = validator.validate(_make_payload(price=4.50))
        assert result.has_errors
        assert any("abaixo do mínimo" in v.message for v in result.violations)

    def test_preco_maximo(self) -> None:
        config = _make_config(max_price=9999.0)
        validator = SellerPolicyValidator(config)
        result = validator.validate(_make_payload(price=10001.0))
        assert result.has_warnings
        assert not result.has_errors
        assert any("acima do máximo" in v.message for v in result.violations)

    def test_categoria_bloqueada(self) -> None:
        config = _make_config(blocked=["MLB000"])
        validator = SellerPolicyValidator(config)
        result = validator.validate(_make_payload(category_id="MLB000"))
        assert result.has_errors
        assert any("bloqueada" in v.message for v in result.violations)

    def test_ai_suggested_sem_revisao(self) -> None:
        config = _make_config(human_review_required=True)
        validator = SellerPolicyValidator(config)
        result = validator.validate(_make_payload(), ai_suggested=True)
        assert result.has_errors
        assert any("IA" in v.message for v in result.violations)

    def test_ai_suggested_revisao_ok(self) -> None:
        config = _make_config(human_review_required=False)
        validator = SellerPolicyValidator(config)
        result = validator.validate(_make_payload(), ai_suggested=True)
        assert not result.has_errors

    def test_override_listing_type(self) -> None:
        config = _make_config(overrides={"MLB271599": "gold_pro"})
        validator = SellerPolicyValidator(config)
        updated = validator.apply_overrides(_make_payload(category_id="MLB271599"))
        assert updated["listing_type_id"] == "gold_pro"

    def test_sem_violacoes(self) -> None:
        config = _make_config()
        validator = SellerPolicyValidator(config)
        result = validator.validate(_make_payload())
        assert result.violations == []
        assert not result.has_errors
        assert not result.has_warnings

    def test_has_errors_property(self) -> None:
        result = PolicyResult(
            violations=[
                PolicyViolation(field="price", message="too low", severity="error"),
                PolicyViolation(
                    field="listing_type_id", message="might be slow", severity="warning"
                ),
            ]
        )
        assert result.has_errors
        assert result.has_warnings


class TestLoadSellerConfig:
    def test_load_seller_config_nested(self, tmp_path: Path) -> None:
        config_file = tmp_path / "seller.yaml"
        config_file.write_text(
            """
seller:
  listing:
    allowed_types: ["gold_special"]
    default_type: "gold_special"
  pricing:
    min_price: 10.0
    max_price: 5000.0
""",
            encoding="utf-8",
        )
        config = load_seller_config(config_file)
        assert config.listing.allowed_types == ["gold_special"]
        assert config.pricing.min_price == 10.0
