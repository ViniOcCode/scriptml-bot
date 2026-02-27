"""Publisher capability resolution for publish flow internals."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar, cast

SellerInfoGetter = Callable[[], dict[str, Any]]
ItemFlowCallable = Callable[[dict[str, Any]], dict[str, Any]]
SiteListingTypesGetter = Callable[[str], list[dict[str, Any]]]
TCallable = TypeVar("TCallable", bound=Callable[..., Any])


@dataclass(frozen=True)
class PublisherCapabilities:
    """Runtime-resolved publisher capabilities used by publish internals."""

    seller_info_getters: tuple[tuple[str, SellerInfoGetter], ...]
    validate_user_product_item: ItemFlowCallable | None
    create_user_product_item: ItemFlowCallable | None
    get_site_listing_types: SiteListingTypesGetter | None

    @property
    def user_products_validate_supported(self) -> bool:
        """Whether publisher exposes user-products validation route."""
        return self.validate_user_product_item is not None

    @property
    def user_products_create_supported(self) -> bool:
        """Whether publisher exposes user-products create route."""
        return self.create_user_product_item is not None


def _resolve_method(publisher: Any, method_name: str) -> TCallable | None:
    """Return callable method by name, or None when unavailable."""
    method = getattr(publisher, method_name, None)
    if callable(method):
        return cast(TCallable, method)
    return None


def build_publisher_capabilities(publisher: Any) -> PublisherCapabilities:
    """Build immutable publisher capability snapshot for one use-case instance."""
    seller_info_getters: list[tuple[str, SellerInfoGetter]] = []
    preferred_getter = _resolve_method(publisher, "get_publisher_users_me")
    if preferred_getter is not None:
        seller_info_getters.append(
            ("publisher/get_users_me", cast(SellerInfoGetter, preferred_getter))
        )

    default_getter = _resolve_method(publisher, "get_users_me")
    if default_getter is not None:
        seller_info_getters.append(("users/me", cast(SellerInfoGetter, default_getter)))

    return PublisherCapabilities(
        seller_info_getters=tuple(seller_info_getters),
        validate_user_product_item=cast(
            ItemFlowCallable | None, _resolve_method(publisher, "validate_user_product_item")
        ),
        create_user_product_item=cast(
            ItemFlowCallable | None, _resolve_method(publisher, "create_user_product_item")
        ),
        get_site_listing_types=cast(
            SiteListingTypesGetter | None, _resolve_method(publisher, "get_site_listing_types")
        ),
    )


__all__ = ["PublisherCapabilities", "build_publisher_capabilities"]
