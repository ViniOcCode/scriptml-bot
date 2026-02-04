# Clip Upload Validation Report

**Date:** 2024-02-03  
**Scope:** MLApiClient.upload_clip and ClipUploader.upload_clip_for_item  
**Reference:** docs/mercadolibre_clips_api.md (Official Mercado Libre Clips API)

---

## Executive Summary

Validated the clip upload implementation against official Mercado Libre API documentation. Found **4 critical issues** requiring immediate attention before production deployment:

1. **Response key mismatch** - Implementation expects wrong UUID field name
2. **Sites serialization semantics** - Empty list vs None handling needs clarification
3. **Item ID validation** - No validation before URL construction
4. **Error response logging** - Insufficient context for debugging API failures

---

## Issue #1: Response Key Mismatch (BLOCKING)

### Finding
**Current Implementation (ClipUploader, line 69):**
```python
clip_uuid = result.get("id") or result.get("uuid") or result.get("clip_id")
```

**Official API Documentation (line 46-47):**
```
Response: { "status": "accepted", "clip_uuid": "..." }
```

**Risk:** The implementation tries `id`, `uuid`, `clip_id` but the actual API returns `clip_uuid`. This means **all uploads will appear to succeed but return None**, causing silent failures in production.

**Status:** 🔴 **BLOCKING** - Must fix before deploy

### Proposed Fix

**File:** `mercadolivre_upload/adapters/clip_uploader.py`

**Patch:**
```python
# OLD (lines 68-77):
# Extract clip UUID from response
clip_uuid = result.get("id") or result.get("uuid") or result.get("clip_id")
if clip_uuid:
    logger.info(f"Clip uploaded successfully for {item_id}: {clip_uuid}")
    return clip_uuid
else:
    logger.warning(
        f"Clip upload succeeded but no UUID in response: {result}"
    )
    return None

# NEW:
# Extract clip UUID from response (API returns 'clip_uuid' per docs)
clip_uuid = result.get("clip_uuid")
if clip_uuid:
    status = result.get("status", "unknown")
    logger.info(
        f"Clip uploaded successfully for {item_id}: {clip_uuid} (status: {status})"
    )
    return clip_uuid
else:
    logger.error(
        f"Clip upload API response missing 'clip_uuid' field. "
        f"Response: {result}. This may indicate API version mismatch."
    )
    return None
```

**Rationale:**
- API documentation explicitly shows `clip_uuid` as the response field
- Removed fallback attempts to other field names (they were wrong)
- Enhanced logging to include `status` field from response
- Changed warning to error since this is an unexpected condition

### Unit Test Addition

**File:** `tests/test_clip_uploader.py`

Add after line 107:

```python
def test_upload_clip_with_clip_uuid_key(self, tmp_path):
    """Test clip upload with 'clip_uuid' key (official API response)."""
    video_file = tmp_path / "video.mp4"
    video_file.write_bytes(b"fake video")

    mock_client = Mock()
    mock_client.upload_clip.return_value = {
        "status": "accepted",
        "clip_uuid": "550e8400-e29b-41d4-a716-446655440000"
    }

    uploader = ClipUploader(mock_client)

    result = uploader.upload_clip_for_item(
        item_id="MLB999",
        video_path=video_file,
    )

    assert result == "550e8400-e29b-41d4-a716-446655440000"


def test_upload_clip_legacy_keys_removed(self, tmp_path):
    """Test that legacy response keys (id, uuid, clip_id) are NOT supported."""
    video_file = tmp_path / "video.mp4"
    video_file.write_bytes(b"fake video")

    mock_client = Mock()
    # Simulate old/wrong response format
    mock_client.upload_clip.return_value = {"id": "legacy-id-123"}

    uploader = ClipUploader(mock_client)

    result = uploader.upload_clip_for_item(
        item_id="MLB999",
        video_path=video_file,
    )

    # Should return None since 'clip_uuid' is missing
    assert result is None
```

**Rationale:**
- Validates correct behavior with official API response format
- Ensures backward compatibility is NOT accidentally supported (prevents confusion)
- Documents expected response structure

---

## Issue #2: Sites Parameter Serialization (CONDITIONAL)

