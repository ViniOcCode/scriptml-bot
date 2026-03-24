"""Custom API exception classes for Mercado Livre API errors.

Per ML API docs (https://developers.mercadolivre.com.br/pt_br/validacoes),
400 responses include a `cause` array with machine-readable error codes,
field references, and human-readable messages.
"""

from __future__ import annotations

from typing import Any

import requests


class MLApiError(requests.HTTPError):
    """HTTPError enriched with the ML API JSON error body.

    Attributes:
        response_body: Parsed JSON from the ML API error response.
        causes: Blocking cause objects from ML's ``cause`` array
            (``type == "error"`` only).
    """

    def __init__(
        self,
        *args: Any,
        response_body: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize with optional ML API response body."""
        super().__init__(*args, **kwargs)
        self.response_body: dict[str, Any] | None = response_body
        causes_raw = (response_body or {}).get("cause")
        self.causes: list[dict[str, Any]] = (
            list(causes_raw) if isinstance(causes_raw, list) else []
        )
