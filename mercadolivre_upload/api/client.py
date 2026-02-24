"""Mercado Livre API client.

Uses ResilientHTTPClient for automatic retry, backoff, jitter and rate limiting.
All HTTP config is read from infrastructure.config.Settings or sensible defaults.
"""

import contextlib
import logging
import re
from typing import Any, cast

import requests

from mercadolivre_upload.auth import AuthManager
from mercadolivre_upload.infrastructure.http import (
    NON_IDEMPOTENT,
    UPLOAD_RETRY,
    ResilientHTTPClient,
    RetryPolicy,
    TokenBucketLimiter,
)

logger = logging.getLogger(__name__)

BASE_URL = "https://api.mercadolibre.com"
DEFAULT_PREDICTION_LIMIT = 3

ITEM_ID_PATTERN = re.compile(r"^ML[A-Z]\d+$")


def validate_item_id(item_id: str | None) -> None:
    r"""Validate Mercado Livre item ID format (e.g., MLB1234567890)."""
    if not item_id:
        raise ValueError("item_id cannot be empty or None")
    if not ITEM_ID_PATTERN.match(item_id):
        raise ValueError(
            f"Invalid item_id format: '{item_id}'. "
            "Expected format: ML[site_code][digits] (e.g., MLB1234567890)"
        )


def validate_clip_item_id(item_id: str | None) -> None:
    r"""Validate item ID format for clip upload (CBT parent items)."""
    if not item_id:
        raise ValueError("item_id cannot be empty or None")
    if not re.match(r"^CBT\d+$", item_id):
        raise ValueError(
            f"Invalid clip item_id format: '{item_id}'. "
            "Expected format: CBT[digits] (e.g., CBT1234567890)"
        )


def _build_http_client() -> ResilientHTTPClient:
    """Build HTTP client reading config from Settings when available."""
    try:
        from mercadolivre_upload.infrastructure.config import get_settings

        settings = get_settings()
        limiter = (
            TokenBucketLimiter(
                rate=settings.rate_limit_requests_per_second,
                burst=settings.rate_limit_burst,
            )
            if settings.rate_limit_enabled
            else None
        )
        default_policy = RetryPolicy(
            max_retries=settings.http_max_retries,
            base_delay=settings.http_backoff_factor,
        )
        return ResilientHTTPClient(
            timeout=settings.http_timeout,
            default_policy=default_policy,
            limiter=limiter,
        )
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        logger.debug("Falling back to default HTTP client settings: %s", exc)
        return ResilientHTTPClient()


