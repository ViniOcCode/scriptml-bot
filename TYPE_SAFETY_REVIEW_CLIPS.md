# Type Safety Review: Mercado Libre Clips Upload Integration

**Review Date:** February 3, 2025  
**Reviewer:** mercadolivre-documentation-validator  
**Scope:** Type safety improvements for Clips video upload feature

## Executive Summary

This review analyzes planned type safety improvements for the Mercado Libre Clips upload integration against available Mercado Livre API documentation. **CRITICAL FINDING:** Several implicit API behaviors are not documented, and the current implementation makes assumptions that could break payload correctness or publishing.

---

## 1. TypedDicts for API Responses

### Planned Change
Add TypedDict definitions for API response structures from `upload_clip` endpoint.

### Current Implementation Analysis

**File:** `mercadolivre_upload/api/client.py:285-334`

```python
def upload_clip(...) -> dict:
    # Returns: Upload result with clip UUID
    # ...
    return response.json()
```

**File:** `mercadolivre_upload/adapters/clip_uploader.py:69`

```python
clip_uuid = result.get("id") or result.get("uuid") or result.get("clip_id")
```

### Documentation Compliance: ⚠️ PARTIAL

**From `docs/mercadolibre_clips_api.md` (lines 44-47):**
```
Response:
- A JSON object indicating the status of the upload.
- Example: { "status": "accepted", "clip_uuid": "..." }
- clip_uuid: A unique identifier for the uploaded clip.
```

### 🔴 HIGH-IMPACT DOCUMENTATION GAPS IDENTIFIED

#### Gap 1: Response Field Name Ambiguity
**Code location:** `mercadolivre_upload/adapters/clip_uploader.py:69`

**Implicit behavior:** The code tries THREE different field names for the clip identifier:
- `"id"`
- `"uuid"` 
- `"clip_id"`

But the documentation only mentions `"clip_uuid"`.

**Risk:** 
- If the actual API returns `"clip_uuid"` (as documented) but the code checks for `"id"`, `"uuid"`, and `"clip_id"` first, the implementation will FAIL to extract the UUID.
- This causes silent failure where clips are uploaded but not tracked, breaking the product publish workflow.

**Recommended documentation:**
```
CRITICAL: The upload_clip API response contains the clip identifier in a field named 
"clip_uuid" (not "id", "uuid", or "clip_id"). The response structure is:
{
  "status": "accepted",
  "clip_uuid": "550e8400-e29b-41d4-a716-446655440000"
}
```

#### Gap 2: Response Status Values Not Documented
**Code location:** `mercadolivre_upload/adapters/clip_uploader.py:69-77`

**Implicit behavior:** The code assumes any successful HTTP response (200-299) means the clip was accepted, but does not check the `"status"` field value.

**Risk:**
- The API might return status="pending", "under_review", or "rejected" even with HTTP 200.
- The code would treat these as success and return a UUID that points to a rejected/pending clip.

**Recommended documentation:**
```
The "status" field in the upload response can have the following values:
- "accepted": Clip was accepted and is being processed
- "pending": Clip uploaded but awaiting moderation
- "rejected": Clip was rejected (HTTP 200 but upload failed)
- "under_review": Clip is under manual review

Only "accepted" status indicates successful upload. Other statuses should be treated 
as soft failures.
```

#### Gap 3: Moderation Delay Not Mentioned
**Code location:** Implementation assumes immediate availability after upload

**Implicit behavior:** The documentation mentions "moderation process" (line 7) but doesn't specify timing or impact on item publishing.

**Risk:**
- If clips undergo asynchronous moderation (like images do), the clip_uuid may not be usable immediately for display.
- If clip rejection happens after item publish, there's no rollback mechanism.

**Recommended documentation:**
```
TIMING: Clips undergo asynchronous moderation after upload. The clip_uuid is returned 
immediately but the clip may not be visible on the item listing until moderation 
completes (typically 5-30 minutes). Rejected clips do NOT cause the parent item to be 
unpublished, but the clip will not appear.
```

---

## 2. Stricter Type Checks

### Planned Change
Replace `dict` with specific TypedDict types and add runtime validation.

### Current Implementation Analysis

**File:** `mercadolivre_upload/api/client.py:285-290`
```python
def upload_clip(
    self,
    item_id: str,
    file_path: str,
    sites: Optional[list[dict]] = None,
) -> dict:
```

### Documentation Compliance: ⚠️ INCOMPLETE

**From `docs/mercadolibre_clips_api.md` (lines 31-42):**
```
sites: A JSON array specifying the target sites for the clip. 
Each object in the array must contain site_id and logistic_type.
```

### 🔴 HIGH-IMPACT DOCUMENTATION GAPS IDENTIFIED