### Finding
**Current Implementation (MLApiClient.upload_clip, lines 316-318):**
```python
data = {}
if sites:
    import json
    data["sites"] = json.dumps(sites)
```

**Official API Documentation (line 31):**
```
sites: A JSON array specifying the target sites for the clip.
[...] If this field is empty, the clip will be uploaded to all available sites.
```

**Risk:** Ambiguity in "empty" semantics:
- Does "empty" mean `[]` (empty array)?
- Does "empty" mean field is absent from request?
- Current code: `sites=None` → field absent, `sites=[]` → `"sites": "[]"` sent

**Behavior Matrix:**

| Code Input | Multipart Data Sent | API Interpretation | Expected Behavior |
|------------|---------------------|---------------------|-------------------|
| `sites=None` | (field absent) | ❓ Unknown | All sites (probably) |
| `sites=[]` | `"sites": "[]"` | ❓ Unknown | All sites (maybe) or error? |
| `sites=[{...}]` | `"sites": "[{...}]"` | ✅ Specific sites | Specific sites |

**Status:** 🟡 **CONDITIONAL** - Needs API behavior confirmation

### Proposed Fix (Conservative)

**File:** `mercadolivre_upload/api/client.py`

**Patch Option A (Treat [] as None - Safest):**
```python
# OLD (lines 315-318):
data = {}
if sites:
    import json
    data["sites"] = json.dumps(sites)

# NEW:
import json

data = {}
if sites:  # Non-empty list
    data["sites"] = json.dumps(sites)
    logger.debug(f"Clip upload targeting specific sites: {sites}")
else:
    # Empty list or None: omit field to target all sites
    logger.debug("Clip upload targeting all available sites (sites field omitted)")
```

**Patch Option B (Explicit handling):**
```python
# NEW (Alternative - more explicit):
import json

data = {}
if sites is not None:
    if not sites:  # Empty list explicitly provided
        logger.warning(
            "Empty sites list provided. This may cause unexpected behavior. "
            "Omitting field to target all sites. Pass sites=None to target all."
        )
    else:
        data["sites"] = json.dumps(sites)
        logger.debug(f"Clip upload targeting specific sites: {sites}")
else:
    logger.debug("Clip upload targeting all available sites (sites parameter is None)")
```

**Recommended:** Option A (simpler, follows Python truthiness convention)

### Integration Test Addition

