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


def test_get_category_conditional_attributes_from_required_attributes():
    http_client = MagicMock()
    client = MLApiClient(http_client=http_client)
    client.post = MagicMock(
        return_value={"required_attributes": [{"id": "BRAND"}, {"id": "MODEL"}]}
    )

    result = client.get_category_conditional_attributes("MLB1", {"title": "Produto"})

    assert result == [{"id": "BRAND"}, {"id": "MODEL"}]


def test_get_category_conditional_attributes_from_list_response():
    http_client = MagicMock()
    client = MLApiClient(http_client=http_client)
    client.post = MagicMock(return_value=[{"id": "BRAND"}])

    result = client.get_category_conditional_attributes("MLB1", {"title": "Produto"})

    assert result == [{"id": "BRAND"}]


def test_get_category_conditional_attributes_returns_empty_for_invalid_shape():
    http_client = MagicMock()
    client = MLApiClient(http_client=http_client)
    client.post = MagicMock(return_value={"required_attributes": "invalid"})

    result = client.get_category_conditional_attributes("MLB1", {"title": "Produto"})

    assert result == []


def test_get_available_listing_types_returns_empty_without_user_id():
    http_client = MagicMock()
    client = MLApiClient(http_client=http_client)
    client.get_users_me = MagicMock(return_value={"nickname": "seller"})
    client.get = MagicMock()

    result = client.get_available_listing_types("MLB1")

    assert result == []
    client.get.assert_not_called()


def test_get_available_listing_types_reads_available_from_dict():
    http_client = MagicMock()
    client = MLApiClient(http_client=http_client)
    client.get_users_me = MagicMock(return_value={"id": 1234})
    client.get = MagicMock(return_value={"available": [{"id": "gold_special"}]})

    result = client.get_available_listing_types("MLB1")

    assert result == [{"id": "gold_special"}]


def test_get_available_listing_types_reads_list_response():
    http_client = MagicMock()
    client = MLApiClient(http_client=http_client)
    client.get_users_me = MagicMock(return_value={"id": 1234})
    client.get = MagicMock(return_value=[{"id": "gold_pro"}])

    result = client.get_available_listing_types("MLB1")

    assert result == [{"id": "gold_pro"}]


def test_check_fiscal_data_exists_returns_false_for_404():
    http_client = MagicMock()
    client = MLApiClient(http_client=http_client)
    response = MagicMock(spec=requests.Response)
    response.status_code = 404
    error = requests.HTTPError("not found")
    error.response = response
    client.get = MagicMock(side_effect=error)

    exists, payload = client.check_fiscal_data_exists("SKU-1")

    assert exists is False
    assert payload is None


def test_check_fiscal_data_exists_reraises_non_404_error():
    http_client = MagicMock()
    client = MLApiClient(http_client=http_client)
    response = MagicMock(spec=requests.Response)
    response.status_code = 500
    error = requests.HTTPError("server error")
    error.response = response
    client.get = MagicMock(side_effect=error)

    with pytest.raises(requests.HTTPError):
        client.check_fiscal_data_exists("SKU-1")


def test_verify_invoice_readiness_reads_status_field():
    http_client = MagicMock()
    client = MLApiClient(http_client=http_client)
    client.get = MagicMock(return_value={"status": True, "reason": None})

    ready, payload = client.verify_invoice_readiness("MLB1234567890")

    assert ready is True
    assert payload == {"status": True, "reason": None}


def test_upload_image_normalizes_url_from_variations(tmp_path):
    image_path = tmp_path / "image.jpg"
    image_path.write_bytes(b"fake")

    response = MagicMock(spec=requests.Response)
    response.json.return_value = {
        "id": "123",
        "variations": [{"secure_url": "https://img.example/test.jpg"}],
    }

    http_client = MagicMock()
    http_client.post.return_value = response

    client = MLApiClient(http_client=http_client)
    result = client.upload_image(str(image_path))

    assert result["secure_url"] == "https://img.example/test.jpg"
    assert result["url"] == "https://img.example/test.jpg"


def test_diagnose_picture_posts_picture_url_payload():
    http_client = MagicMock()
    client = MLApiClient(http_client=http_client)
    client.post = MagicMock(return_value={"id": "diag-1"})

    result = client.diagnose_picture(
        picture_url="https://example.com/image.jpg",
        context={"category_id": "MLB1", "picture_type": "thumbnail"},
    )

    assert result == {"id": "diag-1"}
    client.post.assert_called_once_with(
        "/moderations/pictures/diagnostic",
        json={
            "picture_url": "https://example.com/image.jpg",
            "context": {"category_id": "MLB1", "picture_type": "thumbnail"},
        },
    )


def test_diagnose_picture_requires_single_identifier():
    client = MLApiClient(http_client=MagicMock())

    with pytest.raises(ValueError):
        client.diagnose_picture()

    with pytest.raises(ValueError):
        client.diagnose_picture(picture_url="https://example.com/image.jpg", picture_id="PIC-1")
