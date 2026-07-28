"""Input and category-context helpers for spreadsheet validation adapters."""

import logging
from typing import Any

logger = logging.getLogger(__name__)


def extract_row_identity(row: dict[str, Any]) -> tuple[str | None, str | None]:
    """Return the first non-empty SKU and title values available in a row."""
    sku = None
    for key in ("sku", "codigo", "código", "code"):
        value = row.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            sku = text
            break

    title = None
    for key in ("titulo", "título", "title", "nome"):
        value = row.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            title = text
            break

    return sku, title


def extract_row_category(row: dict[str, Any]) -> str | None:
    """Return the optional category signal carried by a spreadsheet row."""
    direct_keys = ("category_id", "category", "categoria", "categoria_id", "my_category")
    for key in direct_keys:
        value = row.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text

    for key, value in row.items():
        normalized = str(key).strip().lower().replace(" ", "_").replace("-", "_")
        if normalized in direct_keys:
            text = str(value).strip()
            if text:
                return text

    return None


def build_row_category_metadata(row: dict[str, Any], default_category: str) -> dict[str, Any]:
    """Build reporting metadata without changing the CLI-selected category."""
    row_category = extract_row_category(row)
    normalized_default = default_category.strip().casefold()
    normalized_row = row_category.strip().casefold() if isinstance(row_category, str) else ""
    return {
        "row_category_detected": row_category,
        "row_category_mismatch": bool(normalized_row and normalized_row != normalized_default),
    }


def prime_category_resolution_context(
    use_case: Any,
    products: list[dict[str, Any]],
    category: str,
) -> None:
    """Best-effort prime of an optional category resolver before batch execution."""
    resolver = getattr(use_case, "_resolve_category_context", None)
    if not callable(resolver):
        return
    try:
        resolver(products, category, use_cache=False)
    except TypeError:
        try:
            resolver(products, category)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not pre-resolve category context for batch run: %s", exc)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not pre-resolve category context for batch run: %s", exc)