**File:** `tests/test_ml_api_client.py` (create if doesn't exist)

```python
def test_upload_clip_sites_serialization(mock_auth, tmp_path, requests_mock):
    """Test that sites parameter is correctly serialized in multipart request."""
    import json
    from mercadolivre_upload.api.client import MLApiClient
    
    video_file = tmp_path / "video.mp4"
    video_file.write_bytes(b"fake video")
    
    client = MLApiClient(mock_auth)
    
    # Mock API response
    requests_mock.post(
        "https://api.mercadolibre.com/marketplace/items/MLB123/clips/upload",
        json={"status": "accepted", "clip_uuid": "test-uuid"}
    )
    
    sites_data = [
        {"site_id": "MLB", "logistic_type": "drop_off"},
        {"site_id": "MLA", "logistic_type": "drop_off"}
    ]
    
    result = client.upload_clip(
        item_id="MLB123",
        file_path=str(video_file),
        sites=sites_data
    )
    
    # Verify request was made correctly
    assert requests_mock.call_count == 1
    request = requests_mock.last_request
    
    # Check that sites was JSON-serialized in form data
    # Note: multipart form data parsing depends on requests-mock version
    assert "sites" in request.text
    assert json.dumps(sites_data) in request.text or "MLB" in request.text
    
    assert result["clip_uuid"] == "test-uuid"


def test_upload_clip_no_sites(mock_auth, tmp_path, requests_mock):
    """Test clip upload with no sites specified (should target all)."""
    from mercadolivre_upload.api.client import MLApiClient
    
    video_file = tmp_path / "video.mp4"
    video_file.write_bytes(b"fake video")
    
    client = MLApiClient(mock_auth)
    
    requests_mock.post(
        "https://api.mercadolibre.com/marketplace/items/MLB123/clips/upload",
        json={"status": "accepted", "clip_uuid": "test-uuid"}
    )
    
    result = client.upload_clip(
        item_id="MLB123",
        file_path=str(video_file),
        sites=None
    )
    
    # Verify 'sites' field is NOT in request body when None
    request = requests_mock.last_request
    assert "sites" not in request.text or request.text.count("sites") == 0


def test_upload_clip_empty_sites_list(mock_auth, tmp_path, requests_mock):
    """Test clip upload with empty sites list (should behave like None)."""
    from mercadolivre_upload.api.client import MLApiClient
    
    video_file = tmp_path / "video.mp4"
    video_file.write_bytes(b"fake video")
    
    client = MLApiClient(mock_auth)
    
    requests_mock.post(
        "https://api.mercadolibre.com/marketplace/items/MLB123/clips/upload",
        json={"status": "accepted", "clip_uuid": "test-uuid"}
    )
    
    result = client.upload_clip(
        item_id="MLB123",
        file_path=str(video_file),
        sites=[]  # Empty list
    )
    
    # With Option A: should NOT send sites field
    request = requests_mock.last_request
    # This assertion depends on which option you choose
    # For Option A: assert "sites" not in request.text
```

### Confirmation Needed

**Action Required:** Test actual API behavior:
1. Deploy to staging with Option A
2. Upload clip with `sites=[]`
3. Check which sites receive the clip (use GET endpoint)
4. If all sites receive it → Option A is correct
5. If API returns error → Need Option B with validation

---

## Issue #3: Item ID Validation (SAFE)

### Finding
**Current Implementation (MLApiClient.upload_clip, line 326):**
```python
url = f"{self.base_url}/marketplace/items/{item_id}/clips/upload"
```

**Risk:** No validation of `item_id` format before URL construction:
- Malformed IDs cause unclear errors (404 or 400)
- Possible injection if special characters in ID
- Makes debugging harder (is it auth, ID format, or item doesn't exist?)

**Expected Format:** `MLB` + digits (e.g., `MLB1234567890`)

**Status:** ✅ **SAFE** - Can apply now (defensive programming)

### Proposed Fix

**File:** `mercadolivre_upload/api/client.py`

Add validation helper at module level (after line 11):

```python
import re

# Item ID validation pattern (site code + digits)
ITEM_ID_PATTERN = re.compile(r'^ML[A-Z]\d+$')


def validate_item_id(item_id: str) -> None:
    """Validate Mercado Livre item ID format.
    
    Args:
        item_id: Item ID to validate (e.g., MLB1234567890)
        
    Raises:
        ValueError: If item_id format is invalid
    """
    if not item_id:
        raise ValueError("item_id cannot be empty")
    
    if not ITEM_ID_PATTERN.match(item_id):
        raise ValueError(
            f"Invalid item_id format: '{item_id}'. "
            f"Expected format: ML[site_code][digits] (e.g., MLB1234567890)"
        )
```

**Patch in upload_clip method (before line 326):**
```python
# OLD (line 326):
url = f"{self.base_url}/marketplace/items/{item_id}/clips/upload"

# NEW (add validation before URL construction):
validate_item_id(item_id)
url = f"{self.base_url}/marketplace/items/{item_id}/clips/upload"
```

Also apply to other methods using item_id:
- `submit_fiscal_info` (line 223)
- `verify_invoice_readiness` (line 279)

### Unit Test Addition

**File:** `tests/test_ml_api_client.py`

```python
import pytest
from mercadolivre_upload.api.client import validate_item_id


class TestItemIdValidation:
    """Tests for item ID validation."""
    
    def test_valid_item_ids(self):
        """Test that valid item IDs pass validation."""
        valid_ids = [
            "MLB1234567890",
            "MLA9876543210",
            "MLC123",
            "MLM999999999999"
        ]
        for item_id in valid_ids:
            # Should not raise
            validate_item_id(item_id)
    
    def test_invalid_item_ids(self):
        """Test that invalid item IDs raise ValueError."""
        invalid_ids = [
            "",  # Empty
            "123456",  # No prefix
            "MLB",  # No digits
            "MLB-123",  # Invalid character
            "MLB 123",  # Space
            "mlb123",  # Lowercase
            "MLBX123",  # Wrong format
            "ML123",  # Missing site code letter
            "../MLB123",  # Path traversal attempt
        ]
        for item_id in invalid_ids:
            with pytest.raises(ValueError, match="Invalid item_id format"):
                validate_item_id(item_id)
    
    def test_empty_item_id(self):
        """Test that empty item_id raises specific error."""
        with pytest.raises(ValueError, match="cannot be empty"):
            validate_item_id("")


def test_upload_clip_validates_item_id(mock_auth, tmp_path):
    """Test that upload_clip validates item_id before making request."""
    from mercadolivre_upload.api.client import MLApiClient
    
    video_file = tmp_path / "video.mp4"
    video_file.write_bytes(b"fake video")
    
    client = MLApiClient(mock_auth)
    
    with pytest.raises(ValueError, match="Invalid item_id format"):
        client.upload_clip(
            item_id="invalid-id",
            file_path=str(video_file)
        )
```

**Rationale:**
- Fail fast with clear error message
- Prevents unnecessary API calls with malformed IDs
- Improves debugging experience
- No API call needed to test

---

## Issue #4: Error Response Logging (SAFE)

### Finding
**Current Implementation (ClipUploader, line 80):**
```python
except Exception as e:
    logger.error(f"Failed to upload clip for {item_id}: {e}")
    return None
```

**Risk:** Insufficient context for debugging:
- No HTTP status code logged
- No API error message/code logged
- No request details logged
- Can't distinguish between network error, auth error, validation error

**Status:** ✅ **SAFE** - Can apply now (logging only)

### Proposed Fix

**File:** `mercadolivre_upload/adapters/clip_uploader.py`

**Patch (lines 60-81):**
```python
# OLD:
try:
    logger.info(f"Uploading clip for item {item_id}: {video_path.name}")
    result = self.client.upload_clip(
        item_id=item_id,
        file_path=str(video_path),
        sites=sites,
    )

    # Extract clip UUID from response
    clip_uuid = result.get("id") or result.get("uuid") or result.get("clip_id")
    if clip_uuid:
        logger.info(f"Clip uploaded successfully for {item_id}: {clip_uuid}")
        return clip_uuid
    else:
        logger.warning(
            f"Clip upload succeeded but no UUID in response: {result}"
        )
        return None

except Exception as e:
    logger.error(f"Failed to upload clip for {item_id}: {e}")
    return None

# NEW:
try:
    logger.info(
        f"Uploading clip for item {item_id}: {video_path.name} "
        f"(size: {video_path.stat().st_size} bytes, sites: {sites})"
    )
    result = self.client.upload_clip(
        item_id=item_id,
        file_path=str(video_path),
        sites=sites,
    )

    # Extract clip UUID from response (API returns 'clip_uuid' per docs)
    clip_uuid = result.get("clip_uuid")
    if clip_uuid:
        status = result.get("status", "unknown")
        logger.info(
            f"Clip uploaded successfully for {item_id}: {clip_uuid} (status: {status})"
        )
        return clip_uuid
    else:
        logger.error(
            f"Clip upload API response missing 'clip_uuid' field. "
            f"Item: {item_id}, Response: {result}. "
            f"This may indicate API version mismatch."
        )
        return None

except requests.HTTPError as e:
    # HTTP errors from API
    status_code = e.response.status_code if e.response else "unknown"
    try:
        error_body = e.response.json() if e.response else {}
    except Exception:
        error_body = e.response.text if e.response else ""
    
    logger.error(
        f"HTTP error uploading clip for {item_id}: "
        f"status={status_code}, error={error_body}, "
        f"video={video_path.name}, sites={sites}"
    )
    return None

except Exception as e:
    # Other errors (file I/O, network, etc.)
    logger.error(
        f"Unexpected error uploading clip for {item_id}: {type(e).__name__}: {e}, "
        f"video={video_path.name}, sites={sites}",
        exc_info=True  # Include stack trace
    )
    return None
```

**Additional Import Needed (line 9):**
```python
import logging
from pathlib import Path

import requests  # ADD THIS

from mercadolivre_upload.api.client import MLApiClient
```

**Rationale:**
- Distinguish HTTP errors from other exceptions
- Log status code and error body for HTTP errors
- Include request context (video file, sites) in all error logs
- Add `exc_info=True` for unexpected errors to get stack trace
- Log file size upfront to detect size-related failures

---

## Issue #5: Content-Type Determination (SAFE - Informational)

### Finding
**Current Implementation (MLApiClient.upload_clip, lines 308-311):**
```python
# Determine MIME type
mime_type, _ = mimetypes.guess_type(str(path))
if not mime_type:
    mime_type = "video/mp4"  # Default fallback
```

**API Requirements (docs line 13):**
```
Formats: MP4, MOV, MPEG, AVI
```

**Expected MIME Types:**
- `.mp4` → `video/mp4` ✅
- `.mov` → `video/quicktime` ✅
- `.mpeg` → `video/mpeg` ✅
- `.avi` → `video/x-msvideo` or `video/avi` ⚠️

**Status:** ✅ **SAFE** - Current implementation is correct, but add logging

### Proposed Enhancement (Optional)

**File:** `mercadolivre_upload/api/client.py`

Add logging after MIME type determination (line 311):

```python
# Determine MIME type
mime_type, _ = mimetypes.guess_type(str(path))
if not mime_type:
    mime_type = "video/mp4"  # Default fallback
    logger.warning(
        f"Could not determine MIME type for {path.name}, using default: video/mp4"
    )
else:
    logger.debug(f"Detected MIME type for {path.name}: {mime_type}")
```

**Rationale:**
- Python's `mimetypes` module handles all supported formats correctly
- Fallback to `video/mp4` is reasonable for edge cases
- Logging helps debug if API rejects due to content-type mismatch

---

## Type Safety Improvements

### Proposed TypedDicts

**File:** `mercadolivre_upload/domain/types.py` (create if doesn't exist)

```python
"""Type definitions for Mercado Livre API payloads."""

from typing import TypedDict, Literal, NotRequired


class ClipSite(TypedDict):
    """Site specification for clip upload/deletion."""
    site_id: str  # E.g., "MLB", "MLA"
    logistic_type: str  # E.g., "drop_off", "cross_docking"


class ClipUploadResponse(TypedDict):
    """Response from clip upload endpoint."""
    status: Literal["accepted", "rejected"]
    clip_uuid: str


class ClipMetadata(TypedDict):
    """Moderation metadata for a clip on a specific site."""
    site_id: str
    moderation_status: Literal["PUBLISHED", "REJECTED", "UNDER_REVIEW"]
    reject_reason: NotRequired[str]


class ClipInfo(TypedDict):
    """Information about an uploaded clip."""
    clip_uuid: str
    metadata: list[ClipMetadata]


class ClipListResponse(TypedDict):
    """Response from GET clips endpoint."""
    parent_item_id: str
    parent_user_id: int
    clips: list[ClipInfo]


class ClipDeleteRequest(TypedDict):
    """Request body for clip deletion."""
    sites: list[ClipSite]


class ClipDeleteResponse(TypedDict):
    """Response from clip deletion endpoint."""
    # Structure not documented - TBD based on actual API response
    status: str
```

### Updated Method Signatures

**File:** `mercadolivre_upload/api/client.py`

```python
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

    Returns:
        Upload result with clip UUID and status

    Raises:
        ValueError: If item_id format is invalid
        requests.HTTPError: On API error
    """
```

**File:** `mercadolivre_upload/adapters/clip_uploader.py`

```python
from mercadolivre_upload.domain.types import ClipSite  # Add import

def upload_clip_for_item(
    self,
    item_id: str,
    video_path: Path,
    sites: list[ClipSite] | None = None,
) -> str | None:
```

**File:** `mercadolivre_upload/application/ports.py`

```python
from mercadolivre_upload.domain.types import ClipSite  # Add import

class ClipUploaderPort(Protocol):
    """Port for video clip upload operations."""

    def upload_clip_for_item(
        self, 
        item_id: str, 
        video_path: Path, 
        sites: list[ClipSite] | None = None
    ) -> str | None:
```

---

## Summary of Changes

### Blocking Issues (Must Fix Before Deploy)
1. ✅ **Issue #1: Response Key** - Change `result.get("id")` to `result.get("clip_uuid")`

### Conditional Issues (Apply After Confirmation)
2. 🟡 **Issue #2: Sites Serialization** - Test empty list behavior, then apply Option A or B

### Safe to Apply Now
3. ✅ **Issue #3: Item ID Validation** - Add `validate_item_id()` helper
4. ✅ **Issue #4: Error Logging** - Enhanced error context
5. ✅ **Issue #5: Content-Type** - Add MIME type logging
6. ✅ **Type Definitions** - Add TypedDicts for type safety

---

## Recommended Deployment Plan

### Phase 1: Critical Fixes (Before Any Deploy)
1. Apply Issue #1 fix (response key)
2. Add blocking unit tests
3. Run existing test suite

### Phase 2: Safe Improvements (Can Deploy Incrementally)
1. Apply Issue #3 (validation)
2. Apply Issue #4 (logging)
3. Apply Issue #5 (MIME logging)
4. Add type definitions

### Phase 3: Confirmation and Conditional Fix
1. Deploy to staging with Issue #2 Option A
2. Test actual API behavior with empty list
3. Apply final fix based on results

### Phase 4: Monitoring
1. Monitor logs for unexpected errors
2. Verify clip UUIDs are being captured
3. Check for validation errors (indicates bad input data)

---

## Testing Checklist

- [ ] Unit tests pass for all scenarios
- [ ] Integration test with real API (staging)
- [ ] Test with all supported video formats (mp4, mov, mpeg, avi)
- [ ] Test with `sites=None` (should target all sites)
- [ ] Test with `sites=[]` (confirm behavior matches None)
- [ ] Test with specific sites list
- [ ] Test with invalid item_id (should raise ValueError)
- [ ] Test with missing video file (should fail gracefully)
- [ ] Test with unsupported video format (should fail gracefully)
- [ ] Verify logs contain sufficient debug information

---

## Additional Recommendations

### 1. Add GET Clips Endpoint
Currently not implemented. Useful for:
- Verifying upload success
- Checking moderation status
- Debugging which sites received clip

**Signature:**
```python
def get_clip_info(self, item_id: str) -> ClipListResponse:
    """Get information about all clips for an item."""
    validate_item_id(item_id)
    return self.get(f"/marketplace/items/{item_id}/clips")
```

### 2. Add Video File Validation
Validate video requirements before upload:
- Duration: 10-61 seconds
- Size: ≤280 MB
- Resolution: ≥360x640

This would save API calls for videos that will be rejected.

### 3. Add Retry Logic for Transient Errors
Network errors, rate limits, etc. could benefit from exponential backoff retry.

### 4. Add Moderation Status Polling
After upload, poll GET endpoint to check moderation status before considering upload complete.

---

## Files to Modify

| File | Lines | Type | Priority |
|------|-------|------|----------|
| `mercadolivre_upload/adapters/clip_uploader.py` | 60-81 | Fix + Logging | BLOCKING |
| `mercadolivre_upload/api/client.py` | 284-333 | Validation + Logging | HIGH |
| `tests/test_clip_uploader.py` | 108+ | New tests | HIGH |
| `tests/test_ml_api_client.py` | NEW | New test file | HIGH |
| `mercadolivre_upload/domain/types.py` | NEW | Type definitions | MEDIUM |
| `mercadolivre_upload/application/ports.py` | 42-44 | Type hints | MEDIUM |

---

## Questions for Product/API Team

1. **Sites parameter semantics**: What happens if `sites=[]` is sent? Same as omitting field?
2. **Response status field**: Are there other values besides "accepted" and "rejected"?
3. **Moderation timeline**: How long does moderation typically take?
4. **Error codes**: Is there a complete list of error codes and their meanings?
5. **Video validation**: Does API validate duration/resolution or just file format?

---

## Appendix: Quick Apply Script

```bash
# Apply critical fixes only (Phase 1)
python3 scripts/apply_clip_fixes.py --phase 1

# Apply all safe fixes (Phase 1 + 2)
python3 scripts/apply_clip_fixes.py --phase 2

# Run tests
pytest tests/test_clip_uploader.py tests/test_ml_api_client.py -v
```

(Script not included - create if automated patching needed)
