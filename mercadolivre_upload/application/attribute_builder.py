"""Attribute builder service for product publishing.

Handles attribute mapping, validation, scoring, and sanitization.
"""

import logging
from typing import Any, Optional

from mercadolivre_upload.domain.attribute_mapper import AttributeMapper
from mercadolivre_upload.domain.cache_attribute_mapper import CachedAttributeMapper
from mercadolivre_upload.domain.product.model import Product
from mercadolivre_upload.domain.validation import (
    StructuralValidator,
    SemanticScorer,
    AttributeSanitizer,
    ValidationFeedback,
)
from mercadolivre_upload.domain.category.resolver import CategoryResolver

logger = logging.getLogger(__name__)


class AttributeBuilderService:
    """Service for building and validating product attributes."""

    def __init__(
        self,
        category_resolver: CategoryResolver,
        config: Optional[dict] = None,
        min_attribute_score: int = 50,
        feedback: Optional[ValidationFeedback] = None,
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
        self._attr_metadata_cache: dict[str, list] = {}
        self._cache_mapper: Optional[CachedAttributeMapper] = None
        self._current_category_id: Optional[str] = None

    def set_cache_mapper(self, cache_mapper: Optional[CachedAttributeMapper]) -> None:
        """Set the cache mapper for attribute lookup."""
        self._cache_mapper = cache_mapper

    def build_attributes(
        self, product: Product, category_id: str
    ) -> tuple[list[dict], list[dict], list[str], list[str]]:
        """Build sanitized attributes using semantic validation pipeline.

        Returns:
            Tuple of (attributes, sale_terms, warnings, errors)
        """
        warnings = []
        errors = []

        # 1. Get attribute metadata for structural validation
        try:
            attr_metadata = self.category_resolver.get_attribute_metadata(category_id)
            self._attr_metadata_cache[category_id] = attr_metadata
        except Exception as e:
            logger.error(f"Failed to get attribute metadata: {e}")
            errors.append(f"attribute_metadata: {e}")
            return [], [], warnings, errors

        # 2. Map product attributes using cache-first strategy
        ml_attributes: list[dict] = []
        sale_terms: list[dict] = []
        cache_attributes: list[dict] = []

        # Try cache mapper first if available
        if self._cache_mapper is not None:
            cache_attributes = self._map_attributes_with_cache(product.attributes)
            if cache_attributes:
                ml_attributes.extend(cache_attributes)
                logger.info(f"Mapped {len(cache_attributes)} attributes via cache mapper")

        # Apply explicit mappings and fuzzy matching for remaining attributes
        cache_mapped_keys: set[str] = set()
        if self._cache_mapper is not None and cache_attributes:
            # Track which Excel headers were successfully mapped via cache
            for excel_header, excel_value in product.attributes.items():
                if not excel_value:
                    continue
                attr = self._cache_mapper.find_attribute_by_name(excel_header)
                if attr and attr.get('id'):
                    cache_mapped_keys.add(excel_header)

        # Filter out cache-mapped attributes for fuzzy processing
        remaining_attributes = {
            k: v for k, v in product.attributes.items()
            if k not in cache_mapped_keys
        }

        if remaining_attributes:
            logger.info(f"Falling back to fuzzy mapper for {len(remaining_attributes)} attributes")
            attribute_mapper = AttributeMapper(similarity_threshold=0.7)
            explicit_mappings = self.config.get('explicit_mappings', {})
            fuzzy_attributes, fuzzy_sale_terms = attribute_mapper.map_product_attributes(
                remaining_attributes,
                [meta.__dict__ for meta in attr_metadata],
                explicit_mappings=explicit_mappings
            )

            # Merge attributes: cache results take precedence
            cache_attr_ids = {attr["id"] for attr in ml_attributes if "id" in attr}
            for attr in fuzzy_attributes:
                # Skip special markers (like _listing_type_id)
                if "id" not in attr:
                    ml_attributes.append(attr)
                elif attr["id"] not in cache_attr_ids:
                    ml_attributes.append(attr)

            # Merge sale_terms
            if fuzzy_sale_terms:
                sale_terms.extend(fuzzy_sale_terms)
        else:
            logger.info("All attributes mapped via cache, no fuzzy fallback needed")

        # 3. Structural validation
        validator = StructuralValidator(attr_metadata)
        struct_result = validator.validate(ml_attributes)

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
            logger.debug(f"Attribute {scored.id}: score={scored.score}, class={scored.classification}")

        # 5. Apply feedback adjustments if available
        if self.feedback:
            scored_attrs = self.feedback.adjust_scores(scored_attrs)

        # 6. Sanitization
        sanitizer = AttributeSanitizer(min_score=self.min_attribute_score)
        final_attrs = sanitizer.sanitize(scored_attrs)

        # Log dropped attributes
        dropped = set(a.id for a in scored_attrs) - set(a.id for a in final_attrs)
        for attr_id in dropped:
            logger.warning(f"Dropped attribute {attr_id} due to low score or redundancy")

        # 7. Get conditional attributes
        attr_dict = {a.id: a.value for a in final_attrs}
        try:
            conditional_attrs = self.category_resolver.get_conditional_attributes(
                category_id, attr_dict
            )

            # Check if any conditional attributes should be added
            existing_ids = {a["id"] for a in ml_attributes if "id" in a}
            for cond_attr in conditional_attrs:
                if cond_attr["id"] not in existing_ids:
                    ml_attributes.append(cond_attr)
                    logger.info(f"Added conditional attribute: {cond_attr['id']}")

        except Exception as e:
            logger.warning(f"Could not get conditional attributes: {e}")

        # Convert final attributes back to dict format
        final_attr_dicts = [{"id": a.id, "value_name": a.value} for a in final_attrs]

        return final_attr_dicts, sale_terms, warnings, errors

    def _map_attributes_with_cache(self, attributes: dict[str, Any]) -> list[dict]:
        """Map attributes using cache mapper.

        Args:
            attributes: Product attributes from Excel

        Returns:
            List of mapped ML attributes
        """
        if not self._cache_mapper:
            return []

        mapped = []
        for header, value in attributes.items():
            if not value:
                continue

            attr = self._cache_mapper.find_attribute_by_name(header)
            if attr and attr.get('id'):
                mapped.append({
                    "id": attr['id'],
                    "value_name": str(value),
                })
                logger.debug(f"Cache mapped: {header} -> {attr['id']}")

        return mapped
