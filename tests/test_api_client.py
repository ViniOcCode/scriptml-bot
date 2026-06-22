"""Tests for MLApiClient behavior."""

from unittest.mock import MagicMock

import pytest
import requests

from mercadolivre_upload.api.client import MLApiClient
from mercadolivre_upload.api.domains import items as item_endpoints
from mercadolivre_upload.api.exceptions import MLApiError


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


def test_post_returns_empty_payload_for_204_success():
    response = MagicMock(spec=requests.Response)
    response.status_code = 204

    http_client = MagicMock()
    http_client.post.return_value = response

    client = MLApiClient(http_client=http_client)
    result = client.post("/dummy", json={"ok": True})

    assert result == {}
    response.raise_for_status.assert_called_once()
    response.json.assert_not_called()


def test_post_returns_empty_payload_for_non_json_success():
    response = MagicMock(spec=requests.Response)
    response.status_code = 200
    response.json.side_effect = ValueError("invalid json")

    http_client = MagicMock()
    http_client.post.return_value = response

    client = MLApiClient(http_client=http_client)
    result = client.post("/dummy", json={"ok": True})

    assert result == {}
    response.raise_for_status.assert_called_once()


def test_validate_user_product_item_validates_complete_payload_with_items_endpoint():
    client = MLApiClient(http_client=MagicMock())
    payload = {
        "title": "Linha Alpha Model X",
        "model": "user_products",
        "family_name": "Linha Alpha",
        "pictures": [{"id": "123"}],
        "attributes": [{"id": "SELLER_SKU", "value_name": "SKU-123"}],
        "available_quantity": 1,
    }
    client.validate_item = MagicMock(return_value={"cause": []})

    result = client.validate_user_product_item(payload)

    assert result == {"cause": []}
    client.validate_item.assert_called_once_with(payload)


def test_validate_user_product_item_does_not_infer_existing_user_product_from_id():
    client = MLApiClient(http_client=MagicMock())
    client.validate_item = MagicMock(return_value={"cause": []})
    payload = {"user_product_id": "MLBU123", "family_name": "Linha Alpha"}

    result = client.validate_user_product_item(payload)

    assert result == {"cause": []}
    client.validate_item.assert_called_once_with(payload)


def test_validate_existing_user_product_sales_condition_does_not_require_family_name():
    client = MLApiClient(http_client=MagicMock())
    client.validate_item = MagicMock(return_value={"cause": []})

    result = client.validate_user_product_item(
        {
            "user_product_id": " MLBU123 ",
            "target": "existing_user_product_selling_condition",
            "price": 100.0,
            "category_id": "MLB1055",
            "currency_id": "BRL",
            "buying_mode": "buy_it_now",
            "listing_type_id": "gold_special",
        }
    )

    assert result == {}
    client.validate_item.assert_not_called()


def test_get_user_product_fetches_metadata():
    client = MLApiClient(http_client=MagicMock())
    client.get = MagicMock(return_value={"id": "MLBU123", "family_id": "FAM-1"})

    result = item_endpoints.get_user_product(client, "MLBU123")

    assert result == {"id": "MLBU123", "family_id": "FAM-1"}
    client.get.assert_called_once_with("/user-products/MLBU123")


def test_search_user_items_uses_status_pagination_params():
    client = MLApiClient(http_client=MagicMock())
    client.get = MagicMock(return_value={"results": ["MLB1"], "paging": {"total": 1}})

    result = client.search_user_items("123", status="active", limit=50, offset=100)

    assert result == {"results": ["MLB1"], "paging": {"total": 1}}
    client.get.assert_called_once_with(
        "/users/123/items/search",
        params={"status": "active", "limit": 50, "offset": 100},
    )


def test_search_user_items_supports_scan_scroll_params():
    client = MLApiClient(http_client=MagicMock())
    client.get = MagicMock(return_value={"results": ["MLB1"], "scroll_id": "abc"})

    result = client.search_user_items(
        "123",
        status="active",
        limit=50,
        search_type="scan",
        scroll_id="abc",
    )

    assert result == {"results": ["MLB1"], "scroll_id": "abc"}
    client.get.assert_called_once_with(
        "/users/123/items/search",
        params={
            "status": "active",
            "limit": 50,
            "search_type": "scan",
            "scroll_id": "abc",
        },
    )


def test_get_items_batch_accepts_list_json_response():
    response = MagicMock(spec=requests.Response)
    response.status_code = 200
    response.json.return_value = [{"code": 200, "body": {"id": "MLB1"}}]

    http_client = MagicMock()
    http_client.get.return_value = response

    client = MLApiClient(http_client=http_client)
    result = client.get_items_batch(["MLB1", "MLB2"])

    assert result == [{"code": 200, "body": {"id": "MLB1"}}]
    http_client.get.assert_called_once()
    assert http_client.get.call_args.kwargs["params"] == {"ids": "MLB1,MLB2"}
    response.raise_for_status.assert_called_once()


