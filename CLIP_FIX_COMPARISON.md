# Clip Upload Fix - Side-by-Side Comparison

This document shows the exact changes needed for each issue, with before/after code snippets.

---

## 🔴 ISSUE #1: Response Key Mismatch (BLOCKING)

### Problem
The code tries to extract the clip UUID using wrong field names that don't exist in the API response.

### Current Code (WRONG)
```python
# mercadolivre_upload/adapters/clip_uploader.py, lines 68-77

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
```

### Fixed Code (CORRECT)
```python
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
```

### What Changed
✅ `result.get("clip_uuid")` instead of wrong field names  
✅ Added `status` field extraction  
✅ Upgraded from `logger.warning` to `logger.error` (this is unexpected)  
✅ Added context (item_id, full response) to error message

### API Documentation Reference
```
Response: { "status": "accepted", "clip_uuid": "..." }
```
Source: `docs/mercadolibre_clips_api.md`, line 46-47

---

## 🟠 ISSUE #1B: Error Handling (Part of Blocking Fix)

### Problem
Generic exception handling loses critical debugging information (status codes, error bodies).

### Current Code (INSUFFICIENT)
```python
# mercadolivre_upload/adapters/clip_uploader.py, lines 79-81

except Exception as e:
    logger.error(f"Failed to upload clip for {item_id}: {e}")
    return None
```

### Fixed Code (IMPROVED)
```python
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

### What Changed
✅ Split into two exception handlers: HTTPError vs others  
✅ Extract and log HTTP status code  
✅ Extract and log API error body (JSON or text)  
✅ Include request context (video filename, sites) in all error logs  
✅ Add `exc_info=True` for non-HTTP errors (stack traces)  
✅ Add `import requests` at top of file

### Example Log Output

**Before (unhelpful):**
```
ERROR: Failed to upload clip for MLB123: 400 Client Error
```

**After (actionable):**
```
ERROR: HTTP error uploading clip for MLB123: status=400, 
error={'message': 'Invalid video duration', 'error': 'VIDEO_TOO_SHORT', 'status': 400}, 
video=product_demo.mp4, sites=[{'site_id': 'MLB', 'logistic_type': 'drop_off'}]
```

---

## ✅ ISSUE #2: Item ID Validation (SAFE)

### Problem
No validation of item_id format before making API calls, leading to unclear errors.

### Current Code (NO VALIDATION)
```python
# mercadolivre_upload/api/client.py, line 326

url = f"{self.base_url}/marketplace/items/{item_id}/clips/upload"
```

### Fixed Code (WITH VALIDATION)
```python
# Add at module level (after line 11):
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


# In upload_clip method (before line 326):
validate_item_id(item_id)
url = f"{self.base_url}/marketplace/items/{item_id}/clips/upload"
```

### What Changed
✅ Added `validate_item_id()` helper function  
✅ Regex pattern: `^ML[A-Z]\d+$` (matches MLB123, MLA456, etc.)  
✅ Call validation before URL construction  
✅ Raises `ValueError` with clear message for invalid formats  
✅ Prevents API calls with malformed IDs

### Valid vs Invalid Examples

**Valid IDs:**
- `MLB1234567890` ✅
- `MLA9876543210` ✅
- `MLC123` ✅
- `MLM999` ✅

**Invalid IDs (will raise ValueError):**
- `123456` ❌ (no prefix)
- `MLB` ❌ (no digits)
- `MLB-123` ❌ (invalid character)
- `mlb123` ❌ (lowercase)
- `ML123` ❌ (missing site code letter)

---

## 🟡 ISSUE #3: Sites Serialization (CONDITIONAL)

### Problem
Unclear whether empty list `[]` has different semantics than `None`.

### Current Code (AMBIGUOUS)
```python
# mercadolivre_upload/api/client.py, lines 315-318

data = {}
if sites:
    import json
    data["sites"] = json.dumps(sites)
```

### Behavior Matrix

| Input | Sent to API | API Interprets As |
|-------|-------------|-------------------|
| `sites=None` | (field omitted) | Upload to all sites |
| `sites=[]` | `"sites": "[]"` | ❓ All sites or error? |
| `sites=[{...}]` | `"sites": "[{...}]"` | Specific sites |

### Proposed Fix (Conservative)
```python
import json

data = {}
if sites:  # Non-empty list
    data["sites"] = json.dumps(sites)
    logger.debug(f"Clip upload targeting specific sites: {sites}")
else:
    # Empty list or None: omit field to target all sites
    logger.debug("Clip upload targeting all available sites (sites field omitted)")
