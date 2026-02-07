"""Tests for ClipUploader adapter."""

from pathlib import Path
from unittest.mock import Mock

from mercadolivre_upload.adapters.clip_uploader import (
    ClipUploader,
)
from mercadolivre_upload.domain.validation.clip_validator import SUPPORTED_EXTENSIONS


class TestClipUploader:
    """Tests for ClipUploader class."""

    def test_supported_extensions(self):
        """Test that supported extensions are defined correctly."""
        assert ".mp4" in SUPPORTED_EXTENSIONS
        assert ".mov" in SUPPORTED_EXTENSIONS
        assert ".mpeg" in SUPPORTED_EXTENSIONS
        assert ".avi" in SUPPORTED_EXTENSIONS

    def test_upload_clip_file_not_found(self):
        """Test upload fails gracefully when file doesn't exist."""
        mock_client = Mock()
        uploader = ClipUploader(mock_client)

        result = uploader.upload_clip_for_item(
            item_id="MLB123",
            video_path=Path("/nonexistent/video.mp4"),
        )

        assert result.status == "validation_failed"
        assert result.clip_uuid is None
        mock_client.upload_clip.assert_not_called()

    def test_upload_clip_unsupported_extension(self, tmp_path):
        """Test upload fails for unsupported file extensions."""
        video_file = tmp_path / "video.txt"
        video_file.write_text("not a video")

        mock_client = Mock()
        uploader = ClipUploader(mock_client)

        result = uploader.upload_clip_for_item(
            item_id="MLB123",
            video_path=video_file,
        )

        assert result.status == "validation_failed"
        assert result.clip_uuid is None
        mock_client.upload_clip.assert_not_called()

    def test_upload_clip_success(self, tmp_path):
        """Test successful clip upload using 'clip_uuid' key."""
        video_file = tmp_path / "video.mp4"
        video_file.write_bytes(b"fake video content")

        mock_client = Mock()
        mock_client.upload_clip.return_value = {
            "clip_uuid": "clip-uuid-123",
            "status": "accepted",
        }

        uploader = ClipUploader(mock_client)

        result = uploader.upload_clip_for_item(
            item_id="MLB999",
            video_path=video_file,
        )

        assert result.clip_uuid == "clip-uuid-123"
        assert result.status == "accepted"
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

        assert result.clip_uuid == "uuid-456"

    def test_upload_clip_with_legacy_keys_rejected(self, tmp_path):
        """Ensure old response keys (id, uuid, clip_id) are NOT accepted."""
        video_file = tmp_path / "video.avi"
        video_file.write_bytes(b"fake video")

        mock_client = Mock()
        mock_client.upload_clip.return_value = {"id": "legacy-id"}

        uploader = ClipUploader(mock_client)

        result = uploader.upload_clip_for_item(
            item_id="MLB999",
            video_path=video_file,
        )

        assert result.clip_uuid is None
        assert result.status == "error"

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

        assert result.clip_uuid is None
        assert result.status == "error"
        assert "API Error" in result.error

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

        assert result.clip_uuid is None


class TestFindClipsForSku:
    """Tests for clip discovery in SKU directories."""

    def test_find_clips_in_sku_folder(self, tmp_path):
        """Test finding videos in SKU-specific folder."""
        sku_folder = tmp_path / "SKU123"
        sku_folder.mkdir()
        video_file = sku_folder / "product_video.mp4"
        video_file.write_bytes(b"video")

        uploader = ClipUploader(Mock(), base_path=tmp_path)
        clips = uploader.find_clips_for_sku("SKU123")

        assert len(clips) == 1
        assert clips[0] == video_file

    def test_find_multiple_clips(self, tmp_path):
        """Test finding multiple video files."""
        sku_folder = tmp_path / "SKU123"
        sku_folder.mkdir()
        (sku_folder / "video1.mp4").write_bytes(b"video1")
        (sku_folder / "video2.mov").write_bytes(b"video2")
        (sku_folder / "image.jpg").write_bytes(b"not a video")

        uploader = ClipUploader(Mock(), base_path=tmp_path)
        clips = uploader.find_clips_for_sku("SKU123")

        assert len(clips) == 2

    def test_find_no_clips(self, tmp_path):
        """Test when no video files exist."""
        sku_folder = tmp_path / "SKU123"
        sku_folder.mkdir()
        (sku_folder / "image.jpg").write_bytes(b"image")

        uploader = ClipUploader(Mock(), base_path=tmp_path)
        clips = uploader.find_clips_for_sku("SKU123")

        assert len(clips) == 0

    def test_find_clips_nonexistent_sku(self, tmp_path):
        """Test with nonexistent SKU directory."""
        uploader = ClipUploader(Mock(), base_path=tmp_path)
        clips = uploader.find_clips_for_sku("NONEXISTENT")

        assert len(clips) == 0


class TestUploadClips:
    """Tests for bulk clip upload."""

    def test_upload_clips_no_videos(self, tmp_path):
        """Test upload_clips with no videos found."""
        mock_client = Mock()
        uploader = ClipUploader(mock_client, base_path=tmp_path)

        summary = uploader.upload_clips("SKU123", "MLB999")

        assert summary.item_id == "MLB999"
        assert summary.clips_uploaded == 0
        assert summary.clips_failed == 0
        assert len(summary.results) == 0

    def test_upload_clips_success(self, tmp_path):
        """Test successful bulk clip upload."""
        sku_folder = tmp_path / "SKU123"
        sku_folder.mkdir()
        (sku_folder / "video1.mp4").write_bytes(b"video content 1")
        (sku_folder / "video2.mov").write_bytes(b"video content 2")

        mock_client = Mock()
        mock_client.upload_clip.return_value = {
            "clip_uuid": "uuid-1",
            "status": "accepted",
        }

        uploader = ClipUploader(mock_client, base_path=tmp_path)
        summary = uploader.upload_clips("SKU123", "CBT1234567890")

        assert summary.clips_uploaded == 2
        assert summary.clips_failed == 0
        assert len(summary.results) == 2

    def test_upload_clips_dedup(self, tmp_path):
        """Test that duplicate videos are skipped."""
        sku_folder = tmp_path / "SKU123"
        sku_folder.mkdir()
        # Same content = same hash
        (sku_folder / "video1.mp4").write_bytes(b"same content")
        (sku_folder / "video2.mov").write_bytes(b"same content")

        mock_client = Mock()
        mock_client.upload_clip.return_value = {
            "clip_uuid": "uuid-1",
            "status": "accepted",
        }

        uploader = ClipUploader(mock_client, base_path=tmp_path)
        summary = uploader.upload_clips("SKU123", "CBT1234567890")

        assert summary.clips_uploaded == 1
        assert summary.clips_skipped == 1
        assert mock_client.upload_clip.call_count == 1

    def test_upload_clips_rejects_non_cbt_item_id(self, tmp_path):
        """Test that non-CBT item IDs are rejected with warning."""
        sku_folder = tmp_path / "SKU123"
        sku_folder.mkdir()
        (sku_folder / "video1.mp4").write_bytes(b"video content")

        mock_client = Mock()
        uploader = ClipUploader(mock_client, base_path=tmp_path)

        # Test with marketplace-specific ID
        summary = uploader.upload_clips("SKU123", "MLB1234567890")

        assert summary.clips_uploaded == 0
        assert summary.clips_failed == 0
        assert summary.clips_skipped == 0
        assert len(summary.results) == 0
        # Should not have called API
        mock_client.upload_clip.assert_not_called()
