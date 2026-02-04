# Type Safety Integration Guide for Clip Upload

This guide shows how to integrate the TypedDict definitions from `mercadolivre_upload/domain/types.py` into the clip upload implementation for improved type safety.

---

## Overview

TypedDicts provide:
- ✅ IDE autocomplete for dict keys
- ✅ Static type checking with mypy
- ✅ Self-documenting code
- ✅ Runtime validation (when used with type checkers)
- ✅ Clearer function signatures

---

## Phase 1: Add Type Hints to Function Signatures

### File: `mercadolivre_upload/api/client.py`

**Current:**
```python
def upload_clip(
    self,
    item_id: str,
    file_path: str,
    sites: list[dict] | None = None,
) -> dict:
```

**Enhanced:**
```python
from mercadolivre_upload.domain.types import ClipSite, ClipUploadResponse

def upload_clip(
    self,
    item_id: str,
    file_path: str,
    sites: list[ClipSite] | None = None,
) -> ClipUploadResponse:
    """Upload a video clip for an item.

    Args:
        item_id: Mercado Livre item ID (e.g., MLB1234567890)
        file_path: Path to video file (mp4, mov, mpeg, avi)
        sites: Optional list of sites for clip visibility.
               If None or empty, clip is uploaded to all available sites.
               Each site dict must contain 'site_id' and 'logistic_type'.

    Returns:
        Upload result with clip UUID and status.
        Example: {"status": "accepted", "clip_uuid": "..."}

    Raises:
        ValueError: If item_id format is invalid
        requests.HTTPError: On API error
    """
```

### File: `mercadolivre_upload/adapters/clip_uploader.py`

**Current:**
```python
def upload_clip_for_item(
    self,
    item_id: str,
    video_path: Path,
    sites: list[dict] | None = None,
) -> str | None:
```

**Enhanced:**
```python
from mercadolivre_upload.domain.types import ClipSite

def upload_clip_for_item(
    self,
    item_id: str,
    video_path: Path,
    sites: list[ClipSite] | None = None,
) -> str | None:
    """Upload a video clip for a published item.

    Args:
        item_id: Mercado Livre item ID (e.g., MLB1234567890)
        video_path: Path to the video file
        sites: Optional list of sites for clip visibility.
               Each site must have 'site_id' (str) and 'logistic_type' (str).
               If None, targets all available sites.

    Returns:
        Clip UUID on success, None on failure
    """
```

### File: `mercadolivre_upload/application/ports.py`

**Current:**
```python
def upload_clip_for_item(
    self, item_id: str, video_path: Path, sites: list[dict] | None = None
) -> str | None:
```

**Enhanced:**
```python
from mercadolivre_upload.domain.types import ClipSite

def upload_clip_for_item(
    self, item_id: str, video_path: Path, sites: list[ClipSite] | None = None
) -> str | None:
    """Upload a video clip for a published item.
    
    Args:
        item_id: Mercado Livre item ID (e.g., MLB1234567890)
        video_path: Path to the video file
        sites: Optional list of sites. Each dict must contain:
               - site_id: str (e.g., "MLB", "MLA")
               - logistic_type: str (e.g., "drop_off", "cross_docking")
    
    Returns:
        Clip UUID on success, None on failure
    """
```

---

## Phase 2: Use TypedDicts in Tests

### File: `tests/test_clip_uploader.py`

**Enhanced Test:**
```python
from mercadolivre_upload.domain.types import ClipSite, ClipUploadResponse

def test_upload_clip_with_sites(self, tmp_path):
    """Test clip upload with specific sites."""
    video_file = tmp_path / "video.mp4"
    video_file.write_bytes(b"fake video")

    # Type-safe site specification
    sites: list[ClipSite] = [
        {"site_id": "MLB", "logistic_type": "drop_off"},
        {"site_id": "MLA", "logistic_type": "drop_off"},
    ]

    mock_client = Mock()
    mock_response: ClipUploadResponse = {
        "status": "accepted",
        "clip_uuid": "550e8400-e29b-41d4-a716-446655440000"
    }
    mock_client.upload_clip.return_value = mock_response

    uploader = ClipUploader(mock_client)

    result = uploader.upload_clip_for_item(
        item_id="MLB999",
        video_path=video_file,
        sites=sites,
    )

    assert result == "550e8400-e29b-41d4-a716-446655440000"
    mock_client.upload_clip.assert_called_once_with(
        item_id="MLB999",
        file_path=str(video_file),
        sites=sites,
    )
```

---

## Phase 3: Add Type Validation Helpers (Optional)

For runtime validation, you can add helper functions:

### File: `mercadolivre_upload/domain/types.py`

