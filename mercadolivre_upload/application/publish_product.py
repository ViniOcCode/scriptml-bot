"""Publish product use case.

Orchestrates domain logic and adapters to publish products.
"""

import logging
import re
from pathlib import Path
from typing import Any, Optional, Protocol

from mercadolivre_upload.domain.category.resolver import CategoryResolver
from mercadolivre_upload.domain.product.model import Product
from mercadolivre_upload.domain.fiscal.data import FiscalData
from mercadolivre_upload.domain.fiscal.service import FiscalService, FiscalSubmissionResult
from mercadolivre_upload.domain.attribute_mapper import AttributeMapper
from mercadolivre_upload.domain.validation import (
    StructuralValidator,
    SemanticScorer,
    AttributeSanitizer,
    ValidationFeedback,
)
from mercadolivre_upload.adapters.spreadsheet.parser import SpreadsheetParser

logger = logging.getLogger(__name__)


class ImageUploaderPort(Protocol):
    """Port for image upload operations."""

    def upload_images(self, sku: str) -> list[str]:
        """Upload images for SKU and return URLs."""
        ...


class ItemPublisherPort(Protocol):
    """Port for item publishing operations."""

    def validate_item(self, item: dict) -> dict:
        """Validate item payload."""
        ...

    def create_item(self, item: dict) -> dict:
        """Create/publish item."""
        ...


class ShippingResolverPort(Protocol):
    """Port for shipping mode resolution."""

    def get_best_shipping_mode(self) -> str:
        """Get best available shipping mode for user."""
        ...


