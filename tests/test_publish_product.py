"""Tests for publish_product.py module."""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure mercadolivre_upload is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from mercadolivre_upload.application.publish_product import (
    PublishProductService,
    PublishResult,
    ValidationResult,
)


class TestPublishResult:
    """Tests for PublishResult dataclass."""

    def test_publish_result_creation(self):
        """Test creating PublishResult."""
        result = PublishResult(
            success_count=5,
            failure_count=2,
            published_ids=["MLB1", "MLB2", "MLB3"],
            errors=[{"product": "p1", "error": "test"}],
        )
        
        assert result.success_count == 5
        assert result.failure_count == 2
        assert result.published_ids == ["MLB1", "MLB2", "MLB3"]
        assert len(result.errors) == 1

    def test_publish_result_empty(self):
        """Test creating empty PublishResult."""
        result = PublishResult(
            success_count=0,
            failure_count=0,
            published_ids=[],
            errors=[],
        )
        
        assert result.success_count == 0
        assert result.failure_count == 0
        assert result.published_ids == []
        assert result.errors == []


class TestValidationResult:
    """Tests for ValidationResult dataclass."""

    def test_validation_result_valid(self):
        """Test creating valid ValidationResult."""
        result = ValidationResult(
            is_valid=True,
            errors=[],
            warnings=["warning1"],
        )
        
        assert result.is_valid is True
        assert result.errors == []
        assert result.warnings == ["warning1"]

    def test_validation_result_invalid(self):
        """Test creating invalid ValidationResult."""
        result = ValidationResult(
            is_valid=False,
            errors=["error1", "error2"],
            warnings=[],
        )
        
        assert result.is_valid is False
        assert len(result.errors) == 2
        assert result.warnings == []


class TestPublishProductServiceInit:
    """Tests for PublishProductService initialization."""

    @patch("mercadolivre_upload.application.publish_product.AuthManager")
    def test_init_default(self, mock_auth_class):
        """Test default initialization."""
        mock_auth = MagicMock()
        mock_auth_class.return_value = mock_auth
        
        service = PublishProductService()
        
        assert service.config_path is None
        assert service.dry_run is False
        assert service._api is None

    @patch("mercadolivre_upload.application.publish_product.AuthManager")
    def test_init_with_params(self, mock_auth_class):
        """Test initialization with parameters."""
        mock_auth = MagicMock()
        mock_auth_class.return_value = mock_auth
        
        config_path = Path("config.yaml")
        mock_api = MagicMock()
        
        service = PublishProductService(
            config_path=config_path,
            dry_run=True,
            api_client=mock_api,
        )
        
        assert service.config_path == config_path
        assert service.dry_run is True
        assert service._api == mock_api

    @patch("mercadolivre_upload.application.publish_product.AuthManager")
    def test_api_property_initializes(self, mock_auth_class):
        """Test that api property initializes the API."""
        mock_auth = MagicMock()
        mock_auth_class.return_value = mock_auth
        
        service = PublishProductService()
        
        api = service.api
        
        assert api is not None
        assert service._api is api

    @patch("mercadolivre_upload.application.publish_product.AuthManager")
    def test_api_property_reuses_instance(self, mock_auth_class):
        """Test that api property reuses the same instance."""
        mock_auth = MagicMock()
        mock_auth_class.return_value = mock_auth
        
        service = PublishProductService()
        
        api1 = service.api
        api2 = service.api
        
        assert api1 is api2


