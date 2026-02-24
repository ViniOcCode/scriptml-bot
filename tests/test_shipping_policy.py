"""Tests for shipping policy extraction helpers."""

from mercadolivre_upload.application.shipping_policy import (
    coerce_shipping_bool,
    normalize_seller_tags,
    normalize_shipping_constraints,
    resolve_shipping_policy_settings,
)


def test_resolve_shipping_policy_settings_reads_nested_policy_config() -> None:
    settings = resolve_shipping_policy_settings(
        {
            "shipping": {
                "policy": {
                    "non_blocking_codes": [" shipping.free_shipping.cost_exceeded "],
                    "mandatory_free_shipping_tags": ["MANDATORY_FREE_SHIPPING", " "],
                    "enforce_mandatory_free_shipping": False,
                    "allow_runtime_tag_overrides": False,
                    "allow_runtime_free_shipping_override": False,
                }
            }
        },
        default_mandatory_free_shipping_tags={"mandatory_free_shipping"},
    )

    assert settings.non_blocking_codes == {"shipping.free_shipping.cost_exceeded"}
    assert settings.mandatory_free_shipping_tags == {"mandatory_free_shipping"}
    assert settings.enforce_mandatory_free_shipping is False
    assert settings.allow_runtime_tag_overrides is False
    assert settings.allow_runtime_free_shipping_override is False


def test_resolve_shipping_policy_settings_preserves_defaults_when_config_missing() -> None:
    defaults = {"mandatory_free_shipping", "cross_border"}
    settings = resolve_shipping_policy_settings(
        {},
        default_mandatory_free_shipping_tags=defaults,
    )

    assert settings.non_blocking_codes == set()
    assert settings.mandatory_free_shipping_tags == defaults
    assert settings.enforce_mandatory_free_shipping is True
    assert settings.allow_runtime_tag_overrides is True
    assert settings.allow_runtime_free_shipping_override is True


def test_shipping_policy_helper_normalizers() -> None:
    assert normalize_seller_tags(["A", "a", " "]) == ["a"]
    assert normalize_seller_tags({"A": True, "a": True, "B": False}) == ["a"]
    assert normalize_shipping_constraints({" ": 1, "mode": "me2", 10: "x"}) == {
        "mode": "me2",
        "10": "x",
    }
    assert coerce_shipping_bool("yes") is True
    assert coerce_shipping_bool("no") is False
    assert coerce_shipping_bool("unknown") is None
