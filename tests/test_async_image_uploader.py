"""
Tests for async_image_uploader.py - 100% coverage.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from mercadolivre_upload.adapters.async_image_uploader import AsyncImageUploader


class AsyncContextManager:
    """Helper class to create async context managers for mocking."""
    def __init__(self, return_value):
        self.return_value = return_value

    async def __aenter__(self):
        return self.return_value

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return False


class TestAsyncImageUploader:
    """Test cases for AsyncImageUploader class."""

    @pytest.fixture
    def temp_image(self, tmp_path):
        """Create a temporary image file."""
        img_path = tmp_path / "test_image.jpg"
        img_path.write_bytes(b'\xff\xd8\xff\xe0test_content')
        return str(img_path)

    @pytest.fixture
    def temp_images(self, tmp_path):
        """Create multiple temporary image files."""
        paths = []
        for i in range(3):
            img_path = tmp_path / f"test_image_{i}.jpg"
            img_path.write_bytes(f'content{i}'.encode())
            paths.append(str(img_path))
        return paths

    # ==================== Initialization ====================

    def test_init_default(self):
        """Test default initialization."""
        uploader = AsyncImageUploader()
        assert uploader.api_base_url == "https://api.mercadolivre.com"
        assert uploader.max_concurrent == 5
        assert uploader.timeout == 30
        assert uploader._session is None
        assert uploader._upload_results == []

    def test_init_custom_params(self):
        """Test initialization with custom parameters."""
        uploader = AsyncImageUploader(
            api_base_url="https://custom.api.com",
            max_concurrent=10,
            timeout=60
        )
        assert uploader.api_base_url == "https://custom.api.com"
        assert uploader.max_concurrent == 10
        assert uploader.timeout == 60

    # ==================== _get_session ====================

    @pytest.mark.asyncio
    async def test_get_session_creates_new(self):
        """Test that session is created when None."""
        uploader = AsyncImageUploader()
        assert uploader._session is None

        session = await uploader._get_session()
        assert session is not None
        assert not session.closed

        await uploader.close()

    @pytest.mark.asyncio
    async def test_get_session_reuses_existing(self):
        """Test that existing session is reused."""
        uploader = AsyncImageUploader()
        session1 = await uploader._get_session()
        session2 = await uploader._get_session()

        assert session1 is session2

        await uploader.close()

    @pytest.mark.asyncio
    async def test_get_session_recreate_closed(self):
        """Test that new session is created if closed."""
        uploader = AsyncImageUploader()
        session1 = await uploader._get_session()
        await session1.close()

        session2 = await uploader._get_session()
        assert session2 is not session1
        assert not session2.closed

        await uploader.close()

    # ==================== validate_image_async ====================

    @pytest.mark.asyncio
    async def test_validate_image_async_success(self, temp_image):
        """Test async validation with valid image."""
        uploader = AsyncImageUploader()
        result = await uploader.validate_image_async(temp_image)
        assert result is True
        await uploader.close()

    @pytest.mark.asyncio
    async def test_validate_image_async_not_found(self, caplog):
        """Test async validation with non-existent file."""
        caplog.set_level("ERROR")
        uploader = AsyncImageUploader()
        result = await uploader.validate_image_async("/nonexistent.jpg")
        assert result is False
        assert "Image not found" in caplog.text
        await uploader.close()

    @pytest.mark.asyncio
    async def test_validate_image_async_not_file(self, tmp_path, caplog):
        """Test async validation with directory."""
        caplog.set_level("ERROR")
        uploader = AsyncImageUploader()
        result = await uploader.validate_image_async(str(tmp_path))
        assert result is False
        assert "Path is not a file" in caplog.text
        await uploader.close()

    @pytest.mark.asyncio
    async def test_validate_image_async_invalid_extension(self, tmp_path, caplog):
        """Test async validation with invalid extension."""
        caplog.set_level("ERROR")
        uploader = AsyncImageUploader()
        invalid = tmp_path / "test.txt"
        invalid.write_text("content")
        result = await uploader.validate_image_async(str(invalid))
        assert result is False
        assert "Invalid image extension" in caplog.text
        await uploader.close()

    @pytest.mark.asyncio
    async def test_validate_image_async_too_large(self, tmp_path, caplog):
        """Test async validation with oversized image."""
        caplog.set_level("ERROR")
        uploader = AsyncImageUploader()
        large = tmp_path / "large.jpg"
        large.write_bytes(b'x' * (11 * 1024 * 1024))
        result = await uploader.validate_image_async(str(large))
        assert result is False
        assert "Image too large" in caplog.text
        await uploader.close()

    # ==================== read_image_async ====================

    @pytest.mark.asyncio
    async def test_read_image_async(self, temp_image):
        """Test async image reading."""
        uploader = AsyncImageUploader()
        content = await uploader.read_image_async(temp_image)
        assert content == b'\xff\xd8\xff\xe0test_content'
        await uploader.close()

    # ==================== upload_single ====================

    @pytest.mark.asyncio
    async def test_upload_single_invalid_image(self, temp_image):
        """Test upload with invalid validation result."""
        uploader = AsyncImageUploader()
        with patch.object(uploader, 'validate_image_async', return_value=False):
            result = await uploader.upload_single(temp_image)

        assert result['success'] is False
        assert "Invalid image" in result['error']
        await uploader.close()

    @pytest.mark.asyncio
    async def test_upload_single_read_error(self, temp_image, caplog):
        """Test upload when file read fails."""
        caplog.set_level("ERROR")
        uploader = AsyncImageUploader()
        with patch.object(uploader, 'read_image_async', side_effect=OSError("Read failed")):
            result = await uploader.upload_single(temp_image)

        assert result['success'] is False
        assert "Read failed" in result['error']
        await uploader.close()

    @pytest.mark.asyncio
    async def test_upload_single_success(self, temp_image):
        """Test successful upload."""
        uploader = AsyncImageUploader()

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={'url': 'https://example.com/img.jpg', 'id': '123'})

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=AsyncContextManager(mock_response))

        with patch.object(uploader, '_get_session', return_value=mock_session):
            result = await uploader.upload_single(temp_image)

        assert result['success'] is True
        assert result['url'] == 'https://example.com/img.jpg'
        await uploader.close()

    @pytest.mark.asyncio
    async def test_upload_single_unauthorized(self, temp_image):
        """Test upload with 401 response."""
        uploader = AsyncImageUploader()

        mock_response = AsyncMock()
        mock_response.status = 401

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=AsyncContextManager(mock_response))

        with patch.object(uploader, '_get_session', return_value=mock_session):
            result = await uploader.upload_single(temp_image)

        assert result['success'] is False
        assert result['error'] == 'Unauthorized'
        await uploader.close()

    @pytest.mark.asyncio
    async def test_upload_single_too_large(self, temp_image):
        """Test upload with 413 response."""
        uploader = AsyncImageUploader()

        mock_response = AsyncMock()
        mock_response.status = 413

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=AsyncContextManager(mock_response))

        with patch.object(uploader, '_get_session', return_value=mock_session):
            result = await uploader.upload_single(temp_image)

        assert result['success'] is False
        assert result['error'] == 'File too large'
        await uploader.close()

    @pytest.mark.asyncio
    async def test_upload_single_other_error(self, temp_image):
        """Test upload with other HTTP error."""
        uploader = AsyncImageUploader()

        mock_response = AsyncMock()
        mock_response.status = 500

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=AsyncContextManager(mock_response))

        with patch.object(uploader, '_get_session', return_value=mock_session):
            result = await uploader.upload_single(temp_image)

        assert result['success'] is False
        assert "HTTP 500" in result['error']
        await uploader.close()

    @pytest.mark.asyncio
    async def test_upload_single_timeout(self, temp_image, caplog):
        """Test upload with timeout."""
        caplog.set_level("ERROR")
        uploader = AsyncImageUploader()

        mock_session = MagicMock()
        mock_session.post = MagicMock(side_effect=TimeoutError())

        with patch.object(uploader, '_get_session', return_value=mock_session):
            result = await uploader.upload_single(temp_image)

        assert result['success'] is False
        assert result['error'] == 'Timeout'
        assert "Upload timeout" in caplog.text
        await uploader.close()

    @pytest.mark.asyncio
    async def test_upload_single_client_error(self, temp_image, caplog):
        """Test upload with client error."""
        caplog.set_level("ERROR")
        uploader = AsyncImageUploader()

        mock_session = MagicMock()
        mock_session.post = MagicMock(side_effect=aiohttp.ClientError("Connection failed"))

        with patch.object(uploader, '_get_session', return_value=mock_session):
            result = await uploader.upload_single(temp_image)

        assert result['success'] is False
        assert "Client error" in result['error']
        assert "Upload failed" in caplog.text
        await uploader.close()

    @pytest.mark.asyncio
    async def test_upload_single_unexpected_error(self, temp_image, caplog):
        """Test upload with unexpected error."""
        caplog.set_level("ERROR")
        uploader = AsyncImageUploader()

        mock_session = MagicMock()
        mock_session.post = MagicMock(side_effect=RuntimeError("Unexpected"))

        with patch.object(uploader, '_get_session', return_value=mock_session):
            result = await uploader.upload_single(temp_image)

        assert result['success'] is False
        assert "Unexpected" in result['error']
        assert "Unexpected error" in caplog.text
        await uploader.close()

    @pytest.mark.asyncio
    async def test_upload_single_with_auth_token(self, temp_image):
        """Test upload with authentication token."""
        uploader = AsyncImageUploader()

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={'url': 'https://example.com/img.jpg', 'id': '123'})

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=AsyncContextManager(mock_response))

        with patch.object(uploader, '_get_session', return_value=mock_session):
            await uploader.upload_single(temp_image, auth_token="secret_token")

        call_kwargs = mock_session.post.call_args[1]
        assert call_kwargs['headers']['Authorization'] == 'Bearer secret_token'
        await uploader.close()

    @pytest.mark.asyncio
    async def test_upload_single_with_product_id(self, temp_image):
        """Test upload with product_id."""
        uploader = AsyncImageUploader()

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={'url': 'https://example.com/img.jpg', 'id': '123'})

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=AsyncContextManager(mock_response))

        with patch.object(uploader, '_get_session', return_value=mock_session):
            result = await uploader.upload_single(temp_image, product_id="PROD123")

        assert result['success'] is True
        await uploader.close()

    # ==================== upload_batch ====================

    @pytest.mark.asyncio
    async def test_upload_batch_success(self, temp_images):
        """Test batch upload with all successes."""
        uploader = AsyncImageUploader()

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={'url': 'https://example.com/img.jpg', 'id': '123'})

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=AsyncContextManager(mock_response))

        with patch.object(uploader, '_get_session', return_value=mock_session):
            results = await uploader.upload_batch(temp_images)

        assert len(results) == 3
        assert all(r['success'] for r in results)
        await uploader.close()

    @pytest.mark.asyncio
    async def test_upload_batch_with_exception(self, tmp_path):
        """Test batch upload when exception is raised."""
        uploader = AsyncImageUploader()
        img = tmp_path / "test.jpg"
        img.write_bytes(b'content')

        with patch.object(uploader, 'upload_single', side_effect=Exception("Test error")):
            results = await uploader.upload_batch([str(img)])

        assert len(results) == 1
        assert results[0]['success'] is False
        assert "Test error" in results[0]['error']
        await uploader.close()

    # ==================== close ====================

    @pytest.mark.asyncio
    async def test_close_session(self):
        """Test closing session."""
        uploader = AsyncImageUploader()
        session = await uploader._get_session()

        assert not session.closed
        await uploader.close()
        assert session.closed

    @pytest.mark.asyncio
    async def test_close_no_session(self):
        """Test closing when no session exists."""
        uploader = AsyncImageUploader()
        assert uploader._session is None
        await uploader.close()  # Should not raise
        assert uploader._session is None

    @pytest.mark.asyncio
    async def test_close_already_closed(self):
        """Test closing already closed session."""
        uploader = AsyncImageUploader()
        session = await uploader._get_session()
        await session.close()

        # In this case, the session is closed but _session still references it
        # The close() method should set _session to None
        await uploader.close()
        # After close, _session should be None since session.closed is True
        assert uploader._session is None

    # ==================== get_results ====================

    @pytest.mark.asyncio
    async def test_get_returns_copy(self, temp_image):
        """Test that get_results returns a copy."""
        uploader = AsyncImageUploader()
        uploader._upload_results.append({'test': 'data'})

        results1 = uploader.get_results()
        results2 = uploader.get_results()

        assert results1 is not results2
        assert results1 == results2
        await uploader.close()

    # ==================== Context Manager ====================

    @pytest.mark.asyncio
    async def test_context_manager(self):
        """Test async context manager."""
        async with AsyncImageUploader() as uploader:
            assert isinstance(uploader, AsyncImageUploader)
        # Session should be closed after exit

    @pytest.mark.asyncio
    async def test_context_manager_with_exception(self):
        """Test context manager with exception."""
        with pytest.raises(ValueError):
            async with AsyncImageUploader() as uploader:
                raise ValueError("Test")
