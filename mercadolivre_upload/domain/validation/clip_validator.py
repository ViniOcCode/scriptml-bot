"""Clip validation for Mercado Livre video uploads.

Validates video files against ML API requirements:
- Format: MP4, MOV, MPEG, AVI
- Size: max 280 MB
- Duration: 10-61 seconds (requires ffprobe)
- Resolution: min 360x640 pixels (requires ffprobe)
"""

import json
import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".mp4", ".mov", ".mpeg", ".avi"}
MAX_FILE_SIZE_BYTES = 280 * 1024 * 1024  # 280 MB
MIN_DURATION_SECONDS = 10
MAX_DURATION_SECONDS = 61
MIN_WIDTH = 360
MIN_HEIGHT = 640


@dataclass
class VideoProperties:
    """Extracted video metadata."""

    duration: float | None = None
    width: int | None = None
    height: int | None = None
    size_bytes: int = 0


@dataclass
class ClipValidationResult:
    """Result of clip validation."""

    is_valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    properties: VideoProperties | None = None


class ClipValidator:
    """Validates video files against Mercado Livre clip requirements."""

    def __init__(self, ffprobe_path: str = "ffprobe"):
        """Initialize with optional ffprobe path."""
        self._ffprobe_path = ffprobe_path
        self._ffprobe_available: bool | None = None

    @property
    def ffprobe_available(self) -> bool:
        """Check if ffprobe is available on the system (cached)."""
        if self._ffprobe_available is None:
            try:
                subprocess.run(  # noqa: S603
                    [self._ffprobe_path, "-version"],
                    capture_output=True,
                    timeout=5,
                )
                self._ffprobe_available = True
            except (FileNotFoundError, subprocess.TimeoutExpired):
                self._ffprobe_available = False
        return self._ffprobe_available

    def validate(self, path: Path) -> ClipValidationResult:
        """Validate a video file against all ML requirements.

        Args:
            path: Path to video file

        Returns:
            ClipValidationResult with is_valid, errors, warnings, and properties
        """
        errors: list[str] = []
        warnings: list[str] = []

        if not path.exists():
            return ClipValidationResult(is_valid=False, errors=[f"File not found: {path}"])

        # Format validation
        errors.extend(self._validate_format(path))

        # Size validation
        size_bytes = path.stat().st_size
        errors.extend(self._validate_size(path, size_bytes))

        # Video properties (duration, resolution) via ffprobe
        properties = VideoProperties(size_bytes=size_bytes)
        if self.ffprobe_available:
            props = self._probe_video(path)
            if props:
                properties = props
                properties.size_bytes = size_bytes
                errors.extend(self._validate_duration(properties))
                errors.extend(self._validate_resolution(properties))
        else:
            warnings.append(
                "ffprobe not available — skipping duration/resolution validation. "
                "Install ffmpeg for full validation."
            )

        return ClipValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            properties=properties,
        )

    def _validate_format(self, path: Path) -> list[str]:
        """Check file extension."""
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            return [
                f"Unsupported format '{path.suffix}'. "
                f"Allowed: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
            ]
        return []

    def _validate_size(self, path: Path, size_bytes: int) -> list[str]:
        """Check file size."""
        if size_bytes > MAX_FILE_SIZE_BYTES:
            size_mb = size_bytes / (1024 * 1024)
            return [f"File too large: {size_mb:.1f} MB (max: 280 MB)"]
        if size_bytes == 0:
            return ["File is empty"]
        return []

    def _validate_duration(self, props: VideoProperties) -> list[str]:
        """Check video duration."""
        if props.duration is None:
            return []
        if props.duration < MIN_DURATION_SECONDS:
            return [f"Video too short: {props.duration:.1f}s " f"(min: {MIN_DURATION_SECONDS}s)"]
        if props.duration > MAX_DURATION_SECONDS:
            return [f"Video too long: {props.duration:.1f}s " f"(max: {MAX_DURATION_SECONDS}s)"]
        return []

    def _validate_resolution(self, props: VideoProperties) -> list[str]:
        """Check video resolution."""
        if props.width is None or props.height is None:
            return []
        if props.width < MIN_WIDTH or props.height < MIN_HEIGHT:
            return [
                f"Resolution too low: {props.width}x{props.height} "
                f"(min: {MIN_WIDTH}x{MIN_HEIGHT})"
            ]
        return []

    def _probe_video(self, path: Path) -> VideoProperties | None:
        """Extract video properties using ffprobe."""
        try:
            result = subprocess.run(  # noqa: S603
                [
                    self._ffprobe_path,
                    "-v",
                    "error",
                    "-select_streams",
                    "v:0",
                    "-show_entries",
                    "stream=duration,width,height",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "json",
                    str(path),
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                logger.warning(f"ffprobe failed for {path}: {result.stderr}")
                return None

            data = json.loads(result.stdout)
            stream = data.get("streams", [{}])[0] if data.get("streams") else {}
            fmt = data.get("format", {})

            duration = stream.get("duration") or fmt.get("duration")
            return VideoProperties(
                duration=float(duration) if duration else None,
                width=stream.get("width"),
                height=stream.get("height"),
            )
        except (subprocess.TimeoutExpired, json.JSONDecodeError, IndexError) as e:
            logger.warning(f"Failed to probe video {path}: {e}")
            return None
