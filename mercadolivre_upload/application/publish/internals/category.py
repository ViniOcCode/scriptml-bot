"""Category helpers for publish internals."""

from __future__ import annotations

import re
from logging import Logger
from typing import Any

from mercadolivre_upload.domain.product.model import Product
from mercadolivre_upload.shared.utils.text_utils import PortugueseTextNormalizer


def extract_item_identity(product: Product | dict[str, Any]) -> tuple[str | None, str | None]:
    """Extract SKU/title from either input row or Product."""
    if isinstance(product, Product):
        sku = str(product.sku).strip() if product.sku else None
        title = str(product.title).strip() if product.title else None
        return sku, title

    sku = None
    for key in ("sku", "codigo", "código", "code"):
        value = product.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            sku = text
            break

    title = None
    for key in ("titulo", "título", "title", "nome"):
        value = product.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            title = text
            break

    return sku, title


def extract_product_title(product: Product | dict[str, Any]) -> str | None:
    """Extract a normalized title from Product/dict with compatibility key lookup."""
    title: Any | None = None
    if isinstance(product, dict):
        # Try exact key matches first.
        for key in ["título", "titulo", "title", "nome"]:
            if key in product:
                title = product[key]
                break

        # Backward-compatible fallback: keys that start with title patterns.
        if title is None:
            for key in product:
                key_lower = str(key).lower().strip()
                if any(key_lower.startswith(pattern) for pattern in ["título", "titulo", "title"]):
                    title = product[key]
                    break
    else:
        title = getattr(product, "title", None)

    if not isinstance(title, str):
        return None
    title_str = title.strip()
    return title_str or None


def build_resolution_artifact(context: dict[str, Any]) -> dict[str, Any]:
    """Build serializable category resolution fields for item results."""
    category_path = context.get("category_path")
    if not isinstance(category_path, list):
        category_path = []

    strategy = context.get("resolution_strategy")
    if not isinstance(strategy, str) or not strategy:
        strategy = "unresolved"

    category_input = context.get("category_input")
    if not isinstance(category_input, str):
        category_input = str(category_input or "").strip()

    resolved_id = context.get("category_resolved_id")
    if not isinstance(resolved_id, str) or not resolved_id:
        resolved_id = None

    predictor_titles_count_raw = context.get("predictor_titles_count")
    predictor_titles_count = 0
    if isinstance(predictor_titles_count_raw, int) and predictor_titles_count_raw > 0:
        predictor_titles_count = predictor_titles_count_raw

    fallback_reason = context.get("fallback_reason")
    if not isinstance(fallback_reason, str) or not fallback_reason.strip():
        fallback_reason = None

    decision_artifact = {
        "category_input": category_input,
        "category_resolved_id": resolved_id,
        "strategy": strategy,
        "predictor_attempted": bool(context.get("predictor_attempted")),
        "predictor_titles_count": predictor_titles_count,
        "predictor_matched": bool(context.get("predictor_matched")),
        "fallback_attempted": bool(context.get("fallback_attempted")),
        "fallback_reason": fallback_reason,
    }

    return {
        "category_input": category_input,
        "category_resolved_id": resolved_id,
        "category_path": list(category_path),
        "resolution_strategy": strategy,
        "category_resolution_decision": decision_artifact,
    }


def build_category_resolution_observability(
    resolution_artifact: dict[str, Any], product_count: int
) -> dict[str, Any]:
    """Build deterministic counters and decision metadata for category resolution."""
    strategy = (
        str(resolution_artifact.get("resolution_strategy") or "unresolved").strip() or "unresolved"
    )
    decision = resolution_artifact.get("category_resolution_decision")
    if not isinstance(decision, dict):
        decision = {}

    item_count = product_count if product_count > 0 else 0
    strategy_counts: dict[str, int] = {
        "direct_id": 0,
        "predictor_path_match": 0,
        "name_match": 0,
        "unresolved": 0,
    }
    strategy_counts[strategy] = strategy_counts.get(strategy, 0) + item_count

    fallback_attempted = bool(decision.get("fallback_attempted"))
    predictor_attempted = bool(decision.get("predictor_attempted"))
    predictor_matched = bool(decision.get("predictor_matched"))

    fallback_counts = {
        "attempted": item_count if fallback_attempted else 0,
        "resolved": item_count if fallback_attempted and strategy != "unresolved" else 0,
        "unresolved": item_count if fallback_attempted and strategy == "unresolved" else 0,
    }
    predictor_counts = {
        "attempted": item_count if predictor_attempted else 0,
        "matched": item_count if predictor_attempted and predictor_matched else 0,
        "unmatched": item_count if predictor_attempted and not predictor_matched else 0,
    }

    return {
        "decision": dict(decision),
        "strategy_counts": strategy_counts,
        "fallback_counts": fallback_counts,
        "predictor_counts": predictor_counts,
    }


