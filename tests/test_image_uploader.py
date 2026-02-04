"""
Tests for image_uploader.py - 100% coverage.
"""
import base64
import hashlib
import logging
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from mercadolivre_upload.adapters.image_uploader import ImageUploader


class TestImageUploader:
    """Test cases for ImageUploader class."""

    @pytest.fixture
    def uploader(self):
        """Create uploader instance without API client."""
        return ImageUploader()

    @pytest.fixture
    def uploader_with_api(self):
        """Create uploader instance with mocked API client."""
        api_client = Mock()
        return ImageUploader(api_client=api_client)

    @pytest.fixture
    def temp_image(self, tmp_path):
        """Create a temporary image file for testing."""
        img_path = tmp_path / "test_image.jpg"
        # Create a valid JPEG-like file (header only)
        img_path.write_bytes(b'\xff\xd8\xff\xe0test_jpg_content')
        return str(img_path)

    @pytest.fixture
    def large_image(self, tmp_path):
        """Create a large image file for testing."""
        img_path = tmp_path / "large_image.jpg"
        # Create file larger than 10MB
        img_path.write_bytes(b'x' * (11 * 1024 * 1024))
        return str(img_path)

    # ==================== Initialization ====================

    def test_init_default(self):
        """Test default initialization."""
        uploader = ImageUploader()
        assert uploader.api_client is None
        assert uploader.base_path == Path("/tmp/uploads")
        assert uploader._uploaded_images == []

    def test_init_with_api_client(self):
        """Test initialization with API client."""
        api_client = Mock()
        uploader = ImageUploader(api_client=api_client)
        assert uploader.api_client == api_client

    def test_init_creates_base_path(self, tmp_path):
        """Test that base path is created if not exists."""
        base = tmp_path / "new_uploads"
        uploader = ImageUploader(base_path=str(base))
        assert base.exists()

    # ==================== validate_image ====================

    def test_validate_image_success(self, uploader, temp_image):
        """Test validation with valid image."""
        assert uploader.validate_image(temp_image) is True

    def test_validate_image_not_found(self, uploader, caplog):
        """Test validation with non-existent file."""
        caplog.set_level(logging.ERROR)
        assert uploader.validate_image("/nonexistent/file.jpg") is False
        assert "Image not found" in caplog.text

    def test_validate_image_not_a_file(self, uploader, tmp_path, caplog):
        """Test validation with directory."""
        caplog.set_level(logging.ERROR)
        assert uploader.validate_image(str(tmp_path)) is False
        assert "Path is not a file" in caplog.text

    def test_validate_image_invalid_extension(self, uploader, tmp_path, caplog):
        """Test validation with invalid extension."""
        caplog.set_level(logging.ERROR)
        invalid_file = tmp_path / "test.txt"
        invalid_file.write_text("content")
        assert uploader.validate_image(str(invalid_file)) is False
        assert "Invalid image extension" in caplog.text

    @pytest.mark.parametrize("ext", ['.jpg', '.jpeg', '.png', '.gif', '.webp'])
    def test_validate_image_valid_extensions(self, uploader, tmp_path, ext):
        """Test validation with all valid extensions."""
        img_path = tmp_path / f"test{ext}"
        img_path.write_bytes(b'content')
        assert uploader.validate_image(str(img_path)) is True

    def test_validate_image_case_insensitive_extension(self, uploader, tmp_path):
        """Test that extension validation is case insensitive."""
        img_path = tmp_path / "test.JPG"
        img_path.write_bytes(b'content')
        assert uploader.validate_image(str(img_path)) is True

    def test_validate_image_too_large(self, uploader, large_image, caplog):
        """Test validation with oversized image."""
        caplog.set_level(logging.ERROR)
        assert uploader.validate_image(large_image) is False
        assert "Image too large" in caplog.text

    # ==================== calculate_hash ====================

    def test_calculate_hash(self, uploader, temp_image):
        """Test hash calculation."""
        hash_result = uploader.calculate_hash(temp_image)

        # Verify it's a valid MD5 hash (32 hex chars)
        assert len(hash_result) == 32
        assert all(c in '0123456789abcdef' for c in hash_result)

        # Verify consistency
        hash2 = uploader.calculate_hash(temp_image)
        assert hash_result == hash2

    def test_calculate_hash_content(self, uploader, tmp_path):
        """Test hash matches expected value."""
        img_path = tmp_path / "test.jpg"
        content = b'test content'
        img_path.write_bytes(content)

        expected_hash = hashlib.md5(content).hexdigest()
        assert uploader.calculate_hash(str(img_path)) == expected_hash

    # ==================== encode_base64 ====================

    def test_encode_base64(self, uploader, temp_image):
        """Test base64 encoding."""
        encoded = uploader.encode_base64(temp_image)

        # Verify it's valid base64
        decoded = base64.b64decode(encoded)
        assert decoded == b'\xff\xd8\xff\xe0test_jpg_content'

    # ==================== upload ====================

    def test_upload_success_no_api(self, uploader, temp_image):
        """Test upload without API client (mock mode)."""
        result = uploader.upload(temp_image)

        assert result['success'] is True
        assert result['url'].startswith("https://ml.com/images/")
        assert result['filename'] == "test_image.jpg"
        assert 'id' in result
        assert 'hash' in result

    def test_upload_with_product_id(self, uploader, temp_image):
        """Test upload with product_id."""
        result = uploader.upload(temp_image, product_id="PROD123")
        assert result['success'] is True

    def test_upload_invalid_image(self, uploader):
        """Test upload with invalid image raises ValueError."""
        with pytest.raises(ValueError, match="Invalid image"):
            uploader.upload("/nonexistent.jpg")

    def test_upload_duplicate_detection(self, uploader, temp_image):
        """Test that duplicate uploads return cached result."""
        result1 = uploader.upload(temp_image)
        result2 = uploader.upload(temp_image)

        assert result1 == result2

    def test_upload_with_api_success(self, uploader_with_api, temp_image):
        """Test upload with successful API call."""
        uploader_with_api.api_client.upload_image.return_value = {
            'url': 'https://api.mercadolivre.com/img/123',
            'id': '123'
        }

        result = uploader_with_api.upload(temp_image)

        assert result['success'] is True
        assert result['url'] == 'https://api.mercadolivre.com/img/123'
        assert result['id'] == '123'
        uploader_with_api.api_client.upload_image.assert_called_once()

    def test_upload_with_api_failure(self, uploader_with_api, temp_image, caplog):
        """Test upload with failed API call."""
        caplog.set_level(logging.ERROR)
        uploader_with_api.api_client.upload_image.side_effect = Exception("API Error")

        result = uploader_with_api.upload(temp_image)

        assert result['success'] is False
        assert "API Error" in result['error']
        assert "API upload failed" in caplog.text

    def test_upload_adds_to_history(self, uploader, temp_image):
        """Test that uploads are tracked in history."""
        assert len(uploader.get_uploaded_images()) == 0
        uploader.upload(temp_image)
        assert len(uploader.get_uploaded_images()) == 1

    # ==================== upload_batch ====================

    def test_upload_batch_success(self, uploader, tmp_path):
        """Test batch upload with valid images."""
        img1 = tmp_path / "img1.jpg"
        img2 = tmp_path / "img2.jpg"
        img1.write_bytes(b'content1')
        img2.write_bytes(b'content2')

        results = uploader.upload_batch([str(img1), str(img2)])

        assert len(results) == 2
        assert all(r['success'] for r in results)

    def test_upload_batch_with_invalid(self, uploader, tmp_path, temp_image):
        """Test batch upload with some invalid images."""
        results = uploader.upload_batch([temp_image, "/nonexistent.jpg"])

        assert len(results) == 2
        assert results[0]['success'] is True
        assert results[1]['success'] is False

    def test_upload_batch_with_product_id(self, uploader, tmp_path):
        """Test batch upload propagates product_id."""
        img = tmp_path / "img.jpg"
        img.write_bytes(b'content')

        results = uploader.upload_batch([str(img)], product_id="PROD123")
        assert results[0]['success'] is True

    # ==================== get_uploaded_images ====================

    def test_get_uploaded_images_returns_copy(self, uploader, temp_image):
        """Test that get_uploaded_images returns a copy."""
        uploader.upload(temp_image)
        images1 = uploader.get_uploaded_images()
        images2 = uploader.get_uploaded_images()

        assert images1 is not images2
        assert images1 == images2

    # ==================== clear_upload_history ====================

    def test_clear_upload_history(self, uploader, temp_image):
        """Test clearing upload history."""
        uploader.upload(temp_image)
        assert len(uploader.get_uploaded_images()) == 1

        uploader.clear_upload_history()
        assert len(uploader.get_uploaded_images()) == 0

    # ==================== delete_local_copy ====================

    def test_delete_local_copy_success(self, uploader, tmp_path):
        """Test successful file deletion."""
        test_file = tmp_path / "to_delete.jpg"
        test_file.write_text("content")

        assert test_file.exists()
        result = uploader.delete_local_copy(str(test_file))

        assert result is True
        assert not test_file.exists()

    def test_delete_local_copy_not_found(self, uploader):
        """Test deletion of non-existent file."""
        result = uploader.delete_local_copy("/nonexistent/file.jpg")
        assert result is False

    def test_delete_local_copy_directory(self, uploader, tmp_path):
        """Test deletion with directory path."""
        result = uploader.delete_local_copy(str(tmp_path))
        assert result is False

    def test_delete_local_copy_os_error(self, uploader, tmp_path, caplog):
        """Test deletion when OS error occurs."""
        caplog.set_level(logging.ERROR)
        test_file = tmp_path / "readonly.jpg"
        test_file.write_text("content")

        with patch.object(Path, 'unlink', side_effect=OSError("Permission denied")):
            result = uploader.delete_local_copy(str(test_file))

        assert result is False
        assert "Failed to delete file" in caplog.text
