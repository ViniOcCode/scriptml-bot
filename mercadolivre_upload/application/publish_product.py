"""Publish product use case.

Orchestrates domain logic and adapters to publish products.
"""

import logging
import re
from typing import Any

from mercadolivre_upload.api.cbt_extractor import CbtIdExtractor
from mercadolivre_upload.application.builders.product_builder import ProductBuilder
from mercadolivre_upload.domain.cache_attribute_mapper import CachedAttributeMapper
from mercadolivre_upload.domain.category.resolver import CategoryResolver
from mercadolivre_upload.domain.fiscal.data import FiscalData
from mercadolivre_upload.domain.fiscal.service import FiscalService, FiscalSubmissionResult
from mercadolivre_upload.domain.product.model import Product
from mercadolivre_upload.domain.validation import ValidationFeedback
from mercadolivre_upload.shared.utils.text_utils import PortugueseTextNormalizer

from .attribute_builder import AttributeBuilderService
from .ports import ClipUploaderPort, ImageUploaderPort, ItemPublisherPort, ShippingResolverPort

logger = logging.getLogger(__name__)

DIMENSION_KEYWORDS = [
    "height",
    "altura",
    "width",
    "largura",
    "length",
    "comprimento",
    "depth",
    "profundidade",
]
WEIGHT_KEYWORDS = [
    "weight",
    "peso",
]
DIMENSION_NUMERIC_ONLY_PATTERN = r"^\s*\d+(?:[\.,]\d+)?\s*$"
DIMENSION_UNIT_MARKER_PATTERN = r"\b(cm|mm|m|in|pouce|polegadas|g|kg)\b"
DIMENSION_DEFAULT_UNIT = "cm"
WEIGHT_DEFAULT_UNIT = "kg"
PACKAGE_WEIGHT_DEFAULT_UNIT = "g"
DEFAULT_NA_SKIP_TAGS = {
    "required",
    "new_required",
    "conditional_required",
    "catalog_listing_required",
    "allow_variations",
}


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
        config: dict[str, Any] | None = None,
        dry_run: bool = False,
        min_attribute_score: int = 50,
        enable_feedback: bool = True,
        enable_fiscal_submission: bool = True,
        cache_dir: str | None = None,
        attribute_cache: Any | None = None,
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
            cache_dir: Directory containing category attribute cache files
                (deprecated, use attribute_cache)
            attribute_cache: AttributeCache instance for cached attribute mapping (optional)
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
        self.cache_dir = cache_dir  # Deprecated but kept for backward compatibility
        self.attribute_cache = attribute_cache

        self.published = 0
        self.failed = 0
        self.errors: list[str] = []
        self.fiscal_results: list[FiscalSubmissionResult] = []
        self.clip_results: list[dict[str, Any]] = []  # ClipUploadSummary dicts
        self.item_results: list[dict[str, Any]] = []

        # Initialize CBT ID extractor (attempt to find an API client to perform fallback GETs)
        api_client = None
        if hasattr(publisher, "get") and callable(publisher.get):
            # publisher is already an API client (e.g., MLApiClient)
            api_client = publisher
        elif hasattr(publisher, "client"):
            # publisher may be an adapter exposing an underlying client
            api_client = getattr(publisher, "client", None)
        self.cbt_extractor = CbtIdExtractor(api_client=api_client)  # type: ignore[arg-type]

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
        self._available_listing_types_cache: dict[str, list[str]] = {}
        self._category_sale_terms_cache: dict[str, dict[str, dict[str, Any]]] = {}

    def _reset_execution_state(self) -> None:
        """Reset per-run counters and artifacts."""
        self.published = 0
        self.failed = 0
        self.errors = []
        self.fiscal_results = []
        self.clip_results = []
        self.item_results = []
        self._pending_fiscal = []

    @staticmethod
    def _extract_item_identity(product: Product | dict[str, Any]) -> tuple[str | None, str | None]:
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

    @staticmethod
    def _extract_product_title(product: Product | dict[str, Any]) -> str | None:
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
                    if any(
                        key_lower.startswith(pattern) for pattern in ["título", "titulo", "title"]
                    ):
                        title = product[key]
                        break
        else:
            title = getattr(product, "title", None)

        if not isinstance(title, str):
            return None
        title_str = title.strip()
        return title_str or None

    def execute(
        self, products: list[Product | dict[str, Any]], category_name: str
    ) -> dict[str, Any]:
        """Execute publishing use case.

        Args:
            products: List of products to publish
            category_name: Category name for all products

        Returns:
            Execution results
        """
        self._reset_execution_state()

        category_input = str(category_name).strip()
        category_id = None

        # Strategy 0: Accept direct category IDs (e.g. MLB1234)
        if re.fullmatch(r"[A-Z]{3}\d+", category_input):
            category_id = category_input
        else:
            # Strategy 1: Find category by name (fast root match)
            category_id = self.category_resolver.find_category(category_input)

        # Strategy 2: Use domain discovery with product titles
        if not category_id and products:
            logger.info(
                "Category not found by name, trying domain discovery with product titles..."
            )

            # Extract titles from products
            titles = []
            for product in products:
                title = self._extract_product_title(product)
                if title:
                    titles.append(title)

            if titles:
                logger.info(f"Extracted {len(titles)} titles for prediction")
                category_id = self.category_resolver.find_category_with_predictor(
                    category_input, titles
                )

        # Strategy 3: Fallback to simple title prediction (for backwards compatibility)
        if not category_id and products:
            logger.info("Trying simple domain discovery fallback...")
            for product in products:
                title_str = self._extract_product_title(product)
                if title_str:
                    category_id = self.category_resolver.predict_category_from_title(title_str)
                    if category_id:
                        logger.info(f"Found category from title '{title_str[:30]}...'")
                        break

        if not category_id:
            error_msg = f"Category not found: {category_input}"
            logger.error(error_msg)
            item_results = []
            for index, product in enumerate(products):
                sku, title = self._extract_item_identity(product)
                item_results.append(
                    {
                        "index": index,
                        "sku": sku,
                        "title": title,
                        "status": "failed",
                        "error": error_msg,
                    }
                )
            return {
                "success": False,
                "published": 0,
                "failed": len(products),
                "errors": [error_msg],
                "item_results": item_results,
            }

        # Ensure we have a leaf category (no children)
        leaf_category_id = self.category_resolver.resolve_to_leaf(category_id)
        if leaf_category_id != category_id:
            logger.info(f"Resolved to leaf category: {leaf_category_id}")
            category_id = leaf_category_id

        is_listing_allowed = getattr(self.category_resolver, "is_listing_allowed", None)
        if callable(is_listing_allowed) and not is_listing_allowed(category_id):
            error_msg = f"Category not available for listing: {category_id}"
            logger.error(error_msg)
            item_results = []
            for index, product in enumerate(products):
                sku, title = self._extract_item_identity(product)
                item_results.append(
                    {
                        "index": index,
                        "sku": sku,
                        "title": title,
                        "status": "failed",
                        "error": error_msg,
                    }
                )
            return {
                "success": False,
                "published": 0,
                "failed": len(products),
                "errors": [error_msg],
                "item_results": item_results,
            }

        logger.info(f"Publishing {len(products)} products to category {category_id}")

        # Initialize cache mapper for this category
        self._initialize_cache_mapper(category_id)

        for index, product in enumerate(products):
            if isinstance(product, dict):
                source_sku, source_title = self._extract_item_identity(product)
                try:
                    product = self._build_product_from_dict(product)
                except Exception as exc:
                    logger.error(f"Failed to build product from row: {exc}")
                    error_message = str(exc)
                    self.errors.append(error_message)
                    self.failed += 1
                    self.item_results.append(
                        {
                            "index": index,
                            "sku": source_sku,
                            "title": source_title,
                            "status": "failed",
                            "error": error_message,
                        }
                    )
                    continue
            previous_error_count = len(self.errors)
            success = self._publish_one(product, category_id)
            item_result: dict[str, Any] = {
                "index": index,
                "sku": product.sku,
                "title": product.title,
                "status": "success" if success else "failed",
            }
            new_errors = self.errors[previous_error_count:]
            if new_errors:
                item_result["error"] = "; ".join(new_errors)
            elif not success:
                item_result["error"] = f"{product.sku}: publish failed"
            self.item_results.append(item_result)

        # Batch submit fiscal information for all published products
        if not self.dry_run and self._pending_fiscal:
            self._submit_fiscal_batch(self._pending_fiscal)

        # Calculate clip stats
        clip_success = sum(r.get("clips_uploaded", 0) for r in self.clip_results)
        clip_failed = sum(r.get("clips_failed", 0) for r in self.clip_results)

        return {
            "success": self.failed == 0,
            "published": self.published,
            "failed": self.failed,
            "errors": self.errors,
            "fiscal_submitted": len([r for r in self.fiscal_results if r.success]),
            "fiscal_failed": len([r for r in self.fiscal_results if not r.success]),
            "clips_uploaded": clip_success,
            "clips_failed": clip_failed,
            "clips_details": self.clip_results,
            "item_results": self.item_results,
        }

    def _build_product_from_dict(self, data: dict[str, Any]) -> Product:
        def find_key(candidates: list[str], exclude: list[str] | None = None) -> str | None:
            for key in data:
                normalized = PortugueseTextNormalizer.normalize(str(key))
                if exclude and any(ex in normalized for ex in exclude):
                    continue
                if any(candidate in normalized for candidate in candidates):
                    return str(key)
            return None

        builder = ProductBuilder()

        title_key = find_key(["titulo", "title", "nome"], exclude=["livro", "item", "peca"])
        price_key = find_key(["preco", "price", "valor"])
        qty_key = find_key(["estoque", "quantidade", "stock"], exclude=["caracter"])
        condition_key = find_key(["condicao", "condition", "estado", "situacao"])
        sku_key = find_key(["sku", "codigo", "code"])
        description_key = find_key(["descricao", "description", "detalhes"])

        if not title_key or not price_key or not qty_key or not condition_key or not sku_key:
            missing = [
                name
                for name, key in [
                    ("titulo", title_key),
                    ("preco", price_key),
                    ("quantidade", qty_key),
                    ("condicao", condition_key),
                    ("sku", sku_key),
                ]
                if key is None
            ]
            raise ValueError(f"Campos obrigatórios faltando: {', '.join(missing)}")

        title = builder._normalize_text(str(data.get(title_key, "")))
        description_raw = str(data.get(description_key, "") or "")  # type: ignore[arg-type]
        description = builder._normalize_description(description_raw) if description_raw else ""

        price = builder._parse_price(data.get(price_key))
        quantity = builder._parse_quantity(data.get(qty_key))

        condition_value = str(data.get(condition_key, "")).lower().strip()
        if any(token in condition_value for token in ["novo", "new", "0"]):
            condition = "new"
        elif any(token in condition_value for token in ["usado", "used", "1"]):
            condition = "used"
        else:
            raise ValueError(f"Condição inválida: {condition_value}")

        # Resolve fiscal field keys using find_key (config-driven patterns)
        ncm_key = find_key(["ncm"])
        origin_type_key = find_key(["tipo de origem", "tipo origem", "origin type"])
        origin_detail_key = find_key(["origem"], exclude=["tipo"])
        cest_key = find_key(["cest"])
        cfop_key = find_key(["cfop"])
        ean_key = find_key(["ean", "gtin"])
        csosn_key = find_key(["csosn"])
        net_weight_key = find_key(["peso liquido", "net weight"])
        gross_weight_key = find_key(["peso bruto", "gross weight"])

        fiscal = FiscalData(
            sku=str(data.get(sku_key) or "").strip(),
            title=title,
            cost=float(price or 0.0),
            ncm=str(data.get(ncm_key, "") if ncm_key else "").strip(),
            origin_type=str(data.get(origin_type_key, "") if origin_type_key else "").strip(),
            origin_detail=str(data.get(origin_detail_key, "") if origin_detail_key else "").strip(),
            cest=str(data.get(cest_key, "") if cest_key else "").strip() or None,
            cfop=str(data.get(cfop_key, "") if cfop_key else "").strip() or None,
            ean=str(data.get(ean_key, "") if ean_key else "").strip() or None,
            csosn=str(data.get(csosn_key, "") if csosn_key else "").strip() or None,
            net_weight=data.get(net_weight_key) if net_weight_key else None,
            gross_weight=data.get(gross_weight_key) if gross_weight_key else None,
        )

        excluded_keys = {title_key, price_key, qty_key, condition_key, sku_key, description_key}
        attributes = {k: v for k, v in data.items() if k not in excluded_keys}

        return Product(
            sku=str(data.get(sku_key) or "").strip(),
            title=title,
            description=description,
            price=float(price),
            available_quantity=int(quantity),
            condition=condition,
            fiscal=fiscal,
            attributes=attributes,
        )

    def _initialize_cache_mapper(self, category_id: str) -> None:
        """Initialize cache mapper for the given category.

        Args:
            category_id: ML category ID
        """
        # Skip if already initialized for this category
        if self._current_category_id == category_id and self._cache_mapper is not None:
            return

        # Skip if no attribute cache configured
        if not self.attribute_cache:
            logger.debug("No attribute_cache configured, skipping cache mapper initialization")
            return

        try:
            self._cache_mapper = CachedAttributeMapper(self.attribute_cache, category_id)
            self._current_category_id = category_id
            logger.info(f"Cache mapper initialized successfully for category {category_id}")

            # Pass to attribute builder for use
            self._attribute_builder.set_cache_mapper(self._cache_mapper)
        except ValueError as e:
            logger.warning(
                f"No cached attributes for category {category_id}: {e}. "
                f"Will use fuzzy mapper instead."
            )
            self._cache_mapper = None
            self._current_category_id = None
            self._attribute_builder.set_cache_mapper(None)
        except Exception as e:
            logger.error(f"Failed to initialize cache mapper for category {category_id}: {e}")
            self._cache_mapper = None
            self._current_category_id = None
            self._attribute_builder.set_cache_mapper(None)

    def _publish_one(self, product: Product, category_id: str) -> bool:
        """Publish a single product."""
        logger.info(f"Publishing product: {product.sku} (title: {product.title[:50]}...)")

        # Build attributes using attribute builder service
        (
            ml_attributes,
            sale_terms_from_mapping,
            attr_warnings,
            attr_errors,
        ) = self._attribute_builder.build_attributes(
            product,
            category_id,
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
        core_defaults = self.config.get("core_item_fields", {}).get("defaults", {})

        # Check if listing_type_id was explicitly mapped from spreadsheet
        explicit_listing_type: str | None = None
        for attr in ml_attributes:
            if "_listing_type_id" in attr:
                mapped_listing_type = attr.pop("_listing_type_id")
                if isinstance(mapped_listing_type, str) and mapped_listing_type:
                    explicit_listing_type = mapped_listing_type
                break

        available_listing_types = self._get_available_listing_type_ids(category_id)
        listing_type_id = self._resolve_listing_type_id(
            category_id=category_id,
            explicit_listing_type=explicit_listing_type,
            default_listing_type=core_defaults.get("listing_type_id"),
            has_pictures=bool(pictures),
            available_listing_types=available_listing_types,
        )

        default_sale_terms = core_defaults.get("sale_terms", [])
        if not isinstance(default_sale_terms, list):
            default_sale_terms = []

        sale_terms = self._resolve_sale_terms(
            category_id=category_id,
            sale_terms_from_mapping=sale_terms_from_mapping,
            default_sale_terms=default_sale_terms,
        )

        item_condition_config = core_defaults.get("item_condition", {})
        if isinstance(item_condition_config, dict):
            item_condition_id = item_condition_config.get("id")
            item_condition_values = item_condition_config.get("values", {})
            condition_payload = (
                item_condition_values.get(product.condition)
                if isinstance(item_condition_values, dict)
                else None
            )
            if item_condition_id and isinstance(condition_payload, dict):
                existing_ids = {
                    attr.get("id")
                    for attr in ml_attributes
                    if isinstance(attr, dict) and attr.get("id")
                }
                if item_condition_id not in existing_ids:
                    item_condition_attr = {"id": item_condition_id}
                    value_id = condition_payload.get("value_id")
                    value_name = condition_payload.get("value_name")
                    if value_id is not None:
                        item_condition_attr["value_id"] = value_id
                    if value_name is not None:
                        item_condition_attr["value_name"] = value_name
                    if len(item_condition_attr) > 1:
                        ml_attributes.append(item_condition_attr)

        # Build item with values from config only (no hardcoded fallbacks)
        item = {
            "title": product.title,
            "category_id": category_id,
            "price": product.price,
            "currency_id": core_defaults.get("currency_id"),
            "available_quantity": product.available_quantity,
            "buying_mode": core_defaults.get("buying_mode"),
            "condition": product.condition,
            "listing_type_id": listing_type_id,
            "pictures": pictures if pictures else [],
            "attributes": ml_attributes,
            "shipping": shipping_config,
            "sale_terms": sale_terms,
            "seller_custom_field": product.sku,
        }

        channels = core_defaults.get("channels")
        if channels:
            item["channels"] = channels

        # Log shipping section before validation
        logger.info(
            f"Final shipping config for {product.sku}: mode={shipping_config.get('mode')}, "
            f"free_shipping={shipping_config.get('free_shipping')}, "
            f"logistic_type={shipping_config.get('logistic_type')}, "
            f"local_pick_up={shipping_config.get('local_pick_up')}"
        )

        if self.dry_run:
            logger.info(f"DRY RUN: Would publish {product.sku}")
            self.published += 1
            return True

        # Normalize attributes before validation/publish (ensure units)
        self._normalize_item_attributes(item)

        conditional_required_ids = self._inject_optional_na_attributes(
            category_id=category_id,
            item=item,
            sku=product.sku,
            description=product.description,
        )

        missing_conditional_attributes = self._get_missing_conditional_attributes(
            category_id=category_id,
            item=item,
            description=product.description,
            conditional_required_ids=conditional_required_ids,
        )
        if missing_conditional_attributes:
            message = f"Missing conditional attributes: {', '.join(missing_conditional_attributes)}"
            logger.error(f"{product.sku}: {message}")
            self.errors.append(f"{product.sku}: {message}")
            self.failed += 1
            return False

        logger.debug(f"Full item payload for {product.sku}: {item}")

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
                if (
                    "shipping" in str(cause_code).lower()
                    or "shipping" in str(cause_message).lower()
                ):
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
                    self.feedback.record_validation_result(product.sku, ml_attributes, validation)
                return False
        except Exception as e:
            # Try to extract error details from exception
            error_msg = str(e)
            error_detail = None
            if hasattr(e, "response") and e.response is not None:
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
        cbt_item_id: str | None = None
        try:
            result = self.publisher.create_item(item)
            published_item_id = result.get("id")

            # Extract CBT parent item ID using robust extraction strategy
            cbt_item_id = self.cbt_extractor.extract_cbt_id(result)

            logger.info(f"Published {product.sku}: {published_item_id}")
            if cbt_item_id and cbt_item_id != published_item_id:
                logger.debug(f"CBT parent item ID for {product.sku}: {cbt_item_id}")

            description_text = product.description.strip()
            if published_item_id and description_text:
                self._publish_item_description(
                    item_id=published_item_id,
                    description=description_text,
                    sku=product.sku,
                )

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

            # Upload clips if available (soft failure - does not fail the product publish)
            # Note: Clips must be uploaded to CBT parent item ID, not marketplace-specific IDs
            if self.clip_uploader and cbt_item_id:
                sku = product.sku or ""
                if sku:
                    logger.info(f"Uploading clips for {sku} (CBT item: {cbt_item_id})")
                    clip_summary = self.clip_uploader.upload_clips(
                        sku=sku,
                        item_id=cbt_item_id,
                    )
                    self.clip_results.append(
                        {
                            "sku": sku,
                            "item_id": cbt_item_id,
                            "clips_uploaded": clip_summary.clips_uploaded,
                            "clips_failed": clip_summary.clips_failed,
                            "clips_skipped": clip_summary.clips_skipped,
                            "results": [
                                {
                                    "file": r.file,
                                    "clip_uuid": r.clip_uuid,
                                    "status": r.status,
                                    "error": r.error,
                                }
                                for r in clip_summary.results
                            ],
                        }
                    )
                    if clip_summary.clips_uploaded > 0:
                        logger.info(
                            f"Clips uploaded for {sku}: {clip_summary.clips_uploaded} success"
                        )
                    if clip_summary.clips_failed > 0:
                        logger.warning(
                            f"Clip upload failures for {sku}: {clip_summary.clips_failed} failed "
                            f"(item will still be published)"
                        )

            return True
        except Exception as e:
            error_msg = str(e)
            if hasattr(e, "response") and e.response is not None:
                try:
                    error_detail = e.response.json()
                    error_msg = f"{error_msg} - {error_detail}"
                    # Check for shipping-specific errors
                    causes = error_detail.get("cause", []) if isinstance(error_detail, dict) else []
                    # Record publish failure feedback
                    if self.feedback:
                        self.feedback.record_validation_result(
                            product.sku,
                            ml_attributes,
                            error_detail if isinstance(error_detail, dict) else {},
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

    def get_stats(self) -> dict[str, Any]:
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
            clip_success = sum(r.get("clips_uploaded", 0) for r in self.clip_results)
            clip_failed = sum(r.get("clips_failed", 0) for r in self.clip_results)
            stats["clips"] = {
                "attempted": len(self.clip_results),
                "success": clip_success,
                "failed": clip_failed,
                "details": self.clip_results,
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

    def _get_available_listing_type_ids(self, category_id: str) -> list[str]:
        """Fetch available listing types for current seller and category."""
        cached = self._available_listing_types_cache.get(category_id)
        if cached is not None:
            return cached

        getter = getattr(self.publisher, "get_available_listing_types", None)
        if not callable(getter):
            return []

        try:
            listing_types = getter(category_id)
        except Exception as e:
            logger.warning(f"Could not fetch available listing types for {category_id}: {e}")
            return []

        listing_type_ids: list[str] = []
        if isinstance(listing_types, list):
            for listing_type in listing_types:
                if not isinstance(listing_type, dict):
                    continue
                listing_type_id = listing_type.get("id")
                if isinstance(listing_type_id, str) and listing_type_id:
                    listing_type_ids.append(listing_type_id)

        deduped_listing_type_ids = list(dict.fromkeys(listing_type_ids))
        self._available_listing_types_cache[category_id] = deduped_listing_type_ids
        return deduped_listing_type_ids

    def _resolve_listing_type_id(
        self,
        category_id: str,
        explicit_listing_type: str | None,
        default_listing_type: Any,
        has_pictures: bool,
        available_listing_types: list[str],
    ) -> str:
        """Resolve listing_type_id constrained by the category available listing types."""
        candidates: list[str] = []
        if explicit_listing_type:
            candidates.append(explicit_listing_type)

        if has_pictures and isinstance(default_listing_type, str) and default_listing_type:
            candidates.append(default_listing_type)
        if not has_pictures:
            candidates.append("free")
        if isinstance(default_listing_type, str) and default_listing_type:
            candidates.append(default_listing_type)

        candidates.extend(["gold_special", "free"])
        candidates = list(dict.fromkeys(candidates))

        if available_listing_types:
            if explicit_listing_type and explicit_listing_type not in available_listing_types:
                logger.warning(
                    "Explicit listing_type_id %s is not available for category %s. "
                    "Falling back to allowed listing type.",
                    explicit_listing_type,
                    category_id,
                )

            for candidate in candidates:
                if candidate in available_listing_types:
                    return candidate

            logger.warning(
                "No preferred listing_type_id is available for category %s. "
                "Using first allowed: %s",
                category_id,
                available_listing_types[0],
            )
            return available_listing_types[0]

        return candidates[0] if candidates else "free"

    def _get_category_sale_terms_map(self, category_id: str) -> dict[str, dict[str, Any]]:
        """Fetch category sale terms and cache by id."""
        cached = self._category_sale_terms_cache.get(category_id)
        if cached is not None:
            return cached

        getter = getattr(self.publisher, "get_category_sale_terms", None)
        if not callable(getter):
            return {}

        try:
            sale_terms = getter(category_id)
        except Exception as e:
            logger.warning(f"Could not fetch category sale terms for {category_id}: {e}")
            return {}

        mapped_sale_terms: dict[str, dict[str, Any]] = {}
        if isinstance(sale_terms, list):
            for sale_term in sale_terms:
                if not isinstance(sale_term, dict):
                    continue
                sale_term_id = sale_term.get("id")
                if isinstance(sale_term_id, str) and sale_term_id:
                    mapped_sale_terms[sale_term_id] = sale_term

        self._category_sale_terms_cache[category_id] = mapped_sale_terms
        return mapped_sale_terms

    def _is_required_sale_term(self, sale_term: dict[str, Any]) -> bool:
        """Return whether a sale term metadata entry is required."""
        tags = sale_term.get("tags", {})
        if isinstance(tags, dict):
            return bool(tags.get("required") or tags.get("new_required"))
        if isinstance(tags, list):
            normalized_tags = {str(tag).lower() for tag in tags}
            return "required" in normalized_tags or "new_required" in normalized_tags
        return False

    def _resolve_sale_terms(
        self,
        category_id: str,
        sale_terms_from_mapping: list[dict[str, Any]],
        default_sale_terms: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Resolve sale terms constrained to category-allowed definitions."""
        candidate_sale_terms = sale_terms_from_mapping or default_sale_terms
        candidate_sale_terms = [
            sale_term
            for sale_term in candidate_sale_terms
            if isinstance(sale_term, dict) and isinstance(sale_term.get("id"), str)
        ]

        category_sale_terms = self._get_category_sale_terms_map(category_id)
        if not category_sale_terms:
            return candidate_sale_terms

        filtered_sale_terms: list[dict[str, Any]] = []
        dropped_sale_term_ids: list[str] = []
        for sale_term in candidate_sale_terms:
            sale_term_id = sale_term.get("id")
            if sale_term_id in category_sale_terms:
                filtered_sale_terms.append(sale_term)
            else:
                dropped_sale_term_ids.append(str(sale_term_id))

        if dropped_sale_term_ids:
            logger.warning(
                "Ignoring unsupported sale_terms for category %s: %s",
                category_id,
                dropped_sale_term_ids,
            )

        required_sale_term_ids = [
            sale_term_id
            for sale_term_id, sale_term_meta in category_sale_terms.items()
            if self._is_required_sale_term(sale_term_meta)
        ]
        if not required_sale_term_ids:
            return filtered_sale_terms

        default_by_id = {
            sale_term["id"]: sale_term
            for sale_term in default_sale_terms
            if isinstance(sale_term, dict) and isinstance(sale_term.get("id"), str)
        }
        existing_ids = {
            sale_term["id"]
            for sale_term in filtered_sale_terms
            if isinstance(sale_term.get("id"), str)
        }

        for required_sale_term_id in required_sale_term_ids:
            if required_sale_term_id in existing_ids:
                continue
            fallback_sale_term = default_by_id.get(required_sale_term_id)
            if fallback_sale_term:
                filtered_sale_terms.append(fallback_sale_term)
                existing_ids.add(required_sale_term_id)
            else:
                logger.warning(
                    "Required sale term %s is missing for category %s and "
                    "no default is configured.",
                    required_sale_term_id,
                    category_id,
                )

        return filtered_sale_terms

    def _get_missing_conditional_attributes(
        self,
        category_id: str,
        item: dict[str, Any],
        description: str,
        conditional_required_ids: set[str] | None = None,
    ) -> list[str]:
        """Validate conditional required attributes using full item context payload."""
        required_ids = conditional_required_ids
        if required_ids is None:
            required_ids = self._get_conditional_required_attribute_ids(
                category_id=category_id,
                item=item,
                description=description,
            )

        if not required_ids:
            return []

        existing_ids = {
            attr.get("id")
            for attr in item.get("attributes", [])
            if isinstance(attr, dict) and isinstance(attr.get("id"), str)
        }
        return sorted(attr_id for attr_id in required_ids if attr_id not in existing_ids)

    def _get_conditional_required_attribute_ids(
        self,
        category_id: str,
        item: dict[str, Any],
        description: str,
    ) -> set[str]:
        """Get conditional required attribute IDs for the current item context."""
        conditional_payload = dict(item)
        if description:
            conditional_payload["description"] = {"plain_text": description}

        try:
            conditional_attrs = self.category_resolver.get_conditional_attributes(
                category_id, conditional_payload
            )
        except Exception as e:
            logger.warning(f"Could not get conditional attributes for {category_id}: {e}")
            return set()

        if isinstance(conditional_attrs, dict):
            required_attributes = conditional_attrs.get("required_attributes", [])
            conditional_attrs = required_attributes if isinstance(required_attributes, list) else []

        if not isinstance(conditional_attrs, list):
            return set()

        return {
            attr_id
            for attr in conditional_attrs
            if isinstance(attr, dict)
            for attr_id in [attr.get("id")]
            if isinstance(attr_id, str) and attr_id
        }

    def _inject_optional_na_attributes(
        self,
        category_id: str,
        item: dict[str, Any],
        sku: str,
        description: str,
    ) -> set[str] | None:
        """Auto-fill missing optional attributes with N/A payload when enabled."""
        na_policy = self.config.get("na_policy")
        if not isinstance(na_policy, dict) or not na_policy.get("enabled", False):
            return None

        attrs = item.get("attributes")
        if not isinstance(attrs, list):
            return None

        value_id = str(na_policy.get("value_id", "-1"))
        value_name = na_policy.get("value_name")
        configured_skip_tags = na_policy.get("skip_tags", [])
        skip_tags = DEFAULT_NA_SKIP_TAGS.copy()
        if isinstance(configured_skip_tags, list):
            skip_tags = {
                str(tag).strip().lower() for tag in configured_skip_tags if str(tag).strip()
            } or skip_tags

        conditional_required_ids = self._get_conditional_required_attribute_ids(
            category_id=category_id,
            item=item,
            description=description,
        )

        try:
            metadata = self.category_resolver.get_attribute_metadata(category_id)
        except Exception as e:
            logger.warning(
                "Could not fetch attribute metadata for N/A policy in %s: %s",
                category_id,
                e,
            )
            return conditional_required_ids

        existing_ids = {
            attr.get("id")
            for attr in attrs
            if isinstance(attr, dict) and isinstance(attr.get("id"), str)
        }
        auto_filled_count = 0
        skipped: list[str] = []

        for meta in metadata:
            attr_id = getattr(meta, "id", None)
            if not isinstance(attr_id, str) or not attr_id or attr_id in existing_ids:
                continue

            tags = {
                str(tag).strip().lower() for tag in getattr(meta, "tags", set()) if str(tag).strip()
            }
            if bool(getattr(meta, "required", False)):
                tags.add("required")
            if attr_id in conditional_required_ids:
                tags.add("conditional_required")

            if tags.intersection(skip_tags):
                skipped.append(attr_id)
                continue

            attrs.append({"id": attr_id, "value_id": value_id, "value_name": value_name})
            existing_ids.add(attr_id)
            auto_filled_count += 1

        if auto_filled_count:
            logger.info(
                "Auto-filled N/A for %s optional attributes on %s",
                auto_filled_count,
                sku,
            )
            conditional_required_ids = self._get_conditional_required_attribute_ids(
                category_id=category_id,
                item=item,
                description=description,
            )

        if skipped:
            logger.warning(
                "Skipped N/A auto-fill for %s attributes on %s due non-eligible tags",
                len(skipped),
                sku,
            )

        return conditional_required_ids

    def _publish_item_description(self, item_id: str, description: str, sku: str) -> None:
        """Publish description using the dedicated description endpoint."""
        setter = getattr(self.publisher, "create_item_description", None)
        if not callable(setter):
            logger.warning("Publisher does not support description endpoint for %s", sku)
            return

        try:
            setter(item_id, description)
            logger.info(f"Description published for {sku} ({item_id})")
        except Exception as e:
            logger.warning(f"Could not publish description for {sku} ({item_id}): {e}")

    def _build_shipping_config(self) -> dict[str, Any]:
        """Build shipping configuration from config.

        Uses shipping configuration from config file as the single source of truth.
        Builds complete shipping payload matching ML API format:
        {
            "mode": "me2",
            "methods": [],
            "tags": [],
            "dimensions": null,
            "local_pick_up": false,
            "free_shipping": false,
            "logistic_type": "drop_off",
            "store_pick_up": false
        }

        Returns:
            Shipping configuration dictionary
        """
        shipping_config = self.config.get("shipping", {})
        default_mode = shipping_config.get("default_mode", "not_specified")
        modes_config = shipping_config.get("modes", {})

        # Determine shipping mode
        shipping_mode = default_mode
        if self.shipping_resolver:
            shipping_mode = self.shipping_resolver.get_best_shipping_mode()
            logger.info(f"Using shipping mode: {shipping_mode}")

        # Get mode-specific config
        mode_config = modes_config.get(shipping_mode, {})

        # Build complete shipping config matching ML API format
        config_shipping: dict[str, any] = {  # type: ignore[valid-type]
            "mode": shipping_mode,
            "methods": mode_config.get("methods", []),
            "tags": mode_config.get("tags", []),
            "dimensions": mode_config.get("dimensions"),
            "local_pick_up": mode_config.get("local_pick_up", False),
            "free_shipping": mode_config.get("free_shipping", False),
            "logistic_type": mode_config.get("logistic_type"),
            "store_pick_up": mode_config.get("store_pick_up", False),
        }

        # Remove None values to keep payload clean
        config_shipping = {k: v for k, v in config_shipping.items() if v is not None}

        logger.info(f"Shipping config for {shipping_mode} mode: {config_shipping}")
        return config_shipping

    def _normalize_item_attributes(self, item: dict[str, Any]) -> None:
        """Ensure numeric dimensions have units.

        Appends default unit to pure-numeric dimension attributes.
        Uses dimension patterns from config.
        Operates in-place on `item['attributes']`.
        """
        attrs = item.get("attributes")
        if not isinstance(attrs, list):
            return

        # Get dimension patterns from config
        dim_config = self.config.get("dimension_patterns") or {}
        keywords = dim_config.get("keywords", DIMENSION_KEYWORDS)
        weight_keywords = dim_config.get("weight_keywords", WEIGHT_KEYWORDS)
        default_unit = dim_config.get("default_unit", DIMENSION_DEFAULT_UNIT)
        weight_default_unit = dim_config.get("weight_default_unit", WEIGHT_DEFAULT_UNIT)
        package_weight_default_unit = dim_config.get(
            "package_weight_default_unit", PACKAGE_WEIGHT_DEFAULT_UNIT
        )
        numeric_pattern = dim_config.get("numeric_only", DIMENSION_NUMERIC_ONLY_PATTERN)
        unit_pattern = dim_config.get("unit_marker", DIMENSION_UNIT_MARKER_PATTERN)

        # Compile patterns
        numeric_only = re.compile(numeric_pattern)
        unit_marker = re.compile(unit_pattern, re.IGNORECASE)

        for attr in attrs:
            if not isinstance(attr, dict):
                logger.debug("Skipping non-dict attribute during normalization: %r", attr)
                continue

            name_raw = attr.get("name")
            attr_id_raw = attr.get("id")
            name = str(name_raw).lower() if name_raw is not None else ""
            attr_id = str(attr_id_raw).upper() if attr_id_raw is not None else ""

            source_text = f"{name} {attr_id.lower()}".strip()
            is_weight = (
                any(keyword in source_text for keyword in weight_keywords)
                or attr_id == "WEIGHT"
                or attr_id == "SELLER_PACKAGE_WEIGHT"
            )
            is_dimension = (
                any(keyword in source_text for keyword in keywords)
                or attr_id in {"WIDTH", "HEIGHT", "LENGTH", "DEPTH"}
                or attr_id
                in {"SELLER_PACKAGE_WIDTH", "SELLER_PACKAGE_HEIGHT", "SELLER_PACKAGE_LENGTH"}
            )

            if not (is_weight or is_dimension):
                continue

            target_unit = default_unit
            if is_weight:
                target_unit = (
                    package_weight_default_unit
                    if attr_id == "SELLER_PACKAGE_WEIGHT"
                    else weight_default_unit
                )

            # Normalize dimension-like attributes using config keywords
            val = attr.get("value_name")
            if isinstance(val, (int, float)):
                attr["value_name"] = f"{val} {target_unit}"
            elif isinstance(val, str) and numeric_only.match(val) and not unit_marker.search(val):
                # Convert comma decimals to dot (ML accepts dot) then append default unit
                normalized = val.strip().replace(",", ".")
                attr["value_name"] = f"{normalized} {target_unit}"

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
