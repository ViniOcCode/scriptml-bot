"""Deterministic preflight gatherer for category attribute/value mapping.

This module powers an external script to validate spreadsheet headers and values
against Mercado Livre category schema before running upload/validate.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from mercadolivre_upload.adapters.spreadsheet.parser import SpreadsheetParser
from mercadolivre_upload.api.category_adapter import CategoryAdapter
from mercadolivre_upload.api.client import MLApiClient
from mercadolivre_upload.auth import AuthManager
from mercadolivre_upload.domain.cache_attribute_mapper_helpers import (
    extract_variation_hint_from_normalized,
    is_blocked_header,
)
from mercadolivre_upload.domain.category.resolver import CategoryResolver
from mercadolivre_upload.infrastructure.cache.attribute_cache import AttributeCache
from mercadolivre_upload.infrastructure.cache.prediction_cache import PredictionCache
from mercadolivre_upload.shared.utils.config_loader import (
    RUNTIME_SPLIT_CONFIG_PATHS,
    load_merged_yaml_config,
)
from mercadolivre_upload.shared.utils.text_utils import PortugueseTextNormalizer

logger = logging.getLogger(__name__)

CATEGORY_ID_PATTERN = re.compile(r"^ML[A-Z]\d+$")
SPLIT_PATTERN = re.compile(r"[,;/|]")
HEADER_SCORE_THRESHOLD = 0.92
HEADER_SCORE_MARGIN = 0.05
VALUE_SCORE_THRESHOLD = 0.95
VALUE_SCORE_MARGIN = 0.03
NON_FILLABLE_TAGS = {"hidden", "read_only", "non_modifiable"}


@dataclass(frozen=True)
class HeaderMatch:
    """Resolved header candidate match."""

    attribute_id: str
    attribute_name: str
    score: float
    method: str


@dataclass(frozen=True)
class ValueTokenMatch:
    """Resolution result for one token in a cell."""

    raw_token: str
    status: str
    value_id: str | None
    value_name: str | None
    score: float
    reason: str | None = None


def _normalize(text: str) -> str:
    return PortugueseTextNormalizer.normalize(str(text))


def _normalize_header_for_matching(header: str) -> str:
    normalized_header = _normalize(header)
    variation_hint = extract_variation_hint_from_normalized(normalized_header)
    return variation_hint or normalized_header


def _token_overlap(a: str, b: str) -> float:
    a_tokens = {token for token in a.split() if token}
    b_tokens = {token for token in b.split() if token}
    if not a_tokens or not b_tokens:
        return 0.0
    intersection = len(a_tokens.intersection(b_tokens))
    denominator = max(len(a_tokens), len(b_tokens))
    return intersection / denominator


def _string_similarity(a: str, b: str) -> float:
    return PortugueseTextNormalizer.similarity(a, b)


def _extract_numeric_and_unit(raw_value: str) -> tuple[float | int | None, str | None]:
    value = str(raw_value).strip()
    if not value:
        return None, None
    match = re.match(r"^([+-]?\d+(?:[.,]\d+)?)\s*([^\d].*)?$", value)
    if not match:
        return None, None

    number_raw = match.group(1).replace(",", ".")
    numeric: float | int
    try:
        numeric_float = float(number_raw)
    except ValueError:
        return None, None

    numeric = int(numeric_float) if numeric_float.is_integer() else numeric_float
    unit_raw = (match.group(2) or "").strip()
    return numeric, unit_raw or None


def _split_cell_values(raw_value: str) -> list[str]:
    value = str(raw_value).strip()
    if not value:
        return []
    parts = [part.strip() for part in SPLIT_PATTERN.split(value) if part.strip()]
    return parts if parts else [value]


def _parse_tags(raw_tags: Any) -> dict[str, bool]:
    if isinstance(raw_tags, dict):
        parsed: dict[str, bool] = {}
        for key, value in raw_tags.items():
            normalized = _normalize(str(key)).replace("-", "_")
            parsed[normalized] = bool(value)
        return parsed
    if isinstance(raw_tags, (list, tuple, set)):
        return {
            _normalize(str(value)).replace("-", "_"): True
            for value in raw_tags
            if str(value).strip()
        }
    return {}


def _is_required_fillable(attribute: dict[str, Any]) -> bool:
    tags = _parse_tags(attribute.get("tags"))
    required = bool(tags.get("required") or attribute.get("required"))
    if not required:
        return False
    active_tags = {tag for tag, present in tags.items() if present}
    return not bool(active_tags.intersection(NON_FILLABLE_TAGS))


def _build_attr_indexes(
    attributes: list[dict[str, Any]],
) -> tuple[
    dict[str, dict[str, Any]],
    dict[str, list[dict[str, Any]]],
    dict[str, list[dict[str, Any]]],
]:
    by_id: dict[str, dict[str, Any]] = {}
    by_name: dict[str, list[dict[str, Any]]] = {}
    by_id_token: dict[str, list[dict[str, Any]]] = {}

    for attr in attributes:
        attr_id_raw = attr.get("id")
        attr_name_raw = attr.get("name")
        if not isinstance(attr_id_raw, str) or not attr_id_raw:
            continue

        attr_id = attr_id_raw.strip()
        by_id[attr_id] = attr

        if isinstance(attr_name_raw, str) and attr_name_raw.strip():
            normalized_name = _normalize(attr_name_raw)
            by_name.setdefault(normalized_name, []).append(attr)

        normalized_id_token = _normalize(attr_id.replace("_", " "))
        by_id_token.setdefault(normalized_id_token, []).append(attr)

    return by_id, by_name, by_id_token


def _score_header_candidate(header_normalized: str, attribute: dict[str, Any]) -> tuple[float, str]:
    attr_id = str(attribute.get("id", "")).strip()
    attr_name = str(attribute.get("name", "")).strip()

    normalized_name = _normalize(attr_name)
    normalized_id_token = _normalize(attr_id.replace("_", " "))

    name_score = _string_similarity(header_normalized, normalized_name)
    id_score = _string_similarity(header_normalized, normalized_id_token)
    overlap = _token_overlap(header_normalized, normalized_name)

    score = max(name_score, id_score)
    method = "fuzzy_name" if name_score >= id_score else "fuzzy_id"

    if header_normalized in normalized_name or normalized_name in header_normalized:
        score = max(score, 0.90)

    if overlap >= 0.80:
        boosted = min(1.0, max(score, 0.90) + 0.05)
        if boosted > score:
            score = boosted
            method = "fuzzy_token_overlap"

    return score, method


def resolve_header(
    header: str,
    *,
    attributes: list[dict[str, Any]],
    by_name: dict[str, list[dict[str, Any]]],
    by_id_token: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    """Resolve a header to one category attribute using deterministic rules."""
    normalized_header = _normalize_header_for_matching(header)

    if is_blocked_header(normalized_header):
        return {
            "column": header,
            "normalized": normalized_header,
            "status": "skipped_operational",
            "match": None,
            "candidates": [],
        }

    name_candidates = by_name.get(normalized_header, [])
    if len(name_candidates) == 1:
        attr = name_candidates[0]
        return {
            "column": header,
            "normalized": normalized_header,
            "status": "resolved",
            "match": {
                "attribute_id": attr["id"],
                "attribute_name": attr.get("name"),
                "score": 1.0,
                "method": "exact_name",
            },
            "candidates": [],
        }
    if len(name_candidates) > 1:
        return {
            "column": header,
            "normalized": normalized_header,
            "status": "ambiguous",
            "match": None,
            "candidates": [
                {
                    "attribute_id": candidate.get("id"),
                    "attribute_name": candidate.get("name"),
                    "score": 1.0,
                    "method": "exact_name",
                }
                for candidate in name_candidates
            ],
        }

    id_candidates = by_id_token.get(normalized_header, [])
    if len(id_candidates) == 1:
        attr = id_candidates[0]
        return {
            "column": header,
            "normalized": normalized_header,
            "status": "resolved",
            "match": {
                "attribute_id": attr["id"],
                "attribute_name": attr.get("name"),
                "score": 1.0,
                "method": "exact_id",
            },
            "candidates": [],
        }
    if len(id_candidates) > 1:
        return {
            "column": header,
            "normalized": normalized_header,
            "status": "ambiguous",
            "match": None,
            "candidates": [
                {
                    "attribute_id": candidate.get("id"),
                    "attribute_name": candidate.get("name"),
                    "score": 1.0,
                    "method": "exact_id",
                }
                for candidate in id_candidates
            ],
        }

    ranked: list[HeaderMatch] = []
    for attr in attributes:
        attr_id = attr.get("id")
        attr_name = attr.get("name")
        if not isinstance(attr_id, str) or not isinstance(attr_name, str):
            continue
        score, method = _score_header_candidate(normalized_header, attr)
        ranked.append(
            HeaderMatch(
                attribute_id=attr_id,
                attribute_name=attr_name,
                score=score,
                method=method,
            )
        )

    ranked.sort(key=lambda item: (item.score, item.attribute_id), reverse=True)

    if not ranked:
        return {
            "column": header,
            "normalized": normalized_header,
            "status": "unresolved",
            "match": None,
            "candidates": [],
        }

    best = ranked[0]
    second_score = ranked[1].score if len(ranked) > 1 else 0.0
    margin = best.score - second_score

    if best.score >= HEADER_SCORE_THRESHOLD and margin >= HEADER_SCORE_MARGIN:
        return {
            "column": header,
            "normalized": normalized_header,
            "status": "resolved",
            "match": {
                "attribute_id": best.attribute_id,
                "attribute_name": best.attribute_name,
                "score": round(best.score, 4),
                "method": best.method,
            },
            "candidates": [
                {
                    "attribute_id": candidate.attribute_id,
                    "attribute_name": candidate.attribute_name,
                    "score": round(candidate.score, 4),
                    "method": candidate.method,
                }
                for candidate in ranked[:3]
            ],
        }

    status = "ambiguous" if margin < HEADER_SCORE_MARGIN else "unresolved"
    return {
        "column": header,
        "normalized": normalized_header,
        "status": status,
        "match": None,
        "candidates": [
            {
                "attribute_id": candidate.attribute_id,
                "attribute_name": candidate.attribute_name,
                "score": round(candidate.score, 4),
                "method": candidate.method,
            }
            for candidate in ranked[:3]
        ],
    }


def _maybe_translate_candidates(tokens: list[str]) -> list[str]:
    """Try optional translation for unresolved tokens.

    Translation is intentionally optional and best-effort to avoid hard dependency.
    """
    try:
        import argostranslate.translate  # type: ignore[import-not-found]
    except Exception:
        return []

    translated_tokens: list[str] = []
    for token in tokens:
        try:
            translated = argostranslate.translate.translate(token, "en", "pt")
        except Exception as exc:
            logger.debug("Translation failed for token '%s': %s", token, exc)
            continue
        translated_text = str(translated).strip()
        if translated_text:
            translated_tokens.append(translated_text)
    return translated_tokens


def _score_value_name(candidate: str, allowed_name: str) -> float:
    normalized_candidate = _normalize(candidate)
    normalized_allowed = _normalize(allowed_name)
    score = _string_similarity(normalized_candidate, normalized_allowed)
    if (
        normalized_candidate
        and normalized_allowed
        and (
            normalized_candidate in normalized_allowed or normalized_allowed in normalized_candidate
        )
    ):
        score = max(score, 0.90)
    return score


def _resolve_list_token(
    token: str,
    values: list[dict[str, Any]],
) -> ValueTokenMatch:
    value_by_id = {
        str(value.get("id")).strip(): value
        for value in values
        if isinstance(value.get("id"), str) and str(value.get("id")).strip()
    }
    value_by_name_norm = {
        _normalize(str(value.get("name"))): value
        for value in values
        if isinstance(value.get("name"), str) and str(value.get("name")).strip()
    }

    token_stripped = str(token).strip()
    if not token_stripped:
        return ValueTokenMatch(
            raw_token=token,
            status="unresolved",
            value_id=None,
            value_name=None,
            score=0.0,
            reason="empty_token",
        )

    if token_stripped in value_by_id:
        matched = value_by_id[token_stripped]
        return ValueTokenMatch(
            raw_token=token,
            status="resolved",
            value_id=str(matched.get("id")),
            value_name=str(matched.get("name")),
            score=1.0,
        )

    token_norm = _normalize(token_stripped)
    exact_name = value_by_name_norm.get(token_norm)
    if exact_name is not None:
        return ValueTokenMatch(
            raw_token=token,
            status="resolved",
            value_id=str(exact_name.get("id")) if exact_name.get("id") is not None else None,
            value_name=str(exact_name.get("name")),
            score=1.0,
        )

    ranked: list[tuple[float, dict[str, Any]]] = []
    for value in values:
        raw_name = value.get("name")
        if not isinstance(raw_name, str) or not raw_name.strip():
            continue
        score = _score_value_name(token_stripped, raw_name)
        ranked.append((score, value))

    ranked.sort(key=lambda item: item[0], reverse=True)

    if not ranked:
        return ValueTokenMatch(
            raw_token=token,
            status="unresolved",
            value_id=None,
            value_name=None,
            score=0.0,
            reason="no_allowed_values",
        )

    best_score, best_value = ranked[0]
    second_score = ranked[1][0] if len(ranked) > 1 else 0.0
    margin = best_score - second_score

    if best_score >= VALUE_SCORE_THRESHOLD and margin >= VALUE_SCORE_MARGIN:
        value_id = best_value.get("id")
        return ValueTokenMatch(
            raw_token=token,
            status="resolved",
            value_id=str(value_id) if isinstance(value_id, str) else None,
            value_name=str(best_value.get("name")),
            score=best_score,
        )

    return ValueTokenMatch(
        raw_token=token,
        status="unresolved",
        value_id=None,
        value_name=None,
        score=best_score,
        reason="score_below_threshold_or_ambiguous",
    )


def resolve_attribute_value(
    attribute: dict[str, Any],
    raw_value: Any,
    *,
    enable_translate: bool = False,
) -> dict[str, Any]:
    """Resolve a raw spreadsheet value against one attribute definition."""
    value_type = str(attribute.get("value_type", "string"))
    text = "" if raw_value is None else str(raw_value).strip()
    if not text:
        return {
            "status": "empty",
            "value_type": value_type,
            "primary": None,
            "tokens": [],
        }

    if value_type in {"list", "boolean"} and isinstance(attribute.get("values"), list):
        allowed_values = [value for value in attribute["values"] if isinstance(value, dict)]
        tokens = _split_cell_values(text)
        token_results = [_resolve_list_token(token, allowed_values) for token in tokens]

        unresolved_tokens = [
            result.raw_token for result in token_results if result.status != "resolved"
        ]
        if unresolved_tokens and enable_translate:
            translated = _maybe_translate_candidates(unresolved_tokens)
            if translated:
                translated_results = [
                    _resolve_list_token(token, allowed_values) for token in translated
                ]
                resolved_translations = [
                    result for result in translated_results if result.status == "resolved"
                ]
                token_results.extend(resolved_translations)

        resolved = [result for result in token_results if result.status == "resolved"]
        unresolved_count = len([result for result in token_results if result.status != "resolved"])

        status = "resolved"
        if not resolved:
            status = "unresolved"
        elif unresolved_count > 0:
            status = "partial"

        primary = (
            {
                "value_id": resolved[0].value_id,
                "value_name": resolved[0].value_name,
            }
            if resolved
            else None
        )

        return {
            "status": status,
            "value_type": value_type,
            "primary": primary,
            "tokens": [
                {
                    "raw_token": result.raw_token,
                    "status": result.status,
                    "value_id": result.value_id,
                    "value_name": result.value_name,
                    "score": round(result.score, 4),
                    "reason": result.reason,
                }
                for result in token_results
            ],
        }

    if value_type == "number_unit":
        numeric, unit = _extract_numeric_and_unit(text)
        if numeric is None:
            return {
                "status": "unresolved",
                "value_type": value_type,
                "primary": None,
                "tokens": [],
                "reason": "invalid_number_unit_format",
            }

        allowed_units: set[str] = set()
        allowed_units_raw = attribute.get("allowed_units")
        if isinstance(allowed_units_raw, list):
            for item in allowed_units_raw:
                if isinstance(item, dict):
                    item_id = item.get("id")
                    item_name = item.get("name")
                    if isinstance(item_id, str) and item_id.strip():
                        allowed_units.add(_normalize(item_id))
                    if isinstance(item_name, str) and item_name.strip():
                        allowed_units.add(_normalize(item_name))

        default_unit = attribute.get("default_unit")
        default_unit_str = default_unit.strip() if isinstance(default_unit, str) else ""
        chosen_unit = unit or default_unit_str
        if not chosen_unit:
            return {
                "status": "unresolved",
                "value_type": value_type,
                "primary": None,
                "tokens": [],
                "reason": "missing_unit",
            }

        normalized_unit = _normalize(chosen_unit)
        if allowed_units and normalized_unit not in allowed_units:
            return {
                "status": "unresolved",
                "value_type": value_type,
                "primary": None,
                "tokens": [],
                "reason": "unit_not_allowed",
            }

        value_name = f"{numeric} {chosen_unit}".strip()
        return {
            "status": "resolved",
            "value_type": value_type,
            "primary": {
                "value_id": None,
                "value_name": value_name,
            },
            "tokens": [],
        }

    if value_type == "number":
        numeric, _ = _extract_numeric_and_unit(text)
        if numeric is None:
            return {
                "status": "unresolved",
                "value_type": value_type,
                "primary": None,
                "tokens": [],
                "reason": "invalid_number",
            }
        return {
            "status": "resolved",
            "value_type": value_type,
            "primary": {
                "value_id": None,
                "value_name": str(numeric),
            },
            "tokens": [],
        }

    return {
        "status": "resolved",
        "value_type": value_type,
        "primary": {
            "value_id": None,
            "value_name": text,
        },
        "tokens": [],
    }


def derive_core_fields(config: dict[str, Any], parser: SpreadsheetParser) -> set[str]:
    """Return normalized non-attribute columns.

    These fields are generic item/core metadata and must be excluded from
    category attribute header matching.
    """
    core_fields = {_normalize(field) for field in parser.get_supported_columns()}

    core_item_fields = config.get("core_item_fields", {})
    required = core_item_fields.get("required", []) if isinstance(core_item_fields, dict) else []
    if isinstance(required, list):
        for field in required:
            core_fields.add(_normalize(str(field)))

    standard_fields = config.get("standard_fields", {})
    if isinstance(standard_fields, dict):
        for field in standard_fields:
            core_fields.add(_normalize(str(field)))

    generic_category_fields = {
        "category",
        "category_id",
        "categoria",
        "categoria_id",
        "my_category",
    }
    for field in generic_category_fields:
        core_fields.add(_normalize(field))

    return core_fields


def build_item_context(
    row: dict[str, Any],
    resolved_headers: dict[str, str],
    attributes_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Build minimal conditional-attributes payload for one row."""
    title = ""
    for key in ("titulo", "title", "nome"):
        raw = row.get(key)
        if raw is None:
            continue
        text = str(raw).strip()
        if text:
            title = text
            break

    mapped_attributes: list[dict[str, Any]] = []
    for column, attr_id in resolved_headers.items():
        if column not in row:
            continue
        attr_def = attributes_by_id.get(attr_id)
        if attr_def is None:
            continue

        resolved_value = resolve_attribute_value(attr_def, row.get(column), enable_translate=False)
        if resolved_value.get("status") not in {"resolved", "partial"}:
            continue

        primary = resolved_value.get("primary")
        if not isinstance(primary, dict):
            continue

        payload: dict[str, Any] = {"id": attr_id}
        value_id = primary.get("value_id")
        value_name = primary.get("value_name")
        if value_id is not None:
            payload["value_id"] = value_id
        if value_name is not None:
            payload["value_name"] = value_name

        if len(payload) > 1:
            mapped_attributes.append(payload)

    context: dict[str, Any] = {
        "title": title,
        "attributes": mapped_attributes,
    }
    description = row.get("descricao")
    if isinstance(description, str) and description.strip():
        context["description"] = {"plain_text": description.strip()}

    return context