def test_get_raises_ml_api_error_with_json_body_for_403():
    response = MagicMock(spec=requests.Response)
    response.status_code = 403
    response.json.return_value = {"message": "forbidden", "cause": []}

    http_client = MagicMock()
    http_client.get.return_value = response

    client = MLApiClient(http_client=http_client)

    with pytest.raises(MLApiError) as exc:
        client.get("/users/me")

    assert exc.value.response_body == {"message": "forbidden", "cause": []}
    response.raise_for_status.assert_not_called()


def test_create_user_product_item_posts_complete_payload_to_items():
    client = MLApiClient(http_client=MagicMock())
    payload = {
        "title": "Linha Alpha Model X",
        "model": "user_products",
        "family_name": "Linha Alpha",
        "pictures": [{"id": "123"}],
        "attributes": [{"id": "SELLER_SKU", "value_name": "SKU-123"}],
        "available_quantity": 1,
        "shipping": {"mode": "me2", "free_shipping": True, "local_pick_up": False},
        "sale_terms": [{"id": "WARRANTY_TYPE", "value_name": "Garantia do vendedor"}],
        "listing_type_id": "gold_special",
    }
    client.post = MagicMock(return_value={"id": "MLB1234567890"})

    result = item_endpoints.create_user_product_item(client, payload)

    assert result == {"id": "MLB1234567890"}
    client.post.assert_called_once_with("/items", json=payload)
    assert payload["shipping"]["local_pick_up"] is False
    assert client.last_user_product_sanitization is None


def test_create_user_product_item_does_not_infer_existing_user_product_from_id():
    client = MLApiClient(http_client=MagicMock())
    client.create_item = MagicMock(return_value={"id": "MLB1234567890"})
    payload = {"user_product_id": "MLBU123", "family_name": "Linha Alpha"}

    result = client.create_user_product_item(payload)

    assert result == {"id": "MLB1234567890"}
    client.create_item.assert_called_once_with(payload)


def test_create_user_product_item_routes_sales_condition_when_user_product_id_present():
    client = MLApiClient(http_client=MagicMock())
    client.post = MagicMock(return_value={"id": "MLB1234567890"})

    payload = {
        "title": "Linha Alpha Model X",
        "model": "user_products",
        "family_name": "Linha Alpha",
        "user_product_id": "MLBU123",
        "target": "existing_user_product_selling_condition",
        "price": 100.0,
        "category_id": "MLB1055",
        "currency_id": "BRL",
        "buying_mode": "buy_it_now",
        "listing_type_id": "gold_special",
        "available_quantity": 1,
        "attributes": [{"id": "BRAND", "value_name": "Marca"}],
        "pictures": [{"id": "123"}],
        "domain_id": "MLB-CELLPHONES",
        "condition": "new",
        "seller_custom_field": "SKU-123",
        "shipping": {"mode": "me2", "free_shipping": True, "local_pick_up": False},
        "channels": ["marketplace"],
        "tags": ["immediate_payment"],
        "sale_terms": [{"id": "WARRANTY_TYPE", "value_name": "Garantia do vendedor"}],
        "catalog_listing": False,
        "catalog_product_id": "MLB0001",
        "official_store_id": 1234,
    }

    with pytest.raises(ValueError, match="reduced request body"):
        client.create_user_product_item(payload)

    client.post.assert_not_called()


def test_create_user_product_item_routes_explicit_reduced_sales_condition():
    client = MLApiClient(http_client=MagicMock())
    client.post = MagicMock(return_value={"id": "MLB1234567890"})
    payload = {
        "target": "existing_user_product_selling_condition",
        "user_product_id": "MLBU123",
        "price": 100.0,
        "category_id": "MLB1055",
        "currency_id": "BRL",
        "buying_mode": "buy_it_now",
        "listing_type_id": "gold_special",
        "shipping": {"mode": "me2", "free_shipping": True, "local_pick_up": False},
    }

    result = client.create_user_product_item(payload)

    assert result == {"id": "MLB1234567890"}
    client.post.assert_called_once_with(
        "/user-products/MLBU123/items",
        json={
            "price": 100.0,
            "category_id": "MLB1055",
            "currency_id": "BRL",
            "buying_mode": "buy_it_now",
            "listing_type_id": "gold_special",
            "shipping": {"mode": "me2", "free_shipping": True},
        },
    )
    assert client.last_user_product_sanitization == {
        "endpoint": "/user-products/{user_product_id}/items",
        "removed_fields": ["shipping.local_pick_up"],
    }


def test_existing_user_product_selling_condition_requires_user_product_id():
    client = MLApiClient(http_client=MagicMock())
    client.post = MagicMock(return_value={"id": "MLB1234567890"})

    with pytest.raises(ValueError, match="requires non-empty 'user_product_id'"):
        client.create_user_product_item(
            {
                "target": "existing_user_product_selling_condition",
                "price": 100.0,
                "category_id": "MLB1055",
                "currency_id": "BRL",
                "buying_mode": "buy_it_now",
                "listing_type_id": "gold_special",
            }
        )

    client.post.assert_not_called()


