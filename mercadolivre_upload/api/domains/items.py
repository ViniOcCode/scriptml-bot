"""Item and moderation endpoint helpers for MLApiClient."""

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mercadolivre_upload.api.client import MLApiClient


def validate_item(client: "MLApiClient", item: dict[str, Any]) -> dict[str, Any]:
    """Validate item before publishing."""
    return client.post("/items/validate", json=item)


def validate_user_product_item(client: "MLApiClient", item: dict[str, Any]) -> dict[str, Any]:
    """Validate user-products payload using current MVP endpoint routing."""
    payload = client._sanitize_user_product_item_payload(item)
    user_product_id = payload.pop("user_product_id", None)
    if isinstance(user_product_id, str) and user_product_id.strip():
        return {}
    return client.validate_item(payload)


def diagnose_picture(
    client: "MLApiClient",
    *,
    picture_url: str | None = None,
    picture_id: str | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run image diagnostics preflight for a picture."""
    if bool(picture_url) == bool(picture_id):
        raise ValueError("Provide exactly one of picture_url or picture_id")

    payload: dict[str, Any] = {}
    if picture_id:
        payload["picture_id"] = picture_id
    elif picture_url:
        payload["picture_url"] = picture_url

    if isinstance(context, dict) and context:
        payload["context"] = context

    return client.post("/moderations/pictures/diagnostic", json=payload)


def create_item(client: "MLApiClient", item: dict[str, Any]) -> dict[str, Any]:
    """Create/publish an item."""
    return client.post("/items", json=item)


def create_user_product_item(client: "MLApiClient", item: dict[str, Any]) -> dict[str, Any]:
    """Create user-products payload with MLB-safe endpoint routing."""
    payload = client._sanitize_user_product_item_payload(item)
    user_product_id = payload.pop("user_product_id", None)
    if isinstance(user_product_id, str) and user_product_id.strip():
        sales_condition_payload = client._build_user_product_sales_condition_payload(payload)
        return client.post(
            f"/user-products/{user_product_id.strip()}/items",
            json=sales_condition_payload,
        )
    return client.create_item(payload)


def create_item_description(
    client: "MLApiClient",
    item_id: str,
    plain_text: str,
    *,
    validate_item_id_fn: Callable[[str | None], None],
) -> dict[str, Any]:
    """Create or update item description."""
    validate_item_id_fn(item_id)
    return client.post(f"/items/{item_id}/description", json={"plain_text": plain_text})


def update_item(client: "MLApiClient", item_id: str, data: dict[str, Any]) -> dict[str, Any]:
    """Update an existing item via PUT (e.g. change status to paused/active)."""
    return client.put(f"/items/{item_id}", json=data)