def collect_conditional_required_ids(
    resolver: CategoryResolver,
    category_id: str,
    sampled_rows: list[dict[str, Any]],
    resolved_headers: dict[str, str],
    attributes_by_id: dict[str, dict[str, Any]],
) -> set[str]:
    """Collect required conditional attribute IDs from sampled rows."""
    required_ids: set[str] = set()
    seen_context_signatures: set[str] = set()

    for row in sampled_rows[:20]:
        context = build_item_context(row, resolved_headers, attributes_by_id)
        signature = json.dumps(context, ensure_ascii=False, sort_keys=True)
        if signature in seen_context_signatures:
            continue
        seen_context_signatures.add(signature)

        conditional_attributes = resolver.get_conditional_attributes(category_id, context)
        for attribute in conditional_attributes:
            if not isinstance(attribute, dict):
                continue
            attr_id = attribute.get("id")
            if not isinstance(attr_id, str) or not attr_id.strip():
                continue
            if _is_required_fillable(attribute):
                required_ids.add(attr_id)

    return required_ids


def evaluate_readiness(
    *,
    resolved_headers: dict[str, str],
    value_resolution: list[dict[str, Any]],
    required_base_ids: set[str],
    required_conditional_ids: set[str],
    strict: bool,
) -> tuple[str, list[dict[str, Any]], list[str]]:
    """Evaluate preflight readiness with deterministic blocking rules."""
    blocking_issues: list[dict[str, Any]] = []
    warnings: list[str] = []

    mapped_attribute_ids = set(resolved_headers.values())

    missing_required_base = sorted(required_base_ids - mapped_attribute_ids)
    for attr_id in missing_required_base:
        blocking_issues.append(
            {
                "type": "missing_required_attribute_header",
                "attribute_id": attr_id,
                "reason": "required_base_attribute_not_mapped_from_headers",
            }
        )

    missing_required_conditional = sorted(required_conditional_ids - mapped_attribute_ids)
    for attr_id in missing_required_conditional:
        blocking_issues.append(
            {
                "type": "missing_conditional_required_attribute_header",
                "attribute_id": attr_id,
                "reason": "required_conditional_attribute_not_mapped_from_headers",
            }
        )

    for column_result in value_resolution:
        column = column_result.get("column")
        attribute_id = column_result.get("attribute_id")
        unresolved_samples = int(column_result.get("unresolved_samples", 0))
        if unresolved_samples <= 0:
            continue

        is_required = bool(
            attribute_id in required_base_ids or attribute_id in required_conditional_ids
        )
        message = (
            f"Column '{column}' ({attribute_id}) has {unresolved_samples} unresolved sample values."
        )

        if is_required:
            blocking_issues.append(
                {
                    "type": "required_attribute_unresolved_values",
                    "column": column,
                    "attribute_id": attribute_id,
                    "reason": "unresolved_required_enum_or_typed_values",
                    "unresolved_samples": unresolved_samples,
                }
            )
        else:
            warnings.append(message)

    if blocking_issues and strict:
        status = "FAIL"
    else:
        status = "PASS"
        if blocking_issues:
            warnings.append("Strict mode disabled; blocking issues were downgraded to warnings.")

    return status, blocking_issues, warnings


