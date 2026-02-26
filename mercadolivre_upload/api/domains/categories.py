"""Category, site, and listing endpoint helpers for MLApiClient."""

from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from mercadolivre_upload.api.client import MLApiClient


def get_sites(client: "MLApiClient") -> list[dict[str, Any]]:
    """Get available sites."""
    return cast(list[dict[str, Any]], client.get("/sites"))


def get_site_categories(client: "MLApiClient", site_id: str = "MLB") -> list[dict[str, Any]]:
    """Get categories for a site."""
    return cast(list[dict[str, Any]], client.get(f"/sites/{site_id}/categories"))


def predict_category(
    client: "MLApiClient",
    title: str,
    site_id: str = "MLB",
    limit: int | None = None,
    *,
    default_limit: int,
) -> list[dict[str, Any]]:
    """Predict category based on product title."""
    if limit is None:
        limit = default_limit
    endpoint = f"/sites/{site_id}/domain_discovery/search"
    params = {"q": title, "limit": limit}
    return cast(list[dict[str, Any]], client.get(endpoint, params=params))


def get_category(client: "MLApiClient", category_id: str) -> dict[str, Any]:
    """Get category details."""
    return client.get(f"/categories/{category_id}")


def get_category_attributes(client: "MLApiClient", category_id: str) -> list[dict[str, Any]]:
    """Get category attributes."""
    return cast(list[dict[str, Any]], client.get(f"/categories/{category_id}/attributes"))


def get_category_conditional_attributes(
    client: "MLApiClient",
    category_id: str,
    item_context: dict[str, Any],
) -> list[dict[str, Any]]:
    """Get conditional attributes for a category."""
    endpoint = f"/categories/{category_id}/attributes/conditional"
    response = client.post(endpoint, json=item_context)
    if isinstance(response, dict):
        required_attributes = response.get("required_attributes", [])
        if isinstance(required_attributes, list):
            return cast(list[dict[str, Any]], required_attributes)
        return []
    if isinstance(response, list):
        return cast(list[dict[str, Any]], response)
    return []


def get_category_sale_terms(client: "MLApiClient", category_id: str) -> list[dict[str, Any]]:
    """Get sale terms metadata for a category."""
    result = client.get(f"/categories/{category_id}/sale_terms")
    if isinstance(result, list):
        return cast(list[dict[str, Any]], result)
    return []


def get_available_listing_types(client: "MLApiClient", category_id: str) -> list[dict[str, Any]]:
    """Get listing types available for current seller in category."""
    user_info = client.get_users_me()
    user_id = user_info.get("id")
    if not user_id:
        return []

    result = client.get(
        f"/users/{user_id}/available_listing_types",
        params={"category_id": category_id},
    )
    if isinstance(result, dict):
        available = result.get("available", [])
        if isinstance(available, list):
            return cast(list[dict[str, Any]], available)
        return []
    if isinstance(result, list):
        return cast(list[dict[str, Any]], result)
    return []


def get_site_listing_types(client: "MLApiClient", site_id: str = "MLB") -> list[dict[str, Any]]:
    """Get listing types available for a site."""
    result = client.get(f"/sites/{site_id}/listing_types")
    if isinstance(result, list):
        return cast(list[dict[str, Any]], result)
    return []


def get_category_technical_specs(client: "MLApiClient", category_id: str) -> dict[str, Any]:
    """Get category technical specs (input structure)."""
    return client.get(f"/categories/{category_id}/technical_specs/input")