class MLApiClient:
    """Client for Mercado Livre API."""

    def __init__(  # noqa: D107
        self,
        auth_manager: AuthManager | None = None,
        http_client: ResilientHTTPClient | None = None,
    ):
        self.auth = auth_manager
        self.http = http_client or _build_http_client()
        self.base_url = BASE_URL

    def _get_headers(self, content_type: str = "application/json") -> dict[str, str]:
        headers: dict[str, str] = {}
        if content_type:
            headers["Content-Type"] = content_type
        if self.auth:
            token = self.auth.get_access_token()
            if token:
                headers["Authorization"] = f"Bearer {token}"
        return headers

    def _auth_headers_only(self) -> dict[str, str]:
        """Headers without Content-Type (for multipart uploads)."""
        return self._get_headers(content_type="")

    def get(self, endpoint: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """GET request with automatic retry on transient errors."""
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        logger.debug("GET %s", url)
        resp = self.http.get(url, headers=self._get_headers(), params=params)
        resp.raise_for_status()
        return cast(dict[str, Any], resp.json())

    def post(
        self,
        endpoint: str,
        data: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        *,
        policy: RetryPolicy | None = None,
    ) -> dict[str, Any]:
        """POST request. Uses NON_IDEMPOTENT policy by default for safety."""
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        logger.debug("POST %s", url)
        resp = self.http.post(
            url,
            headers=self._get_headers(),
            data=data,
            json=json,
            policy=policy or NON_IDEMPOTENT,
        )

        # Validation endpoint returns 400 with useful error body
        if endpoint.strip("/") == "items/validate" and resp.status_code == 400:
            try:
                return cast(dict[str, Any], resp.json())
            except ValueError as exc:
                logger.warning("Validation endpoint returned non-JSON response: %s", exc)

        resp.raise_for_status()
        return cast(dict[str, Any], resp.json())

    def get_sites(self) -> list[dict[str, Any]]:
        """Get available sites."""
        return cast(list[dict[str, Any]], self.get("/sites"))

    def get_site_categories(self, site_id: str = "MLB") -> list[dict[str, Any]]:
        """Get categories for a site.

        Args:
            site_id: Site ID (default: MLB for Brazil)

        Returns:
            List of category objects
        """
        return cast(list[dict[str, Any]], self.get(f"/sites/{site_id}/categories"))

    def predict_category(
        self, title: str, site_id: str = "MLB", limit: int | None = None
    ) -> list[dict[str, Any]]:
        """Predict category based on product title.

        Uses ML domain discovery to predict the best category for a title.

        Args:
            title: Product title
            site_id: Site ID (default: MLB for Brazil)
            limit: Maximum number of predictions (default from client settings)

        Returns:
            List of predicted categories with confidence scores
        """
        if limit is None:
            limit = DEFAULT_PREDICTION_LIMIT
        endpoint = f"/sites/{site_id}/domain_discovery/search"
        params = {"q": title, "limit": limit}
        return cast(list[dict[str, Any]], self.get(endpoint, params=params))

    def get_category(self, category_id: str) -> dict[str, Any]:
        """Get category details."""
        return self.get(f"/categories/{category_id}")

    def get_category_attributes(self, category_id: str) -> list[dict[str, Any]]:
        """Get category attributes."""
        return cast(list[dict[str, Any]], self.get(f"/categories/{category_id}/attributes"))

    def get_category_conditional_attributes(
        self, category_id: str, item_context: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Get conditional attributes for a category.

        Args:
            category_id: Category ID
            item_context: Full item context payload used by ML conditional checks

        Returns:
            List of conditional attributes
        """
        endpoint = f"/categories/{category_id}/attributes/conditional"
        response = self.post(endpoint, json=item_context)
        if isinstance(response, dict):
            required_attributes = response.get("required_attributes", [])
            if isinstance(required_attributes, list):
                return cast(list[dict[str, Any]], required_attributes)
            return []
        if isinstance(response, list):
            return cast(list[dict[str, Any]], response)
        return []

    def get_category_sale_terms(self, category_id: str) -> list[dict[str, Any]]:
        """Get sale terms metadata for a category."""
        result = self.get(f"/categories/{category_id}/sale_terms")
        if isinstance(result, list):
            return cast(list[dict[str, Any]], result)
        return []

    def get_available_listing_types(self, category_id: str) -> list[dict[str, Any]]:
        """Get listing types available for current seller in category."""
        user_info = self.get_users_me()
        user_id = user_info.get("id")
        if not user_id:
            return []

        result = self.get(
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

    def get_category_technical_specs(self, category_id: str) -> dict[str, Any]:
        """Get category technical specs (input structure)."""
        return self.get(f"/categories/{category_id}/technical_specs/input")

    def validate_item(self, item: dict[str, Any]) -> dict[str, Any]:
        """Validate item before publishing.

        Args:
            item: Item data to validate

        Returns:
            Validation result
        """
        return self.post("/items/validate", json=item)

    @staticmethod
    def _sanitize_user_product_item_payload(item: dict[str, Any]) -> dict[str, Any]:
        """Strip legacy fields not supported by MLB user-products create contract."""
        payload = dict(item)
        family_name = payload.get("family_name")
        if not isinstance(family_name, str) or not family_name.strip():
            title = payload.get("title")
            if isinstance(title, str) and title.strip():
                payload["family_name"] = title.strip()
        payload.pop("title", None)
        payload.pop("variations", None)
        payload.pop("user_product", None)
        return payload

    @staticmethod
    def _build_user_product_sales_condition_payload(
        item: dict[str, Any],
    ) -> dict[str, Any]:
        """Keep only fields accepted by /user-products/{id}/items."""
        allowed_fields = {
            "price",
            "category_id",
            "currency_id",
            "buying_mode",
            "listing_type_id",
            "shipping",
            "channels",
            "tags",
            "sale_terms",
            "catalog_listing",
            "catalog_product_id",
            "official_store_id",
        }
        return {field: value for field, value in item.items() if field in allowed_fields}

    def validate_user_product_item(self, item: dict[str, Any]) -> dict[str, Any]:
        """Validate user-products payload using current MVP endpoint routing."""
        payload = self._sanitize_user_product_item_payload(item)
        payload.pop("user_product_id", None)
        return self.validate_item(payload)

    def diagnose_picture(
        self,
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

        return self.post("/moderations/pictures/diagnostic", json=payload)

    def create_item(self, item: dict[str, Any]) -> dict[str, Any]:
        """Create/publish an item.

        Args:
            item: Item data

        Returns:
            Created item data
        """
        return self.post("/items", json=item)

    def create_user_product_item(self, item: dict[str, Any]) -> dict[str, Any]:
        """Create user-products payload with MLB-safe endpoint routing."""
        payload = self._sanitize_user_product_item_payload(item)
        user_product_id = payload.pop("user_product_id", None)
        if isinstance(user_product_id, str) and user_product_id.strip():
            sales_condition_payload = self._build_user_product_sales_condition_payload(payload)
            return self.post(
                f"/user-products/{user_product_id.strip()}/items",
                json=sales_condition_payload,
            )
        return self.create_item(payload)

    def create_item_description(self, item_id: str, plain_text: str) -> dict[str, Any]:
        """Create or update item description."""
        validate_item_id(item_id)
        return self.post(f"/items/{item_id}/description", json={"plain_text": plain_text})

    def get_users_me(self) -> dict[str, Any]:
        """Get current authenticated user info.

        Returns:
            User data including shipping modes
        """
        return self.get("/users/me")

    def get_user_shipping_preferences(self, user_id: str) -> dict[str, Any]:
        """Get shipping preferences for a specific seller."""
        return self.get(f"/users/{user_id}/shipping_preferences")

    def upload_image(self, image_path: str) -> dict[str, Any]:
        """Upload an image with retry on transient errors."""
        from pathlib import Path

        path = Path(image_path)
        with open(path, "rb") as f:
            files = {"file": (path.name, f, "image/jpeg")}
            url = f"{self.base_url}/pictures/items/upload"
            resp = self.http.post(
                url,
                headers=self._auth_headers_only(),
                files=files,
                policy=UPLOAD_RETRY,
                timeout=60,
            )
            resp.raise_for_status()

        data = resp.json()

        # Normalize response: extract top-level url from variations if needed
        if isinstance(data, dict):
            top_url = data.get("secure_url") or data.get("url")
            if not top_url:
                variations = data.get("variations", [])
                if isinstance(variations, list) and variations:
                    first_var = variations[0]
                    if isinstance(first_var, dict):
                        top_url = first_var.get("secure_url") or first_var.get("url")
            if top_url and "url" not in data:
                data["url"] = top_url
            if top_url and "secure_url" not in data:
                data["secure_url"] = top_url

        return cast(dict[str, Any], data)

    def submit_fiscal_info(self, item_id: str, fiscal_data: dict[str, Any]) -> dict[str, Any]:
        """Submit fiscal information for an item.

        Args:
            item_id: Mercado Livre item ID (e.g., MLB1234567890)
            fiscal_data: Fiscal data payload following ML API format

        Returns:
            API response

        Raises:
            requests.HTTPError: On API error
        """
        validate_item_id(item_id)
        endpoint = f"/items/{item_id}/fiscal_info"
        return self.post(endpoint, json=fiscal_data)

    def check_fiscal_data_exists(self, sku: str) -> tuple[bool, dict[str, Any] | None]:
        """Check if fiscal data exists for a SKU.

        Args:
            sku: Product SKU

        Returns:
            Tuple of (exists, response_data)
            - exists: True if fiscal data exists (200), False if not (404)
            - response_data: API response if exists, None otherwise

        Raises:
            requests.HTTPError: For non-404 errors
        """
        endpoint = f"/items/fiscal_information/{sku}"
        try:
            response = self.get(endpoint)
            return True, response
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 404:
                return False, None
            raise

    def register_fiscal_data(self, fiscal_data: dict[str, Any]) -> dict[str, Any]:
        """Register new fiscal data for a product.

        Args:
            fiscal_data: Fiscal data payload with sku, title, type, measurement_unit,
                        cost, and tax_information fields

        Returns:
            API response

        Raises:
            requests.HTTPError: On API error
        """
        endpoint = "/items/fiscal_information"
        return self.post(endpoint, json=fiscal_data)

    def link_fiscal_sku_to_item(
        self,
        sku: str,
        item_id: str,
        variation_id: str | None = None,
    ) -> dict[str, Any]:
        """Link a fiscal SKU to a published item.

        Args:
            sku: Registered fiscal SKU
            item_id: Mercado Livre item ID (e.g., MLB1234567890)
            variation_id: Optional variation ID

        Returns:
            API response
        """
        validate_item_id(item_id)
        payload: dict[str, Any] = {"sku": sku, "item_id": item_id}
        if variation_id is not None:
            payload["variation_id"] = variation_id
        endpoint = "/items/fiscal_information/items"
        return self.post(endpoint, json=payload)

    def verify_invoice_readiness(self, item_id: str) -> tuple[bool, dict[str, Any] | None]:
        """Verify if an item is ready for invoice generation.

        Args:
            item_id: Mercado Livre item ID (e.g., MLB1234567890)

        Returns:
            Tuple of (is_ready, response_data)
            - is_ready: True if status is true, False otherwise
            - response_data: Full API response

        Raises:
            requests.HTTPError: On API error
        """
        validate_item_id(item_id)
        endpoint = f"/can_invoice/items/{item_id}"
        response = self.get(endpoint)
        is_ready = response.get("status", False) is True
        return is_ready, response

    def upload_clip(
        self,
        item_id: str,
        file_path: str,
        sites: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Upload a video clip for an item (CBT parent ID required)."""
        import mimetypes
        from pathlib import Path

        path = Path(file_path)
        validate_clip_item_id(item_id)

        mime_type, _ = mimetypes.guess_type(str(path))
        if not mime_type:
            mime_type = "video/mp4"

        with open(path, "rb") as f:
            files = {"file": (path.name, f, mime_type)}
            data: dict[str, Any] = {}
            if sites is not None and sites:
                import json as json_mod

                data["sites"] = json_mod.dumps(sites)

            url = f"{self.base_url}/marketplace/items/{item_id}/clips/upload"

            try:
                resp = self.http.post(
                    url,
                    headers=self._auth_headers_only(),
                    files=files,
                    data=data,
                    policy=UPLOAD_RETRY,
                    timeout=120,
                )
                resp.raise_for_status()
            except requests.RequestException as e:
                error_resp = getattr(e, "response", None)
                status_code = getattr(error_resp, "status_code", "unknown")
                error_body: dict[str, Any] = {}
                if error_resp is not None:
                    with contextlib.suppress(ValueError):
                        error_body = error_resp.json()
                logger.error(
                    "Clip upload failed for %s: [%s] %s: %s",
                    item_id,
                    status_code,
                    error_body.get("error_status", ""),
                    error_body.get("message", ""),
                )
                raise

        return cast(dict[str, Any], resp.json())
