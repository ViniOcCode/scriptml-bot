"""Attribute builder service for product publishing.

Handles attribute mapping, validation, scoring, and sanitization.
"""

import logging
import re
from typing import Any

from mercadolivre_upload.domain.attribute_mapper import AttributeMapper
from mercadolivre_upload.domain.attribute_metadata import AttributeMeta
from mercadolivre_upload.domain.cache_attribute_mapper import CachedAttributeMapper
from mercadolivre_upload.domain.category.resolver import CategoryResolver
from mercadolivre_upload.domain.product.model import Product
from mercadolivre_upload.domain.validation import (
    AttributeSanitizer,
    SemanticScorer,
    StructuralValidator,
    ValidationFeedback,
)
from mercadolivre_upload.shared.utils.text_utils import PortugueseTextNormalizer

logger = logging.getLogger(__name__)
_UNIT_ONLY_VALUE_PATTERN = re.compile(r"^(cm|mm|m|kg|g|mg|ml|l|oz|in)$", re.IGNORECASE)


class AttributeBuilderService:
    """Service for building and validating product attributes."""

    def __init__(
        self,
        category_resolver: CategoryResolver,
        config: dict[str, Any] | None = None,
        min_attribute_score: int = 50,
        feedback: ValidationFeedback | None = None,
    ):
        """Initialize attribute builder.

        Args:
            category_resolver: Category resolution service
            config: Configuration dictionary
            min_attribute_score: Minimum score for attributes (0-100)
            feedback: Validation feedback tracker
        """
        self.category_resolver = category_resolver
        self.config = config or {}
        self.min_attribute_score = min_attribute_score
        self.feedback = feedback
        self._attr_metadata_cache: dict[str, list[Any]] = {}
        self._cache_mapper: CachedAttributeMapper | None = None
        self._current_category_id: str | None = None

    def set_cache_mapper(self, cache_mapper: CachedAttributeMapper | None) -> None:
        """Set the cache mapper for attribute lookup."""
        self._cache_mapper = cache_mapper

    def build_attributes(
        self,
        product: Product,
        category_id: str,
        *,
        drop_invalid_domain_values: bool = True,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str], list[str]]:
        """Build sanitized attributes using semantic validation pipeline.

        Returns:
            Tuple of (attributes, sale_terms, warnings, errors)
        """
        warnings = []  # type: ignore[var-annotated]
        errors = []

        # 1. Get attribute metadata for structural validation
        try:
            attr_metadata = list(self.category_resolver.get_attribute_metadata(category_id))
            self._attr_metadata_cache[category_id] = list(attr_metadata)
        except Exception as e:
            logger.error(f"Failed to get attribute metadata: {e}")
            errors.append(f"attribute_metadata: {e}")
            return [], [], warnings, errors

        # 2. Map product attributes using cache-first strategy
        ml_attributes: list[dict[str, Any]] = []
        sale_terms: list[dict[str, Any]] = []
        cache_mapped_keys: set[str] = set()
        explicit_mappings = self.config.get("explicit_mappings", {})
        auto_explicit_mappings = self.config.get("auto_explicit_mappings", [])
        attribute_mapper = AttributeMapper(similarity_threshold=0.7)

        explicit_mapped_keys = attribute_mapper.get_explicitly_mapped_columns(
            product.attributes,
            explicit_mappings=explicit_mappings,
            auto_explicit_mappings=auto_explicit_mappings,
        )
        cache_candidates = {
            key: value
            for key, value in product.attributes.items()
            if key not in explicit_mapped_keys
        }

        # Try cache mapper first for non-explicit mappings
        if self._cache_mapper is not None:
            cache_attributes, cache_mapped_keys = self._map_attributes_with_cache(cache_candidates)
            if cache_attributes:
                ml_attributes.extend(cache_attributes)
                logger.info(f"Mapped {len(cache_attributes)} attributes via cache mapper")

        # Apply explicit mappings and fuzzy matching for remaining attributes
        # Filter out cache-mapped attributes for fuzzy processing
        remaining_attributes = {
            k: v for k, v in product.attributes.items() if k not in cache_mapped_keys
        }

        if remaining_attributes:
            logger.info(f"Falling back to fuzzy mapper for {len(remaining_attributes)} attributes")
            fuzzy_attributes, fuzzy_sale_terms = attribute_mapper.map_product_attributes(
                remaining_attributes,
                [meta.__dict__ for meta in attr_metadata],
                explicit_mappings=explicit_mappings,
                auto_explicit_mappings=auto_explicit_mappings,
            )

            # Merge attributes: cache results take precedence
            cache_attr_ids = {attr["id"] for attr in ml_attributes if "id" in attr}
            for attr in fuzzy_attributes:
                # Skip special markers (like _listing_type_id)
                if "id" not in attr or attr["id"] not in cache_attr_ids:
                    ml_attributes.append(attr)

            # Merge sale_terms
            if fuzzy_sale_terms:
                sale_terms.extend(fuzzy_sale_terms)
        else:
            logger.info("All attributes mapped via cache, no fuzzy fallback needed")

        previous_metadata_count = len(attr_metadata)
        attr_metadata = self._merge_conditional_metadata(
            category_id=category_id,
            product=product,
            ml_attributes=ml_attributes,
            attr_metadata=attr_metadata,
        )
        if len(attr_metadata) > previous_metadata_count and remaining_attributes:
            remapped_attributes, remapped_sale_terms = attribute_mapper.map_product_attributes(
                remaining_attributes,
                [meta.__dict__ for meta in attr_metadata],
                explicit_mappings=explicit_mappings,
                auto_explicit_mappings=auto_explicit_mappings,
            )
            ml_attributes.extend(
                attr
                for attr in remapped_attributes
                if isinstance(attr, dict) and isinstance(attr.get("id"), str) and attr.get("id")
            )
            existing_sale_term_ids = {
                sale_term["id"]
                for sale_term in sale_terms
                if isinstance(sale_term, dict) and isinstance(sale_term.get("id"), str)
            }
            sale_terms.extend(
                sale_term
                for sale_term in remapped_sale_terms
                if isinstance(sale_term, dict)
                and isinstance(sale_term.get("id"), str)
                and sale_term["id"] not in existing_sale_term_ids
            )

        # 3. Structural validation
        special_markers = [
            attr
            for attr in ml_attributes
            if isinstance(attr, dict) and "id" not in attr and any(k.startswith("_") for k in attr)
        ]
        attrs_for_validation = [
            attr
            for attr in ml_attributes
            if isinstance(attr, dict) and isinstance(attr.get("id"), str) and attr.get("id")
        ]
        attrs_for_validation = self._deduplicate_attributes(attrs_for_validation, attr_metadata)

        validator = StructuralValidator(attr_metadata)
        struct_result = validator.validate(
            attrs_for_validation,
            drop_invalid_domain_values=drop_invalid_domain_values,
        )

        warnings.extend(struct_result.warnings)
        if struct_result.blocking_errors:
            errors.extend(struct_result.blocking_errors)
            logger.error(f"Structural validation failed: {struct_result.blocking_errors}")

        if not struct_result.valid:
            logger.warning("Proceeding with sanitized attributes despite errors")

        # 4. Semantic scoring
        scorer = SemanticScorer(attr_metadata)
        scored_attrs = []
        for attr in struct_result.sanitized_attrs:
            scored = scorer.score_attribute(attr["id"], attr["value_name"])
            scored_attrs.append(scored)
            logger.debug(
                f"Attribute {scored.id}: score={scored.score}, class={scored.classification}"
            )

        # 5. Apply feedback adjustments if available
        if self.feedback:
            scored_attrs = self.feedback.adjust_scores(scored_attrs)

        # 6. Sanitization
        sanitizer = AttributeSanitizer(min_score=self.min_attribute_score)
        final_attrs = sanitizer.sanitize(scored_attrs)

        # Log dropped attributes
        dropped = {a.id for a in scored_attrs} - {a.id for a in final_attrs}
        for attr_id in dropped:
            logger.warning(f"Dropped attribute {attr_id} due to low score or redundancy")

        # Convert final attributes back to dict format
        final_attr_dicts = [{"id": a.id, "value_name": a.value} for a in final_attrs]
        final_attr_dicts.extend(special_markers)

        return final_attr_dicts, sale_terms, warnings, errors

    def _merge_conditional_metadata(
        self,
        *,
        category_id: str,
        product: Product,
        ml_attributes: list[dict[str, Any]],
        attr_metadata: list[AttributeMeta],
    ) -> list[AttributeMeta]:
        """Merge dynamic conditional attribute metadata into base category metadata."""
        get_conditionals = getattr(self.category_resolver, "get_conditional_attributes", None)
        if not callable(get_conditionals):
            return attr_metadata

        conditional_payload: dict[str, Any] = {
            "title": product.title,
            "attributes": [
                attr
                for attr in ml_attributes
                if isinstance(attr, dict) and isinstance(attr.get("id"), str) and attr.get("id")
            ],
        }
        if product.description:
            conditional_payload["description"] = {"plain_text": product.description}

        try:
            conditional_attrs = get_conditionals(category_id, conditional_payload)
        except Exception as e:
            logger.debug("Failed to load conditional metadata for %s: %s", category_id, e)
            return attr_metadata

        if not isinstance(conditional_attrs, list) or not conditional_attrs:
            return attr_metadata

        existing_ids = {
            meta.id
            for meta in attr_metadata
            if isinstance(getattr(meta, "id", None), str) and meta.id
        }
        merged_metadata = list(attr_metadata)
        added = 0
        for raw_attr in conditional_attrs:
            if not isinstance(raw_attr, dict):
                continue
            attr_id = raw_attr.get("id")
            if not isinstance(attr_id, str) or not attr_id or attr_id in existing_ids:
                continue

            normalized_attr = dict(raw_attr)
            normalized_attr.setdefault("name", attr_id)
            normalized_attr.setdefault("value_type", "string")
            tags = normalized_attr.get("tags")
            if isinstance(tags, (list, tuple, set)):
                normalized_attr["tags"] = {
                    str(tag).strip(): True for tag in tags if str(tag).strip()
                }
            elif not isinstance(tags, dict):
                normalized_attr["tags"] = {}

            try:
                merged_metadata.append(AttributeMeta.from_ml_api(normalized_attr))
                existing_ids.add(attr_id)
                added += 1
            except Exception as e:
                logger.debug("Skipping invalid conditional metadata for %s: %s", attr_id, e)

        if added:
            logger.info("Loaded %s dynamic conditional attributes for %s", added, category_id)
        return merged_metadata

    def _map_attributes_with_cache(
        self, attributes: dict[str, Any]
    ) -> tuple[list[dict[str, Any]], set[str]]:
        """Map attributes using cache mapper.

        Args:
            attributes: Product attributes from Excel

        Returns:
            Tuple of mapped ML attributes and mapped spreadsheet headers
        """
        if not self._cache_mapper:
            return [], set()

        mapped = []
        mapped_headers: set[str] = set()
        for header, value in attributes.items():
            if not value:
                continue

            variation_hint: str | None = None
            extract_variation_hint = getattr(self._cache_mapper, "extract_variation_hint", None)
            if callable(extract_variation_hint):
                variation_hint = extract_variation_hint(header)

            attr = self._cache_mapper.find_attribute_by_name(header)
            if attr and attr.get("id"):
                attr_id = str(attr["id"])
                payload = self._cache_mapper.map_value(attr_id, str(value))
                payload["_source_column"] = header
                if (
                    isinstance(attr.get("values"), list)
                    and attr.get("values")
                    and payload.get("value_id") is None
                    and payload.get("value_name") is None
                ):
                    logger.debug("Skipping cache mapped value with no allowed match: %s", header)
                    continue
                mapped.append(payload)
                tags = attr.get("tags", {})
                should_extract_variations = bool(variation_hint)
                if isinstance(tags, dict) and tags.get("allow_variations"):
                    should_extract_variations = True

                if should_extract_variations:
                    variation_values: list[dict[str, Any]] = []
                    map_all_values = getattr(self._cache_mapper, "map_all_values", None)
                    if callable(map_all_values):
                        variation_values = map_all_values(attr_id, str(value))
                    if variation_hint and len(variation_values) <= 1:
                        variation_values = self._expand_variation_candidates_from_hint(
                            str(value),
                            variation_values,
                        )
                    if len(variation_values) > 1:
                        mapped.append({"_variation_candidates": {attr_id: variation_values}})
                mapped_headers.add(header)
                logger.debug(f"Cache mapped: {header} -> {attr['id']}")

        return mapped, mapped_headers

    @staticmethod
    def _expand_variation_candidates_from_hint(
        excel_value: str,
        base_values: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Expand variation candidates from raw hint value tokens."""
        candidates = [
            value
            for value in base_values
            if isinstance(value, dict) and isinstance(value.get("name"), str) and value.get("name")
        ]
        seen = {
            PortugueseTextNormalizer.normalize(str(value["name"]))
            for value in candidates
            if isinstance(value.get("name"), str)
        }
        for token in re.split(r"[,;/|]", excel_value):
            candidate = token.strip()
            normalized_candidate = PortugueseTextNormalizer.normalize(candidate)
            if not normalized_candidate or normalized_candidate in seen:
                continue
            seen.add(normalized_candidate)
            candidates.append({"id": None, "name": candidate})
        return candidates

    def _deduplicate_attributes(
        self, attributes: list[dict[str, Any]], attr_metadata: list[Any]
    ) -> list[dict[str, Any]]:
        """Keep one payload per attribute id, preferring higher-quality values."""
        metadata_by_id = {
            meta.id: meta for meta in attr_metadata if isinstance(getattr(meta, "id", None), str)
        }

        selected: dict[str, tuple[int, dict[str, Any]]] = {}
        order: list[str] = []
        for attr in attributes:
            attr_id = attr.get("id")
            if not isinstance(attr_id, str) or not attr_id:
                continue

            score = self._score_attribute_payload(attr, metadata_by_id.get(attr_id))
            if attr_id not in selected:
                selected[attr_id] = (score, attr)
                order.append(attr_id)
                continue

            previous_score, _previous_attr = selected[attr_id]
            if score > previous_score:
                selected[attr_id] = (score, attr)

        return [selected[attr_id][1] for attr_id in order]

    def _score_attribute_payload(self, attr: dict[str, Any], meta: Any | None) -> int:
        """Score payload quality so duplicates keep the most informative value."""
        score = 0
        value = attr.get("value_name")
        value_text = str(value).strip() if value is not None else ""
        value_id = attr.get("value_id")

        if value_id not in (None, ""):
            score += 4
        if isinstance(attr.get("values"), list) and attr.get("values"):
            score += 2
        if attr.get("id") == "GTIN":
            source_column = attr.get("_source_column")
            priority_config = self.config.get("gtin_source_priority", [])
            if isinstance(source_column, str) and isinstance(priority_config, list):
                normalized_source = PortugueseTextNormalizer.normalize(source_column)
                for index, priority_column in enumerate(priority_config):
                    normalized_priority = PortugueseTextNormalizer.normalize(str(priority_column))
                    if normalized_source == normalized_priority:
                        score += max(0, 10 - index)
                        break
        if value_text:
            score += 1
            if any(char.isdigit() for char in value_text):
                score += 3
            if _UNIT_ONLY_VALUE_PATTERN.match(value_text):
                score -= 4

        if meta is not None and getattr(meta, "value_type", "") == "number_unit":
            lower = value_text.lower()
            if any(char.isdigit() for char in value_text) and any(
                unit in lower for unit in ("cm", "mm", "m", "kg", "g", "in", "oz")
            ):
                score += 3

        return score