class TestPublishFromFile:
    """Tests for publish_from_file method."""

    @patch("mercadolivre_upload.application.publish_product.SpreadsheetParser")
    @patch("mercadolivre_upload.application.publish_product.ProductBuilder")
    @patch("mercadolivre_upload.application.publish_product.AuthManager")
    def test_publish_from_file_success(self, mock_auth_class, mock_builder_class, mock_parser_class):
        """Test successful publish from file."""
        mock_auth = MagicMock()
        mock_auth_class.return_value = mock_auth
        
        mock_parser = MagicMock()
        mock_parser_class.return_value = mock_parser
        mock_parser.parse.return_value = [
            {"id": "1", "title": "Product 1"},
            {"id": "2", "title": "Product 2"},
        ]
        
        mock_builder = MagicMock()
        mock_builder_class.return_value = mock_builder
        mock_builder.build.return_value = {"title": "Test"}
        
        mock_api = MagicMock()
        mock_api.publish_product.return_value = MagicMock(
            success=True, product_id="MLB123"
        )
        
        service = PublishProductService(api_client=mock_api)
        result = service.publish_from_file(Path("test.xlsx"))
        
        assert result.success_count == 2
        assert result.failure_count == 0
        assert len(result.published_ids) == 2
        assert result.published_ids[0] == "MLB123"

    @patch("mercadolivre_upload.application.publish_product.SpreadsheetParser")
    @patch("mercadolivre_upload.application.publish_product.ProductBuilder")
    @patch("mercadolivre_upload.application.publish_product.AuthManager")
    def test_publish_from_file_dry_run(self, mock_auth_class, mock_builder_class, mock_parser_class):
        """Test publish from file in dry run mode."""
        mock_auth = MagicMock()
        mock_auth_class.return_value = mock_auth
        
        mock_parser = MagicMock()
        mock_parser_class.return_value = mock_parser
        mock_parser.parse.return_value = [
            {"id": "1", "title": "Product 1"},
        ]
        
        mock_builder = MagicMock()
        mock_builder_class.return_value = mock_builder
        mock_builder.build.return_value = {"title": "Test"}
        
        service = PublishProductService(dry_run=True)
        result = service.publish_from_file(Path("test.xlsx"))
        
        assert result.success_count == 1
        assert result.published_ids[0].startswith("DRY_")

    @patch("mercadolivre_upload.application.publish_product.SpreadsheetParser")
    @patch("mercadolivre_upload.application.publish_product.ProductBuilder")
    @patch("mercadolivre_upload.application.publish_product.AuthManager")
    def test_publish_from_file_api_failure(self, mock_auth_class, mock_builder_class, mock_parser_class):
        """Test publish with API failures."""
        mock_auth = MagicMock()
        mock_auth_class.return_value = mock_auth
        
        mock_parser = MagicMock()
        mock_parser_class.return_value = mock_parser
        mock_parser.parse.return_value = [
            {"id": "1", "title": "Product 1"},
            {"id": "2", "title": "Product 2"},
        ]
        
        mock_builder = MagicMock()
        mock_builder_class.return_value = mock_builder
        mock_builder.build.return_value = {"title": "Test"}
        
        mock_api = MagicMock()
        mock_api.publish_product.side_effect = [
            MagicMock(success=True, product_id="MLB1"),
            MagicMock(success=False, error_message="API Error"),
        ]
        
        service = PublishProductService(api_client=mock_api)
        result = service.publish_from_file(Path("test.xlsx"))
        
        assert result.success_count == 1
        assert result.failure_count == 1
        assert len(result.errors) == 1

    @patch("mercadolivre_upload.application.publish_product.SpreadsheetParser")
    @patch("mercadolivre_upload.application.publish_product.ProductBuilder")
    @patch("mercadolivre_upload.application.publish_product.AuthManager")
    def test_publish_from_file_exception(self, mock_auth_class, mock_builder_class, mock_parser_class):
        """Test publish with exception during processing."""
        mock_auth = MagicMock()
        mock_auth_class.return_value = mock_auth
        
        mock_parser = MagicMock()
        mock_parser_class.return_value = mock_parser
        mock_parser.parse.return_value = [
            {"id": "1", "title": "Product 1"},
        ]
        
        mock_builder = MagicMock()
        mock_builder_class.return_value = mock_builder
        mock_builder.build.side_effect = ValueError("Invalid product")
        
        service = PublishProductService()
        result = service.publish_from_file(Path("test.xlsx"))
        
        assert result.success_count == 0
        assert result.failure_count == 1
        assert len(result.errors) == 1

    @patch("mercadolivre_upload.application.publish_product.SpreadsheetParser")
    @patch("mercadolivre_upload.application.publish_product.AuthManager")
    def test_publish_from_file_empty(self, mock_auth_class, mock_parser_class):
        """Test publish with empty file."""
        mock_auth = MagicMock()
        mock_auth_class.return_value = mock_auth
        
        mock_parser = MagicMock()
        mock_parser_class.return_value = mock_parser
        mock_parser.parse.return_value = []
        
        service = PublishProductService()
        result = service.publish_from_file(Path("test.xlsx"))
        
        assert result.success_count == 0
        assert result.failure_count == 0


