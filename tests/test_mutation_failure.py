"""Tests for ambiguous non-idempotent mutation failures."""

from __future__ import annotations

from unittest.mock import Mock

import pytest
import requests

from mercadolivre_upload.api.exceptions import MLApiError
from mercadolivre_upload.application.mutation_failure import is_ambiguous_mutation_failure


@pytest.mark.parametrize(
    "failure",
    [
        requests.Timeout("timed out"),
        requests.ConnectionError("connection dropped"),
        requests.HTTPError("503 Service Unavailable", response=Mock(status_code=503)),
    ],
)
def test_transport_and_5xx_failures_are_ambiguous(
    failure: requests.RequestException,
) -> None:
    assert is_ambiguous_mutation_failure(failure) is True


def test_http_4xx_failure_is_definitive() -> None:
    failure = requests.HTTPError("422 Unprocessable Entity", response=Mock(status_code=422))

    assert is_ambiguous_mutation_failure(failure) is False


@pytest.mark.parametrize("status_code", [200, 201, 302])
def test_non_json_success_or_redirect_response_is_ambiguous(status_code: int) -> None:
    failure = MLApiError(
        "POST /items returned non-JSON response",
        response=Mock(status_code=status_code),
    )

    assert is_ambiguous_mutation_failure(failure) is True


def test_structured_ml_error_without_explicit_status_is_ambiguous() -> None:
    failure = MLApiError(
        "bad request",
        response_body={"cause": [{"type": "error", "code": "item.invalid"}]},
    )

    assert is_ambiguous_mutation_failure(failure) is True


def test_response_without_status_is_ambiguous_instead_of_raising() -> None:
    failure = requests.HTTPError(
        "response has no status",
        response=requests.Response(),
    )

    assert is_ambiguous_mutation_failure(failure) is True
