"""Tests for MLApiClient behavior."""

from unittest.mock import MagicMock

import pytest
import requests

from mercadolivre_upload.api.client import MLApiClient


def test_validate_item_returns_400_json_payload():
    response = MagicMock(spec=requests.Response)
    response.status_code = 400
    response.json.return_value = {"cause": [{"code": "item.invalid"}]}

    http_client = MagicMock()
    http_client.post.return_value = response

    client = MLApiClient(http_client=http_client)
    result = client.validate_item({"title": "Produto teste"})

    assert result == {"cause": [{"code": "item.invalid"}]}
    response.raise_for_status.assert_not_called()


def test_validate_item_raises_for_non_json_400_response():
    response = MagicMock(spec=requests.Response)
    response.status_code = 400
    response.json.side_effect = ValueError("invalid json")
    response.raise_for_status.side_effect = requests.HTTPError("bad request")

    http_client = MagicMock()
    http_client.post.return_value = response

    client = MLApiClient(http_client=http_client)

    with pytest.raises(requests.HTTPError):
        client.validate_item({"title": "Produto teste"})

    response.raise_for_status.assert_called_once()