def resolve_category(
    resolver: CategoryResolver,
    category_input: str,
    site_id: str,
) -> tuple[str, str]:
    """Resolve a category input as ID or name, then normalize to leaf when possible."""
    category_input_clean = category_input.strip()
    if CATEGORY_ID_PATTERN.match(category_input_clean):
        category_id = category_input_clean
    elif category_input_clean:
        logger.info(
            "Using category input '%s' as predictor query from -c flag.",
            category_input_clean,
        )
        found = resolver.find_category_with_predictor(
            category_input_clean,
            [category_input_clean],
            site_id=site_id,
        )
        if not found:
            raise ValueError(
                "Could not resolve category from input with predictor: " f"'{category_input}'."
            )
        category_id = found
    else:
        raise ValueError("Could not resolve category from empty input.")

    leaf_id = resolver.resolve_to_leaf(category_id)
    category_data = resolver.get_category_data(leaf_id)
    category_name = str(category_data.get("name") or category_input_clean)
    return leaf_id, category_name


def run_preflight(
    *,
    excel_path: Path,
    category_input: str,
    site_id: str,
    sample_rows: int,
    out_dir: Path,
    sheet_name: str | int | None,
    strict: bool,
    enable_translate: bool,
    cache_dir: Path,
) -> dict[str, Any]:
    """Run deterministic preflight gatherer and persist artifacts."""
    config = load_merged_yaml_config(*RUNTIME_SPLIT_CONFIG_PATHS)

    auth_manager = AuthManager()
    api_client = MLApiClient(auth_manager)
    attribute_cache = AttributeCache(cache_dir=str(cache_dir))
    prediction_cache = PredictionCache(cache_dir=str(cache_dir / "predictions"))
    category_adapter = CategoryAdapter(api_client)
    resolver = CategoryResolver(
        category_adapter,
        attribute_cache=attribute_cache,
        prediction_cache=prediction_cache,
    )

    category_id, category_name = resolve_category(resolver, category_input, site_id)
    logger.info("Resolved category '%s' to %s (%s)", category_input, category_id, category_name)

    parser = SpreadsheetParser()
    parsed_rows = parser.parse(excel_path, sheet_name=sheet_name)
    sampled_rows = parsed_rows[:sample_rows]

    if not parsed_rows:
        raise ValueError("Spreadsheet has no data rows after parsing.")

    attributes = resolver.get_all_attributes(category_id)
    attributes_sorted = sorted(
        [attribute for attribute in attributes if isinstance(attribute, dict)],
        key=lambda attribute: str(attribute.get("id", "")),
    )

    by_id, by_name, by_id_token = _build_attr_indexes(attributes_sorted)
    required_base_ids = {
        attr_id for attr_id, attribute in by_id.items() if _is_required_fillable(attribute)
    }

    core_fields = derive_core_fields(config, parser)

    all_headers = sorted({str(key) for row in sampled_rows for key in row})
    header_resolution: list[dict[str, Any]] = []
    resolved_headers: dict[str, str] = {}

    for header in all_headers:
        normalized = _normalize_header_for_matching(header)
        if _normalize(header) in core_fields:
            header_resolution.append(
                {
                    "column": header,
                    "normalized": normalized,
                    "status": "skipped_core",
                    "match": None,
                    "candidates": [],
                }
            )
            continue

        result = resolve_header(
            header,
            attributes=attributes_sorted,
            by_name=by_name,
            by_id_token=by_id_token,
        )
        header_resolution.append(result)

        if result.get("status") == "resolved":
            match = result.get("match")
            if isinstance(match, dict):
                attribute_id = match.get("attribute_id")
                if isinstance(attribute_id, str) and attribute_id:
                    resolved_headers[header] = attribute_id

    value_resolution: list[dict[str, Any]] = []
    unresolved_value_samples_by_attribute: dict[str, set[str]] = {}

    for column, attr_id in sorted(resolved_headers.items(), key=lambda item: item[0]):
        attribute = by_id.get(attr_id)
        if attribute is None:
            continue

        total_samples = 0
        unresolved_samples = 0
        sample_details: list[dict[str, Any]] = []

        for row_index, row in enumerate(sampled_rows):
            if column not in row:
                continue
            raw = row.get(column)
            if raw is None or str(raw).strip() == "":
                continue

            total_samples += 1
            resolved = resolve_attribute_value(
                attribute,
                raw,
                enable_translate=enable_translate,
            )
            status = str(resolved.get("status"))
            if status in {"unresolved", "partial"}:
                unresolved_samples += 1
                unresolved_value_samples_by_attribute.setdefault(attr_id, set()).add(
                    str(raw).strip()
                )

            if len(sample_details) < 10:
                sample_details.append(
                    {
                        "row_index": row_index,
                        "raw_value": str(raw),
                        "status": status,
                        "primary": resolved.get("primary"),
                        "tokens": resolved.get("tokens", []),
                        "reason": resolved.get("reason"),
                    }
                )

        value_resolution.append(
            {
                "column": column,
                "attribute_id": attr_id,
                "attribute_name": attribute.get("name"),
                "value_type": attribute.get("value_type", "string"),
                "total_samples": total_samples,
                "unresolved_samples": unresolved_samples,
                "sample_details": sample_details,
            }
        )

    required_conditional_ids = collect_conditional_required_ids(
        resolver,
        category_id,
        sampled_rows,
        resolved_headers,
        by_id,
    )

    status, blocking_issues, warnings = evaluate_readiness(
        resolved_headers=resolved_headers,
        value_resolution=value_resolution,
        required_base_ids=required_base_ids,
        required_conditional_ids=required_conditional_ids,
        strict=strict,
    )

    run_id = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    run_dir = out_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    schema_snapshot = {
        "run_id": run_id,
        "category": {
            "input": category_input,
            "site_id": site_id,
            "id": category_id,
            "name": category_name,
        },
        "attributes": attributes_sorted,
    }

    header_resolution_artifact = {
        "run_id": run_id,
        "category_id": category_id,
        "resolved_headers": resolved_headers,
        "headers": header_resolution,
    }

    value_resolution_artifact = {
        "run_id": run_id,
        "category_id": category_id,
        "columns": value_resolution,
    }

    readiness_report = {
        "run_id": run_id,
        "category": {
            "id": category_id,
            "name": category_name,
            "site_id": site_id,
        },
        "summary": {
            "headers_total": len(all_headers),
            "headers_resolved": len(resolved_headers),
            "values_total": sum(int(item["total_samples"]) for item in value_resolution),
            "values_resolved": sum(
                max(0, int(item["total_samples"]) - int(item["unresolved_samples"]))
                for item in value_resolution
            ),
            "required_missing_count": len(
                [
                    issue
                    for issue in blocking_issues
                    if issue.get("type")
                    in {
                        "missing_required_attribute_header",
                        "missing_conditional_required_attribute_header",
                    }
                ]
            ),
            "status": status,
        },
        "required": {
            "base_required_ids": sorted(required_base_ids),
            "conditional_required_ids": sorted(required_conditional_ids),
        },
        "blocking_issues": blocking_issues,
        "warnings": warnings,
        "recommended_next_command": (
            "uv run ml-upload validate " f"{excel_path} -i anuncios/ -c '{category_input}'"
            if status == "PASS"
            else "Resolve blocking issues and rerun preflight before validate/upload."
        ),
    }

    manual_overrides_template = {
        "manual_header_overrides": {
            item["column"]: None
            for item in header_resolution
            if item.get("status") in {"ambiguous", "unresolved"}
        },
        "manual_value_overrides": {
            attr_id: dict.fromkeys(sorted(raw_values), None)
            for attr_id, raw_values in sorted(unresolved_value_samples_by_attribute.items())
        },
    }

    files = {
        "schema_snapshot": run_dir / "schema_snapshot.json",
        "header_resolution": run_dir / "header_resolution.json",
        "value_resolution": run_dir / "value_resolution.json",
        "readiness_report": run_dir / "readiness_report.json",
        "manual_overrides_template": run_dir / "manual_overrides_template.yaml",
    }

    files["schema_snapshot"].write_text(
        json.dumps(schema_snapshot, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    files["header_resolution"].write_text(
        json.dumps(header_resolution_artifact, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    files["value_resolution"].write_text(
        json.dumps(value_resolution_artifact, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    files["readiness_report"].write_text(
        json.dumps(readiness_report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    files["manual_overrides_template"].write_text(
        yaml.safe_dump(
            manual_overrides_template,
            allow_unicode=True,
            sort_keys=True,
            default_flow_style=False,
        ),
        encoding="utf-8",
    )

    return {
        "run_id": run_id,
        "run_dir": str(run_dir),
        "files": {key: str(path) for key, path in files.items()},
        "status": status,
        "summary": readiness_report["summary"],
    }


def build_argument_parser() -> argparse.ArgumentParser:
    """Build argument parser for preflight script."""
    parser = argparse.ArgumentParser(
        description="Deterministic preflight gatherer for ML category attribute mapping.",
    )
    parser.add_argument("--excel", required=True, help="Path to spreadsheet (.xlsx/.xls).")
    parser.add_argument("--category", required=True, help="Category name or category ID.")
    parser.add_argument("--site", default="MLB", help="ML site ID (default: MLB).")
    parser.add_argument("--sheet", default=None, help="Optional sheet name/index.")
    parser.add_argument(
        "--sample-rows",
        type=int,
        default=30,
        help="Rows sampled for preflight.",
    )
    parser.add_argument(
        "--out-dir",
        default="cache/preflight",
        help="Preflight artifacts directory.",
    )
    parser.add_argument(
        "--cache-dir",
        default="cache/categories",
        help="Cache directory for category attributes/predictions.",
    )
    parser.add_argument(
        "--strict",
        dest="strict",
        action="store_true",
        default=True,
        help="Fail readiness on blocking issues (default: true).",
    )
    parser.add_argument(
        "--no-strict",
        dest="strict",
        action="store_false",
        help="Downgrade blocking issues to warnings.",
    )
    parser.add_argument(
        "--enable-translate",
        action="store_true",
        default=False,
        help="Enable optional best-effort translation fallback for unresolved enum tokens.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for deterministic preflight gatherer."""
    parser = build_argument_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )

    excel_path = Path(args.excel)
    out_dir = Path(args.out_dir)
    cache_dir = Path(args.cache_dir)

    sheet_name: str | int | None
    if args.sheet is None:
        sheet_name = None
    else:
        sheet_value = str(args.sheet).strip()
        sheet_name = int(sheet_value) if sheet_value.isdigit() else sheet_value

    try:
        result = run_preflight(
            excel_path=excel_path,
            category_input=str(args.category),
            site_id=str(args.site),
            sample_rows=max(1, int(args.sample_rows)),
            out_dir=out_dir,
            sheet_name=sheet_name,
            strict=bool(args.strict),
            enable_translate=bool(args.enable_translate),
            cache_dir=cache_dir,
        )
    except Exception as exc:
        logger.error("Preflight failed: %s", exc)
        return 1

    logger.info("Preflight completed: status=%s run_dir=%s", result["status"], result["run_dir"])
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
