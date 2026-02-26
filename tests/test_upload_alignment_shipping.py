"""Tests for upload alignment shipping mode behavior."""

from __future__ import annotations

from mercadolivre_upload.domain.shipping.resolver import ShippingResolver
from tests.support.upload_alignment import _FakeShippingProvider


def test_shipping_resolver_uses_shipping_preferences_modes() -> None:
    provider = _FakeShippingProvider(
        user_info={"id": 123, "shipping_modes": ["me1", "me2"]},
        shipping_preferences={"modes": ["me2", "custom"]},
    )
    resolver = ShippingResolver(
        provider,
        config={"mode_priority": ["me1", "me2"], "default_mode": "not_specified"},
    )

    assert resolver.get_best_shipping_mode() == "me2"
    assert provider.requested_user_id == "123"


def test_shipping_resolver_falls_back_to_users_me_modes_if_preferences_fail() -> None:
    provider = _FakeShippingProvider(
        user_info={"id": 321, "shipping_modes": ["me2"]},
        raise_preferences=True,
    )
    resolver = ShippingResolver(
        provider,
        config={"mode_priority": ["me1", "me2"], "default_mode": "not_specified"},
    )

    assert resolver.get_best_shipping_mode() == "me2"


def test_shipping_resolver_returns_default_when_no_modes_available() -> None:
    provider = _FakeShippingProvider(user_info={"id": 123}, shipping_preferences={"modes": []})
    resolver = ShippingResolver(
        provider,
        config={"mode_priority": ["me1", "me2"], "default_mode": "not_specified"},
    )

    assert resolver.get_best_shipping_mode() == "not_specified"


def test_shipping_resolver_selection_reads_modes_and_logistic_type_from_logistics() -> None:
    provider = _FakeShippingProvider(
        user_info={"id": 123, "shipping_modes": []},
        shipping_preferences={
            "modes": [],
            "logistics": [
                {
                    "mode": "me2",
                    "types": [{"type": "drop_off"}, {"type": "fulfillment", "default": True}],
                },
                {"mode": "me1", "types": [{"type": "cross_docking", "default": True}]},
            ],
        },
    )
    resolver = ShippingResolver(
        provider,
        config={"mode_priority": ["me2", "me1"], "default_mode": "not_specified"},
    )

    selection = resolver.get_best_shipping_selection()

    assert selection["mode"] == "me2"
    assert selection["logistic_type"] == "fulfillment"
    assert provider.requested_user_id == "123"


def test_shipping_resolver_selection_uses_first_logistic_type_when_no_default() -> None:
    provider = _FakeShippingProvider(
        user_info={"id": 456},
        shipping_preferences={
            "modes": [],
            "logistics": [{"mode": "me1", "types": [{"type": "xd_drop_off"}, {"type": "self"}]}],
        },
    )
    resolver = ShippingResolver(
        provider,
        config={"mode_priority": ["me1", "me2"], "default_mode": "not_specified"},
    )

    selection = resolver.get_best_shipping_selection()

    assert selection["mode"] == "me1"
    assert selection["logistic_type"] == "xd_drop_off"


def test_shipping_resolver_selection_exposes_runtime_policy_hints() -> None:
    provider = _FakeShippingProvider(
        user_info={"id": 789},
        shipping_preferences={
            "modes": [],
            "logistics": [
                {
                    "mode": "me2",
                    "types": [{"type": "drop_off", "default": True}],
                    "tags": ["mandatory_free_shipping", "cross_border"],
                    "free_shipping": {"required": True},
                    "constraints": {"carrier": "me2", "dimensions": "required"},
                }
            ],
        },
    )
    resolver = ShippingResolver(
        provider,
        config={"mode_priority": ["me2", "me1"], "default_mode": "not_specified"},
    )

    selection = resolver.get_best_shipping_selection()

    assert selection["mode"] == "me2"
    assert selection["logistic_type"] == "drop_off"
    assert selection["tags"] == ["mandatory_free_shipping", "cross_border"]
    assert selection["free_shipping"] is True
    assert selection["constraints"] == {"carrier": "me2", "dimensions": "required"}
