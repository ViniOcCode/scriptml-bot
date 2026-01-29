"""Mercado Livre API client."""

import logging
from typing import Optional

import requests

from mercadolivre_upload.auth import AuthManager

logger = logging.getLogger(__name__)

BASE_URL = "https://api.mercadolibre.com"


class MLApiClient:
    """Client for Mercado Livre API."""

    def __init__(self, auth_manager: Optional[AuthManager] = None):
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

    def get(self, endpoint: str, params: Optional[dict] = None) -> dict:
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

    def post(
        self, endpoint: str, data: Optional[dict] = None, json: Optional[dict] = None
    ) -> dict:
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
        response = self.session.post(
            url, headers=headers, data=data, json=json, timeout=30
        )

        # Special handling for validation endpoint - return error response
        # so caller can distinguish warnings from actual errors
        if endpoint.strip('/') == 'items/validate' and response.status_code == 400:
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

            url = f"{self.base_url}/pictures"
            response = self.session.post(url, headers=headers, files=files, timeout=60)
            response.raise_for_status()

        return response.json()

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
        endpoint = f"/items/{item_id}/fiscal_info"
        return self.post(endpoint, json=fiscal_data)