class TestValidateFile:
    """Tests for validate_file method."""

    @patch("mercadolivre_upload.application.publish_product.SpreadsheetParser")
    @patch("mercadolivre_upload.application.publish_product.ProductBuilder")
    @patch("mercadolivre_upload.application.publish_product.AuthManager")
    def test_validate_file_success(self, mock_auth_class, mock_builder_class, mock_parser_class):
        """Test successful validation."""
        mock_auth = MagicMock()
        mock_auth_class.return_value = mock_auth
        
        mock_parser = MagicMock()
        mock_parser_class.return_value = mock_parser
        mock_parser.parse.return_value = [
            {"id": "1", "title": "Product 1"},
        ]
        
        mock_builder = MagicMock()
        mock_builder_class.return_value = mock_builder
        mock_builder.validate.return_value = []
        
        service = PublishProductService()
        result = service.validate_file(Path("test.xlsx"))
        
        assert result.is_valid is True
        assert result.errors == []

    @patch("mercadolivre_upload.application.publish_product.SpreadsheetParser")
    @patch("mercadolivre_upload.application.publish_product.ProductBuilder")
    @patch("mercadolivre_upload.application.publish_product.AuthManager")
    def test_validate_file_with_errors(self, mock_auth_class, mock_builder_class, mock_parser_class):
        """Test validation with errors."""
        mock_auth = MagicMock()
        mock_auth_class.return_value = mock_auth
        
        mock_parser = MagicMock()
        mock_parser_class.return_value = mock_parser
        mock_parser.parse.return_value = [
            {"id": "1"},
            {"id": "2"},
        ]
        
        mock_builder = MagicMock()
        mock_builder_class.return_value = mock_builder
        mock_builder.validate.side_effect = [
            ["missing title"],
            ["missing price"],
        ]
        
        service = PublishProductService()
        result = service.validate_file(Path("test.xlsx"))
        
        assert result.is_valid is False
        assert len(result.errors) == 2
        assert "Linha 1: missing title" in result.errors
        assert "Linha 2: missing price" in result.errors

    @patch("mercadolivre_upload.application.publish_product.SpreadsheetParser")
    @patch("mercadolivre_upload.application.publish_product.AuthManager")
    def test_validate_file_empty(self, mock_auth_class, mock_parser_class):
        """Test validation with empty file."""
        mock_auth = MagicMock()
        mock_auth_class.return_value = mock_auth
        
        mock_parser = MagicMock()
        mock_parser_class.return_value = mock_parser
        mock_parser.parse.return_value = []
        
        service = PublishProductService()
        result = service.validate_file(Path("test.xlsx"))
        
        assert result.is_valid is False
        assert any("Nenhum produto" in e for e in result.errors)

    @patch("mercadolivre_upload.application.publish_product.SpreadsheetParser")
    @patch("mercadolivre_upload.application.publish_product.AuthManager")
    def test_validate_file_exception(self, mock_auth_class, mock_parser_class):
        """Test validation with exception."""
        mock_auth = MagicMock()
        mock_auth_class.return_value = mock_auth
        
        mock_parser = MagicMock()
        mock_parser_class.return_value = mock_parser
        mock_parser.parse.side_effect = Exception("Parse error")
        
        service = PublishProductService()
        result = service.validate_file(Path("test.xlsx"))
        
        assert result.is_valid is False
        assert "Erro ao processar arquivo" in result.errors[0]