```python
def validate_clip_site(site: dict) -> ClipSite:
    """Validate and convert a dict to ClipSite.
    
    Args:
        site: Dictionary with site_id and logistic_type
        
    Returns:
        Validated ClipSite TypedDict
        
    Raises:
        ValueError: If required fields are missing or invalid
    """
    if "site_id" not in site:
        raise ValueError("ClipSite missing required field 'site_id'")
    if "logistic_type" not in site:
        raise ValueError("ClipSite missing required field 'logistic_type'")
    
    if not isinstance(site["site_id"], str):
        raise ValueError(f"site_id must be str, got {type(site['site_id'])}")
    if not isinstance(site["logistic_type"], str):
        raise ValueError(f"logistic_type must be str, got {type(site['logistic_type'])}")
    
    return ClipSite(site_id=site["site_id"], logistic_type=site["logistic_type"])


def validate_clip_upload_response(response: dict) -> ClipUploadResponse:
    """Validate API response matches expected structure.
    
    Args:
        response: Raw API response dict
        
    Returns:
        Validated ClipUploadResponse TypedDict
        
    Raises:
        ValueError: If response is invalid
    """
    if "status" not in response:
        raise ValueError("Response missing required field 'status'")
    if "clip_uuid" not in response:
        raise ValueError("Response missing required field 'clip_uuid'")
    
    status = response["status"]
    if status not in ("accepted", "rejected"):
        raise ValueError(f"Invalid status: {status}. Must be 'accepted' or 'rejected'")
    
    return ClipUploadResponse(status=status, clip_uuid=response["clip_uuid"])
```

### Usage in `clip_uploader.py`:

```python
from mercadolivre_upload.domain.types import validate_clip_upload_response

try:
    result = self.client.upload_clip(
        item_id=item_id,
        file_path=str(video_path),
        sites=sites,
    )
    
    # Validate response structure
    validated_response = validate_clip_upload_response(result)
    
    clip_uuid = validated_response["clip_uuid"]
    status = validated_response["status"]
    
    logger.info(
        f"Clip uploaded successfully for {item_id}: {clip_uuid} (status: {status})"
    )
    return clip_uuid
    
except ValueError as e:
    logger.error(f"Invalid API response for {item_id}: {e}, response: {result}")
    return None
```

---

## Phase 4: Add Future Endpoints with Types

When implementing GET and DELETE clip endpoints:

### File: `mercadolivre_upload/api/client.py`

```python
from mercadolivre_upload.domain.types import (
    ClipListResponse,
    ClipDeleteRequest,
    ClipDeleteResponse,
)

def get_clip_info(self, item_id: str) -> ClipListResponse:
    """Get information about all clips for an item.
    
    Args:
        item_id: Mercado Livre item ID (e.g., MLB1234567890)
        
    Returns:
        Clip information with parent item/user IDs and list of clips
        
    Raises:
        ValueError: If item_id format is invalid
        requests.HTTPError: On API error
    """
    validate_item_id(item_id)
    return self.get(f"/marketplace/items/{item_id}/clips")


def delete_clip(
    self,
    item_id: str,
    clip_uuid: str,
    sites: list[ClipSite] | None = None,
) -> ClipDeleteResponse:
    """Delete a clip from specified sites.
    
    Args:
        item_id: Mercado Livre item ID
        clip_uuid: UUID of clip to delete
        sites: Optional list of sites to delete from. If None, deletes from all sites.
        
    Returns:
        Deletion status response
        
    Raises:
        ValueError: If item_id format is invalid
        requests.HTTPError: On API error
    """
    validate_item_id(item_id)
    
    request_body: ClipDeleteRequest = {
        "sites": sites or []
    }
    
    endpoint = f"/marketplace/items/{item_id}/clips/{clip_uuid}"
    return self.delete(endpoint, json=request_body)
```

---

## Phase 5: Mypy Configuration

To enable static type checking, configure mypy:

### File: `pyproject.toml`

```toml
[tool.mypy]
python_version = "3.11"
warn_return_any = true
warn_unused_configs = true
disallow_untyped_defs = false  # Set to true for stricter checking
no_implicit_optional = true

# Per-module options
[[tool.mypy.overrides]]
module = "mercadolivre_upload.api.*"
disallow_untyped_defs = true

[[tool.mypy.overrides]]
module = "mercadolivre_upload.domain.*"
disallow_untyped_defs = true
```

### Run Type Checking

```bash
# Check all files
mypy mercadolivre_upload/

# Check specific module
mypy mercadolivre_upload/api/client.py

# Check with strict mode
mypy --strict mercadolivre_upload/domain/types.py
```

---

## Benefits Demonstration

### Before (No Type Safety)

```python
# No IDE autocomplete
sites = [{"site": "MLB", "type": "drop_off"}]  # Typo: 'site' should be 'site_id'

# No type checking
result = client.upload_clip("MLB123", "video.mp4", sites)
clip_id = result["id"]  # Wrong key, but no warning

# Runtime error only discovered in production!
```

### After (With Type Safety)

```python
# IDE autocomplete suggests 'site_id' and 'logistic_type'
sites: list[ClipSite] = [
    {"site_id": "MLB", "logistic_type": "drop_off"}  # IDE catches typos
]

# Type checker validates response structure
result: ClipUploadResponse = client.upload_clip("MLB123", "video.mp4", sites)
clip_id = result["clip_uuid"]  # IDE knows this field exists

# Errors caught at development time!
```