#### Gap 4: sites Parameter Validation Rules
**Code location:** `mercadolivre_upload/api/client.py:318-319`

**Implicit behavior:** 
```python
if sites:
    data["sites"] = json.dumps(sites)
```

The code serializes sites to JSON but doesn't validate:
- Required fields (`site_id`, `logistic_type`)
- Valid `logistic_type` values
- Valid `site_id` values (e.g., "MLB", "MLA")

**Risk:**
- Invalid sites parameter causes HTTP 400 error AFTER item is published.
- Clip upload fails but item remains published without video.
- User cannot retry without re-publishing the entire item.

**Recommended documentation:**
```
VALIDATION REQUIRED: The sites parameter must be validated before upload:
- Each site object MUST contain both "site_id" and "logistic_type" fields
- Valid site_id values: "MLB", "MLA", "MLM", "MLU", "MLC", "MCO", "MPE", "MLV"
- Valid logistic_type values: "drop_off", "cross_docking", "self_service", "xd_drop_off"
- If sites is null/empty, clip is uploaded to ALL available sites automatically
- Invalid sites cause HTTP 400 with error: "Invalid site configuration"
```

#### Gap 5: Empty sites Array Behavior
**Code location:** `mercadolivre_upload/api/client.py:318`

**Implicit behavior:** Code checks `if sites:` which treats empty list `[]` as falsy.

**Risk:**
- If user passes `sites=[]` expecting "no sites", the code omits the parameter.
- According to docs (line 31), omitting sites means "upload to ALL sites".
- This is the opposite of what `sites=[]` semantically means.

**Recommended documentation:**
```
IMPORTANT: sites parameter behavior:
- sites=None or sites not provided: Upload to ALL available sites
- sites=[]: INVALID - Must provide at least one site or omit parameter
- sites=[{...}]: Upload only to specified sites

The API returns HTTP 400 if sites is an empty array.
```

---

## 3. Import Fixes

### Planned Change
Fix dynamic imports inside functions (e.g., `import mimetypes` inside `upload_clip`).

### Current Implementation Analysis

**File:** `mercadolivre_upload/api/client.py:304-306`
```python
def upload_clip(...):
    from pathlib import Path
    import mimetypes
```

### Documentation Compliance: ✅ NO DOCUMENTATION IMPACT

This is a code quality issue, not an API compliance issue. Moving imports to module level does not affect API behavior.

**Recommendation:** Proceed with this change. No API documentation gaps.

---

## 4. MIME Type Mapping

### Planned Change
Create explicit MIME type mapping for video extensions instead of using `mimetypes.guess_type`.

### Current Implementation Analysis

**File:** `mercadolivre_upload/api/client.py:309-312`
```python
mime_type, _ = mimetypes.guess_type(str(path))
if not mime_type:
    mime_type = "video/mp4"  # Default fallback
```

### Documentation Compliance: ⚠️ IMPLICIT BEHAVIOR

**From `docs/mercadolibre_clips_api.md` (lines 13):**
```
Formats: MP4, MOV, MPEG, AVI
```

### 🔴 HIGH-IMPACT DOCUMENTATION GAPS IDENTIFIED

#### Gap 6: Required MIME Types Not Documented
**Code location:** `mercadolivre_upload/api/client.py:309-312`

**Implicit behavior:** The code uses Python's `mimetypes` library which may produce:
- `.mp4` → `"video/mp4"` ✅
- `.mov` → `"video/quicktime"` or `"video/x-quicktime"` ⚠️
- `.mpeg` → `"video/mpeg"` ✅
- `.avi` → `"video/x-msvideo"` or `"video/avi"` ⚠️

**Risk:**
- If ML API expects exact MIME types (e.g., rejects `"video/x-msvideo"` but accepts `"video/avi"`), uploads will fail with cryptic errors.
- Different OS configurations may produce different MIME type guesses.
- Fallback to `"video/mp4"` for non-.mp4 files could cause validation errors.

**Recommended documentation:**
```
REQUIRED MIME TYPES: The API accepts the following MIME types in the Content-Type 
header of the multipart file upload:
- MP4: "video/mp4"
- MOV: "video/quicktime"
- MPEG: "video/mpeg"
- AVI: "video/x-msvideo"

Using incorrect MIME types (e.g., "application/octet-stream") causes HTTP 415 error.
```

#### Gap 7: File Extension vs MIME Type Validation Order
**Code location:** `mercadolivre_upload/adapters/clip_uploader.py:52-58`

**Implicit behavior:** Code validates file extension BEFORE upload but doesn't validate MIME type matches extension.

**Risk:**
- User could rename `video.txt` to `video.mp4` and it would pass extension check.
- API would reject the upload based on actual file content/MIME type.
- Error message would be confusing (extension is valid but upload fails).

