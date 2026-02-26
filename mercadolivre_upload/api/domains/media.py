"""Media upload endpoint helpers for MLApiClient."""

import contextlib
import json
import logging
import mimetypes
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import requests

from mercadolivre_upload.infrastructure.http import UPLOAD_RETRY

if TYPE_CHECKING:
    from mercadolivre_upload.api.client import MLApiClient

logger = logging.getLogger(__name__)


def upload_image(client: "MLApiClient", image_path: str) -> dict[str, Any]:
    """Upload an image with retry on transient errors."""
    path = Path(image_path)
    with open(path, "rb") as file_handle:
        files = {"file": (path.name, file_handle, "image/jpeg")}
        url = f"{client.base_url}/pictures/items/upload"
        response = client.http.post(
            url,
            headers=client._auth_headers_only(),
            files=files,
            policy=UPLOAD_RETRY,
            timeout=60,
        )
        response.raise_for_status()

    data = response.json()

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


def upload_clip(
    client: "MLApiClient",
    item_id: str,
    file_path: str,
    sites: list[dict[str, Any]] | None = None,
    *,
    validate_clip_item_id_fn: Callable[[str | None], None],
) -> dict[str, Any]:
    """Upload a video clip for an item (CBT parent ID required)."""
    path = Path(file_path)
    validate_clip_item_id_fn(item_id)

    mime_type, _ = mimetypes.guess_type(str(path))
    if not mime_type:
        mime_type = "video/mp4"

    with open(path, "rb") as file_handle:
        files = {"file": (path.name, file_handle, mime_type)}
        data: dict[str, Any] = {}
        if sites is not None and sites:
            data["sites"] = json.dumps(sites)

        url = f"{client.base_url}/marketplace/items/{item_id}/clips/upload"

        try:
            response = client.http.post(
                url,
                headers=client._auth_headers_only(),
                files=files,
                data=data,
                policy=UPLOAD_RETRY,
                timeout=120,
            )
            response.raise_for_status()
        except requests.RequestException as error:
            error_resp = getattr(error, "response", None)
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

    return cast(dict[str, Any], response.json())
