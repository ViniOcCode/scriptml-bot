"""Tests for publish_inactive flag on PublishProductUseCase."""

from __future__ import annotations

from typing import Any

from mercadolivre_upload.application.publish_product import PublishProductUseCase
from tests.support.upload_alignment import (
    _build_product,
    _FakeCategoryResolver,
    _FakeImageUploader,
    _FakePublisher,
    _FixedShippingResolver,
)

_MINIMAL_CONFIG: dict[str, Any] = {
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
}


def _make_use_case(
    publisher: _FakePublisher,
    publish_inactive: bool = False,
) -> PublishProductUseCase:
    return PublishProductUseCase(
        category_resolver=_FakeCategoryResolver([]),  # type: ignore[arg-type]
        publisher=publisher,  # type: ignore[arg-type]
        image_uploader=_FakeImageUploader(),  # type: ignore[arg-type]
        shipping_resolver=_FixedShippingResolver("me2"),  # type: ignore[arg-type]
        fiscal_service=None,
        clip_uploader=None,
        config=_MINIMAL_CONFIG,
        dry_run=False,
        min_attribute_score=0,
        enable_feedback=False,
        enable_fiscal_submission=False,
        publish_inactive=publish_inactive,
    )


def test_publish_inactive_flag_stored_on_use_case() -> None:
    """publish_inactive=True is stored as instance attribute."""
    publisher = _FakePublisher(listing_types=[{"id": "gold_special"}], sale_terms=[])
    use_case = _make_use_case(publisher, publish_inactive=True)
    assert use_case.publish_inactive is True


def test_publish_inactive_default_is_false() -> None:
    """publish_inactive defaults to False."""
    publisher = _FakePublisher(listing_types=[{"id": "gold_special"}], sale_terms=[])
    use_case = _make_use_case(publisher, publish_inactive=False)
    assert use_case.publish_inactive is False


def test_publish_inactive_true_calls_update_item_after_create() -> None:
    """When publish_inactive=True, update_item is called with status=paused after publish."""
    publisher = _FakePublisher(listing_types=[{"id": "gold_special"}], sale_terms=[])
    use_case = _make_use_case(publisher, publish_inactive=True)

    result = use_case._publish_one(_build_product({}), "MLB123")

    assert result is True
    assert len(publisher.updated_items) == 1
    item_id, data = publisher.updated_items[0]
    assert item_id == "MLB1234567890"
    assert data == {"status": "paused"}


def test_publish_inactive_false_does_not_call_update_item() -> None:
    """When publish_inactive=False (default), update_item is never called."""
    publisher = _FakePublisher(listing_types=[{"id": "gold_special"}], sale_terms=[])
    use_case = _make_use_case(publisher, publish_inactive=False)

    result = use_case._publish_one(_build_product({}), "MLB123")

    assert result is True
    assert publisher.updated_items == []


def test_publish_inactive_update_failure_does_not_fail_item() -> None:
    """If update_item raises, the item is still counted as published (warn-only)."""

    class _FailingUpdatePublisher(_FakePublisher):
        def update_item(self, item_id: str, data: dict[str, Any]) -> dict[str, Any]:
            raise RuntimeError("API update failed")

    publisher = _FailingUpdatePublisher(listing_types=[{"id": "gold_special"}], sale_terms=[])
    use_case = _make_use_case(publisher, publish_inactive=True)

    result = use_case._publish_one(_build_product({}), "MLB123")

    # Item was published (create succeeded), even though pause failed
    assert result is True
    assert use_case.published == 1
    assert use_case.failed == 0
