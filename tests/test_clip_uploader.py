"""Tests for ClipUploader adapter."""

from pathlib import Path
from unittest.mock import Mock

from mercadolivre_upload.adapters.clip_uploader import (
    SUPPORTED_VIDEO_EXTENSIONS,
    ClipUploader,
)


class TestClipUploader:
    """Tests for ClipUploader class."""

    def test_supported_extensions(self):
        """Test that supported extensions are defined correctly."""
        assert ".mp4" in SUPPORTED_VIDEO_EXTENSIONS
        assert ".mov" in SUPPORTED_VIDEO_EXTENSIONS
        assert ".mpeg" in SUPPORTED_VIDEO_EXTENSIONS
        assert ".avi" in SUPPORTED_VIDEO_EXTENSIONS

    def test_upload_clip_file_not_found(self):
        """Test upload fails gracefully when file doesn't exist."""
        mock_client = Mock()
        uploader = ClipUploader(mock_client)

        result = uploader.upload_clip_for_item(
            item_id="MLB123",
            video_path=Path("/nonexistent/video.mp4"),
        )

        assert result is None
        mock_client.upload_clip.assert_not_called()

    def test_upload_clip_unsupported_extension(self, tmp_path):
        """Test upload fails for unsupported file extensions."""
        # Create a file with unsupported extension
        video_file = tmp_path / "video.txt"
        video_file.write_text("not a video")

        mock_client = Mock()
        uploader = ClipUploader(mock_client)

        result = uploader.upload_clip_for_item(
            item_id="MLB123",
            video_path=video_file,
        )

        assert result is None
        mock_client.upload_clip.assert_not_called()

    def test_upload_clip_success(self, tmp_path):
        """Test successful clip upload using 'clip_uuid' key."""
        # Create a mock video file
        video_file = tmp_path / "video.mp4"
        video_file.write_bytes(b"fake video content")

        mock_client = Mock()
        mock_client.upload_clip.return_value = {"clip_uuid": "clip-uuid-123"}

        uploader = ClipUploader(mock_client)

        result = uploader.upload_clip_for_item(
            item_id="MLB999",
            video_path=video_file,
        )

        assert result == "clip-uuid-123"
        mock_client.upload_clip.assert_called_once_with(
            item_id="MLB999",
            file_path=str(video_file),
            sites=None,
        )

    def test_upload_clip_with_clip_uuid_key(self, tmp_path):
        """Test clip upload when API returns 'clip_uuid' key."""
        video_file = tmp_path / "video.mov"
        video_file.write_bytes(b"fake video")

        mock_client = Mock()
        mock_client.upload_clip.return_value = {"clip_uuid": "uuid-456"}

        uploader = ClipUploader(mock_client)

        result = uploader.upload_clip_for_item(
            item_id="MLB999",
            video_path=video_file,
        )

        assert result == "uuid-456"

    def test_upload_clip_with_legacy_keys_rejected(self, tmp_path):
        """Ensure old response keys (id, uuid, clip_id) are NOT accepted and treated as missing."""
        video_file = tmp_path / "video.avi"
        video_file.write_bytes(b"fake video")

        mock_client = Mock()
        mock_client.upload_clip.return_value = {"id": "legacy-id"}

        uploader = ClipUploader(mock_client)

        result = uploader.upload_clip_for_item(
            item_id="MLB999",
            video_path=video_file,
        )

        assert result is None

    def test_upload_clip_api_error(self, tmp_path):
        """Test clip upload handles API errors gracefully."""
        video_file = tmp_path / "video.mp4"
        video_file.write_bytes(b"fake video")

        mock_client = Mock()
        mock_client.upload_clip.side_effect = Exception("API Error")

        uploader = ClipUploader(mock_client)

        result = uploader.upload_clip_for_item(
            item_id="MLB999",
            video_path=video_file,
        )

        assert result is None

    def test_upload_clip_no_uuid_in_response(self, tmp_path):
        """Test clip upload when response has no UUID field."""
        video_file = tmp_path / "video.mp4"
        video_file.write_bytes(b"fake video")

        mock_client = Mock()
        mock_client.upload_clip.return_value = {"status": "ok"}

        uploader = ClipUploader(mock_client)

        result = uploader.upload_clip_for_item(
            item_id="MLB999",
            video_path=video_file,
        )

        assert result is None


class TestFindVideoFile:
    """Tests for find_video_file static method."""

    def test_find_video_in_sku_folder(self, tmp_path):
        """Test finding video in SKU-specific folder."""
        sku_folder = tmp_path / "SKU123"
        sku_folder.mkdir()
        video_file = sku_folder / "product_video.mp4"
        video_file.write_bytes(b"video")

        result = ClipUploader.find_video_file(tmp_path, sku="SKU123")

        assert result == video_file

    def test_find_video_fallback_to_base(self, tmp_path):
        """Test fallback to base directory when SKU folder doesn't exist."""
        video_file = tmp_path / "default_video.mp4"
        video_file.write_bytes(b"video")

        result = ClipUploader.find_video_file(tmp_path, sku="NONEXISTENT")

        assert result == video_file

    def test_find_video_no_sku(self, tmp_path):
        """Test finding video without SKU specified."""
        video_file = tmp_path / "video.mov"
        video_file.write_bytes(b"video")

        result = ClipUploader.find_video_file(tmp_path)

        assert result == video_file

    def test_find_video_no_video_found(self, tmp_path):
        """Test when no video file exists."""
        # Create only non-video files
        (tmp_path / "image.jpg").write_bytes(b"image")
        (tmp_path / "document.txt").write_text("text")

        result = ClipUploader.find_video_file(tmp_path)

        assert result is None

    def test_find_video_nonexistent_directory(self):
        """Test with nonexistent directory."""
        result = ClipUploader.find_video_file(Path("/nonexistent"))

        assert result is None
