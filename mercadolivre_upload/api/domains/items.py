"""Item and moderation endpoint helpers for MLApiClient."""

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from mercadolivre_upload.infrastructure.http import NON_IDEMPOTENT, SAFE_RETRY

if TYPE_CHECKING:
    from mercadolivre_upload.api.client import MLApiClient

_EXISTING_UP_SELLING_CONDITION_MODE = "existing_user_product_selling_condition"
_EXISTING_UP_MODE_FIELDS = ("target", "execution_mode")
_COMPLETE_UP_ITEM_FIELDS = {
    "family_name",
    "pictures",
    "attributes",
    "available_quantity",
    "title",
    "condition",
    "variations",
    "user_product",
    "model",
    "items",
    "payload",
}


def _is_existing_user_product_selling_condition_request(item: dict[str, Any]) -> bool:
    return any(
        item.get(field) == _EXISTING_UP_SELLING_CONDITION_MODE for field in _EXISTING_UP_MODE_FIELDS
    )


def _require_existing_user_product_selling_condition_request(item: dict[str, Any]) -> None:
    user_product_id = item.get("user_product_id")
    if not isinstance(user_product_id, str) or not user_product_id.strip():
        raise ValueError(
            "existing_user_product_selling_condition mode requires non-empty 'user_product_id'."
        )
    complete_fields = sorted(field for field in _COMPLETE_UP_ITEM_FIELDS if field in item)
    if complete_fields:
        raise ValueError(
            "existing_user_product_selling_condition mode requires a reduced request body; "
            f"unexpected fields: {complete_fields}"
        )


def validate_item(client: "MLApiClient", item: dict[str, Any]) -> dict[str, Any]:
    """Validate item before publishing."""
    return client.post("/items/validate", json=item, policy=SAFE_RETRY)


def validate_user_product_item(client: "MLApiClient", item: dict[str, Any]) -> dict[str, Any]:
    """Validate every user-products payload through the non-mutating item endpoint."""
    if _is_existing_user_product_selling_condition_request(item):
        _require_existing_user_product_selling_condition_request(item)
    return client.validate_item(dict(item))


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
    client.last_user_product_sanitization = None
    client.last_publish_endpoint = "/items"
    return client.post("/items", json=item)


def get_user_product(client: "MLApiClient", user_product_id: str) -> dict[str, Any]:
    """Fetch user-product metadata (including family_id) after publish."""
    if not isinstance(user_product_id, str) or not user_product_id.strip():
        raise ValueError("user_product_id cannot be empty")
    return client.get(f"/user-products/{user_product_id.strip()}")


def search_user_items(
    client: "MLApiClient",
    seller_id: str,
    *,
    status: str,
    limit: int,
    offset: int | None = None,
    search_type: str | None = None,
    scroll_id: str | None = None,
) -> dict[str, Any]:
    """Search current seller item IDs by status."""
    if not isinstance(seller_id, str) or not seller_id.strip():
        raise ValueError("seller_id cannot be empty")
    params: dict[str, Any] = {"status": status, "limit": limit}
    if offset is not None:
        params["offset"] = offset
    if search_type:
        params["search_type"] = search_type
    if scroll_id:
        params["scroll_id"] = scroll_id
    return client.get(
        f"/users/{seller_id.strip()}/items/search",
        params=params,
    )


def get_items_batch(client: "MLApiClient", item_ids: list[str]) -> list[Any]:
    """Fetch item details in a single /items?ids=... request."""
    normalized_ids = [item_id.strip() for item_id in item_ids if item_id.strip()]
    if not normalized_ids:
        return []
    result = client.get_json("/items", params={"ids": ",".join(normalized_ids)})
    if isinstance(result, list):
        return result
    return []


def create_user_product_item(client: "MLApiClient", item: dict[str, Any]) -> dict[str, Any]:
    """Create user-products payload with MLB-safe endpoint routing."""
    if not _is_existing_user_product_selling_condition_request(item):
        client.last_user_product_sanitization = None
        return client.create_item(dict(item))

    _require_existing_user_product_selling_condition_request(item)
    payload = client._sanitize_user_product_item_payload(item)
    user_product_id = payload.pop("user_product_id", None)
    sales_condition_payload, sanitization_metadata = (
        client._build_user_product_sales_condition_payload(payload)
    )
    client.last_user_product_sanitization = sanitization_metadata
    client.last_publish_endpoint = "/user-products/{user_product_id}/items"
    return client.post(
        f"/user-products/{user_product_id.strip()}/items",
        json=sales_condition_payload,
    )


def create_item_description(
    client: "MLApiClient",
    item_id: str,
    plain_text: str,
    *,
    validate_item_id_fn: Callable[[str | None], None],
) -> dict[str, Any]:
    """Create or update item description."""
    validate_item_id_fn(item_id)
    return client.post(
        f"/items/{item_id}/description",
        json={"plain_text": plain_text},
        policy=NON_IDEMPOTENT,
    )


def update_item(client: "MLApiClient", item_id: str, data: dict[str, Any]) -> dict[str, Any]:
    """Update an existing item via PUT (e.g. change status to paused/active)."""
    return client.put(f"/items/{item_id}", json=data, policy=NON_IDEMPOTENT)
