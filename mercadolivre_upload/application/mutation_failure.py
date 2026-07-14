"""Failure classification for non-idempotent remote mutations."""

from __future__ import annotations

import re

import requests


def _http_status(exc: requests.HTTPError) -> int | None:
    response = exc.response
    if response is not None:
        response_status = response.status_code
        if isinstance(response_status, int):
            return response_status
    response_body = getattr(exc, "response_body", None)
    if isinstance(response_body, dict):
        raw_status = response_body.get("status")
        if isinstance(raw_status, int):
            return raw_status
    match = re.search(r"\b([45]\d{2})\b", str(exc))
    return int(match.group(1)) if match else None


def is_ambiguous_mutation_failure(exc: BaseException) -> bool:
    """Return whether a transport/provider failure may have applied remotely.

    Only an explicit HTTP 4xx response proves rejection. A 2xx/3xx response
    whose body cannot be interpreted, a 5xx response, a connection failure, or
    another request transport failure cannot prove the mutation result and
    therefore requires reconciliation.
    """
    if not isinstance(exc, requests.RequestException):
        return False
    if not isinstance(exc, requests.HTTPError):
        return True
    status = _http_status(exc)
    return status is None or not 400 <= status < 500


__all__ = ["is_ambiguous_mutation_failure"]