def test_create_item_clears_previous_user_product_sanitization_metadata():
    client = MLApiClient(http_client=MagicMock())
    client.post = MagicMock(return_value={"id": "MLB1234567890"})
    client.last_user_product_sanitization = {
        "endpoint": "/user-products/{user_product_id}/items",
        "removed_fields": ["shipping.local_pick_up"],
    }

    result = item_endpoints.create_item(client, {"title": "Produto"})

    assert result == {"id": "MLB1234567890"}
    assert client.last_user_product_sanitization is None


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


def test_get_site_listing_types_reads_list_response():
    http_client = MagicMock()
    client = MLApiClient(http_client=http_client)
    client.get = MagicMock(return_value=[{"id": "gold_special"}, {"id": "free"}])

    result = client.get_site_listing_types("MLB")

    assert result == [{"id": "gold_special"}, {"id": "free"}]


def test_get_site_listing_types_returns_empty_for_invalid_shape():
    http_client = MagicMock()
    client = MLApiClient(http_client=http_client)
    client.get = MagicMock(return_value={"unexpected": "shape"})

    result = client.get_site_listing_types("MLB")

    assert result == []


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


def test_upload_image_uses_mime_type_from_extension(tmp_path):
    image_path = tmp_path / "image.png"
    image_path.write_bytes(b"fake")

    response = MagicMock(spec=requests.Response)
    response.json.return_value = {"id": "123", "secure_url": "https://img.example/test.png"}

    http_client = MagicMock()
    http_client.post.return_value = response

    client = MLApiClient(http_client=http_client)
    client.upload_image(str(image_path))

    _, kwargs = http_client.post.call_args
    file_tuple = kwargs["files"]["file"]
    assert file_tuple[2] == "image/png"


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


def test_put_returns_json_response():
    response = MagicMock(spec=requests.Response)
    response.status_code = 200
    response.json.return_value = {"id": "MLB1234", "status": "paused"}

    http_client = MagicMock()
    http_client.put.return_value = response

    client = MLApiClient(http_client=http_client)
    result = client.put("/items/MLB1234", json={"status": "paused"})

    assert result == {"id": "MLB1234", "status": "paused"}
    http_client.put.assert_called_once()
    response.raise_for_status.assert_called_once()


def test_update_item_calls_put_with_item_endpoint_and_data():
    response = MagicMock(spec=requests.Response)
    response.status_code = 200
    response.json.return_value = {"id": "MLB1234", "status": "paused"}

    http_client = MagicMock()
    http_client.put.return_value = response

    client = MLApiClient(http_client=http_client)
    result = client.update_item("MLB1234", {"status": "paused"})

    assert result == {"id": "MLB1234", "status": "paused"}
    _args, kwargs = http_client.put.call_args
    assert "items/MLB1234" in _args[0]
    assert kwargs["json"] == {"status": "paused"}


def test_create_item_400_raises_ml_api_error_with_body():
    """POST /items 400 with ML JSON body must raise MLApiError with parsed causes."""
    from mercadolivre_upload.api.exceptions import MLApiError  # fails until Step 2

    ml_error_body = {
        "message": "Validation error",
        "error": "validation_error",
        "status": 400,
        "cause": [
            {
                "cause_id": 147,
                "type": "error",
                "code": "item.attributes.missing_required",
                "references": ["item.attributes"],
                "message": "The attributes [BRAND] are required for category MLB437616",
            }
        ],
    }
    response = MagicMock(spec=requests.Response)
    response.status_code = 400
    response.json.return_value = ml_error_body

    http_client = MagicMock()
    http_client.post.return_value = response

    client = MLApiClient(http_client=http_client)

    with pytest.raises(MLApiError) as exc_info:
        client.create_item({"title": "Produto Teste"})

    assert exc_info.value.causes == ml_error_body["cause"]
    response.raise_for_status.assert_not_called()


def test_create_item_400_non_json_falls_back_to_http_error():
    """POST /items 400 with non-JSON body must fall back to plain HTTPError."""
    response = MagicMock(spec=requests.Response)
    response.status_code = 400
    response.json.side_effect = ValueError("invalid json")
    response.raise_for_status.side_effect = requests.HTTPError("bad request")

    http_client = MagicMock()
    http_client.post.return_value = response

    client = MLApiClient(http_client=http_client)

    with pytest.raises(requests.HTTPError):
        client.create_item({"title": "Produto Teste"})

    response.raise_for_status.assert_called_once()


def test_validate_item_400_still_returns_body_not_raises():
    """Regression guard: /items/validate 400 behavior must remain unchanged (return body)."""
    response = MagicMock(spec=requests.Response)
    response.status_code = 400
    response.json.return_value = {"cause": [{"code": "item.invalid"}]}

    http_client = MagicMock()
    http_client.post.return_value = response

    client = MLApiClient(http_client=http_client)
    result = client.validate_item({"title": "Produto Teste"})

    assert result == {"cause": [{"code": "item.invalid"}]}
    response.raise_for_status.assert_not_called()
