"""Mercado Livre API client."""

import logging
import re

import requests

from mercadolivre_upload.auth import AuthManager

logger = logging.getLogger(__name__)

BASE_URL = "https://api.mercadolibre.com"

# Item ID validation pattern (e.g., MLB1234567890)
ITEM_ID_PATTERN = re.compile(r"^ML[A-Z]\d+$")


def validate_item_id(item_id: str | None) -> None:
    r"""Validate Mercado Livre item ID format (e.g., MLB1234567890).

    Raises:
        ValueError: If item_id is empty or not in format ML[A-Z]\d+
    """
    if not item_id:
        raise ValueError("item_id cannot be empty or None")
    if not ITEM_ID_PATTERN.match(item_id):
        # Keep message lines short to satisfy linters
        raise ValueError(
            "Invalid item_id format: "
            f"'{item_id}'. Expected format: ML[site_code][digits] "
            "(e.g., MLB1234567890)"
        )


def validate_clip_item_id(item_id: str | None) -> None:
    r"""Validate item ID format for clip upload (CBT parent items).

    Raises:
        ValueError: If item_id is empty or not in format CBT\d+
    """
    if not item_id:
        raise ValueError("item_id cannot be empty or None")
    if not re.match(r"^CBT\d+$", item_id):
        raise ValueError(
            "Invalid clip item_id format: "
            f"'{item_id}'. Expected format: CBT[digits] "
            "(e.g., CBT1234567890)"
        )


