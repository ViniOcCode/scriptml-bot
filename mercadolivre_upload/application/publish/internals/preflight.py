"""Preflight helpers extracted from publish orchestration."""

from __future__ import annotations

import logging
from typing import Any

from ...policy_snapshot import compile_schema_contract

logger = logging.getLogger(__name__)


def _as_artifact(value: Any, fallback: dict[str, Any] | None = None) -> dict[str, Any]:
    """Normalize unknown values to dictionary artifacts."""
    if isinstance(value, dict):
        return value
    if fallback is None:
        return {}
    return dict(fallback)


def get_schema_contract_compiled(use_case: Any, category_id: str) -> dict[str, Any]:
    """Compile and cache schema contract for a category."""
    cached = use_case._category_schema_contract_cache.get(category_id)
    if isinstance(cached, dict):
        return cached

    category_data = use_case._get_policy_category_data(category_id)
    attributes = use_case._get_policy_attributes(category_id)
    sale_terms = list(use_case._get_category_sale_terms_map(category_id).values())

    try:
        compiled_raw = compile_schema_contract(
            category_id=category_id,
            category_data=category_data,
            attributes=attributes,
            sale_terms=sale_terms,
        )
    except Exception as error:
        logger.error("Failed to compile schema contract for %s: %s", category_id, error)
        compiled_raw = compile_schema_contract(
            category_id=category_id,
            category_data={},
            attributes=[],
            sale_terms=[],
        )
    compiled = _as_artifact(compiled_raw)

    summary = compiled.get("schema_contract_summary", {})
    if isinstance(summary, dict):
        if summary.get("required_attribute_count", 0) == 0:
            logger.info(
                "Schema contract %s has no deterministic required attributes metadata.",
                category_id,
            )
        if summary.get("max_pictures") is None and summary.get("max_variations_allowed") is None:
            logger.info(
                "Schema contract %s has no category limits metadata for pictures/variations.",
                category_id,
            )

    use_case._category_schema_contract_cache[category_id] = compiled
    return compiled


def get_schema_contract_artifact(use_case: Any, category_id: str) -> dict[str, Any]:
    """Return compact schema contract metadata for reports."""
    compiled = get_schema_contract_compiled(use_case, category_id)
    artifact: dict[str, Any] = {}
    schema_contract_hash = compiled.get("schema_contract_hash")
    if isinstance(schema_contract_hash, str) and schema_contract_hash:
        artifact["schema_contract_hash"] = schema_contract_hash
    summary = compiled.get("schema_contract_summary")
    if isinstance(summary, dict):
        artifact["schema_contract_summary"] = summary
    return artifact


def run_image_diagnostic_preflight(
    use_case: Any,
    *,
    sku: str,
    title: str,
    category_id: str,
    picture_urls: list[str],
    picture_ids: list[str],
) -> dict[str, Any]:
    """Run optional image diagnostics before validate/publish gates."""
    artifact: dict[str, Any] = {
        "status": "unavailable",
        "available": False,
        "checked": 0,
        "issues": [],
        "results": [],
    }

    if use_case.image_diagnostics_gate_mode == "disabled":
        artifact["status"] = "skipped"
        artifact["message"] = (
            "Image diagnostics gate disabled by rollout flag 'image_diagnostics.gate_mode'."
        )
        annotated = use_case._annotate_image_diagnostics_artifact(artifact)
        return _as_artifact(annotated, artifact)

    diagnose_images = getattr(use_case.image_uploader, "diagnose_images", None)
    if not callable(diagnose_images):
        message = "Image diagnostics unavailable: image uploader does not expose diagnose_images."
        logger.warning(message)
        artifact["message"] = message
        annotated = use_case._annotate_image_diagnostics_artifact(artifact)
        return _as_artifact(annotated, artifact)

    try:
        diagnostic_result = diagnose_images(
            sku=sku,
            category_id=category_id,
            title=title,
            picture_urls=picture_urls,
            picture_ids=picture_ids,
        )
    except Exception as error:
        message = f"Image diagnostics preflight failed for {sku}: {error}"
        logger.warning(message)
        artifact["message"] = message
        annotated = use_case._annotate_image_diagnostics_artifact(artifact)
        return _as_artifact(annotated, artifact)

    if isinstance(diagnostic_result, dict):
        annotated = use_case._annotate_image_diagnostics_artifact(diagnostic_result)
        return _as_artifact(annotated, artifact)

    message = (
        "Image diagnostics preflight returned unexpected payload type: "
        f"{type(diagnostic_result).__name__}"
    )
    logger.warning(message)
    artifact["message"] = message
    annotated = use_case._annotate_image_diagnostics_artifact(artifact)
    return _as_artifact(annotated, artifact)