---

## IDE Support

### VS Code

Install Python extension and add to `settings.json`:

```json
{
    "python.linting.mypyEnabled": true,
    "python.linting.enabled": true,
    "python.analysis.typeCheckingMode": "basic"
}
```

### PyCharm

PyCharm has built-in type checking. Enable in:
- **Settings** → **Editor** → **Inspections** → **Python** → **Type Checker**

---

## Testing Type Safety

### File: `tests/test_types.py` (NEW)

```python
"""Tests for type definitions and validation."""

import pytest
from mercadolivre_upload.domain.types import (
    ClipSite,
    ClipUploadResponse,
    validate_clip_site,
    validate_clip_upload_response,
)


class TestClipSite:
    """Tests for ClipSite TypedDict."""
    
    def test_valid_clip_site(self):
        """Test valid clip site structure."""
        site: ClipSite = {
            "site_id": "MLB",
            "logistic_type": "drop_off"
        }
        
        validated = validate_clip_site(site)
        assert validated["site_id"] == "MLB"
        assert validated["logistic_type"] == "drop_off"
    
    def test_missing_site_id(self):
        """Test validation fails for missing site_id."""
        with pytest.raises(ValueError, match="site_id"):
            validate_clip_site({"logistic_type": "drop_off"})
    
    def test_missing_logistic_type(self):
        """Test validation fails for missing logistic_type."""
        with pytest.raises(ValueError, match="logistic_type"):
            validate_clip_site({"site_id": "MLB"})


class TestClipUploadResponse:
    """Tests for ClipUploadResponse TypedDict."""
    
    def test_valid_response(self):
        """Test valid upload response."""
        response: ClipUploadResponse = {
            "status": "accepted",
            "clip_uuid": "550e8400-e29b-41d4-a716-446655440000"
        }
        
        validated = validate_clip_upload_response(response)
        assert validated["status"] == "accepted"
        assert validated["clip_uuid"] == "550e8400-e29b-41d4-a716-446655440000"
    
    def test_rejected_status(self):
        """Test response with rejected status."""
        response = {
            "status": "rejected",
            "clip_uuid": "test-uuid"
        }
        
        validated = validate_clip_upload_response(response)
        assert validated["status"] == "rejected"
    
    def test_missing_status(self):
        """Test validation fails for missing status."""
        with pytest.raises(ValueError, match="status"):
            validate_clip_upload_response({"clip_uuid": "test"})
    
    def test_missing_clip_uuid(self):
        """Test validation fails for missing clip_uuid."""
        with pytest.raises(ValueError, match="clip_uuid"):
            validate_clip_upload_response({"status": "accepted"})
    
    def test_invalid_status(self):
        """Test validation fails for invalid status value."""
        with pytest.raises(ValueError, match="Invalid status"):
            validate_clip_upload_response({
                "status": "pending",
                "clip_uuid": "test"
            })
```

---

## Migration Checklist

- [ ] Add TypedDict definitions to `mercadolivre_upload/domain/types.py`
- [ ] Update function signatures in `api/client.py`
- [ ] Update function signatures in `adapters/clip_uploader.py`
- [ ] Update protocol in `application/ports.py`
- [ ] Add validation helpers (optional)
- [ ] Update tests to use typed dicts
- [ ] Configure mypy in `pyproject.toml`
- [ ] Run mypy and fix any type errors
- [ ] Update IDE settings for type checking
- [ ] Add type validation tests
- [ ] Document type requirements in README

---

## Common Type Issues and Solutions

### Issue: "Incompatible types in assignment"

```python
# Problem:
sites: list[ClipSite] = [
    {"site_id": "MLB"}  # Missing logistic_type
]

# Solution:
sites: list[ClipSite] = [
    {"site_id": "MLB", "logistic_type": "drop_off"}
]
```

### Issue: "TypedDict expects exact keys"

```python
# Problem:
site: ClipSite = {
    "site_id": "MLB",
    "logistic_type": "drop_off",
    "extra_field": "value"  # Extra key not in TypedDict
}

# Solution: Only include defined keys
site: ClipSite = {
    "site_id": "MLB",
    "logistic_type": "drop_off"
}
```

### Issue: "Optional vs Required fields"

```python
# Use NotRequired for optional fields
class ClipMetadata(TypedDict):
    site_id: str  # Required
    moderation_status: str  # Required
    reject_reason: NotRequired[str]  # Optional
```

---

## Summary

Type safety integration:
1. **Zero runtime overhead** - TypedDicts are just dicts at runtime
2. **Catch errors early** - Development time instead of production
3. **Better documentation** - Self-documenting function signatures
4. **IDE support** - Autocomplete and inline documentation
5. **Optional adoption** - Can be added incrementally

**Recommendation:** Apply type hints to public API methods first, then gradually to internal methods.