class MLApiClient:
    """Client for Mercado Livre API."""

    def __init__(self, auth_manager: AuthManager | None = None):
        """Initialize API client.

        Args:
            auth_manager: Optional auth manager for token handling.
        """
        self.auth = auth_manager
        self.session = requests.Session()
        self.base_url = BASE_URL

    def _get_headers(self) -> dict:
        """Get request headers with auth if available."""
        headers = {"Content-Type": "application/json"}

        if self.auth:
            token = self.auth.get_access_token()
            if token:
                headers["Authorization"] = f"Bearer {token}"

        return headers

    def get(self, endpoint: str, params: dict | None = None) -> dict:
        """Make GET request to API.

        Args:
            endpoint: API endpoint (without base URL)
            params: Optional query parameters

        Returns:
            JSON response

        Raises:
            requests.HTTPError: On API error
        """
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        headers = self._get_headers()

        logger.debug(f"GET {url}")
        response = self.session.get(url, headers=headers, params=params, timeout=30)
        response.raise_for_status()

        return response.json()

    def post(self, endpoint: str, data: dict | None = None, json: dict | None = None) -> dict:
        """Make POST request to API.

        Args:
            endpoint: API endpoint (without base URL)
            data: Optional form data
            json: Optional JSON data

        Returns:
            JSON response

        Raises:
            requests.HTTPError: On API error
        """
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        headers = self._get_headers()

        logger.debug(f"POST {url}")
        response = self.session.post(url, headers=headers, data=data, json=json, timeout=30)

        # Special handling for validation endpoint - return error response
        # so caller can distinguish warnings from actual errors
        if endpoint.strip("/") == "items/validate" and response.status_code == 400:
            try:
                return response.json()
            except Exception:
                pass

        response.raise_for_status()

        return response.json()

    def get_sites(self) -> list[dict]:
        """Get available sites."""
        return self.get("/sites")

    def get_site_categories(self, site_id: str = "MLB") -> list[dict]:
        """Get categories for a site.

        Args:
            site_id: Site ID (default: MLB for Brazil)

        Returns:
            List of category objects
        """
        return self.get(f"/sites/{site_id}/categories")

    def predict_category(self, title: str, site_id: str = "MLB") -> list[dict]:
        """Predict category based on product title.

        Uses ML domain discovery to predict the best category for a title.

        Args:
            title: Product title
            site_id: Site ID (default: MLB for Brazil)

        Returns:
            List of predicted categories with confidence scores
        """
        endpoint = f"/sites/{site_id}/domain_discovery/search"
        return self.get(endpoint, params={"q": title})

    def get_category(self, category_id: str) -> dict:
        """Get category details."""
        return self.get(f"/categories/{category_id}")

    def get_category_attributes(self, category_id: str) -> list[dict]:
        """Get category attributes."""
        return self.get(f"/categories/{category_id}/attributes")

    def get_category_conditional_attributes(
        self, category_id: str, current_attributes: dict
    ) -> list[dict]:
        """Get conditional attributes for a category.

        Args:
            category_id: Category ID
            current_attributes: Current attribute values to check conditions against

        Returns:
            List of conditional attributes
        """
        endpoint = f"/categories/{category_id}/attributes/conditional"
        return self.post(endpoint, json=current_attributes)

    def get_category_technical_specs(self, category_id: str) -> dict:
        """Get category technical specs (input structure)."""
        return self.get(f"/categories/{category_id}/technical_specs/input")

    def validate_item(self, item: dict) -> dict:
        """Validate item before publishing.

        Args:
            item: Item data to validate

        Returns:
            Validation result
        """
        return self.post("/items/validate", json=item)

    def create_item(self, item: dict) -> dict:
        """Create/publish an item.

        Args:
            item: Item data

        Returns:
            Created item data
        """
        return self.post("/items", json=item)

    def get_users_me(self) -> dict:
        """Get current authenticated user info.

        Returns:
            User data including shipping modes
        """
        return self.get("/users/me")

    def upload_image(self, image_path: str) -> dict:
        """Upload an image.

        Args:
            image_path: Path to image file

        Returns:
            Upload result with picture ID and URLs
        """
        from pathlib import Path

        path = Path(image_path)
        with open(path, "rb") as f:
            files = {"file": (path.name, f, "image/jpeg")}
            headers = {}
            if self.auth:
                token = self.auth.get_access_token()
                if token:
                    headers["Authorization"] = f"Bearer {token}"

            url = f"{self.base_url}/pictures/items/upload"
            response = self.session.post(url, headers=headers, files=files, timeout=60)
            response.raise_for_status()

        data = response.json()

        # Normalize response: extract top-level url from variations if needed
        if isinstance(data, dict):
            # Check if url/secure_url exists at top level
            top_url = data.get("secure_url") or data.get("url")

            # If not, extract from first variation
            if not top_url:
                variations = data.get("variations", [])
                if isinstance(variations, list) and variations:
                    first_var = variations[0]
                    if isinstance(first_var, dict):
                        top_url = first_var.get("secure_url") or first_var.get("url")

            # Ensure there's always a url field for convenience
            if top_url and "url" not in data:
                data["url"] = top_url
            if top_url and "secure_url" not in data:
                data["secure_url"] = top_url

        return data

    def submit_fiscal_info(self, item_id: str, fiscal_data: dict) -> dict:
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

    def check_fiscal_data_exists(self, sku: str) -> tuple[bool, dict | None]:
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

    def register_fiscal_data(self, fiscal_data: dict) -> dict:
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

    def verify_invoice_readiness(self, item_id: str) -> tuple[bool, dict | None]:
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
        sites: list[dict] | None = None,
    ) -> dict:
        """Upload a video clip for an item.

        Args:
            item_id: CBT parent item ID (e.g., CBT1234567890) - NOT marketplace-specific IDs
            file_path: Path to video file (mp4, mov, mpeg, avi)
            sites: Optional list of sites for clip visibility

        Returns:
            Upload result with clip UUID

        Raises:
            requests.HTTPError: On API error with detailed message
        """
        import mimetypes
        from pathlib import Path

        path = Path(file_path)
        validate_clip_item_id(item_id)

        # Determine MIME type
        mime_type, _ = mimetypes.guess_type(str(path))
        if not mime_type:
            mime_type = "video/mp4"  # Default fallback

        with open(path, "rb") as f:
            files = {"file": (path.name, f, mime_type)}
            data = {}
            if sites is not None:
                import json

                if sites:
                    data["sites"] = json.dumps(sites)
                    logger.debug(f"Clip upload targeting specific sites: {sites}")
                else:
                    # empty list => omit field to target all sites
                    logger.debug("Clip upload targeting all sites (empty list normalized to None)")

            headers = {}
            if self.auth:
                token = self.auth.get_access_token()
                if token:
                    headers["Authorization"] = f"Bearer {token}"

            url = f"{self.base_url}/marketplace/items/{item_id}/clips/upload"
            
            try:
                response = self.session.post(url, headers=headers, files=files, data=data, timeout=120)
                response.raise_for_status()
            except Exception as e:
                # Log error details for debugging
                resp = getattr(e, "response", None)
                status_code = getattr(resp, "status_code", "unknown")
                error_body = {}
                if resp is not None:
                    try:
                        error_body = resp.json()
                    except Exception:
                        try:
                            error_body = {"text": resp.text}
                        except Exception:
                            pass
                
                api_message = error_body.get("message", "") if isinstance(error_body, dict) else ""
                error_status = error_body.get("error_status", "") if isinstance(error_body, dict) else ""
                logger.error(
                    f"Clip upload failed for item {item_id}: "
                    f"[{status_code}] {error_status}: {api_message}"
                )
                raise

        return response.json()
