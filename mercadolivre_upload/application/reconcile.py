"""Reconcile generated builder payloads with live Mercado Livre inventory."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from mercadolivre_upload.application.ports import ItemInventoryPort
from mercadolivre_upload.contracts.run_manifest import load_run_manifest

ExecutionProfile = Literal["paid", "dev"]

ReconcileStatus = Literal[
    "generated_published",
    "generated_not_published",
    "closed_on_ml",
    "expected_not_generated",
    "local_payload_error",
    "manifest_error",
    "ml_without_local_payload",
]

RECONCILE_STATUSES: tuple[ReconcileStatus, ...] = (
    "generated_published",
    "generated_not_published",
    "closed_on_ml",
    "expected_not_generated",
    "local_payload_error",
    "manifest_error",
    "ml_without_local_payload",
)

PUBLISHED_ML_STATUSES = {"active", "paused"}
INVENTORY_ML_STATUSES = ("active", "paused", "closed")
SEARCH_PAGE_SIZE = 50
ITEM_BATCH_SIZE = 20
MAX_SCAN_PAGES_PER_STATUS = 10_000


class ReconcileUsageError(ValueError):
    """Raised when reconcile command inputs are invalid."""


class ReconcileOperationalError(RuntimeError):
    """Raised when reconcile cannot complete due to external/runtime errors."""


@dataclass(frozen=True)
class LocalPublication:
    """One local payload or manifest payload variant to reconcile."""

    group_id: str | None
    family_id: str | None
    sku_scope: tuple[str, ...]
    variant: str | None
    listing_type_id: str | None
    payload_path: str | None
    error_reason: str | None = None
    pre_status: ReconcileStatus | None = None


@dataclass(frozen=True)
class MercadoLivreItem:
    """One live Mercado Livre item with the fields needed for matching."""

    item_id: str
    status: str | None
    listing_type_id: str | None
    sku_scope: tuple[str, ...]


@dataclass
class ReconcileRow:
    """One report row."""

    status: ReconcileStatus
    group_id: str | None = None
    family_id: str | None = None
    sku_scope: list[str] = field(default_factory=list)
    variant: str | None = None
    listing_type_id: str | None = None
    ml_item_id: str | None = None
    ml_status: str | None = None
    payload_path: str | None = None
    error_reason: str | None = None
    ml_item_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert row to JSON-safe report shape."""
        return {
            "status": self.status,
            "group_id": self.group_id,
            "family_id": self.family_id,
            "sku_scope": self.sku_scope,
            "variant": self.variant,
            "listing_type_id": self.listing_type_id,
            "ml_item_id": self.ml_item_id,
            "ml_status": self.ml_status,
            "payload_path": self.payload_path,
            "error_reason": self.error_reason,
            "ml_item_ids": self.ml_item_ids,
        }