class TestPublishSingle:
    """Tests for publish_single method."""

    @patch("mercadolivre_upload.application.publish_product.ProductBuilder")
    @patch("mercadolivre_upload.application.publish_product.AuthManager")
    def test_publish_single_success(self, mock_auth_class, mock_builder_class):
        """Test successful single publish."""
        mock_auth = MagicMock()
        mock_auth_class.return_value = mock_auth
        
        mock_builder = MagicMock()
        mock_builder_class.return_value = mock_builder
        mock_builder.build.return_value = {"title": "Test"}
        
        mock_api = MagicMock()
        mock_api.publish_product.return_value = MagicMock(
            success=True, product_id="MLB123"
        )
        
        service = PublishProductService(api_client=mock_api)
        result = service.publish_single({"title": "Test"})
        
        assert result.success_count == 1
        assert result.failure_count == 0
        assert result.published_ids == ["MLB123"]

    @patch("mercadolivre_upload.application.publish_product.ProductBuilder")
    @patch("mercadolivre_upload.application.publish_product.AuthManager")
    def test_publish_single_dry_run(self, mock_auth_class, mock_builder_class):
        """Test single publish in dry run mode."""
        mock_auth = MagicMock()
        mock_auth_class.return_value = mock_auth
        
        mock_builder = MagicMock()
        mock_builder_class.return_value = mock_builder
        mock_builder.build.return_value = {
            "title": "Test",
            "category_id": "MLB123",
            "price": 99.99,
            "currency_id": "BRL",
        }
        
        service = PublishProductService(dry_run=True)
        result = service.publish_single({"title": "Test"})
        
        assert result.success_count == 1
        assert result.published_ids == ["DRY_RUN_ID"]

    @patch("mercadolivre_upload.application.publish_product.ProductBuilder")
    @patch("mercadolivre_upload.application.publish_product.AuthManager")
    def test_publish_single_api_failure(self, mock_auth_class, mock_builder_class):
        """Test single publish with API failure."""
        mock_auth = MagicMock()
        mock_auth_class.return_value = mock_auth
        
        mock_builder = MagicMock()
        mock_builder_class.return_value = mock_builder
        mock_builder.build.return_value = {"title": "Test"}
        
        mock_api = MagicMock()
        mock_api.publish_product.return_value = MagicMock(
            success=False, error_message="API Error"
        )
        
        service = PublishProductService(api_client=mock_api)
        result = service.publish_single({"title": "Test"})
        
        assert result.success_count == 0
        assert result.failure_count == 1
        assert len(result.errors) == 1

    @patch("mercadolivre_upload.application.publish_product.ProductBuilder")
    @patch("mercadolivre_upload.application.publish_product.AuthManager")
    def test_publish_single_exception(self, mock_auth_class, mock_builder_class):
        """Test single publish with exception."""
        mock_auth = MagicMock()
        mock_auth_class.return_value = mock_auth
        
        mock_builder = MagicMock()
        mock_builder_class.return_value = mock_builder
        mock_builder.build.side_effect = ValueError("Invalid product")
        
        service = PublishProductService()
        result = service.publish_single({"title": "Test"})
        
        assert result.success_count == 0
        assert result.failure_count == 1
        assert "Invalid product" in result.errors[0]["error"]


class TestCheckCredentials:
    """Tests for check_credentials method."""

    @patch("mercadolivre_upload.application.publish_product.AuthManager")
    def test_check_credentials_true(self, mock_auth_class):
        """Test check credentials when authenticated."""
        mock_auth = MagicMock()
        mock_auth_class.return_value = mock_auth
        mock_auth.is_authenticated.return_value = True
        
        service = PublishProductService()
        result = service.check_credentials()
        
        assert result is True
        mock_auth.is_authenticated.assert_called_once()

    @patch("mercadolivre_upload.application.publish_product.AuthManager")
    def test_check_credentials_false(self, mock_auth_class):
        """Test check credentials when not authenticated."""
        mock_auth = MagicMock()
        mock_auth_class.return_value = mock_auth
        mock_auth.is_authenticated.return_value = False
        
        service = PublishProductService()
        result = service.check_credentials()
        
        assert result is False