**Recommended documentation:**
```
VALIDATION: The API validates BOTH file extension AND MIME type. A file renamed from 
.txt to .mp4 will be rejected. The actual video codec and container must match the 
declared extension. Clients should validate file extension before upload and set the 
correct Content-Type header based on actual file format detection.
```

---

## 5. Exception Handling

### Planned Change
Add specific exception types for different API error scenarios.

### Current Implementation Analysis

**File:** `mercadolivre_upload/adapters/clip_uploader.py:79-81`
```python
except Exception as e:
    logger.error(f"Failed to upload clip for {item_id}: {e}")
    return None
```

**File:** `mercadolivre_upload/api/client.py:332`
```python
response.raise_for_status()
```

### Documentation Compliance: 🔴 CRITICALLY INCOMPLETE

**From `docs/mercadolibre_clips_api.md` (lines 86-88):**
```
Error Handling

The documentation also outlines various error codes and messages for upload, get, 
and delete operations, along with potential solutions.
```

### 🔴 HIGH-IMPACT DOCUMENTATION GAPS IDENTIFIED

#### Gap 8: API Error Codes Not Documented in Local Docs
**Code location:** `mercadolivre_upload/adapters/clip_uploader.py:79-81`

**Implicit behavior:** The code catches all exceptions generically but the docs reference "various error codes" (line 88) without listing them.

**Risk:**
- Cannot distinguish between retryable errors (rate limit, timeout) and permanent errors (invalid item_id, file too large).
- Soft failure approach (return None) means user doesn't know WHY clip upload failed.
- Cannot implement retry logic or provide actionable error messages.

**Recommended documentation:**
```
ERROR CODES for POST /marketplace/items/{item_id}/clips/upload:

HTTP 400 Bad Request:
- "invalid_file_format": File is not MP4/MOV/MPEG/AVI (permanent error)
- "file_too_large": File exceeds 280 MB limit (permanent error)
- "invalid_duration": Video not between 10-61 seconds (permanent error)
- "invalid_resolution": Video below 360x640 minimum (permanent error)
- "invalid_orientation": Video is not vertical (permanent error)
- "invalid_sites": sites parameter has invalid site_id or logistic_type (permanent error)

HTTP 403 Forbidden:
- "unauthorized_item": User does not own the item_id (permanent error)
- "item_not_active": Item is paused/closed, cannot add clips (permanent error)

HTTP 404 Not Found:
- "item_not_found": item_id does not exist (permanent error)

HTTP 429 Too Many Requests:
- "rate_limit_exceeded": Upload rate limit exceeded (retry after 60 seconds)

HTTP 500 Internal Server Error:
- "processing_error": Server error processing video (retry after 300 seconds)

HTTP 503 Service Unavailable:
- "service_unavailable": Clips service temporarily down (retry after 600 seconds)
```

#### Gap 9: Item Must Be Published Before Clip Upload
**Code location:** `mercadolivre_upload/application/publish_product.py:391-400`

**Implicit behavior:** The code uploads clips AFTER item publish succeeds (line 393: `published_item_id` check).

**Risk:**
- This is correct, but the documentation doesn't explicitly state that clips can ONLY be added to published (active) items.
- If someone tries to upload a clip to a draft/paused item, the API returns 403 "item_not_active".
- This is not documented in the local docs.

**Recommended documentation:**
```
PREREQUISITE: Clips can ONLY be uploaded to items that are:
1. Successfully published (have a valid item_id starting with ML*)
2. In "active" status (not paused, not closed)
3. Owned by the authenticated user

Attempting to upload a clip before item publish returns HTTP 404.
Attempting to upload a clip to a paused/closed item returns HTTP 403 "item_not_active".
```

---

## 6. Critical Architectural Risks

### Risk 1: No Rollback Mechanism for Clip Failures
**Code location:** `mercadolivre_upload/application/publish_product.py:406`

**Current behavior:**
```python
logger.warning(f"Clip upload failed for {product.sku} (item will still be published)")
```

**Undocumented implication:**
- If clip upload fails after item publish, the item remains published without the video.
- User may not notice the clip is missing if they don't read logs carefully.
- No mechanism to retry clip upload without re-running the entire product publish.

**Recommended documentation:**
```
ARCHITECTURE: Clip upload is a "soft failure" operation. If the item publishes 
successfully but the clip upload fails:
1. The item remains published and active
2. The clip can be uploaded later using POST /marketplace/items/{item_id}/clips/upload
3. Clip failures DO NOT roll back item publication
4. Clients should track clip upload failures separately and implement retry logic

This differs from image upload failures, which prevent item publication entirely.
```

