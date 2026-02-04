"""Publish product use case.

Orchestrates domain logic and adapters to publish products.
"""

import logging
import re
from typing import Any

from mercadolivre_upload.domain.cache_attribute_mapper import CachedAttributeMapper
from mercadolivre_upload.domain.category.resolver import CategoryResolver
from mercadolivre_upload.domain.fiscal.data import FiscalData
from mercadolivre_upload.domain.fiscal.service import FiscalService, FiscalSubmissionResult
from mercadolivre_upload.domain.product.model import Product
from mercadolivre_upload.domain.validation import ValidationFeedback

from .attribute_builder import AttributeBuilderService
from .ports import ClipUploaderPort, ImageUploaderPort, ItemPublisherPort, ShippingResolverPort

logger = logging.getLogger(__name__)


class PublishProductUseCase:
    """Use case for publishing products to ML."""

    def __init__(
        self,
        category_resolver: CategoryResolver,
        publisher: ItemPublisherPort,
        image_uploader: ImageUploaderPort,
        shipping_resolver: ShippingResolverPort | None = None,
        fiscal_service: FiscalService | None = None,
        clip_uploader: ClipUploaderPort | None = None,
        config: dict | None = None,
        dry_run: bool = False,
        min_attribute_score: int = 50,
        enable_feedback: bool = True,
        enable_fiscal_submission: bool = True,
        cache_dir: str | None = None,
    ):
        """Initialize use case.

        Args:
            category_resolver: Category resolution service
            publisher: Item publisher (API adapter)
            image_uploader: Image uploader service
            shipping_resolver: Shipping mode resolver (optional)
            fiscal_service: Fiscal data submission service (optional)
            clip_uploader: Video clip uploader service (optional)
            config: Configuration dictionary with defaults (optional)
            dry_run: If True, only validate
            min_attribute_score: Minimum score for attributes (0-100)
            enable_feedback: Enable validation feedback tracking
            enable_fiscal_submission: Whether to submit fiscal data after publishing
            cache_dir: Directory containing category attribute cache files (optional)
        """
        self.category_resolver = category_resolver
        self.publisher = publisher
        self.image_uploader = image_uploader
        self.shipping_resolver = shipping_resolver
        self.fiscal_service = fiscal_service
        self.clip_uploader = clip_uploader
        self.config = config or {}
        self.dry_run = dry_run
        self.enable_fiscal_submission = enable_fiscal_submission
        self.cache_dir = cache_dir

        self.published = 0
        self.failed = 0
        self.errors: list[str] = []
        self.fiscal_results: list[FiscalSubmissionResult] = []
        self.clip_results: list[tuple[str, str | None]] = []  # (item_id, clip_uuid or None)

        # Initialize feedback system
        self.feedback = ValidationFeedback() if enable_feedback else None

        # Initialize attribute builder service
        self._attribute_builder = AttributeBuilderService(
            category_resolver=category_resolver,
            config=self.config,
            min_attribute_score=min_attribute_score,
            feedback=self.feedback,
        )

        # Cache mapper instance (initialized per category)
        self._cache_mapper: CachedAttributeMapper | None = None
        self._current_category_id: str | None = None

        # Pending fiscal data for batch submission
        self._pending_fiscal: list[tuple[str, FiscalData]] = []

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
            logger.info("Category not found by name, trying domain discovery...")
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

        # Initialize cache mapper for this category
        self._initialize_cache_mapper(category_id)

        for product in products:
            self._publish_one(product, category_id)

        # Batch submit fiscal information for all published products
        if not self.dry_run and self._pending_fiscal:
            self._submit_fiscal_batch(self._pending_fiscal)

        # Calculate clip stats
        clip_success = sum(1 for _, uuid in self.clip_results if uuid) if self.clip_results else 0
        clip_failed = len(self.clip_results) - clip_success if self.clip_results else 0

        return {
            "success": self.failed == 0,
            "published": self.published,
            "failed": self.failed,
            "errors": self.errors,
            "fiscal_submitted": len([r for r in self.fiscal_results if r.success]),
            "fiscal_failed": len([r for r in self.fiscal_results if not r.success]),
            "clips_uploaded": clip_success,
            "clips_failed": clip_failed,
        }

    def _initialize_cache_mapper(self, category_id: str) -> None:
        """Initialize cache mapper for the given category.
        
        Args:
            category_id: ML category ID
        """
        # Skip if already initialized for this category
        if self._current_category_id == category_id and self._cache_mapper is not None:
            return

        # Skip if no cache directory configured
        if not self.cache_dir:
            logger.debug("No cache_dir configured, skipping cache mapper initialization")
            return

        try:
            self._cache_mapper = CachedAttributeMapper(self.cache_dir, category_id)
            self._current_category_id = category_id
            logger.info(f"Cache loaded successfully for category {category_id}")
        except FileNotFoundError:
            logger.warning(
                f"Cache file not found for category {category_id}. "
                f"Falling back to fuzzy mapper."
            )
            self._cache_mapper = None
            self._current_category_id = None
        except Exception as e:
            logger.error(f"Failed to load cache for category {category_id}: {e}")
            self._cache_mapper = None
            self._current_category_id = None

    def _publish_one(self, product: Product, category_id: str) -> bool:
        """Publish a single product."""
        logger.info(f"Publishing product: {product.sku} (title: {product.title[:50]}...)")

        # Build attributes using attribute builder service
        ml_attributes, sale_terms_from_mapping, attr_warnings, attr_errors = self._attribute_builder.build_attributes(
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

        # Determine shipping mode from config
        shipping_config = self._build_shipping_config()

        logger.debug(f"Shipping config for {product.sku}: {shipping_config}")

        # Load defaults from config (config is the single source of truth)
        core_defaults = self.config.get('core_item_fields', {}).get('defaults', {})

        # Build sale_terms: use explicit mappings if available, otherwise use config defaults
        if sale_terms_from_mapping:
            sale_terms = sale_terms_from_mapping
            logger.info(f"Using sale_terms from explicit column mappings: {[st['id'] for st in sale_terms]}")
        else:
            # Use config defaults only - no hardcoded fallbacks
            sale_terms = core_defaults.get('sale_terms', [])
            logger.info("Using default sale_terms from config")

        # Check if listing_type_id was explicitly mapped from spreadsheet
        explicit_listing_type = None
        for attr in ml_attributes:
            if "_listing_type_id" in attr:
                explicit_listing_type = attr.pop("_listing_type_id")
                break

        # Determine listing_type_id: explicit > has_pictures_default > free
        if explicit_listing_type:
            listing_type_id = explicit_listing_type
        elif pictures:
            listing_type_id = core_defaults.get('listing_type_id')
        else:
            listing_type_id = "free"

        # Build item with values from config only (no hardcoded fallbacks)
        item = {
            "title": product.title,
            "category_id": category_id,
            "price": product.price,
            "currency_id": core_defaults.get('currency_id'),
            "available_quantity": product.available_quantity,
            "buying_mode": core_defaults.get('buying_mode'),
            "condition": product.condition,
            "listing_type_id": listing_type_id,
            "description": {"plain_text": product.description},
            "pictures": pictures if pictures else [],
            "attributes": ml_attributes,
            "shipping": shipping_config,
            "sale_terms": sale_terms,
            "seller_custom_field": product.sku,
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

            # Queue fiscal data for batch submission if available
            if (
                self.enable_fiscal_submission
                and self.fiscal_service
                and published_item_id
                and product.fiscal
                and product.fiscal.is_valid
            ):
                logger.info(f"Queueing fiscal data for {product.sku} (item: {published_item_id})")
                self._pending_fiscal.append((published_item_id, product.fiscal))

            # Upload clip if available (soft failure - does not fail the product publish)
            if (
                self.clip_uploader
                and published_item_id
                and product.clip_file_path
            ):
                logger.info(f"Uploading clip for {product.sku} (item: {published_item_id})")
                clip_uuid = self.clip_uploader.upload_clip_for_item(
                    item_id=published_item_id,
                    video_path=product.clip_file_path,
                )
                self.clip_results.append((published_item_id, clip_uuid))
                if clip_uuid:
                    product.clip_uuid = clip_uuid
                    logger.info(f"Clip uploaded for {product.sku}: {clip_uuid}")
                else:
                    logger.warning(f"Clip upload failed for {product.sku} (item will still be published)")

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

        # Add clip upload results
        if self.clip_results:
            clip_success = sum(1 for _, uuid in self.clip_results if uuid)
            clip_failed = len(self.clip_results) - clip_success
            stats["clips"] = {
                "attempted": len(self.clip_results),
                "success": clip_success,
                "failed": clip_failed,
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

    def _build_shipping_config(self) -> dict:
        """Build shipping configuration from config.
        
        Uses shipping configuration from config file as the single source of truth.
        Builds complete shipping payload matching ML API format:
        {
            "mode": "me2",
            "methods": [],
            "tags": ["mandatory_free_shipping"],
            "dimensions": null,
            "local_pick_up": false,
            "free_shipping": true,
            "logistic_type": "drop_off",
            "store_pick_up": false
        }
        
        Returns:
            Shipping configuration dictionary
        """
        shipping_config = self.config.get('shipping', {})
        default_mode = shipping_config.get('default_mode', 'not_specified')
        modes_config = shipping_config.get('modes', {})

        # Determine shipping mode
        shipping_mode = default_mode
        if self.shipping_resolver:
            shipping_mode = self.shipping_resolver.get_best_shipping_mode()
            logger.info(f"Using shipping mode: {shipping_mode}")

        # Get mode-specific config
        mode_config = modes_config.get(shipping_mode, {})

        # Build complete shipping config matching ML API format
        config_shipping: dict[str, any] = {
            "mode": shipping_mode,
            "methods": mode_config.get('methods', []),
            "tags": mode_config.get('tags', []),
            "dimensions": mode_config.get('dimensions'),
            "local_pick_up": mode_config.get('local_pick_up', False),
            "free_shipping": mode_config.get('free_shipping', False),
            "logistic_type": mode_config.get('logistic_type'),
            "store_pick_up": mode_config.get('store_pick_up', False),
        }

        # Remove None values to keep payload clean
        config_shipping = {k: v for k, v in config_shipping.items() if v is not None}

        logger.info(f"Shipping config for {shipping_mode} mode: {config_shipping}")
        return config_shipping

    def _normalize_item_attributes(self, item: dict) -> None:
        """Ensure numeric dimensions have units.

        Appends default unit to pure-numeric dimension attributes.
        Uses dimension patterns from config.
        Operates in-place on `item['attributes']`.
        """
        attrs = item.get("attributes")
        if not isinstance(attrs, list):
            return

        # Get dimension patterns from config
        dim_config = self.config.get('dimension_patterns', {})
        keywords = dim_config.get('keywords', ["height", "altura", "width", "largura", "length", "comprimento", "depth", "profundidade"])
        default_unit = dim_config.get('default_unit', 'cm')
        numeric_pattern = dim_config.get('numeric_only', r'^\s*\d+(?:[\.,]\d+)?\s*$')
        unit_pattern = dim_config.get('unit_marker', r'\b(cm|mm|m|in|pouce|polegadas)\b')

        # Compile patterns
        numeric_only = re.compile(numeric_pattern)
        unit_marker = re.compile(unit_pattern, re.IGNORECASE)

        for attr in attrs:
            try:
                name = str(attr.get("name", "")).lower()
            except Exception:
                name = ""

            # Normalize dimension-like attributes using config keywords
            if name and any(k in name for k in keywords):
                val = attr.get("value_name")
                if isinstance(val, (int, float)):
                    attr["value_name"] = f"{val} {default_unit}"
                elif isinstance(val, str):
                    if numeric_only.match(val) and not unit_marker.search(val):
                        # Convert comma decimals to dot (ML accepts dot) then append default unit
                        normalized = val.strip().replace(",", ".")
                        attr["value_name"] = f"{normalized} {default_unit}"

    def _submit_fiscal_batch(self, pending_fiscal: list[tuple[str, FiscalData]]) -> None:
        """Submit fiscal data for multiple items using the fiscal service.

        Args:
            pending_fiscal: List of (item_id, fiscal_data) tuples
        """
        if not self.fiscal_service:
            logger.warning("No fiscal service configured, skipping fiscal batch submission")
            return

        logger.info(f"Submitting fiscal data for {len(pending_fiscal)} items")
        results = self.fiscal_service.submit_fiscal_data_batch(pending_fiscal)
        self.fiscal_results.extend(results)

        success_count = sum(1 for r in results if r.success)
        failed_count = len(results) - success_count

        if success_count:
            logger.info(f"Successfully submitted fiscal data for {success_count} items")
        if failed_count:
            logger.warning(f"Failed to submit fiscal data for {failed_count} items")