class PublishProductUseCase:
    """Use case for publishing products to ML."""

    def __init__(
        self,
        category_resolver: CategoryResolver,
        publisher: ItemPublisherPort,
        image_uploader: ImageUploaderPort,
        shipping_resolver: Optional[ShippingResolverPort] = None,
        fiscal_service: Optional[FiscalService] = None,
        dry_run: bool = False,
        min_attribute_score: int = 50,
        enable_feedback: bool = True,
        enable_fiscal_submission: bool = True,
    ):
        """Initialize use case.

        Args:
            category_resolver: Category resolution service
            publisher: Item publisher (API adapter)
            image_uploader: Image uploader service
            shipping_resolver: Shipping mode resolver (optional)
            fiscal_service: Fiscal data submission service (optional)
            dry_run: If True, only validate
            min_attribute_score: Minimum score for attributes (0-100)
            enable_feedback: Enable validation feedback tracking
            enable_fiscal_submission: Whether to submit fiscal data after publishing
        """
        self.category_resolver = category_resolver
        self.publisher = publisher
        self.image_uploader = image_uploader
        self.shipping_resolver = shipping_resolver
        self.fiscal_service = fiscal_service
        self.dry_run = dry_run
        self.min_attribute_score = min_attribute_score
        self.enable_fiscal_submission = enable_fiscal_submission

        self.published = 0
        self.failed = 0
        self.errors: list[str] = []
        self.fiscal_results: list[FiscalSubmissionResult] = []

        # Initialize feedback system
        self.feedback = ValidationFeedback() if enable_feedback else None

        # Cache for attribute metadata
        self._attr_metadata_cache: dict[str, list] = {}

    def execute(self, products: list[Product], category_name: str) -> dict:
        """Execute publishing use case.

        Args:
            products: List of products to publish
            category_name: Category name for all products

        Returns:
            Execution results
        """
        # Find category ID using predictor-first strategy
        category_id = self.category_resolver.find_category(category_name)

        # Fallback: try domain discovery with product titles
        if not category_id and products:
            logger.info(f"Category not found by name, trying domain discovery...")
            for product in products:
                if product.title:
                    category_id = self.category_resolver.predict_category_from_title(
                        product.title
                    )
                    if category_id:
                        logger.info(f"Found category from title '{product.title[:30]}...'")
                        break

        if not category_id:
            error_msg = f"Category not found: {category_name}"
            logger.error(error_msg)
            return {
                "success": False,
                "published": 0,
                "failed": len(products),
                "errors": [error_msg],
            }

        # Ensure we have a leaf category (no children)
        leaf_category_id = self.category_resolver.resolve_to_leaf(category_id)
        if leaf_category_id != category_id:
            logger.info(f"Resolved to leaf category: {leaf_category_id}")
            category_id = leaf_category_id

        logger.info(f"Publishing {len(products)} products to category {category_id}")

        for product in products:
            self._publish_one(product, category_id)

        return {
            "success": self.failed == 0,
            "published": self.published,
            "failed": self.failed,
            "errors": self.errors,
        }

    def _build_attributes(
        self, product: Product, category_id: str
    ) -> tuple[list[dict], list[str], list[str]]:
        """Build sanitized attributes using semantic validation pipeline.

        Returns:
            Tuple of (attributes, warnings, errors)
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
            return [], warnings, errors

        # 2. Map product attributes to ML format using fuzzy matching
        attribute_mapper = AttributeMapper(similarity_threshold=0.7)
        ml_attributes = attribute_mapper.map_product_attributes(
            product.attributes,
            [meta.__dict__ for meta in attr_metadata]
        )

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
            for cond_attr in conditional_attrs:
                attr_id = cond_attr.get("id")
                attr_name = cond_attr.get("name", "").lower()

                if attr_id in attr_dict:
                    continue

                if attr_name in product.attributes:
                    meta = next((m for m in attr_metadata if m.id == attr_id), None)
                    if meta:
                        final_attrs.append(
                            scorer.score_attribute(attr_id, product.attributes[attr_name])
                        )
                    else:
                        # Create meta from API data and score
                        from ..domain.attribute_metadata import AttributeMeta
                        meta = AttributeMeta.from_ml_api(cond_attr)
                        final_attrs.append(
                            scorer.score_attribute(attr_id, product.attributes[attr_name])
                        )
        except Exception as e:
            logger.warning(f"Could not get conditional attributes: {e}")

        # Convert to dict format
        result_attrs = [{"id": a.id, "value_name": a.value} for a in final_attrs]

        return result_attrs, warnings, errors

    def _publish_one(self, product: Product, category_id: str) -> bool:
        """Publish a single product."""
        logger.info(f"Publishing product: {product.sku} (title: {product.title[:50]}...)")

        # Build attributes using semantic validation pipeline
        ml_attributes, attr_warnings, attr_errors = self._build_attributes(
            product, category_id
        )

        # Handle blocking attribute errors
        if attr_errors:
            logger.error(f"Attribute validation failed for {product.sku}: {attr_errors}")
            self.errors.append(f"{product.sku}: {attr_errors}")
            self.failed += 1
            return False

        # Log attribute processing results
        if attr_warnings:
            logger.warning(f"Attribute warnings for {product.sku}: {attr_warnings}")

        logger.info(f"Final attribute count for {product.sku}: {len(ml_attributes)}")

        # Upload images
        picture_urls = self.image_uploader.upload_images(product.sku)

        # Build pictures list
        pictures = [{"source": url} for url in picture_urls]

        if not pictures:
            logger.warning(f"No pictures for {product.sku}")

        # Determine shipping mode
        shipping_mode = "not_specified"
        if self.shipping_resolver:
            shipping_mode = self.shipping_resolver.get_best_shipping_mode()
            logger.info(f"Using shipping mode: {shipping_mode}")

        # Build shipping config
        shipping_config = {"mode": shipping_mode}
        if shipping_mode == "not_specified":
            shipping_config["local_pick_up"] = True
            logger.info("Enabled local_pick_up for not_specified shipping")
        elif shipping_mode in ("me1", "me2"):
            shipping_config["logistic_type"] = "drop_off"
            shipping_config["local_pick_up"] = False
            shipping_config["methods"] = []
            logger.info(f"Shipping config for {shipping_mode} mode")

        logger.debug(f"Shipping config for {product.sku}: {shipping_config}")

        # Build item
        item = {
            "title": product.title,
            "category_id": category_id,
            "price": product.price,
            "currency_id": "BRL",
            "available_quantity": product.available_quantity,
            "buying_mode": "buy_it_now",
            "condition": product.condition,
            "listing_type_id": "free" if not pictures else "gold_special",
            "description": {"plain_text": product.description},
            "pictures": pictures,
            "attributes": ml_attributes,
            "shipping": shipping_config,
        }

        # Log shipping section before validation
        logger.info(f"Final shipping config for {product.sku}: mode={shipping_config.get('mode')}, "
                    f"free_shipping={shipping_config.get('free_shipping')}, "
                    f"logistic_type={shipping_config.get('logistic_type')}, "
                    f"local_pick_up={shipping_config.get('local_pick_up')}")

        if self.dry_run:
            logger.info(f"DRY RUN: Would publish {product.sku}")
            self.published += 1
            return True

        # Normalize attributes before validation/publish (ensure units)
        self._normalize_item_attributes(item)

        # DEBUG: Log full item payload (with sensitive data redacted if needed)
        debug_item = item.copy()
        debug_item.pop('description', None)  # Remove long description for cleaner logs
        logger.debug(f"Full item payload for {product.sku}: {debug_item}")

        # Validate
        validation_result = None
        try:
            validation = self.publisher.validate_item(item)
            logger.debug(f"Validation response for {product.sku}: {validation}")

            # Parse validation causes to distinguish warnings from errors
            causes = validation.get("cause", [])
            errors = []
            warnings = []
            shipping_issues = []

            for cause in causes:
                cause_type = cause.get("type", "").lower()
                cause_code = cause.get("code", "")
                cause_message = cause.get("message", "")
                logger.debug(f"Validation cause for {product.sku}: {cause}")

                # Check for shipping-specific issues
                if "shipping" in str(cause_code).lower() or "shipping" in str(cause_message).lower():
                    shipping_issues.append(f"{cause_code}: {cause_message}")

                # Separate actual errors from warnings
                if cause_type == "error":
                    errors.append(f"{cause_code}: {cause_message}")
                elif cause_type == "warning":
                    warnings.append(f"{cause_code}: {cause_message}")

            # Log shipping issues
            if shipping_issues:
                logger.info(f"Shipping validation issues for {product.sku}: {shipping_issues}")

            # Log warnings (don't block publishing)
            if warnings:
                logger.warning(f"Validation warnings for {product.sku}: {warnings}")

            # Record validation result for feedback
            validation_result = validation

            # Only fail if there are actual errors
            if errors:
                logger.error(f"Validation failed for {product.sku}: {errors}")
                self.errors.append(f"{product.sku}: {errors}")
                self.failed += 1
                # Record feedback
                if self.feedback:
                    self.feedback.record_validation_result(
                        product.sku, ml_attributes, validation
                    )
                return False
        except Exception as e:
            # Try to extract error details from exception
            error_msg = str(e)
            error_detail = None
            if hasattr(e, 'response') and e.response is not None:
                try:
                    error_detail = e.response.json()
                    error_msg = f"{error_msg} - {error_detail}"
                    # Check for shipping-specific errors
                    causes = error_detail.get("cause", []) if isinstance(error_detail, dict) else []
                    for cause in causes:
                        cause_code = cause.get("code", "").lower()
                        cause_message = cause.get("message", "").lower()
                        if "shipping" in cause_code or "shipping" in cause_message:
                            logger.error(f"Shipping validation error for {product.sku}: {cause}")
                except Exception:
                    error_msg = f"{error_msg} - {e.response.text[:200]}"
            logger.error(f"Validation error for {product.sku}: {error_msg}")
            self.errors.append(f"{product.sku}: {error_msg}")
            self.failed += 1
            return False

        # Publish
        published_item_id: str | None = None
        try:
            result = self.publisher.create_item(item)
            published_item_id = result.get('id')
            logger.info(f"Published {product.sku}: {published_item_id}")
            self.published += 1

            # Record successful validation feedback
            if self.feedback and validation_result:
                self.feedback.record_validation_result(
                    product.sku, ml_attributes, validation_result
                )

            # Submit fiscal data if available and service is configured
            if (
                self.enable_fiscal_submission
                and self.fiscal_service
                and published_item_id
                and product.fiscal
                and product.fiscal.is_valid
            ):
                logger.info(f"Submitting fiscal data for {product.sku} (item: {published_item_id})")
                fiscal_result = self.fiscal_service.submit_fiscal_data(
                    published_item_id,
                    product.fiscal
                )
                self.fiscal_results.append(fiscal_result)
                
                if fiscal_result.success:
                    logger.info(f"Fiscal data submitted successfully for {product.sku}")
                else:
                    logger.warning(
                        f"Fiscal data submission failed for {product.sku}: "
                        f"{fiscal_result.error_message}"
                    )

            return True
        except Exception as e:
            error_msg = str(e)
            if hasattr(e, 'response') and e.response is not None:
                try:
                    error_detail = e.response.json()
                    error_msg = f"{error_msg} - {error_detail}"
                    # Check for shipping-specific errors
                    causes = error_detail.get("cause", []) if isinstance(error_detail, dict) else []
                    # Record publish failure feedback
                    if self.feedback:
                        self.feedback.record_validation_result(
                            product.sku, ml_attributes, error_detail if isinstance(error_detail, dict) else {}
                        )
                    for cause in causes:
                        cause_code = cause.get("code", "").lower()
                        cause_message = cause.get("message", "").lower()
                        if "shipping" in cause_code or "shipping" in cause_message:
                            logger.error(f"Shipping publish error for {product.sku}: {cause}")
                except Exception:
                    error_msg = f"{error_msg} - {e.response.text[:200]}"
            logger.error(f"Publish error for {product.sku}: {error_msg}")
            self.errors.append(f"{product.sku}: {error_msg}")
            self.failed += 1
            return False

    def get_stats(self) -> dict:
        """Get publishing statistics."""
        stats: dict[str, Any] = {
            "published": self.published,
            "failed": self.failed,
            "total": self.published + self.failed,
            "errors": self.errors,
        }

        # Add feedback summary if available
        if self.feedback:
            stats["feedback"] = self.feedback.get_feedback_summary()

        # Add fiscal submission results
        if self.fiscal_results:
            fiscal_success = sum(1 for r in self.fiscal_results if r.success)
            fiscal_failed = len(self.fiscal_results) - fiscal_success
            stats["fiscal"] = {
                "submitted": len(self.fiscal_results),
                "success": fiscal_success,
                "failed": fiscal_failed,
            }

        return stats

    def get_problematic_attributes(self) -> dict[str, int]:
        """Get attributes that frequently cause errors.

        Returns:
            Dictionary mapping attribute IDs to error counts
        """
        if self.feedback:
            return self.feedback.get_problematic_attributes()
        return {}

    def _normalize_item_attributes(self, item: dict) -> None:
        """Ensure numeric dimensions have units.

        Appends ' cm' to pure-numeric dimension attributes (height/width/length/depth).
        Operates in-place on `item['attributes']`.
        """
        attrs = item.get("attributes")
        if not isinstance(attrs, list):
            return

        # Patterns
        numeric_only = re.compile(r"^\s*\d+(?:[\.,]\d+)?\s*$")
        unit_marker = re.compile(r"\b(cm|mm|m|in|pouce|polegadas)\b", re.IGNORECASE)

        for attr in attrs:
            try:
                name = str(attr.get("name", "")).lower()
            except Exception:
                name = ""

            # Normalize dimension-like attributes
            if name and any(k in name for k in ("height", "altura", "width", "largura", "length", "comprimento", "depth", "profundidade")):
                val = attr.get("value_name")
                if isinstance(val, (int, float)):
                    attr["value_name"] = f"{val} cm"
                elif isinstance(val, str):
                    if numeric_only.match(val) and not unit_marker.search(val):
                        # Convert comma decimals to dot (ML accepts dot) then append cm
                        normalized = val.strip().replace(",", ".")
                        attr["value_name"] = f"{normalized} cm"