```

### What Changed
✅ Move `import json` to top  
✅ Comment clarifies behavior  
✅ Add debug logging for both paths  
✅ Treat empty list same as None (omit field)

### API Documentation Reference
```
sites: [...] If this field is empty, the clip will be uploaded to all available sites.
```
Source: `docs/mercadolibre_clips_api.md`, line 31

**Note:** "Empty" could mean either:
1. Field omitted from request
2. Field present with empty array `[]`

**Action Required:** Test in staging to confirm which interpretation is correct.

---

## ✅ ISSUE #4: Content-Type Detection (INFORMATIONAL)

### Problem
None - current implementation is correct, but lacks logging.

### Current Code (WORKING)
```python
# mercadolivre_upload/api/client.py, lines 308-311

# Determine MIME type
mime_type, _ = mimetypes.guess_type(str(path))
if not mime_type:
    mime_type = "video/mp4"  # Default fallback
```

### Enhanced Code (WITH LOGGING)
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

### What Changed
✅ Log warning when falling back to default MIME type  
✅ Log debug message with detected MIME type

### MIME Type Mappings (Python mimetypes)

| Extension | MIME Type | Status |
|-----------|-----------|--------|
| `.mp4` | `video/mp4` | ✅ |
| `.mov` | `video/quicktime` | ✅ |
| `.mpeg` | `video/mpeg` | ✅ |
| `.avi` | `video/x-msvideo` | ✅ |

All supported formats are correctly handled by Python's `mimetypes` module.

---

## 📝 Tests to Update

### Test: Correct Response Format

**OLD (Wrong):**
```python
mock_client.upload_clip.return_value = {"id": "clip-uuid-123"}
```

**NEW (Correct):**
```python
mock_client.upload_clip.return_value = {
    "status": "accepted",
    "clip_uuid": "clip-uuid-123"
}
```

### Test: Add Official Response Format Test

**NEW TEST:**
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
```

### Test: Verify Legacy Keys Rejected

**NEW TEST:**
```python
def test_upload_clip_legacy_keys_removed(self, tmp_path):
    """Test that legacy response keys (id, uuid, clip_id) are NOT supported."""
    video_file = tmp_path / "video.mp4"
    video_file.write_bytes(b"fake video")

    mock_client = Mock()
    mock_client.upload_clip.return_value = {"id": "legacy-id-123"}

    uploader = ClipUploader(mock_client)

    result = uploader.upload_clip_for_item(
        item_id="MLB999",
        video_path=video_file,
    )

    # Should return None since 'clip_uuid' is missing
    assert result is None
```

---

## Summary of Changes by File

### `mercadolivre_upload/adapters/clip_uploader.py`
- Line 7: Add `import requests`
- Lines 60-81: Replace entire try-except block with fixed version
- Key changes:
  - `result.get("clip_uuid")` instead of wrong field names
  - Split exception handling (HTTPError vs others)
  - Enhanced logging with status codes and error bodies

### `mercadolivre_upload/api/client.py`
- Line 3: Add `import re`
- Lines 12-30: Add `ITEM_ID_PATTERN` and `validate_item_id()` function
- Line 241: Add `validate_item_id(item_id)` before fiscal_info POST
- Line 298: Add `validate_item_id(item_id)` before invoice verification
- Line 325: Add `validate_item_id(item_id)` before clip upload
- Lines 308-320: Add MIME type logging

### `tests/test_clip_uploader.py`
- Lines 52-92: Add two new tests (official format, legacy rejection)
- Line 60: Update existing test mock to use correct response format
- Lines 73-105: Remove obsolete tests for wrong response keys

### `tests/test_item_id_validation.py` (NEW FILE)
- Complete new test file for item ID validation logic

### `mercadolivre_upload/domain/types.py` (NEW FILE)
- TypedDict definitions for clip API request/response types

---

## Impact Analysis

### Before Fix
```python
# Upload clip
result = client.upload_clip("MLB123", "video.mp4")
# API returns: {"status": "accepted", "clip_uuid": "abc-123"}

# Extract UUID
uuid = result.get("id")  # None
uuid = uuid or result.get("uuid")  # None
uuid = uuid or result.get("clip_id")  # None

# Return None (even though upload succeeded!)
return None  # ❌ WRONG
```

### After Fix
```python
# Upload clip
result = client.upload_clip("MLB123", "video.mp4")
# API returns: {"status": "accepted", "clip_uuid": "abc-123"}

# Extract UUID
uuid = result.get("clip_uuid")  # "abc-123"

# Return correct UUID
return "abc-123"  # ✅ CORRECT
```

---

## Application Priority

1. **MUST APPLY** (Blocking): Issue #1 + #1B (response key + error handling)
2. **SHOULD APPLY** (Safe): Issue #2 (item ID validation)
3. **SHOULD APPLY** (Safe): Issue #4 (MIME type logging)
4. **TEST FIRST** (Conditional): Issue #3 (sites serialization)

Total lines changed: ~80 lines across 3 files  
Total new tests: ~40 lines  
Time to apply: ~30 minutes  
Risk if not applied: HIGH (silent failures in production)
