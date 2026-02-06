"""Type definitions for Mercado Livre API payloads and responses."""

from typing import Literal, NotRequired, TypedDict


class ClipSite(TypedDict):
    """Site specification for clip upload/delete operations."""

    site_id: str  # Ex: "MLB", "MLA"
    logistic_type: str  # Ex: "drop_off", "cross_docking"


class ClipUploadResponse(TypedDict):
    """Response from POST /marketplace/items/{item_id}/clips/upload."""

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
    """Response from GET /marketplace/items/{item_id}/clips."""

    parent_item_id: str
    parent_user_id: int
    clips: list[ClipInfo]


class ClipDeleteRequest(TypedDict):
    """Request body for clip deletion."""

    sites: list[ClipSite]
