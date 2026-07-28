"""Tests for dependency wiring used by spreadsheet validation adapters."""

from unittest.mock import MagicMock

from mercadolivre_upload.cli.commands import spreadsheet_runtime


def test_build_publish_use_case_wires_spreadsheet_dependencies(tmp_path, monkeypatch) -> None:
    auth_manager = MagicMock()
    api_client = MagicMock()
    attribute_cache = MagicMock()
    prediction_cache = MagicMock()
    category_adapter = MagicMock()
    image_uploader = MagicMock()
    clip_uploader = MagicMock()
    category_resolver = MagicMock()
    shipping_resolver = MagicMock()
    fiscal_service = MagicMock()
    use_case = MagicMock()

    monkeypatch.setattr(spreadsheet_runtime, "TokenManager", MagicMock(return_value=auth_manager))
    monkeypatch.setattr(spreadsheet_runtime, "MLApiClient", MagicMock(return_value=api_client))
    monkeypatch.setattr(
        spreadsheet_runtime,
        "AttributeCache",
        MagicMock(return_value=attribute_cache),
    )
    monkeypatch.setattr(
        spreadsheet_runtime,
        "PredictionCache",
        MagicMock(return_value=prediction_cache),
    )
    monkeypatch.setattr(
        spreadsheet_runtime,
        "CategoryAdapter",
        MagicMock(return_value=category_adapter),
    )
    monkeypatch.setattr(
        spreadsheet_runtime,
        "ImageUploader",
        MagicMock(return_value=image_uploader),
    )
    monkeypatch.setattr(
        spreadsheet_runtime,
        "ClipUploader",
        MagicMock(return_value=clip_uploader),
    )
    category_resolver_factory = MagicMock(return_value=category_resolver)
    monkeypatch.setattr(spreadsheet_runtime, "CategoryResolver", category_resolver_factory)
    monkeypatch.setattr(
        spreadsheet_runtime,
        "ShippingResolver",
        MagicMock(return_value=shipping_resolver),
    )
    monkeypatch.setattr(
        spreadsheet_runtime,
        "FiscalService",
        MagicMock(return_value=fiscal_service),
    )
    use_case_factory = MagicMock(return_value=use_case)
    monkeypatch.setattr(spreadsheet_runtime, "PublishProductUseCase", use_case_factory)

    result = spreadsheet_runtime.build_publish_use_case(
        images=tmp_path / "images",
        cache_dir=tmp_path / "cache",
        config={"feature": True},
        validation_only=True,
    )

    assert result is use_case
    category_resolver_factory.assert_called_once_with(
        category_adapter,
        attribute_cache=attribute_cache,
        prediction_cache=prediction_cache,
    )
    use_case_factory.assert_called_once_with(
        category_resolver=category_resolver,
        publisher=api_client,
        image_uploader=image_uploader,
        shipping_resolver=shipping_resolver,
        fiscal_service=fiscal_service,
        clip_uploader=clip_uploader,
        config={"feature": True},
        dry_run=True,
        validation_only=True,
        execute=False,
        confirmation=None,
        publish_inactive=False,
        attribute_cache=attribute_cache,
    )
