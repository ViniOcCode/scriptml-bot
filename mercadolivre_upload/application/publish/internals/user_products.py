"""User-products helper functions extracted from publish_product use case."""

from __future__ import annotations

from itertools import product as cartesian_product
from typing import Any

from mercadolivre_upload.domain.product.model import Product
from mercadolivre_upload.shared.utils.text_utils import PortugueseTextNormalizer


def extract_user_products_family_name(product: Product) -> str | None:
    """Extract user-products family name from source row attributes."""
    aliases = {
        "familyname",
        "family name",
        "familia",
        "nome da familia",
        "nome familia",
    }
    for key, raw_value in product.attributes.items():
        normalized_key = PortugueseTextNormalizer.normalize(str(key))
        if normalized_key not in aliases:
            continue
        value = str(raw_value).strip()
        if value:
            return value
    return None


def extract_selected_model(
    ml_attributes: list[dict[str, Any]],
    variation_candidates: dict[str, list[dict[str, Any]]],
) -> str | None:
    """Extract deterministic MODEL value for UP flow artifacts."""
    for attr in ml_attributes:
        if not isinstance(attr, dict):
            continue
        attr_id = attr.get("id")
        if not isinstance(attr_id, str) or attr_id.upper() != "MODEL":
            continue
        value_name = attr.get("value_name")
        if isinstance(value_name, str) and value_name.strip():
            return value_name.strip()
        value_id = attr.get("value_id")
        if value_id is not None and str(value_id).strip():
            return str(value_id).strip()

    for attr_id, values in variation_candidates.items():
        if not isinstance(attr_id, str) or attr_id.upper() != "MODEL":
            continue
        for value in values:
            if not isinstance(value, dict):
                continue
            value_name = value.get("name")
            if isinstance(value_name, str) and value_name.strip():
                return value_name.strip()

    return None


def normalize_variation_candidates(
    variation_candidates: dict[str, list[dict[str, Any]]],
) -> list[tuple[str, list[dict[str, Any]]]]:
    """Normalize and deduplicate variation candidates preserving deterministic order."""
    normalized_candidates: list[tuple[str, list[dict[str, Any]]]] = []
    for attr_id, values in variation_candidates.items():
        if not isinstance(attr_id, str):
            continue
        normalized_attr_id = attr_id.strip()
        if not normalized_attr_id:
            continue
        unique_values: list[dict[str, Any]] = []
        seen: set[tuple[Any, Any]] = set()
        for value in values:
            if not isinstance(value, dict):
                continue
            value_name = value.get("name")
            if not isinstance(value_name, str):
                continue
            normalized_name = value_name.strip()
            if not normalized_name:
                continue
            key = (value.get("id"), normalized_name)
            if key in seen:
                continue
            seen.add(key)
            unique_values.append({"id": value.get("id"), "name": normalized_name})

        if unique_values:
            normalized_candidates.append((normalized_attr_id, unique_values))
    return normalized_candidates


def variation_value_sort_key(value: dict[str, Any]) -> tuple[str, str]:
    """Return deterministic sort key for variation candidate values."""
    value_name = value.get("name")
    value_id = value.get("id")
    normalized_name = (
        PortugueseTextNormalizer.normalize(str(value_name)) if isinstance(value_name, str) else ""
    )
    normalized_id = str(value_id).strip() if value_id is not None else ""
    return normalized_name, normalized_id


def build_user_products_payload(
    *,
    product: Product,
    ml_attributes: list[dict[str, Any]],
    variation_candidates: dict[str, list[dict[str, Any]]],
    quantity: int,
    price: float,
    picture_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Build MLB-safe user-products metadata and payload fields."""
    family_name = extract_user_products_family_name(product)
    family_name_source = "attribute"
    if not family_name:
        raise ValueError("missing required field 'family_name'.")

    selected_model = extract_selected_model(ml_attributes, variation_candidates)

    normalized_candidates = normalize_variation_candidates(variation_candidates)
    variations: list[dict[str, Any]] = []
    if normalized_candidates:
        combinations = list(
            cartesian_product(*(values for _attr_id, values in normalized_candidates))
        )
        for combination in combinations:
            attributes: list[dict[str, Any]] = []
            for (attr_id, _values), value in zip(normalized_candidates, combination, strict=True):
                mapped = {"id": attr_id, "value_name": value["name"]}
                value_id = value.get("id")
                if value_id is not None:
                    mapped["value_id"] = value_id
                attributes.append(mapped)

            variation_payload: dict[str, Any] = {
                "attributes": attributes,
                "available_quantity": max(1, quantity),
                "price": price,
            }
            if picture_ids:
                variation_payload["picture_ids"] = picture_ids[:10]
            variations.append(variation_payload)

    return {
        "family_name": family_name,
        "family_name_source": family_name_source,
        "selected_model": selected_model,
        "variation_attribute_ids": [attr_id for attr_id, _values in normalized_candidates],
        "variations": variations,
    }
