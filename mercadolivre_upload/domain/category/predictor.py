"""Prediction helpers for category resolver."""

from __future__ import annotations

import logging
from typing import Any

from mercadolivre_upload.shared.utils.text_utils import TextNormalizer

logger = logging.getLogger(__name__)


def call_domain_discovery(
    api: Any,
    title: str,
    site_id: str,
    limit: int = 3,
) -> list[dict[str, Any]]:
    """Call domain discovery API and return normalized prediction list."""
    try:
        logger.info(f"Calling domain discovery for: '{title[:60]}...'")
        predictions = api.predict_category(title, site_id, limit=limit)
        logger.debug(f"Domain discovery response: {predictions}")
        return predictions if isinstance(predictions, list) else []
    except Exception as error:
        logger.warning(f"Domain discovery failed: {error}")
        return []


def predict_category_from_title(
    resolver: Any,
    title: str,
    site_id: str = "MLB",
) -> str | None:
    """Predict category based on product title using ML domain discovery."""
    if not title or not isinstance(title, str):
        logger.warning(f"Invalid title for domain discovery: {title}")
        return None

    title = title.strip()
    if len(title) < 3:
        logger.warning(f"Title too short for domain discovery: '{title}'")
        return None

    normalized_site = resolver._normalize_site_id(site_id)
    cache_key = TextNormalizer.normalize(title) or title

    if resolver._prediction_cache:
        cached = resolver._prediction_cache.get(cache_key, normalized_site)
        if cached is not None:
            predictions = cached
        else:
            predictions = resolver._call_domain_discovery(title, normalized_site)
            resolver._prediction_cache.set(cache_key, predictions, normalized_site)
    else:
        predictions = resolver._call_domain_discovery(title, normalized_site)

    if predictions and len(predictions) > 0:
        best_candidate: tuple[str, tuple[Any, ...]] | None = None
        for index, prediction in enumerate(predictions):
            if not isinstance(prediction, dict):
                continue

            category_id = resolver._normalize_category_id(
                prediction.get("category_id"), normalized_site
            )
            if not category_id:
                continue

            confidence = resolver._safe_float(
                prediction.get("confidence", prediction.get("score")), 0.0
            )
            candidate_score = (confidence, -index)
            best_candidate = resolver._pick_best_candidate(
                best_candidate,
                (category_id, candidate_score),
            )

        if best_candidate:
            category_name = next(
                (
                    prediction.get("category_name", "unknown")
                    for prediction in predictions
                    if isinstance(prediction, dict)
                    and resolver._normalize_category_id(
                        prediction.get("category_id"), normalized_site
                    )
                    == best_candidate[0]
                ),
                "unknown",
            )
            logger.info(
                f"Domain discovery found: '{category_name}' ({best_candidate[0]}) for title"
            )
            return best_candidate[0]

    logger.warning(f"Domain discovery returned empty for: '{title}'")
    return None


def find_category_with_predictor(
    resolver: Any,
    category_name: str,
    product_titles: list[str],
    site_id: str = "MLB",
) -> str | None:
    """Find category using domain discovery predictions."""
    if not product_titles:
        return None

    normalized_site = resolver._normalize_site_id(site_id)
    target_name, context_terms = resolver._split_category_query(category_name)
    if not target_name:
        return None

    logger.info(
        f"Finding category '{category_name}' using predictor with {len(product_titles)} titles..."
    )

    titles_to_check = product_titles[: resolver._max_predictions]
    batch_predictions: dict[str, list[dict[str, Any]]] = {}

    for title in titles_to_check:
        title_str = title.strip() if isinstance(title, str) else ""
        if len(title_str) < 3:
            continue

        normalized_title = TextNormalizer.normalize(title_str)
        if not normalized_title:
            continue

        if normalized_title in batch_predictions:
            predictions = batch_predictions[normalized_title]
        elif resolver._prediction_cache:
            cached = resolver._prediction_cache.get(normalized_title, normalized_site)
            if cached is not None:
                predictions = cached
            else:
                predictions = resolver._call_domain_discovery(title_str, normalized_site, limit=3)
                resolver._prediction_cache.set(normalized_title, predictions, normalized_site)
        else:
            predictions = resolver._call_domain_discovery(title_str, normalized_site, limit=3)

        batch_predictions[normalized_title] = predictions

        if not predictions:
            continue

        title_best_match: tuple[str, tuple[Any, ...]] | None = None

        for prediction_rank, prediction in enumerate(predictions[:3]):
            if not isinstance(prediction, dict):
                continue

            predicted_id = resolver._normalize_category_id(
                prediction.get("category_id"), normalized_site
            )
            if not predicted_id:
                continue

            confidence = resolver._safe_float(
                prediction.get("confidence", prediction.get("score")), 0.0
            )
            depth_hint = prediction_rank

            category_data = resolver._get_category_cached(predicted_id)
            if not category_data:
                continue

            path_from_root = category_data.get("path_from_root", [])
            normalized_path: list[str] = []
            for node in path_from_root:
                if not isinstance(node, dict):
                    continue
                node_id = resolver._normalize_category_id(node.get("id"), normalized_site)
                node_name = node.get("name")
                if not node_id or not isinstance(node_name, str):
                    continue

                normalized_name = TextNormalizer.normalize(node_name)
                normalized_path.append(normalized_name)
                score = resolver._build_match_score(
                    target_name=target_name,
                    candidate_name=normalized_name,
                    context_terms=context_terms,
                    path_names=normalized_path,
                    depth=depth_hint,
                    min_similarity=0.8,
                )
                if score is None:
                    continue

                candidate_score = (*score, confidence, -prediction_rank)
                title_best_match = resolver._pick_best_candidate(
                    title_best_match,
                    (predicted_id, candidate_score),
                )

            predicted_name = prediction.get("category_name", "")
            if isinstance(predicted_name, str):
                normalized_predicted_name = TextNormalizer.normalize(predicted_name)
                score = resolver._build_match_score(
                    target_name=target_name,
                    candidate_name=normalized_predicted_name,
                    context_terms=context_terms,
                    path_names=normalized_path or [normalized_predicted_name],
                    depth=depth_hint,
                    min_similarity=0.8,
                )
                if score is not None:
                    candidate_score = (*score, confidence, -prediction_rank)
                    title_best_match = resolver._pick_best_candidate(
                        title_best_match,
                        (predicted_id, candidate_score),
                    )

        if title_best_match:
            logger.info(
                "Found matching category from predictor: %s for '%s' using title '%s'",
                title_best_match[0],
                category_name,
                title_str,
            )
            return title_best_match[0]

    logger.info(f"No prediction matched category '{category_name}' deterministically")
    return None
