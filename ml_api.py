import os
import requests
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)


class MLAPI:
    def __init__(self, token_manager):
        self.token_manager = token_manager
        self.base_url = "https://api.mercadolibre.com"
        logger.info("MLAPI initialized")

    def upload_images_for_sku_folder(
        self,
        sku: str,
        image_paths: list,
        dry_run: bool = False,
        max_concurrent_uploads: int = 2,
    ) -> list:
        """Centralized image uploader for a given SKU folder.

        This is a lightweight, test-friendly implementation that either:
        - returns deterministic placeholder URLs when in dry-run mode, or
        - simulates parallel uploads and returns the generated URLs in the original image order.

        Args:
            sku: SKU identifier (used to build URLs).
            image_paths: List of local image file paths to upload.
            dry_run: If True, do not perform real I/O and return placeholder URLs.
            max_concurrent_uploads: Concurrency level for simulated uploads.

        Returns:
            A list of URLs corresponding to the uploaded images, in the same order as image_paths.
        """
        if not image_paths:
            return []

        # Normalize input order
        ordered_paths = list(image_paths)
        urls: list[str] = []

        if dry_run:
            # Generate deterministic placeholder URLs for dry-run
            for p in ordered_paths:
                filename = os.path.basename(p)
                urls.append(f"https://example.local/{sku}/{filename}")
            return urls

        # Real (simulated) upload flow with basic concurrency and retry placeholder
        base_url = f"https://uploads.local/{sku}"

        def _upload_one(path: str) -> tuple[str, str]:
            filename = os.path.basename(path)
            max_retries = 2
            for attempt in range(1, max_retries + 4):
                try:
                    with open(path, "rb") as f:
                        data = self.request(
                            "POST",
                            "/pictures/items/upload",
                            files={"file": (filename, f, "image/jpeg")},
                        )
                    # Choose largest variation URL if provided
                    chosen_url = None
                    variations = (
                        data.get("variations") if isinstance(data, dict) else None
                    )
                    if isinstance(variations, list) and variations:
                        max_area = -1
                        for v in variations:
                            size = v.get("size", "0x0")
                            w, h = 0, 0
                            try:
                                w, h = [int(x) for x in str(size).split("x")]
                            except Exception:
                                pass
                            area = w * h
                            if area > max_area:
                                max_area = area
                                chosen_url = v.get("secure_url") or v.get("url")
                    if not chosen_url and isinstance(data, dict):
                        chosen_url = data.get("secure_url") or data.get("url")
                    if chosen_url:
                        return filename, chosen_url
                    raise ValueError("Upload response missing URL")
                except requests.HTTPError as e:
                    # Retry on transient errors (429/5xx); 401/403 will refresh in self.request
                    status = getattr(e, "response", None)
                    code = status.status_code if status else None
                    if code in (429, 500, 502, 503, 504) and attempt <= max_retries + 1:
                        delay = min(60, 2**attempt)
                        time.sleep(delay)
                        continue
                    logger.error(f"Upload failed for {path}: {e}")
                    return filename, ""
                except Exception as e:
                    if attempt <= max_retries + 1:
                        delay = min(60, 2**attempt)
                        time.sleep(delay)
                        continue
                    logger.error(f"Upload failed for {path}: {e}")
                    return filename, ""

        results: list[tuple[str, str]] = []
        try:
            with ThreadPoolExecutor(max_workers=max_concurrent_uploads) as executor:
                futures = {executor.submit(_upload_one, p): p for p in ordered_paths}
                for fut in as_completed(futures):
                    try:
                        filename, url = fut.result()
                        results.append((filename, url))
                    except Exception as e:
                        logger.error(f"Image upload failed for {futures[fut]}: {e}")
        except Exception as e:
            logger.error(f"Upload pipeline failed: {e}")

        # Build URL mapping in original order
        url_map = {fn: url for fn, url in results}
        for p in ordered_paths:
            fn = os.path.basename(p)
            urls.append(url_map.get(fn, ""))

        # Remove any empty URLs that might have failed silently
        urls = [u for u in urls if u]
        return urls

    def request(self, method, path, **kwargs):
        token = self.token_manager.get_valid_token()
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {token}"

        url = f"{self.base_url}{path}"
        r = requests.request(method, url, headers=headers, **kwargs)

        if r.status_code == 401:
            logger.warning("401 received, refreshing token...")
            self.token_manager.refresh()
            headers["Authorization"] = f"Bearer {self.token_manager.get_valid_token()}"
            r = requests.request(method, url, headers=headers, **kwargs)

        if not r.ok:
            logger.error(f"HTTP {r.status_code}")
            logger.error(r.text)
            r.raise_for_status()

        return r.json()

    def publish_item(self, item):
        return self.request("POST", "/items", json=item)

    def get_category(self, category_id):
        """Fetch category details including required attributes."""
        return self.request("GET", f"/categories/{category_id}")

    def get_category_attributes(self, category_id):
        """Fetch all attributes (required and optional) for a category."""
        logger.info(f"Fetching attributes for category {category_id}...")
        return self.request("GET", f"/categories/{category_id}/attributes")

    def predict_category(self, title):
        """
        Predict the category for a given item title using Domain Discovery.
        Returns a dict with 'id' (category_id) and 'name'.
        """
        import urllib.parse

        logger.info(f"Predicting category for title: '{title}'")
        encoded_title = urllib.parse.quote(title)

        # Use domain_discovery/search which is the modern endpoint
        results = self.request(
            "GET", f"/sites/MLB/domain_discovery/search?limit=1&q={encoded_title}"
        )

        if results and isinstance(results, list) and len(results) > 0:
            # Results contain domain_id and category_id
            prediction = results[0]
            # Extract category_id from the result
            category_id = prediction.get("category_id")
            category_name = prediction.get(
                "category_name", prediction.get("domain_name", "Unknown")
            )

            if category_id:
                return {"id": category_id, "name": category_name}

        return None

    def validate_item(self, item):
        """
        Validate an item against the API rules before publishing.
        Returns a tuple: (is_valid, warnings, errors)
        """
        token = self.token_manager.get_valid_token()
        headers = {"Authorization": f"Bearer {token}"}

        url = f"{self.base_url}/items/validate"
        r = requests.post(url, headers=headers, json=item)

        # Handle 400 responses specially - they may contain only warnings
        if r.status_code == 400:
            try:
                data = r.json()
                causes = data.get("cause", [])

                warnings = [c for c in causes if c.get("type") == "warning"]
                errors = [c for c in causes if c.get("type") == "error"]

                if errors:
                    # There are actual errors, raise exception
                    error_msgs = [
                        f"{e.get('code')}: {e.get('message')}" for e in errors
                    ]
                    raise ValueError(f"Validation errors: {'; '.join(error_msgs)}")

                # Only warnings - item can likely be published
                if warnings:
                    warning_msgs = [
                        f"{w.get('code')}: {w.get('message')}" for w in warnings
                    ]
                    logger.warning(
                        f"Validation warnings (item may still publish): {'; '.join(warning_msgs)}"
                    )
                    return {"status": "warnings", "warnings": warnings}

            except ValueError:
                raise
            except Exception as e:
                logger.error(f"Failed to parse validation response: {e}")
                r.raise_for_status()

        if not r.ok:
            logger.error(f"HTTP {r.status_code}")
            logger.error(r.text)
            r.raise_for_status()

        # 200 OK or 204 No Content = valid
        return {"status": "valid"}
