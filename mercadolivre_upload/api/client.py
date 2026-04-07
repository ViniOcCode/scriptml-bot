"""Mercado Livre API client.

Uses ResilientHTTPClient for automatic retry, backoff, jitter and rate limiting.
All HTTP config is read from infrastructure.config.Settings or sensible defaults.
"""

import logging
import re
from typing import Any, cast

from mercadolivre_upload.api.domains import categories as category_endpoints
from mercadolivre_upload.api.domains import fiscal as fiscal_endpoints
from mercadolivre_upload.api.domains import items as item_endpoints
from mercadolivre_upload.api.domains import media as media_endpoints
from mercadolivre_upload.api.exceptions import MLApiError
from mercadolivre_upload.auth import TokenManager
from mercadolivre_upload.infrastructure.http import (
    NON_IDEMPOTENT,
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
        auth_manager: TokenManager | None = None,
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

        # Validation endpoint returns 400 with useful error body — return as dict
        if endpoint.strip("/") == "items/validate" and resp.status_code == 400:
            try:
                return cast(dict[str, Any], resp.json())
            except ValueError as exc:
                logger.warning("Validation endpoint returned non-JSON response: %s", exc)

        # For other 4xx errors, capture the ML API JSON body before raising
        if 400 <= resp.status_code < 500:
            try:
                body = cast(dict[str, Any], resp.json())
            except (ValueError, AttributeError):
                pass  # non-JSON body — fall through to raise_for_status()
            else:
                raise MLApiError(
                    f"{resp.status_code} Client Error",
                    response=resp,
                    response_body=body,
                )

        resp.raise_for_status()
        if resp.status_code == 204:
            return {}
        try:
            return cast(dict[str, Any], resp.json())
        except ValueError:
            logger.warning(
                "POST %s returned a non-JSON success response (status %s); "
                "returning empty payload.",
                endpoint,
                resp.status_code,
            )
            return {}

    def put(
        self,
        endpoint: str,
        json: dict[str, Any] | None = None,
        *,
        policy: RetryPolicy | None = None,
    ) -> dict[str, Any]:
        """PUT request. Idempotent — uses SAFE_RETRY by default."""
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        logger.debug("PUT %s", url)
        resp = self.http.put(
            url,
            headers=self._get_headers(),
            json=json,
            policy=policy,
        )
        resp.raise_for_status()
        if resp.status_code == 204:
            return {}
        try:
            return cast(dict[str, Any], resp.json())
        except ValueError:
            logger.warning(
                "PUT %s returned a non-JSON success response (status %s); "
                "returning empty payload.",
                endpoint,
                resp.status_code,
            )
            return {}

    def get_sites(self) -> list[dict[str, Any]]:
        """Get available sites."""
        return category_endpoints.get_sites(self)

    def get_site_categories(self, site_id: str = "MLB") -> list[dict[str, Any]]:
        """Get categories for a site.

        Args:
            site_id: Site ID (default: MLB for Brazil)

        Returns:
            List of category objects
        """
        return category_endpoints.get_site_categories(self, site_id)

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
        return category_endpoints.predict_category(
            self,
            title,
            site_id,
            limit,
            default_limit=DEFAULT_PREDICTION_LIMIT,
        )

    def get_category(self, category_id: str) -> dict[str, Any]:
        """Get category details."""
        return category_endpoints.get_category(self, category_id)

    def get_category_attributes(self, category_id: str) -> list[dict[str, Any]]:
        """Get category attributes."""
        return category_endpoints.get_category_attributes(self, category_id)

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
        return category_endpoints.get_category_conditional_attributes(
            self,
            category_id,
            item_context,
        )

    def get_category_sale_terms(self, category_id: str) -> list[dict[str, Any]]:
        """Get sale terms metadata for a category."""
        return category_endpoints.get_category_sale_terms(self, category_id)

    def get_available_listing_types(self, category_id: str) -> list[dict[str, Any]]:
        """Get listing types available for current seller in category."""
        return category_endpoints.get_available_listing_types(self, category_id)

    def get_site_listing_types(self, site_id: str = "MLB") -> list[dict[str, Any]]:
        """Get listing types available for a site."""
        return category_endpoints.get_site_listing_types(self, site_id)

    def get_category_technical_specs(self, category_id: str) -> dict[str, Any]:
        """Get category technical specs (input structure)."""
        return category_endpoints.get_category_technical_specs(self, category_id)

    def validate_item(self, item: dict[str, Any]) -> dict[str, Any]:
        """Validate item before publishing.

        Args:
            item: Item data to validate

        Returns:
            Validation result
        """
        return item_endpoints.validate_item(self, item)

    @staticmethod
    def _sanitize_user_product_item_payload(item: dict[str, Any]) -> dict[str, Any]:
        """Strip legacy fields not supported by MLB user-products create contract."""
        payload = dict(item)
        family_name = payload.get("family_name")
        if not isinstance(family_name, str) or not family_name.strip():
            raise ValueError("user-products payload requires non-empty 'family_name'.")
        payload["family_name"] = family_name.strip()
        payload.pop("title", None)
        payload.pop("variations", None)
        payload.pop("user_product", None)
        payload.pop("model", None)
        payload.pop("items", None)
        payload.pop("_meta", None)
        payload.pop("payload", None)
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
        return item_endpoints.validate_user_product_item(self, item)

    def diagnose_picture(
        self,
        *,
        picture_url: str | None = None,
        picture_id: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run image diagnostics preflight for a picture."""
        return item_endpoints.diagnose_picture(
            self,
            picture_url=picture_url,
            picture_id=picture_id,
            context=context,
        )

    def create_item(self, item: dict[str, Any]) -> dict[str, Any]:
        """Create/publish an item.

        Args:
            item: Item data

        Returns:
            Created item data
        """
        return item_endpoints.create_item(self, item)

    def create_user_product_item(self, item: dict[str, Any]) -> dict[str, Any]:
        """Create user-products payload with MLB-safe endpoint routing."""
        return item_endpoints.create_user_product_item(self, item)

    def create_item_description(self, item_id: str, plain_text: str) -> dict[str, Any]:
        """Create or update item description."""
        return item_endpoints.create_item_description(
            self,
            item_id,
            plain_text,
            validate_item_id_fn=validate_item_id,
        )

    def update_item(self, item_id: str, data: dict[str, Any]) -> dict[str, Any]:
        """Update an existing item (e.g. change status to paused/active)."""
        return item_endpoints.update_item(self, item_id, data)

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
        return media_endpoints.upload_image(self, image_path)

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
        return fiscal_endpoints.submit_fiscal_info(
            self,
            item_id,
            fiscal_data,
            validate_item_id_fn=validate_item_id,
        )

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
        return fiscal_endpoints.check_fiscal_data_exists(self, sku)

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
        return fiscal_endpoints.register_fiscal_data(self, fiscal_data)

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
        return fiscal_endpoints.link_fiscal_sku_to_item(
            self,
            sku,
            item_id,
            variation_id,
            validate_item_id_fn=validate_item_id,
        )

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
        return fiscal_endpoints.verify_invoice_readiness(
            self,
            item_id,
            validate_item_id_fn=validate_item_id,
        )

    def upload_clip(
        self,
        item_id: str,
        file_path: str,
        sites: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Upload a video clip for an item (CBT parent ID required)."""
        return media_endpoints.upload_clip(
            self,
            item_id,
            file_path,
            sites,
            validate_clip_item_id_fn=validate_clip_item_id,
        )