@dataclass
class ReconcileReport:
    """Structured reconcile result."""

    generated_at: str
    workspace_root: str
    source: str
    summary: dict[str, int]
    rows: list[ReconcileRow]
    execution_profile: ExecutionProfile = "paid"
    diagnostics: list[dict[str, str]] = field(default_factory=list)
    report_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert report to JSON-safe shape."""
        return {
            "generated_at": self.generated_at,
            "workspace_root": self.workspace_root,
            "source": self.source,
            "execution_profile": self.execution_profile,
            "summary": self.summary,
            "rows": [row.to_dict() for row in self.rows],
            "diagnostics": self.diagnostics,
            "report_path": self.report_path,
        }


def _clean_text(value: Any) -> str | None:
    if isinstance(value, str):
        normalized = value.strip()
        return normalized or None
    if isinstance(value, int):
        return str(value)
    return None


def _dedupe_text(values: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return tuple(result)


def _is_within_root(*, path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _metadata(raw: dict[str, Any]) -> dict[str, Any]:
    meta = raw.get("_meta")
    return meta if isinstance(meta, dict) else {}


def _publication_meta(meta: dict[str, Any]) -> dict[str, Any]:
    publication = meta.get("publication")
    return publication if isinstance(publication, dict) else {}


def _traceability_meta(meta: dict[str, Any]) -> dict[str, Any]:
    traceability = meta.get("traceability")
    return traceability if isinstance(traceability, dict) else {}


def _field_text(*sources: Any) -> str | None:
    for source in sources:
        normalized = _clean_text(source)
        if normalized:
            return normalized
    return None


def _is_marker_payload(raw: dict[str, Any]) -> bool:
    return raw.get("type") == "independent_listings_index"


def _publication_not_ready(raw: dict[str, Any]) -> str | None:
    meta = _metadata(raw)
    publication = _publication_meta(meta)
    for value in (
        raw.get("publishable"),
        meta.get("publishable"),
        publication.get("publishable"),
    ):
        if value is False:
            return "publishable_false"
    publication_ready = meta.get("publication_ready", publication.get("publication_ready"))
    if publication_ready is False:
        return "publication_ready_false"
    return None


def _has_root_item_fields(payload: dict[str, Any]) -> bool:
    return any(
        field in payload
        for field in (
            "title",
            "category_id",
            "price",
            "available_quantity",
            "pictures",
            "items",
            "payload",
            "family_name",
        )
    )


def _effective_payload_object(raw: dict[str, Any]) -> Any:
    payload_obj = raw.get("payload")
    if payload_obj is not None:
        return payload_obj
    return {
        key: value for key, value in raw.items() if key not in {"_meta", "fiscal", "description"}
    }


def _expand_payload_items(raw: dict[str, Any]) -> list[dict[str, Any]]:
    payload_obj = _effective_payload_object(raw)
    if isinstance(payload_obj, list):
        return [dict(item) for item in payload_obj if isinstance(item, dict)]

    if not isinstance(payload_obj, dict):
        return []

    nested_payload = payload_obj.get("payload")
    if isinstance(nested_payload, list):
        base = {
            key: value
            for key, value in payload_obj.items()
            if key not in {"payload", "items", "_meta", "fiscal", "description"}
        }
        return [{**base, **item} for item in nested_payload if isinstance(item, dict)]

    nested_items = payload_obj.get("items")
    if isinstance(nested_items, list):
        base = {
            key: value
            for key, value in payload_obj.items()
            if key not in {"payload", "items", "_meta", "fiscal", "description"}
        }
        return [{**base, **item} for item in nested_items if isinstance(item, dict)]

    nested_item = payload_obj.get("item")
    if isinstance(nested_item, dict) and not _has_root_item_fields(payload_obj):
        normalized = dict(nested_item)
        model = payload_obj.get("model")
        if isinstance(model, str) and "model" not in normalized:
            normalized["model"] = model
        return [normalized]

    return [dict(payload_obj)] if payload_obj else []


def _seller_skus_from_attributes(attributes: Any) -> list[str]:
    if not isinstance(attributes, list):
        return []

    skus: list[str] = []
    for attribute in attributes:
        if not isinstance(attribute, dict):
            continue
        attr_id = _clean_text(attribute.get("id"))
        if not attr_id or attr_id.upper() != "SELLER_SKU":
            continue
        for key in ("value_name", "value_id"):
            candidate = _clean_text(attribute.get(key))
            if candidate:
                skus.append(candidate)
    return skus


def _seller_skus_from_payload_item(item: dict[str, Any]) -> list[str]:
    skus: list[str] = []
    seller_custom_field = _clean_text(item.get("seller_custom_field"))
    if seller_custom_field:
        skus.append(seller_custom_field)
    skus.extend(_seller_skus_from_attributes(item.get("attributes")))

    variations = item.get("variations")
    if not isinstance(variations, list):
        return skus

    for variation in variations:
        if not isinstance(variation, dict):
            continue
        variation_seller_custom_field = _clean_text(variation.get("seller_custom_field"))
        if variation_seller_custom_field:
            skus.append(variation_seller_custom_field)
        skus.extend(_seller_skus_from_attributes(variation.get("attributes")))
        skus.extend(_seller_skus_from_attributes(variation.get("attribute_combinations")))
    return skus


def _traceability_skus(meta: dict[str, Any]) -> list[str]:
    traceability = _traceability_meta(meta)
    raw_skus = traceability.get("publish_item_skus")
    if not isinstance(raw_skus, list):
        return []
    return [sku for raw_sku in raw_skus if (sku := _clean_text(raw_sku))]


def _payload_skus(raw: dict[str, Any]) -> tuple[str, ...]:
    meta = _metadata(raw)
    skus: list[str] = []
    skus.extend(_traceability_skus(meta))
    meta_sku = _clean_text(meta.get("sku"))
    if meta_sku:
        skus.append(meta_sku)
    for item in _expand_payload_items(raw):
        skus.extend(_seller_skus_from_payload_item(item))
    return _dedupe_text(skus)


def _payload_listing_type_id(raw: dict[str, Any]) -> tuple[str | None, str | None]:
    listing_types = {
        listing_type
        for item in _expand_payload_items(raw)
        if (listing_type := _clean_text(item.get("listing_type_id")))
    }
    if not listing_types:
        return None, "listing_type_id_missing"
    if len(listing_types) > 1:
        return None, "listing_type_id_inconsistent"
    return next(iter(listing_types)), None


def _group_id_from_path(payload_path: Path, workspace_root: Path) -> str | None:
    try:
        relative = payload_path.relative_to(workspace_root)
    except ValueError:
        return payload_path.parent.name
    parts = relative.parts
    if "groups" in parts:
        index = parts.index("groups")
        if index + 1 < len(parts):
            return parts[index + 1]
    return payload_path.parent.name


def _local_identity(
    *,
    payload_path: Path,
    workspace_root: Path,
    raw: dict[str, Any],
    group_id: str | None = None,
    family_id: str | None = None,
    variant: str | None = None,
) -> tuple[str | None, str | None, str | None]:
    meta = _metadata(raw)
    publication = _publication_meta(meta)
    traceability = _traceability_meta(meta)
    resolved_group_id = _field_text(
        group_id,
        traceability.get("group_id"),
        meta.get("group_id"),
        _group_id_from_path(payload_path, workspace_root),
    )
    resolved_family_id = _field_text(
        family_id,
        traceability.get("family_id"),
        traceability.get("family_key"),
        meta.get("family_id"),
    )
    resolved_variant = _field_text(variant, publication.get("variant"), meta.get("variant"))
    return resolved_group_id, resolved_family_id, resolved_variant


def _local_publication_from_raw(
    *,
    payload_path: Path,
    workspace_root: Path,
    raw: dict[str, Any],
    group_id: str | None = None,
    family_id: str | None = None,
    variant: str | None = None,
    listing_type_id: str | None = None,
) -> LocalPublication | None:
    if _is_marker_payload(raw):
        return None

    resolved_group_id, resolved_family_id, resolved_variant = _local_identity(
        payload_path=payload_path,
        workspace_root=workspace_root,
        raw=raw,
        group_id=group_id,
        family_id=family_id,
        variant=variant,
    )
    skus = _payload_skus(raw)
    payload_listing_type_id, listing_error = _payload_listing_type_id(raw)
    effective_listing_type_id = listing_type_id or payload_listing_type_id

    not_ready_reason = _publication_not_ready(raw)
    if not_ready_reason:
        return LocalPublication(
            group_id=resolved_group_id,
            family_id=resolved_family_id,
            sku_scope=skus,
            variant=resolved_variant,
            listing_type_id=effective_listing_type_id,
            payload_path=str(payload_path),
            error_reason=not_ready_reason,
            pre_status="local_payload_error",
        )
    if listing_error:
        return LocalPublication(
            group_id=resolved_group_id,
            family_id=resolved_family_id,
            sku_scope=skus,
            variant=resolved_variant,
            listing_type_id=effective_listing_type_id,
            payload_path=str(payload_path),
            error_reason=listing_error,
            pre_status="local_payload_error",
        )
    if listing_type_id and payload_listing_type_id and listing_type_id != payload_listing_type_id:
        return LocalPublication(
            group_id=resolved_group_id,
            family_id=resolved_family_id,
            sku_scope=skus,
            variant=resolved_variant,
            listing_type_id=listing_type_id,
            payload_path=str(payload_path),
            error_reason=(
                "listing_type_id_mismatch: "
                f"manifest={listing_type_id} payload={payload_listing_type_id}"
            ),
            pre_status="local_payload_error",
        )
    if not skus:
        return LocalPublication(
            group_id=resolved_group_id,
            family_id=resolved_family_id,
            sku_scope=(),
            variant=resolved_variant,
            listing_type_id=effective_listing_type_id,
            payload_path=str(payload_path),
            error_reason="seller_sku_missing",
            pre_status="local_payload_error",
        )

    return LocalPublication(
        group_id=resolved_group_id,
        family_id=resolved_family_id,
        sku_scope=skus,
        variant=resolved_variant,
        listing_type_id=effective_listing_type_id,
        payload_path=str(payload_path),
    )


def _local_payload_error(
    *,
    status: ReconcileStatus,
    group_id: str | None = None,
    family_id: str | None = None,
    sku_scope: list[str] | tuple[str, ...] | None = None,
    variant: str | None = None,
    listing_type_id: str | None = None,
    payload_path: Path | str | None = None,
    error_reason: str | None = None,
) -> ReconcileRow:
    return ReconcileRow(
        status=status,
        group_id=group_id,
        family_id=family_id,
        sku_scope=list(sku_scope or []),
        variant=variant,
        listing_type_id=listing_type_id,
        payload_path=str(payload_path) if payload_path is not None else None,
        error_reason=error_reason,
    )


def _read_local_payload(
    *,
    payload_path: Path,
    workspace_root: Path,
    group_id: str | None = None,
    family_id: str | None = None,
    variant: str | None = None,
    listing_type_id: str | None = None,
) -> tuple[LocalPublication | None, ReconcileRow | None]:
    try:
        raw_value = json.loads(payload_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return None, _local_payload_error(
            status="local_payload_error",
            group_id=group_id,
            family_id=family_id,
            variant=variant,
            listing_type_id=listing_type_id,
            payload_path=payload_path,
            error_reason=f"invalid_json: {exc}",
        )
    except OSError as exc:
        return None, _local_payload_error(
            status="local_payload_error",
            group_id=group_id,
            family_id=family_id,
            variant=variant,
            listing_type_id=listing_type_id,
            payload_path=payload_path,
            error_reason=f"payload_read_error: {exc}",
        )
    if not isinstance(raw_value, dict):
        return None, _local_payload_error(
            status="local_payload_error",
            group_id=group_id,
            family_id=family_id,
            variant=variant,
            listing_type_id=listing_type_id,
            payload_path=payload_path,
            error_reason="payload_root_not_object",
        )
    return (
        _local_publication_from_raw(
            payload_path=payload_path,
            workspace_root=workspace_root,
            raw=raw_value,
            group_id=group_id,
            family_id=family_id,
            variant=variant,
            listing_type_id=listing_type_id,
        ),
        None,
    )


def _resolve_manifest_payload_path(
    *,
    manifest_path: Path,
    workspace_root: Path,
    raw_path: str,
) -> Path:
    path = Path(raw_path).expanduser()
    resolved_workspace = workspace_root.expanduser().resolve()
    if path.is_absolute():
        candidates = [path.resolve()]
    elif path.parts and path.parts[0] == resolved_workspace.name:
        candidates = [
            (resolved_workspace.parent / path).resolve(),
            (manifest_path.parent / path).resolve(),
        ]
    else:
        candidates = [
            (manifest_path.parent / path).resolve(),
            (resolved_workspace / path).resolve(),
        ]

    valid_candidates = [
        candidate
        for candidate in candidates
        if _is_within_root(path=candidate, root=resolved_workspace)
    ]
    if not valid_candidates:
        raise ValueError(f"Payload path escapes workspace root: {candidates[0]}")

    for candidate in valid_candidates:
        if candidate.exists():
            return candidate
    return valid_candidates[0]


def _select_manifest_paths(
    *,
    workspace_root: Path,
    manifest_path: Path | None,
    run_id: str | None,
    all_manifests: bool,
) -> tuple[list[Path], str]:
    selectors = sum(
        [
            manifest_path is not None,
            bool(run_id),
            all_manifests,
        ]
    )
    if selectors > 1:
        raise ReconcileUsageError("Use only one of --manifest, --run-id, or --all-manifests")
    if manifest_path is not None:
        return [manifest_path.expanduser().resolve()], "manifest"
    if run_id:
        return [workspace_root / "runs" / run_id / "run_manifest.json"], "manifest"

    candidates = sorted((workspace_root / "runs").rglob("run_manifest.json"))
    if all_manifests:
        return candidates, "all_manifests"
    if not candidates:
        raise ReconcileUsageError(f"No run_manifest.json found under {workspace_root / 'runs'}")
    newest = max(candidates, key=lambda path: path.stat().st_mtime)
    return [newest], "manifest"


def _artifact_publications(
    workspace_root: Path,
) -> tuple[list[LocalPublication], list[ReconcileRow]]:
    publications: list[LocalPublication] = []
    rows: list[ReconcileRow] = []
    groups_root = workspace_root / "groups"
    if not groups_root.exists():
        return publications, rows

    for payload_path in sorted(groups_root.rglob("70_payload.json")):
        publication, error_row = _read_local_payload(
            payload_path=payload_path,
            workspace_root=workspace_root,
        )
        if error_row is not None:
            rows.append(error_row)
        if publication is not None:
            publications.append(publication)
    return publications, rows


def _manifest_publications(
    *,
    workspace_root: Path,
    manifest_paths: list[Path],
    execution_profile: ExecutionProfile,
    skip_profile_mismatches: bool,
) -> tuple[list[LocalPublication], list[ReconcileRow], list[dict[str, str]]]:
    publications: list[LocalPublication] = []
    rows: list[ReconcileRow] = []
    diagnostics: list[dict[str, str]] = []
    for manifest_path in manifest_paths:
        try:
            manifest = load_run_manifest(manifest_path)
        except Exception as exc:  # noqa: BLE001
            rows.append(
                ReconcileRow(
                    status="manifest_error",
                    payload_path=str(manifest_path),
                    error_reason=f"manifest_invalid: {exc}",
                )
            )
            continue

        if manifest.execution_profile != execution_profile:
            if not skip_profile_mismatches:
                raise ReconcileUsageError(
                    f"Manifest execution_profile={manifest.execution_profile!r} does not match "
                    f"requested profile {execution_profile!r}: {manifest_path}"
                )
            diagnostics.append(
                {
                    "code": "manifest_execution_profile_skipped",
                    "manifest_path": str(manifest_path),
                    "requested_execution_profile": execution_profile,
                    "manifest_execution_profile": manifest.execution_profile,
                }
            )
            continue

        for failure in manifest.build_failures:
            failure_sku = _clean_text(getattr(failure, "sku", None))
            reason = (
                ":".join(
                    part
                    for part in [
                        _clean_text(getattr(failure, "stage", None)),
                        _clean_text(getattr(failure, "reason", None)),
                    ]
                    if part
                )
                or "build_failure"
            )
            rows.append(
                ReconcileRow(
                    status="expected_not_generated",
                    group_id=getattr(failure, "group_id", None),
                    family_id=getattr(failure, "family_id", None),
                    sku_scope=[failure_sku] if failure_sku else [],
                    error_reason=reason,
                )
            )

        for candidate in manifest.publication_candidates:
            for payload_variant in candidate.payloads:
                payload_path_text = _clean_text(payload_variant.payload_path)
                if not payload_path_text:
                    rows.append(
                        _local_payload_error(
                            status="expected_not_generated",
                            group_id=candidate.group_id,
                            family_id=candidate.family_id,
                            sku_scope=candidate.sku_scope,
                            variant=payload_variant.variant,
                            listing_type_id=payload_variant.listing_type_id,
                            error_reason="payload_path_missing",
                        )
                    )
                    continue

                try:
                    payload_path = _resolve_manifest_payload_path(
                        manifest_path=manifest_path,
                        workspace_root=workspace_root,
                        raw_path=payload_path_text,
                    )
                except ValueError as exc:
                    rows.append(
                        _local_payload_error(
                            status="local_payload_error",
                            group_id=candidate.group_id,
                            family_id=candidate.family_id,
                            sku_scope=candidate.sku_scope,
                            variant=payload_variant.variant,
                            listing_type_id=payload_variant.listing_type_id,
                            payload_path=payload_path_text,
                            error_reason=str(exc),
                        )
                    )
                    continue

                if not payload_variant.publishable:
                    rows.append(
                        _local_payload_error(
                            status="local_payload_error",
                            group_id=candidate.group_id,
                            family_id=candidate.family_id,
                            sku_scope=candidate.sku_scope,
                            variant=payload_variant.variant,
                            listing_type_id=payload_variant.listing_type_id,
                            payload_path=payload_path,
                            error_reason="manifest_marked_not_publishable",
                        )
                    )
                    continue
                if payload_variant.block_reason or payload_variant.skip_reason:
                    rows.append(
                        _local_payload_error(
                            status="local_payload_error",
                            group_id=candidate.group_id,
                            family_id=candidate.family_id,
                            sku_scope=candidate.sku_scope,
                            variant=payload_variant.variant,
                            listing_type_id=payload_variant.listing_type_id,
                            payload_path=payload_path,
                            error_reason=payload_variant.block_reason
                            or payload_variant.skip_reason,
                        )
                    )
                    continue
                if not payload_path.exists() or not payload_path.is_file():
                    rows.append(
                        _local_payload_error(
                            status="expected_not_generated",
                            group_id=candidate.group_id,
                            family_id=candidate.family_id,
                            sku_scope=candidate.sku_scope,
                            variant=payload_variant.variant,
                            listing_type_id=payload_variant.listing_type_id,
                            payload_path=payload_path,
                            error_reason="payload_missing",
                        )
                    )
                    continue

                publication, error_row = _read_local_payload(
                    payload_path=payload_path,
                    workspace_root=workspace_root,
                    group_id=candidate.group_id,
                    family_id=candidate.family_id,
                    variant=payload_variant.variant,
                    listing_type_id=payload_variant.listing_type_id,
                )
                if error_row is not None:
                    rows.append(error_row)
                if publication is not None:
                    publications.append(publication)
    return publications, rows, diagnostics


def _item_from_batch_entry(entry: Any) -> dict[str, Any] | None:
    if not isinstance(entry, dict):
        return None
    body = entry.get("body")
    if isinstance(body, dict):
        code = entry.get("code")
        if isinstance(code, int) and code >= 400:
            return None
        return body
    if entry.get("id") is not None:
        return entry
    return None


def _ml_item_from_payload(payload: dict[str, Any]) -> MercadoLivreItem | None:
    item_id = _clean_text(payload.get("id"))
    if not item_id:
        return None
    status = _clean_text(payload.get("status"))
    listing_type_id = _clean_text(payload.get("listing_type_id"))
    sku_scope = _dedupe_text(_seller_skus_from_payload_item(payload))
    return MercadoLivreItem(
        item_id=item_id,
        status=status,
        listing_type_id=listing_type_id,
        sku_scope=sku_scope,
    )


def _fetch_ml_inventory(inventory: ItemInventoryPort) -> list[MercadoLivreItem]:
    seller = inventory.get_users_me()
    seller_id = _clean_text(seller.get("id"))
    if not seller_id:
        raise ReconcileOperationalError("GET /users/me did not return seller id")

    item_ids: list[str] = []
    seen_ids: set[str] = set()
    for status in INVENTORY_ML_STATUSES:
        scroll_id: str | None = None
        seen_scroll_ids: set[str] = set()
        seen_page_signatures: set[tuple[str, ...]] = set()
        declared_total: int | None = None
        fetched_for_status = 0
        page_count = 0
        while True:
            page_count += 1
            if page_count > MAX_SCAN_PAGES_PER_STATUS:
                raise ReconcileOperationalError(
                    "Mercado Livre inventory scan exceeded "
                    f"{MAX_SCAN_PAGES_PER_STATUS} page(s) for status={status!r}."
                )
            response = inventory.search_user_items(
                seller_id,
                status=status,
                limit=SEARCH_PAGE_SIZE,
                search_type="scan",
                scroll_id=scroll_id,
            )
            raw_results = response.get("results")
            results = raw_results if isinstance(raw_results, list) else []
            page_ids = [item_id for raw_item_id in results if (item_id := _clean_text(raw_item_id))]
            if declared_total is None:
                paging = response.get("paging")
                raw_total = paging.get("total") if isinstance(paging, dict) else None
                if isinstance(raw_total, int) and raw_total >= 0:
                    declared_total = raw_total
                elif isinstance(raw_total, str) and raw_total.isdigit():
                    declared_total = int(raw_total)
            if declared_total is not None:
                remaining = max(declared_total - fetched_for_status, 0)
                page_ids = page_ids[:remaining]
            page_signature = tuple(page_ids)
            if page_signature and page_signature in seen_page_signatures:
                raise ReconcileOperationalError(
                    "Mercado Livre inventory scan returned a repeated page "
                    f"for status={status!r} and scroll_id={scroll_id!r}."
                )
            if page_signature:
                seen_page_signatures.add(page_signature)
            for item_id in page_ids:
                if item_id in seen_ids:
                    continue
                seen_ids.add(item_id)
                item_ids.append(item_id)
            fetched_for_status += len(page_ids)

            if not page_ids:
                break
            if declared_total is not None and fetched_for_status >= declared_total:
                break
            next_scroll_id = _clean_text(response.get("scroll_id"))
            if not next_scroll_id:
                break
            if next_scroll_id == scroll_id or next_scroll_id in seen_scroll_ids:
                raise ReconcileOperationalError(
                    "Mercado Livre inventory scan returned a repeated scroll_id "
                    f"for status={status!r}: {next_scroll_id!r}."
                )
            seen_scroll_ids.add(next_scroll_id)
            scroll_id = next_scroll_id

    items: list[MercadoLivreItem] = []
    for index in range(0, len(item_ids), ITEM_BATCH_SIZE):
        batch_ids = item_ids[index : index + ITEM_BATCH_SIZE]
        for entry in inventory.get_items_batch(batch_ids):
            body = _item_from_batch_entry(entry)
            if body is None:
                continue
            item = _ml_item_from_payload(body)
            if item is not None:
                items.append(item)
    return items


def _row_from_local(
    *,
    local: LocalPublication,
    status: ReconcileStatus,
    matches: list[MercadoLivreItem] | None = None,
    error_reason: str | None = None,
) -> ReconcileRow:
    matched_items = matches or []
    ml_item_ids = [item.item_id for item in matched_items]
    ml_statuses = _dedupe_text(
        [item.status for item in matched_items if isinstance(item.status, str)]
    )
    return ReconcileRow(
        status=status,
        group_id=local.group_id,
        family_id=local.family_id,
        sku_scope=list(local.sku_scope),
        variant=local.variant,
        listing_type_id=local.listing_type_id,
        ml_item_id=ml_item_ids[0] if ml_item_ids else None,
        ml_status=",".join(ml_statuses) if ml_statuses else None,
        payload_path=local.payload_path,
        error_reason=error_reason or local.error_reason,
        ml_item_ids=ml_item_ids,
    )


def _dedupe_ml_items(items: list[MercadoLivreItem]) -> list[MercadoLivreItem]:
    seen: set[str] = set()
    result: list[MercadoLivreItem] = []
    for item in items:
        if item.item_id in seen:
            continue
        seen.add(item.item_id)
        result.append(item)
    return result


def _status_rank(item: MercadoLivreItem) -> tuple[int, str]:
    status = item.status or ""
    ranks = {"active": 0, "paused": 1, "closed": 2}
    return ranks.get(status, 99), item.item_id


def _reconcile_rows(
    *,
    publications: list[LocalPublication],
    pre_rows: list[ReconcileRow],
    ml_items: list[MercadoLivreItem],
) -> list[ReconcileRow]:
    by_key: dict[tuple[str, str], list[MercadoLivreItem]] = {}
    by_sku: dict[str, list[MercadoLivreItem]] = {}
    for item in ml_items:
        for sku in item.sku_scope:
            by_sku.setdefault(sku, []).append(item)
            if item.listing_type_id:
                by_key.setdefault((sku, item.listing_type_id), []).append(item)

    rows = list(pre_rows)
    consumed_item_ids: set[str] = set()
    for local in publications:
        if local.pre_status is not None:
            rows.append(_row_from_local(local=local, status=local.pre_status))
            continue

        matches: list[MercadoLivreItem] = []
        if local.listing_type_id:
            for sku in local.sku_scope:
                matches.extend(by_key.get((sku, local.listing_type_id), []))
        matches = _dedupe_ml_items(sorted(matches, key=_status_rank))
        published_matches = [
            item for item in matches if (item.status or "") in PUBLISHED_ML_STATUSES
        ]
        closed_matches = [item for item in matches if item.status == "closed"]
        if published_matches:
            for item in published_matches:
                consumed_item_ids.add(item.item_id)
            rows.append(
                _row_from_local(
                    local=local,
                    status="generated_published",
                    matches=published_matches,
                )
            )
            continue
        if closed_matches:
            for item in closed_matches:
                consumed_item_ids.add(item.item_id)
            rows.append(
                _row_from_local(
                    local=local,
                    status="closed_on_ml",
                    matches=closed_matches,
                )
            )
            continue

        same_sku_items: list[MercadoLivreItem] = []
        for sku in local.sku_scope:
            same_sku_items.extend(by_sku.get(sku, []))
        same_sku_items = _dedupe_ml_items(same_sku_items)
        has_listing_mismatch = any(
            item.listing_type_id
            and local.listing_type_id
            and item.listing_type_id != local.listing_type_id
            for item in same_sku_items
        )
        rows.append(
            _row_from_local(
                local=local,
                status="generated_not_published",
                error_reason="listing_type_mismatch" if has_listing_mismatch else None,
            )
        )

    for item in ml_items:
        if item.item_id in consumed_item_ids:
            continue
        rows.append(
            ReconcileRow(
                status="ml_without_local_payload",
                sku_scope=list(item.sku_scope),
                listing_type_id=item.listing_type_id,
                ml_item_id=item.item_id,
                ml_item_ids=[item.item_id],
                ml_status=item.status,
                error_reason=None if item.sku_scope else "seller_sku_missing",
            )
        )
    return rows


def _build_summary(rows: list[ReconcileRow]) -> dict[str, int]:
    counts = Counter(row.status for row in rows)
    summary: dict[str, int] = {status: counts.get(status, 0) for status in RECONCILE_STATUSES}
    summary["total"] = len(rows)
    return summary


def _write_report(report: ReconcileReport, workspace_root: Path) -> Path:
    audit_dir = workspace_root / "publication_audits"
    audit_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    report_path = audit_dir / f"reconcile-{timestamp}.json"
    report.report_path = str(report_path)
    report_path.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return report_path


class ReconcileUseCase:
    """Compare local generated payloads with live Mercado Livre inventory."""

    def __init__(self, inventory: ItemInventoryPort) -> None:
        """Initialize with an inventory reader implementation."""
        self._inventory = inventory

    def execute(
        self,
        *,
        workspace_root: Path,
        execution_profile: ExecutionProfile = "paid",
        from_manifest: bool = False,
        manifest_path: Path | None = None,
        run_id: str | None = None,
        all_manifests: bool = False,
        save_report: bool = False,
    ) -> ReconcileReport:
        """Run reconciliation and optionally persist a JSON audit report."""
        if execution_profile not in {"paid", "dev"}:
            raise ReconcileUsageError("execution_profile must be 'paid' or 'dev'")
        workspace = workspace_root.expanduser().resolve()
        if not workspace.exists() or not workspace.is_dir():
            raise ReconcileUsageError(f"Workspace not found: {workspace}")
        if execution_profile == "paid" and not from_manifest:
            raise ReconcileUsageError(
                "Paid reconcile requires canonical manifest provenance; "
                "set from_manifest=True and select a manifest, run, or all manifests."
            )

        if from_manifest:
            manifest_paths, source = _select_manifest_paths(
                workspace_root=workspace,
                manifest_path=manifest_path,
                run_id=run_id,
                all_manifests=all_manifests,
            )
            publications, pre_rows, diagnostics = _manifest_publications(
                workspace_root=workspace,
                manifest_paths=manifest_paths,
                execution_profile=execution_profile,
                skip_profile_mismatches=source == "all_manifests",
            )
        else:
            if manifest_path is not None or run_id or all_manifests:
                raise ReconcileUsageError(
                    "--manifest, --run-id, and --all-manifests require --from-manifest"
                )
            source = "artifacts"
            publications, pre_rows = _artifact_publications(workspace)
            diagnostics = []

        manifest_only_errors = (
            from_manifest
            and not publications
            and pre_rows
            and all(row.status == "manifest_error" for row in pre_rows)
        )
        ml_items = [] if manifest_only_errors else _fetch_ml_inventory(self._inventory)
        rows = _reconcile_rows(
            publications=publications,
            pre_rows=pre_rows,
            ml_items=ml_items,
        )
        report = ReconcileReport(
            generated_at=datetime.now(UTC).isoformat(),
            workspace_root=str(workspace),
            source=source,
            summary=_build_summary(rows),
            rows=rows,
            execution_profile=execution_profile,
            diagnostics=diagnostics,
        )
        if save_report:
            try:
                _write_report(report, workspace)
            except OSError as exc:
                raise ReconcileOperationalError(f"Could not write reconcile report: {exc}") from exc
        return report


__all__ = [
    "ExecutionProfile",
    "ReconcileOperationalError",
    "ReconcileReport",
    "ReconcileRow",
    "ReconcileUsageError",
    "ReconcileUseCase",
]
