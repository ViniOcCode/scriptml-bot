"""Hierarchy helper logic for category resolver."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from mercadolivre_upload.shared.utils.text_utils import TextNormalizer


def load_categories(
    api_port: Any,
    site_id: str,
    normalize_category_id: Callable[[Any, str | None], str | None],
) -> dict[str, str]:
    """Load and normalize root categories for a site."""
    categories = api_port.get_site_categories(site_id)

    items: list[tuple[str, str]] = []
    for category in categories:
        if not isinstance(category, dict):
            continue

        category_id = normalize_category_id(category.get("id"), site_id)
        category_name = category.get("name")
        if not category_id or not isinstance(category_name, str):
            continue

        name_normalized = TextNormalizer.normalize(category_name)
        if name_normalized:
            items.append((name_normalized, category_id))

    result: dict[str, str] = {}
    for name_normalized, category_id in sorted(items, key=lambda item: (item[0], item[1])):
        result[name_normalized] = category_id

    return result


def get_category_children(
    api_port: Any,
    category_id: str,
    children_cache: dict[str, list[Any]],
    normalize_category_id: Callable[[Any, str | None], str | None],
) -> list[dict[str, Any]]:
    """Get children of a category from cached category data."""
    if category_id not in children_cache:
        category_data = api_port.get_category(category_id)
        raw_children = []
        if isinstance(category_data, dict):
            raw_children = category_data.get("children_categories", [])

        expected_site = category_id[:3] if len(category_id) >= 3 else None
        children: list[dict[str, Any]] = []
        if isinstance(raw_children, list):
            for child in raw_children:
                if not isinstance(child, dict):
                    continue

                child_id = normalize_category_id(child.get("id"), expected_site)
                child_name = child.get("name")
                if not child_id or not isinstance(child_name, str):
                    continue

                children.append({**child, "id": child_id, "name": child_name.strip()})

        children.sort(
            key=lambda child: (
                TextNormalizer.normalize(str(child.get("name", ""))),
                str(child.get("id", "")),
            )
        )
        children_cache[category_id] = children

    return children_cache[category_id]


def search_in_hierarchy(
    *,
    target_name: str,
    parent_id: str,
    get_category_children: Callable[[str], list[dict[str, Any]]],
    normalize_category_id: Callable[[Any, str | None], str | None],
    build_match_score: Callable[..., tuple[Any, ...] | None],
    pick_best_candidate: Callable[
        [tuple[str, tuple[Any, ...]] | None, tuple[str, tuple[Any, ...]] | None],
        tuple[str, tuple[Any, ...]] | None,
    ],
    context_terms: set[str] | None = None,
    path_names: list[str] | None = None,
    visited: set[str] | None = None,
    depth: int = 0,
    max_depth: int = 8,
    min_similarity: float = 0.8,
    site_id: str = "MLB",
) -> tuple[str, tuple[Any, ...]] | None:
    """Search for category name in hierarchy starting from parent."""
    if visited is None:
        visited = set()
    if context_terms is None:
        context_terms = set()
    if path_names is None:
        path_names = []

    if depth > max_depth:
        return None
    if parent_id in visited:
        return None

    visited.add(parent_id)
    children = get_category_children(parent_id)
    best_match: tuple[str, tuple[Any, ...]] | None = None

    for child in children:
        child_id = normalize_category_id(child.get("id"), site_id)
        child_name = child.get("name")
        if not child_id or not isinstance(child_name, str):
            continue

        child_normalized = TextNormalizer.normalize(child_name)
        child_path = [*path_names, child_normalized]

        score = build_match_score(
            target_name=target_name,
            candidate_name=child_normalized,
            context_terms=context_terms,
            path_names=child_path,
            depth=depth + 1,
            min_similarity=min_similarity,
        )
        if score is not None:
            best_match = pick_best_candidate(best_match, (child_id, score))

        subtree_match = search_in_hierarchy(
            target_name=target_name,
            parent_id=child_id,
            get_category_children=get_category_children,
            normalize_category_id=normalize_category_id,
            build_match_score=build_match_score,
            pick_best_candidate=pick_best_candidate,
            context_terms=context_terms,
            path_names=child_path,
            visited=visited,
            depth=depth + 1,
            max_depth=max_depth,
            min_similarity=min_similarity,
            site_id=site_id,
        )
        best_match = pick_best_candidate(best_match, subtree_match)

    return best_match