def log_category_resolution_observability(observability: dict[str, Any], logger: Logger) -> None:
    """Emit category-resolution decision metadata and counters to logs."""
    decision = observability.get("decision")
    if not isinstance(decision, dict):
        decision = {}
    logger.info(
        "Category resolution decision: strategy=%s predictor_attempted=%s "
        "predictor_matched=%s fallback_attempted=%s fallback_reason=%s "
        "strategy_counts=%s fallback_counts=%s",
        decision.get("strategy", "unresolved"),
        decision.get("predictor_attempted", False),
        decision.get("predictor_matched", False),
        decision.get("fallback_attempted", False),
        decision.get("fallback_reason"),
        observability.get("strategy_counts", {}),
        observability.get("fallback_counts", {}),
    )


def resolve_category_context(
    use_case: Any,
    products: list[Product | dict[str, Any]],
    category_name: str,
    logger: Logger,
) -> dict[str, Any]:
    """Resolve category with deterministic strategy metadata."""
    category_input = str(category_name).strip()
    resolved_id: str | None = None
    strategy = "unresolved"
    titles: list[str] = []
    predictor_attempted = False
    predictor_matched = False
    fallback_attempted = False
    fallback_reason: str | None = None

    if products:
        for product in products:
            title = extract_product_title(product)
            if title:
                titles.append(title)

    # Strategy 0: Accept direct category IDs (e.g. MLB1234)
    if re.fullmatch(r"[A-Z]{3}\d+", category_input):
        resolved_id = category_input
        strategy = "direct_id"
    # Strategy 1: Predictor-first title matching against category hint
    elif titles:
        predictor_attempted = True
        logger.info("Extracted %s titles for predictor-first resolution", len(titles))
        resolved_id = use_case.category_resolver.find_category_with_predictor(
            category_input, titles
        )
        if resolved_id:
            strategy = "predictor_path_match"
            predictor_matched = True
        else:
            fallback_attempted = True
            fallback_reason = "predictor_no_match"
            title_predictor = getattr(
                use_case.category_resolver, "predict_category_from_title", None
            )
            if callable(title_predictor):
                deduped_titles: list[str] = []
                seen_titles: set[str] = set()
                for title in titles:
                    normalized_title = PortugueseTextNormalizer.normalize(title)
                    if not normalized_title or normalized_title in seen_titles:
                        continue
                    seen_titles.add(normalized_title)
                    deduped_titles.append(title)
                    if len(deduped_titles) >= 3:
                        break

                for title in deduped_titles:
                    fallback_prediction = title_predictor(title, "MLB")
                    if isinstance(fallback_prediction, str) and fallback_prediction.strip():
                        resolved_id = fallback_prediction.strip()
                        strategy = "predictor_title_fallback"
                        fallback_reason = "predictor_title_fallback"
                        logger.info(
                            "Predictor path miss for '%s'; using bounded title fallback '%s' "
                            "resolved to %s.",
                            category_input,
                            title,
                            resolved_id,
                        )
                        break

            if not resolved_id:
                logger.info(
                    "Predictor path matching did not resolve '%s'; "
                    "returning unresolved context.",
                    category_input,
                )
    else:
        # Fallback for non-title flows: resolve by category name.
        fallback_attempted = True
        fallback_reason = "missing_titles_for_predictor"
        resolved_id = use_case.category_resolver.find_category(category_input)
        if resolved_id:
            strategy = "name_match"
        else:
            logger.info(
                "Category '%s' not found by name and no usable titles were provided.",
                category_input,
            )

    category_path: list[Any] = []
    if resolved_id:
        resolved_before_leaf = resolved_id
        leaf_category_id = use_case.category_resolver.resolve_to_leaf(resolved_id)
        if leaf_category_id != resolved_before_leaf:
            logger.info(f"Resolved to leaf category: {leaf_category_id}")
        resolved_id = leaf_category_id

        category_data = use_case._get_policy_category_data(resolved_id)
        if isinstance(category_data, dict):
            raw_children = category_data.get("children_categories", [])
            has_children = isinstance(raw_children, list) and any(
                isinstance(child, dict) for child in raw_children
            )
            if has_children:
                logger.warning(
                    "Resolved category %s is still non-leaf (children=%s); "
                    "blocking publish to avoid unsafe auto-selection.",
                    resolved_id,
                    len(raw_children),
                )
                fallback_attempted = True
                fallback_reason = "ambiguous_leaf_resolution"
                strategy = "unresolved"
                resolved_id = None
                category_path = []
                return {
                    "category_input": category_input,
                    "category_resolved_id": resolved_id,
                    "category_path": category_path,
                    "resolution_strategy": strategy,
                    "predictor_attempted": predictor_attempted,
                    "predictor_titles_count": len(titles),
                    "predictor_matched": predictor_matched,
                    "fallback_attempted": fallback_attempted,
                    "fallback_reason": fallback_reason,
                }
            raw_path = category_data.get("path_from_root")
            if isinstance(raw_path, list):
                category_path = list(raw_path)

    return {
        "category_input": category_input,
        "category_resolved_id": resolved_id,
        "category_path": category_path,
        "resolution_strategy": strategy,
        "predictor_attempted": predictor_attempted,
        "predictor_titles_count": len(titles),
        "predictor_matched": predictor_matched,
        "fallback_attempted": fallback_attempted,
        "fallback_reason": fallback_reason,
    }


__all__ = [
    "build_category_resolution_observability",
    "build_resolution_artifact",
    "extract_item_identity",
    "extract_product_title",
    "log_category_resolution_observability",
    "resolve_category_context",
]
