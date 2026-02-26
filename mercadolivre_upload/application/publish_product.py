"""Publish product use case.

Orchestrates domain logic and adapters to publish products.
"""

import logging
from typing import Any

from mercadolivre_upload.api.cbt_extractor import CbtIdExtractor
from mercadolivre_upload.domain.cache_attribute_mapper import CachedAttributeMapper
from mercadolivre_upload.domain.category.resolver import CategoryResolver
from mercadolivre_upload.domain.fiscal.data import FiscalData
from mercadolivre_upload.domain.fiscal.service import FiscalService, FiscalSubmissionResult
from mercadolivre_upload.domain.product.model import Product
from mercadolivre_upload.domain.validation import ValidationFeedback

from .attribute_builder import AttributeBuilderService
from .ports import ClipUploaderPort, ImageUploaderPort, ItemPublisherPort, ShippingResolverPort
from .publish.internals.category import (
    build_category_resolution_observability,
    build_resolution_artifact,
    extract_item_identity,
    extract_product_title,
    log_category_resolution_observability,
)
from .publish.internals.category import (
    resolve_category_context as _resolve_category_context_helper,
)
from .publish.internals.decisioning import (
    build_validation_decision,
    classify_shipping_cause,
    extract_exception_error_detail,
    extract_exception_response_excerpt,
    is_shipping_cause,
    register_shipping_causes,
)
from .publish.internals.execution import (
    build_product_from_dict as _build_product_from_dict_helper,
)
from .publish.internals.execution import execute_publish as _execute_publish_helper
from .publish.internals.flow import (
    create_item_for_flow as _create_item_for_flow_helper,
)
from .publish.internals.flow import (
    get_flow_routing_artifact as _get_flow_routing_artifact_helper,
)
from .publish.internals.flow import (
    get_seller_capabilities_artifact as _get_seller_capabilities_artifact_helper,
)
from .publish.internals.flow import (
    resolve_selected_flow as _resolve_selected_flow_helper,
)
from .publish.internals.flow import (
    validate_item_for_flow as _validate_item_for_flow_helper,
)
from .publish.internals.identifier import (
    collect_identifier_state,
    normalize_identifier_text,
    validate_identifier_state,
)
from .publish.internals.payload import (
    get_available_listing_type_ids as _get_available_listing_type_ids_helper,
)
from .publish.internals.payload import (
    get_category_sale_terms_map as _get_category_sale_terms_map_helper,
)
from .publish.internals.payload import (
    get_conditional_required_attribute_ids as _get_conditional_required_attribute_ids_helper,
)
from .publish.internals.payload import (
    get_missing_conditional_attributes as _get_missing_conditional_attributes_helper,
)
from .publish.internals.payload import (
    get_non_fillable_attribute_ids as _get_non_fillable_attribute_ids_helper,
)
from .publish.internals.payload import (
    inject_optional_na_attributes as _inject_optional_na_attributes_helper,
)
from .publish.internals.payload import is_required_sale_term as _is_required_sale_term_helper
from .publish.internals.payload import (
    normalize_item_attributes as _normalize_item_attributes_helper,
)
from .publish.internals.payload import resolve_listing_type_id as _resolve_listing_type_id_helper
from .publish.internals.payload import resolve_sale_terms as _resolve_sale_terms_helper
from .publish.internals.policy import (
    build_policy_attribute_rows as _build_policy_attribute_rows_helper,
)
from .publish.internals.policy import get_policy_artifact as _get_policy_artifact_helper
from .publish.internals.policy import get_policy_attributes as _get_policy_attributes_helper
from .publish.internals.policy import (
    get_policy_category_data as _get_policy_category_data_helper,
)
from .publish.internals.preflight import (
    get_schema_contract_artifact as _get_schema_contract_artifact_helper,
)
from .publish.internals.preflight import (
    get_schema_contract_compiled as _get_schema_contract_compiled_helper,
)
from .publish.internals.preflight import (
    run_image_diagnostic_preflight as _run_image_diagnostic_preflight_helper,
)
from .publish.internals.preflight_validation import (
    inject_default_empty_gtin_reason as _inject_default_empty_gtin_reason_helper,
)
from .publish.internals.preflight_validation import (
    run_identifier_preflight_checks as _run_identifier_preflight_checks_helper,
)
from .publish.internals.preflight_validation import (
    run_schema_contract_preflight as _run_schema_contract_preflight_helper,
)
from .publish.internals.publish_item import publish_one as _publish_one_helper
from .publish.internals.publisher_capabilities import build_publisher_capabilities
from .publish.internals.runtime_settings import resolve_runtime_settings
from .publish.internals.shipping import build_shipping_config as _build_shipping_config_helper
from .publish.internals.state import (
    annotate_image_diagnostics_artifact as _annotate_image_diagnostics_artifact_helper,
)
from .publish.internals.state import (
    build_rollout_flags_artifact as _build_rollout_flags_artifact_helper,
)
from .publish.internals.state import build_stats as _build_stats_helper
from .publish.internals.state import (
    get_problematic_attributes as _get_problematic_attributes_helper,
)
from .publish.internals.state import reset_execution_state as _reset_execution_state_helper
from .publish.internals.user_products import (
    build_user_products_payload,
    extract_selected_model,
    extract_user_products_family_name,
    normalize_variation_candidates,
    variation_value_sort_key,
)
from .publish.internals.validation import (
    build_validation_cause_taxonomy,
    get_critical_attribute_warnings,
)
from .publish.internals.variations import (
    build_legacy_variation_seller_sku as _build_legacy_variation_seller_sku_helper,
)
from .publish.internals.variations import (
    build_variations_from_candidates as _build_variations_from_candidates_helper,
)
from .publish.internals.variations import (
    get_legacy_variation_contract as _get_legacy_variation_contract_helper,
)
from .publish.internals.variations import (
    get_mapped_variation_candidate as _get_mapped_variation_candidate_helper,
)
from .publish.internals.variations import resolve_picture_ids as _resolve_picture_ids_helper
from .shipping_policy import (
    coerce_shipping_bool,
    normalize_seller_tags,
    normalize_shipping_constraints,
)

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
        config: dict[str, Any] | None = None,
        dry_run: bool = False,
        validation_only: bool = False,
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
            validation_only: If True, validates payloads via /items/validate and skips create
            min_attribute_score: Minimum score for attributes (0-100)
            enable_feedback: Enable validation feedback tracking
            enable_fiscal_submission: Whether to submit fiscal data after publishing
            cache_dir: Directory containing category attribute cache files
                (deprecated, use attribute_cache)
            attribute_cache: AttributeCache instance for cached attribute mapping (optional)
        """
        self.category_resolver = category_resolver
        self.publisher = publisher
        self._publisher_capabilities = build_publisher_capabilities(publisher)
        self.image_uploader = image_uploader
        self.shipping_resolver = shipping_resolver
        self.fiscal_service = fiscal_service
        self.clip_uploader = clip_uploader
        self.config = config or {}
        runtime_settings = resolve_runtime_settings(self.config, logger=logger)
        self.strict_warning_gate_mode = runtime_settings.strict_warning_gate_mode
        self.strict_attribute_warnings = runtime_settings.strict_attribute_warnings
        self.validation_decision_mode = runtime_settings.validation_decision_mode
        self.flow_user_products_enabled = runtime_settings.flow_user_products_enabled
        self.flow_blocked_behavior = runtime_settings.flow_blocked_behavior
        self.image_diagnostics_gate_mode = runtime_settings.image_diagnostics_gate_mode
        self.shipping_non_blocking_codes = runtime_settings.shipping_non_blocking_codes
        self.shipping_mandatory_free_shipping_tags = (
            runtime_settings.shipping_mandatory_free_shipping_tags
        )
        self.shipping_enforce_mandatory_free_shipping = (
            runtime_settings.shipping_enforce_mandatory_free_shipping
        )
        self.shipping_allow_runtime_tag_overrides = (
            runtime_settings.shipping_allow_runtime_tag_overrides
        )
        self.shipping_allow_runtime_free_shipping_override = (
            runtime_settings.shipping_allow_runtime_free_shipping_override
        )

        self._rollout_flags_artifact = self._build_rollout_flags_artifact()
        self.dry_run = dry_run
        self.validation_only = validation_only
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
        self._category_policy_cache: dict[str, dict[str, Any]] = {}
        self._category_schema_contract_cache: dict[str, dict[str, Any]] = {}
        self._category_non_fillable_attribute_ids_cache: dict[str, set[str]] = {}
        self._current_cause_codes: list[str] = []
        self._current_preflight_artifact: dict[str, Any] = {
            "identifier_gate": {"checked": False, "violations": []}
        }
        self._current_cause_taxonomy: list[dict[str, str]] = []
        self._current_validation_decision: dict[str, Any] = {}
        self._current_image_diagnostics: dict[str, Any] | None = None
        self._current_shipping_policy: dict[str, Any] | None = None
        self._seller_capabilities_artifact: dict[str, Any] | None = None
        self._flow_routing_artifact: dict[str, Any] | None = None
        self._current_flow_artifact: dict[str, Any] = {}
        self._current_publish_category_id: str | None = None
        self._current_publish_sku: str | None = None
        self._current_variation_reference_attributes: list[dict[str, Any]] = []

    def _reset_execution_state(self) -> None:
        """Reset per-run counters and artifacts."""
        _reset_execution_state_helper(self)

    def _build_rollout_flags_artifact(self) -> dict[str, Any]:
        """Build static rollout feature flag snapshot for item/report metadata."""
        return _build_rollout_flags_artifact_helper(self)

    def _annotate_image_diagnostics_artifact(self, artifact: dict[str, Any]) -> dict[str, Any]:
        """Attach gate decision metadata to image diagnostics artifact."""
        return _annotate_image_diagnostics_artifact_helper(
            artifact,
            gate_mode=self.image_diagnostics_gate_mode,
        )

    @staticmethod
    def _extract_item_identity(product: Product | dict[str, Any]) -> tuple[str | None, str | None]:
        """Extract SKU/title from either input row or Product."""
        return extract_item_identity(product)

    @staticmethod
    def _extract_product_title(product: Product | dict[str, Any]) -> str | None:
        """Extract a normalized title from Product/dict with compatibility key lookup."""
        return extract_product_title(product)

    @staticmethod
    def _build_resolution_artifact(context: dict[str, Any]) -> dict[str, Any]:
        """Build serializable category resolution fields for item results."""
        return build_resolution_artifact(context)

    @staticmethod
    def _build_category_resolution_observability(
        resolution_artifact: dict[str, Any], product_count: int
    ) -> dict[str, Any]:
        """Build deterministic counters and decision metadata for category resolution."""
        return build_category_resolution_observability(resolution_artifact, product_count)

    @staticmethod
    def _log_category_resolution_observability(observability: dict[str, Any]) -> None:
        """Emit category-resolution decision metadata and counters to logs."""
        log_category_resolution_observability(observability, logger)

    def _resolve_category_context(
        self, products: list[Product | dict[str, Any]], category_name: str
    ) -> dict[str, Any]:
        """Resolve category with deterministic strategy metadata."""
        return _resolve_category_context_helper(self, products, category_name, logger)

    @staticmethod
    def _get_critical_attribute_warnings(warnings: list[str]) -> list[str]:
        """Return attribute-processing warnings that should block publication."""
        return get_critical_attribute_warnings(warnings)

    @classmethod
    def _build_validation_cause_taxonomy(cls, causes: list[dict[str, Any]]) -> list[dict[str, str]]:
        """Normalize raw validation causes into a persisted taxonomy."""
        return build_validation_cause_taxonomy(causes)

    def _build_validation_decision(self, taxonomy: list[dict[str, str]]) -> dict[str, Any]:
        """Resolve deterministic strict/controlled decision from taxonomy."""
        return build_validation_decision(
            taxonomy=taxonomy,
            validation_decision_mode=self.validation_decision_mode,
            strict_warning_gate_mode=self.strict_warning_gate_mode,
            strict_attribute_warnings=self.strict_attribute_warnings,
        )

    @staticmethod
    def _is_shipping_cause(cause_code: str, cause_message: str) -> bool:
        """Check whether a cause row is shipping-related."""
        return is_shipping_cause(cause_code, cause_message)

    def _classify_shipping_cause(self, cause_code: str, cause_message: str) -> str:
        """Classify shipping causes into blocking/retryable/unknown buckets."""
        return classify_shipping_cause(
            cause_code=cause_code,
            cause_message=cause_message,
            shipping_non_blocking_codes=self.shipping_non_blocking_codes,
        )

    def _register_shipping_causes(self, causes: list[Any], *, stage: str) -> list[dict[str, str]]:
        """Extract and store shipping-cause classification metadata for current item."""
        return register_shipping_causes(
            causes,
            stage=stage,
            current_shipping_policy=self._current_shipping_policy,
            shipping_non_blocking_codes=self.shipping_non_blocking_codes,
        )

    @staticmethod
    def _extract_exception_error_detail(error: Exception) -> dict[str, Any] | None:
        """Return parsed API error payload when available."""
        return extract_exception_error_detail(error)

    @staticmethod
    def _extract_exception_response_excerpt(error: Exception, *, limit: int = 200) -> str | None:
        """Return bounded response text excerpt for non-JSON API failures."""
        return extract_exception_response_excerpt(error, limit=limit)

    @staticmethod
    def _normalize_seller_tags(raw_tags: Any) -> list[str]:
        """Normalize seller tag payload from users/me style responses."""
        return normalize_seller_tags(raw_tags)

    @staticmethod
    def _normalize_shipping_constraints(raw_constraints: Any) -> dict[str, Any]:
        """Normalize shipping constraints payload into a deterministic mapping."""
        return normalize_shipping_constraints(raw_constraints)

    @staticmethod
    def _coerce_shipping_bool(value: Any) -> bool | None:
        """Coerce supported shipping booleans into strict bool values."""
        return coerce_shipping_bool(value)

    def _get_seller_capabilities_artifact(self) -> dict[str, Any]:
        """Read seller capability tags once and reuse within the use case instance."""
        return _get_seller_capabilities_artifact_helper(self)

    def _get_flow_routing_artifact(self) -> dict[str, Any]:
        """Resolve deterministic publish flow routing metadata."""
        return _get_flow_routing_artifact_helper(self)

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
        return _execute_publish_helper(self, products, category_name)

    def _build_product_from_dict(self, data: dict[str, Any]) -> Product:
        return _build_product_from_dict_helper(data)

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
        return _publish_one_helper(self, product, category_id)

    def _resolve_selected_flow(self) -> str:
        """Resolve currently selected publish flow with legacy fallback."""
        return _resolve_selected_flow_helper(self)

    def _validate_item_for_flow(
        self, *, item: dict[str, Any], selected_flow: str
    ) -> dict[str, Any]:
        """Validate payload using the selected publish route."""
        return _validate_item_for_flow_helper(self, item=item, selected_flow=selected_flow)

    def _create_item_for_flow(self, *, item: dict[str, Any], selected_flow: str) -> dict[str, Any]:
        """Publish payload using the selected publish route."""
        return _create_item_for_flow_helper(self, item=item, selected_flow=selected_flow)

    @staticmethod
    def _extract_user_products_family_name(product: Product) -> str | None:
        """Extract user-products family name from source row attributes."""
        return extract_user_products_family_name(product)

    @staticmethod
    def _extract_selected_model(
        ml_attributes: list[dict[str, Any]],
        variation_candidates: dict[str, list[dict[str, Any]]],
    ) -> str | None:
        """Extract deterministic MODEL value for UP flow artifacts."""
        return extract_selected_model(ml_attributes, variation_candidates)

    def _build_user_products_payload(
        self,
        *,
        product: Product,
        ml_attributes: list[dict[str, Any]],
        variation_candidates: dict[str, list[dict[str, Any]]],
        quantity: int,
        price: float,
        picture_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Build MLB-safe user-products metadata and payload fields."""
        return build_user_products_payload(
            product=product,
            ml_attributes=ml_attributes,
            variation_candidates=variation_candidates,
            quantity=quantity,
            price=price,
            picture_ids=picture_ids,
        )

    @staticmethod
    def _normalize_variation_candidates(
        variation_candidates: dict[str, list[dict[str, Any]]],
    ) -> list[tuple[str, list[dict[str, Any]]]]:
        """Normalize and deduplicate variation candidates preserving deterministic order."""
        return normalize_variation_candidates(variation_candidates)

    @staticmethod
    def _variation_value_sort_key(value: dict[str, Any]) -> tuple[str, str]:
        """Return deterministic sort key for variation candidate values."""
        return variation_value_sort_key(value)

    def _get_legacy_variation_contract(self) -> tuple[list[str], dict[str, Any]]:
        """Return allow_variations IDs and limits for the current category."""
        return _get_legacy_variation_contract_helper(self)

    def _get_mapped_variation_candidate(self, attr_id: str) -> dict[str, Any] | None:
        """Resolve mapped attribute payload as preferred variation candidate."""
        return _get_mapped_variation_candidate_helper(self, attr_id)

    def _build_legacy_variation_seller_sku(self, index: int) -> str | None:
        """Build deterministic SELLER_SKU value for legacy variation attributes."""
        return _build_legacy_variation_seller_sku_helper(self, index)

    def get_stats(self) -> dict[str, Any]:
        """Get publishing statistics."""
        return _build_stats_helper(self)

    def get_problematic_attributes(self) -> dict[str, int]:
        """Get attributes that frequently cause errors.

        Returns:
            Dictionary mapping attribute IDs to error counts
        """
        return _get_problematic_attributes_helper(self)

    def _build_variations_from_candidates(
        self,
        variation_candidates: dict[str, list[dict[str, Any]]],
        quantity: int,
        price: float,
        picture_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Build variations payload from candidate values extracted during mapping."""
        return _build_variations_from_candidates_helper(
            self,
            variation_candidates=variation_candidates,
            quantity=quantity,
            price=price,
            picture_ids=picture_ids,
        )

    def _resolve_picture_ids(self, picture_urls: list[str]) -> list[str]:
        """Resolve ML picture IDs for current picture URLs from uploader history."""
        return _resolve_picture_ids_helper(self, picture_urls)

    def _get_policy_category_data(self, category_id: str) -> dict[str, Any]:
        """Fetch category metadata for policy compilation."""
        return _get_policy_category_data_helper(self, category_id)

    def _build_policy_attribute_rows(self, attributes: list[Any]) -> list[dict[str, Any]]:
        """Normalize arbitrary attribute metadata payloads into dict rows."""
        return _build_policy_attribute_rows_helper(attributes)

    def _get_policy_attributes(self, category_id: str) -> list[dict[str, Any]]:
        """Fetch category attributes for policy compilation."""
        return _get_policy_attributes_helper(self, category_id)

    def _get_policy_artifact(self, category_id: str) -> dict[str, Any]:
        """Compile and cache policy hash/summary for a category."""
        return _get_policy_artifact_helper(self, category_id)

    def _get_schema_contract_compiled(self, category_id: str) -> dict[str, Any]:
        return _get_schema_contract_compiled_helper(self, category_id)

    def _get_schema_contract_artifact(self, category_id: str) -> dict[str, Any]:
        return _get_schema_contract_artifact_helper(self, category_id)

    def _run_image_diagnostic_preflight(
        self,
        *,
        sku: str,
        title: str,
        category_id: str,
        picture_urls: list[str],
        picture_ids: list[str],
    ) -> dict[str, Any]:
        return _run_image_diagnostic_preflight_helper(
            self,
            sku=sku,
            title=title,
            category_id=category_id,
            picture_urls=picture_urls,
            picture_ids=picture_ids,
        )

    @staticmethod
    def _normalize_identifier_text(value: Any) -> str | None:
        return normalize_identifier_text(value)

    def _collect_identifier_state(self, attributes: Any) -> dict[str, Any]:
        return collect_identifier_state(attributes)

    def _validate_identifier_state(
        self,
        *,
        scope: str,
        state: dict[str, Any],
        gtin_required: bool,
        fallback_reason_available: bool,
        enforce_identifier_coverage: bool,
        allowed_reason_ids: set[str],
        allowed_reason_names: set[str],
    ) -> list[str]:
        return validate_identifier_state(
            scope=scope,
            state=state,
            gtin_required=gtin_required,
            fallback_reason_available=fallback_reason_available,
            enforce_identifier_coverage=enforce_identifier_coverage,
            allowed_reason_ids=allowed_reason_ids,
            allowed_reason_names=allowed_reason_names,
        )

    def _run_identifier_preflight_checks(
        self,
        *,
        schema_contract: dict[str, Any],
        item: dict[str, Any],
    ) -> tuple[list[str], dict[str, Any]]:
        return _run_identifier_preflight_checks_helper(
            self,
            schema_contract=schema_contract,
            item=item,
        )

    def _inject_default_empty_gtin_reason(
        self,
        *,
        item: dict[str, Any],
        gtin_required: bool,
        empty_gtin_reason_attribute_id: str | None,
        allowed_reason_ids: set[str],
        allowed_reason_names: list[str],
    ) -> dict[str, Any]:
        return _inject_default_empty_gtin_reason_helper(
            self,
            item=item,
            gtin_required=gtin_required,
            empty_gtin_reason_attribute_id=empty_gtin_reason_attribute_id,
            allowed_reason_ids=allowed_reason_ids,
            allowed_reason_names=allowed_reason_names,
        )

    def _run_schema_contract_preflight(
        self,
        *,
        category_id: str,
        item: dict[str, Any],
    ) -> list[str]:
        return _run_schema_contract_preflight_helper(
            self,
            category_id=category_id,
            item=item,
        )

    def _get_available_listing_type_ids(self, category_id: str) -> list[str]:
        return _get_available_listing_type_ids_helper(self, category_id)

    def _resolve_listing_type_id(
        self,
        category_id: str,
        explicit_listing_type: str | None,
        default_listing_type: Any,
        has_pictures: bool,
        available_listing_types: list[str],
    ) -> str:
        return _resolve_listing_type_id_helper(
            self,
            category_id,
            explicit_listing_type,
            default_listing_type,
            has_pictures,
            available_listing_types,
        )

    def _get_category_sale_terms_map(self, category_id: str) -> dict[str, dict[str, Any]]:
        return _get_category_sale_terms_map_helper(self, category_id)

    def _is_required_sale_term(self, sale_term: dict[str, Any]) -> bool:
        return _is_required_sale_term_helper(sale_term)

    def _resolve_sale_terms(
        self,
        category_id: str,
        sale_terms_from_mapping: list[dict[str, Any]],
        default_sale_terms: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        return _resolve_sale_terms_helper(
            self,
            category_id,
            sale_terms_from_mapping,
            default_sale_terms,
        )

    def _get_non_fillable_attribute_ids(self, category_id: str) -> set[str]:
        return _get_non_fillable_attribute_ids_helper(self, category_id)

    def _get_missing_conditional_attributes(
        self,
        category_id: str,
        item: dict[str, Any],
        description: str,
        conditional_required_ids: set[str] | None = None,
    ) -> list[str]:
        return _get_missing_conditional_attributes_helper(
            self,
            category_id,
            item,
            description,
            conditional_required_ids,
        )

    def _get_conditional_required_attribute_ids(
        self,
        category_id: str,
        item: dict[str, Any],
        description: str,
    ) -> set[str]:
        return _get_conditional_required_attribute_ids_helper(
            self,
            category_id,
            item,
            description,
        )

    def _inject_optional_na_attributes(
        self,
        category_id: str,
        item: dict[str, Any],
        sku: str,
        description: str,
    ) -> set[str] | None:
        return _inject_optional_na_attributes_helper(
            self,
            category_id,
            item,
            sku,
            description,
        )

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

    def _build_shipping_config(
        self,
        category_id: str | None = None,
        row_attributes: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return _build_shipping_config_helper(
            self,
            category_id=category_id,
            row_attributes=row_attributes,
        )

    def _normalize_item_attributes(self, item: dict[str, Any]) -> None:
        _normalize_item_attributes_helper(self, item)

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
