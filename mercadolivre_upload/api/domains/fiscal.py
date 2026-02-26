"""Fiscal endpoint helpers for MLApiClient."""

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import requests

if TYPE_CHECKING:
    from mercadolivre_upload.api.client import MLApiClient


def submit_fiscal_info(
    client: "MLApiClient",
    item_id: str,
    fiscal_data: dict[str, Any],
    *,
    validate_item_id_fn: Callable[[str | None], None],
) -> dict[str, Any]:
    """Submit fiscal information for an item."""
    validate_item_id_fn(item_id)
    endpoint = f"/items/{item_id}/fiscal_info"
    return client.post(endpoint, json=fiscal_data)


def check_fiscal_data_exists(client: "MLApiClient", sku: str) -> tuple[bool, dict[str, Any] | None]:
    """Check if fiscal data exists for a SKU."""
    endpoint = f"/items/fiscal_information/{sku}"
    try:
        response = client.get(endpoint)
        return True, response
    except requests.HTTPError as error:
        if error.response is not None and error.response.status_code == 404:
            return False, None
        raise


def register_fiscal_data(client: "MLApiClient", fiscal_data: dict[str, Any]) -> dict[str, Any]:
    """Register new fiscal data for a product."""
    endpoint = "/items/fiscal_information"
    return client.post(endpoint, json=fiscal_data)


def link_fiscal_sku_to_item(
    client: "MLApiClient",
    sku: str,
    item_id: str,
    variation_id: str | None = None,
    *,
    validate_item_id_fn: Callable[[str | None], None],
) -> dict[str, Any]:
    """Link a fiscal SKU to a published item."""
    validate_item_id_fn(item_id)
    payload: dict[str, Any] = {"sku": sku, "item_id": item_id}
    if variation_id is not None:
        payload["variation_id"] = variation_id
    endpoint = "/items/fiscal_information/items"
    return client.post(endpoint, json=payload)


def verify_invoice_readiness(
    client: "MLApiClient",
    item_id: str,
    *,
    validate_item_id_fn: Callable[[str | None], None],
) -> tuple[bool, dict[str, Any] | None]:
    """Verify if an item is ready for invoice generation."""
    validate_item_id_fn(item_id)
    endpoint = f"/can_invoice/items/{item_id}"
    response = client.get(endpoint)
    is_ready = response.get("status", False) is True
    return is_ready, response