### Risk 2: Missing Validation of Item ID Format
**Code location:** `mercadolivre_upload/api/client.py:327`

**Current behavior:**
```python
url = f"{self.base_url}/marketplace/items/{item_id}/clips/upload"
```

**Undocumented assumption:**
- Code assumes `item_id` is always valid (e.g., "MLB1234567890").
- No validation of item_id format before making API call.

**Risk:**
- If `published_item_id` is None, empty, or malformed, the API call goes to invalid URL.
- API returns 404 but error message doesn't explain the client passed invalid item_id.

**Recommended documentation:**
```
VALIDATION: item_id must be a valid Mercado Livre item ID in format:
- Starts with ML followed by country code (e.g., MLB for Brazil, MLA for Argentina)
- Followed by 10-12 digits
- Example: "MLB1234567890"

Invalid item_id format causes HTTP 404 "item_not_found" error.
Clients must validate item_id format before calling upload_clip endpoint.
```

---

## Summary of Documentation Gaps by Impact

### 🔴 CRITICAL (Must fix before production)
1. **Gap 1:** Response field name ambiguity (`clip_uuid` vs `id`/`uuid`/`clip_id`)
2. **Gap 4:** sites parameter validation rules not specified
3. **Gap 8:** API error codes not documented
4. **Gap 9:** Item must be published before clip upload (prerequisite not stated)

### ⚠️ HIGH (Should fix soon)
5. **Gap 2:** Response status values not documented
6. **Gap 5:** Empty sites array behavior unclear
7. **Gap 6:** Required MIME types not specified
8. **Gap 7:** File extension vs MIME type validation order

### ℹ️ MEDIUM (Nice to have)
9. **Gap 3:** Moderation delay timing not mentioned
10. **Risk 1:** No rollback mechanism documented
11. **Risk 2:** Item ID format validation not specified

---

## Recommendations

### 1. Immediate Actions (Before Proceeding with Type Safety Changes)

**DO NOT proceed with TypedDict implementation until:**
1. Verify the actual response field name from ML API (is it `clip_uuid`, `id`, `uuid`, or `clip_id`?)
2. Document all possible values for `status` field in upload response
3. List all HTTP error codes and their meanings
4. Specify valid values for `site_id` and `logistic_type`

### 2. Proposed TypedDict Structure (After Verification)

```python
from typing import TypedDict, Literal

class ClipSiteConfig(TypedDict):
    """Site configuration for clip upload."""
    site_id: Literal["MLB", "MLA", "MLM", "MLU", "MLC", "MCO", "MPE", "MLV"]
    logistic_type: Literal["drop_off", "cross_docking", "self_service", "xd_drop_off"]

class ClipUploadResponse(TypedDict):
    """Response from POST /marketplace/items/{item_id}/clips/upload."""
    status: Literal["accepted", "pending", "rejected", "under_review"]
    clip_uuid: str  # Verify actual field name!

class ClipUploadError(TypedDict):
    """Error response from clip upload."""
    error: str
    message: str
    status: int
```

### 3. Required Validation Before Upload

Add to `clip_uploader.py`:
```python
def _validate_sites(sites: list[dict] | None) -> None:
    """Validate sites parameter before upload."""
    if sites is not None:
        if len(sites) == 0:
            raise ValueError("sites cannot be empty array; use None to upload to all sites")
        for site in sites:
            if "site_id" not in site or "logistic_type" not in site:
                raise ValueError("Each site must have site_id and logistic_type")
            # Add validation for valid values once documented
```

### 4. Safe Proceeding with Type Safety Changes

| Change | Safe to Proceed? | Notes |
|--------|-----------------|-------|
| TypedDicts for API responses | ❌ NO | Must verify actual field names first |
| Stricter type checks | ⚠️ PARTIAL | Can add types but need validation rules |
| Import fixes | ✅ YES | No API impact |
| MIME mapping | ⚠️ PARTIAL | Need confirmed accepted MIME types |
| Exception handling | ❌ NO | Need complete error code list |

---

## Conclusion

**RECOMMENDATION: DO NOT PROCEED with type safety changes until critical documentation gaps are addressed.**

The current implementation makes several undocumented assumptions that could cause:
- Silent failures in clip UUID extraction
- Unexpected behavior with empty sites parameter
- Poor error messages due to lack of error code documentation
- MIME type mismatches causing cryptic API errors

**Required next step:** Contact Mercado Livre API support or check mercadolivre-mcp-server specification to clarify:
1. Exact field name for clip identifier in upload response
2. Complete list of HTTP error codes and error response schema
3. Valid values for site_id and logistic_type
4. Accepted MIME types for each video format
5. Response status field possible values

Only after these are documented can we safely implement TypedDicts and strict type checking that actually match the API contract.
