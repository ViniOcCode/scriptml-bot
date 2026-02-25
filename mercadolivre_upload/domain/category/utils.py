"""Utility helpers for category resolver matching and normalization."""

import re
from typing import Any

from mercadolivre_upload.shared.utils.text_utils import TextNormalizer

CATEGORY_ID_PATTERN = re.compile(r"^[A-Z]{3}\d+$")


def normalize_site_id(site_id: str | None) -> str:
    """Normalize/validate a Mercado Livre site id."""
    if site_id is None:
        return "MLB"
    normalized = str(site_id).strip().upper()
    return normalized if normalized else "MLB"


def normalize_category_id(category_id: Any, expected_site_id: str | None = None) -> str | None:
    """Normalize category id and optionally validate site prefix."""
    if not isinstance(category_id, str):
        return None

    normalized = category_id.strip().upper()
    if not CATEGORY_ID_PATTERN.fullmatch(normalized):
        return None

    if expected_site_id:
        site_id = normalize_site_id(expected_site_id)
        if not normalized.startswith(site_id):
            return None

    return normalized


def split_category_query(name: str) -> tuple[str, set[str]]:
    """Split category query into target term and optional context path terms."""
    parts = [
        TextNormalizer.normalize(part)
        for part in re.split(r"\s*(?:>|/|\\|\|)\s*", str(name))
        if str(part).strip()
    ]
    if not parts:
        return "", set()
    return parts[-1], set(parts[:-1])


def safe_float(value: Any, default: float = 0.0) -> float:
    """Convert arbitrary value to float with deterministic default."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def pick_best_candidate(
    current: tuple[str, tuple[Any, ...]] | None,
    candidate: tuple[str, tuple[Any, ...]] | None,
) -> tuple[str, tuple[Any, ...]] | None:
    """Pick best scoring candidate with deterministic tie-break by id."""
    if candidate is None:
        return current
    if current is None:
        return candidate

    current_id, current_score = current
    candidate_id, candidate_score = candidate
    if candidate_score > current_score:
        return candidate
    if candidate_score < current_score:
        return current
    return candidate if candidate_id < current_id else current


def build_match_score(
    *,
    target_name: str,
    candidate_name: str,
    context_terms: set[str],
    path_names: list[str],
    depth: int,
    min_similarity: float,
) -> tuple[Any, ...] | None:
    """Compute category matching score tuple used for deterministic ranking."""
    if not target_name or not candidate_name:
        return None

    match_rank = 0
    similarity = 0.0
    length_bias = -abs(len(candidate_name) - len(target_name))

    if candidate_name == target_name:
        match_rank = 3
        similarity = 1.0
    elif target_name in candidate_name or candidate_name in target_name:
        match_rank = 2
        similarity = min(len(target_name), len(candidate_name)) / max(
            len(target_name), len(candidate_name)
        )
    else:
        similarity = TextNormalizer.similarity(candidate_name, target_name)
        if similarity < min_similarity:
            return None
        match_rank = 1

    context_match_count = sum(1 for token in context_terms if token in path_names)
    context_complete = int(bool(context_terms) and context_match_count == len(context_terms))
    return (
        context_complete,
        context_match_count,
        match_rank,
        round(similarity, 6),
        length_bias,
        -depth,
    )


def extract_technical_spec_attributes(specs: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Flatten technical specs input into an attribute ID map."""
    attributes: dict[str, dict[str, Any]] = {}
    groups = specs.get("groups", []) if isinstance(specs, dict) else []

    for group in groups:
        components = group.get("components", []) if isinstance(group, dict) else []
        for component in components:
            comp_attrs = component.get("attributes", []) if isinstance(component, dict) else []
            for attr in comp_attrs:
                if not isinstance(attr, dict):
                    continue
                attr_id = attr.get("id")
                if attr_id:
                    attributes[attr_id] = attr

    return attributes


def merge_technical_spec(attr: dict[str, Any], spec: dict[str, Any]) -> None:
    """Merge technical spec metadata into a base attribute definition."""
    if "relevance" in spec:
        attr["relevance"] = spec.get("relevance")
    if "hierarchy" in spec:
        attr["hierarchy"] = spec.get("hierarchy")

    if "tags" in spec:
        base_tags = attr.get("tags", {})
        merged_tags: dict[str, Any] = {}
        if isinstance(base_tags, dict):
            merged_tags.update(base_tags)
        elif isinstance(base_tags, list):
            merged_tags.update(dict.fromkeys(base_tags, True))

        spec_tags = spec.get("tags", [])
        if isinstance(spec_tags, dict):
            merged_tags.update(spec_tags)
        elif isinstance(spec_tags, list):
            merged_tags.update(dict.fromkeys(spec_tags, True))

        if merged_tags:
            attr["tags"] = merged_tags

    if spec.get("values") and not attr.get("values"):
        attr["values"] = spec.get("values")
