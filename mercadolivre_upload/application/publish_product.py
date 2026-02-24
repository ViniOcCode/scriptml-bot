"""Publish product use case.

Orchestrates domain logic and adapters to publish products.
"""

import logging
import re
from copy import deepcopy
from itertools import product as cartesian_product
from typing import Any, cast

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
from .policy_snapshot import compile_policy_snapshot, compile_schema_contract
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
NON_FILLABLE_ATTRIBUTE_TAGS = {"hidden", "read_only", "non_modifiable"}
DEFAULT_NA_SKIP_TAGS = {
    "required",
    "new_required",
    "conditional_required",
    "catalog_listing_required",
    "allow_variations",
    "variation_attribute",
    *NON_FILLABLE_ATTRIBUTE_TAGS,
}
IDENTIFIER_EMPTY_TOKENS = {
    "",
    "-",
    "na",
    "n a",
    "nao informado",
    "not informed",
    "none",
    "null",
    "sem gtin",
}
CRITICAL_ATTRIBUTE_WARNING_TOKENS = (
    "unknown attribute",
    "attribute missing id",
    "value type mismatch",
    "doesn't match pattern",
)
CRITICAL_VALIDATION_WARNING_TOKENS = (
    "item.attributes.omitted",
    "item.attributes.invalid",
    "item.attributes.required",
)
SHIPPING_BLOCKING_CODE_TOKENS = (
    "shipping.mode",
    "shipping.logistic_type",
    "shipping.free_shipping",
    "shipping.not_allowed",
    "shipping.invalid",
)
SHIPPING_RETRYABLE_CODE_TOKENS = (
    "shipping.timeout",
    "shipping.internal_error",
    "shipping.service_unavailable",
    "shipping.rate_limit",
    "shipping.too_many_requests",
)
SHIPPING_BLOCKING_MESSAGE_TOKENS = (
    "not allowed",
    "mandatory",
    "required",
    "forbidden",
    "unsupported",
    "incompatible",
    "não permitido",
    "nao permitido",
    "obrigat",
    "must be",
)
SHIPPING_RETRYABLE_MESSAGE_TOKENS = (
    "temporary",
    "temporar",
    "timeout",
    "timed out",
    "service unavailable",
    "try again",
    "internal error",
    "rate limit",
)
RETRYABLE_VALIDATION_ERROR_TOKENS = (
    "internal_error",
    "internal.server.error",
    "service_unavailable",
    "temporarily_unavailable",
    "gateway_timeout",
    "too_many_requests",
    "rate_limit",
    "timeout",
    "timed out",
    "temporar",
    "retry",
)
VALIDATION_DECISION_MODES = {"strict", "controlled"}
USER_PRODUCTS_SELLER_TAG = "user_product_seller"
AVAILABLE_ROUTING_FLOWS = {"legacy", "user_products"}
IMPLEMENTED_ROUTING_FLOWS = {"legacy", "user_products"}
STRICT_WARNING_GATE_MODES = {"enforce", "report_only"}
IMAGE_DIAGNOSTIC_GATE_MODES = {"enforce", "report_only", "disabled"}
FLOW_BLOCKED_BEHAVIORS = {"fail", "fallback_legacy"}
DEFAULT_MANDATORY_FREE_SHIPPING_TAGS = {"mandatory_free_shipping"}


def _normalize_attribute_tag(tag: Any) -> str:
    """Normalize API/config attribute tags into a canonical token."""
    return str(tag).strip().lower().replace("-", "_")


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
        self.image_uploader = image_uploader
        self.shipping_resolver = shipping_resolver
        self.fiscal_service = fiscal_service
        self.clip_uploader = clip_uploader
        self.config = config or {}

        strict_warning_gate_mode = self.config.get("strict_warning_gate_mode")
        normalized_strict_mode: str | None = None
        if isinstance(strict_warning_gate_mode, str) and strict_warning_gate_mode.strip():
            normalized_strict_mode = strict_warning_gate_mode.strip().lower()
            if normalized_strict_mode not in STRICT_WARNING_GATE_MODES:
                logger.warning(
                    "Invalid strict warning gate mode '%s'; falling back to enforce.",
                    normalized_strict_mode,
                )
                normalized_strict_mode = "enforce"

        strict_warnings = self.config.get("strict_attribute_warnings")
        if normalized_strict_mode is not None:
            self.strict_warning_gate_mode = normalized_strict_mode
            self.strict_attribute_warnings = normalized_strict_mode == "enforce"
        else:
            self.strict_attribute_warnings = (
                True if strict_warnings is None else bool(strict_warnings)
            )
            self.strict_warning_gate_mode = (
                "enforce" if self.strict_attribute_warnings else "report_only"
            )

        raw_validation_mode = self.config.get("validation_decision_mode", "strict")
        if isinstance(raw_validation_mode, str) and raw_validation_mode.strip():
            validation_mode = raw_validation_mode.strip().lower()
        else:
            validation_mode = "strict"
        if validation_mode not in VALIDATION_DECISION_MODES:
            logger.warning(
                "Invalid validation decision mode '%s'; falling back to strict.",
                validation_mode,
            )
            validation_mode = "strict"
        self.validation_decision_mode = validation_mode

        flow_config = self.config.get("flow_routing", {})
        self.flow_user_products_enabled = True
        self.flow_blocked_behavior = "fail"
        if isinstance(flow_config, dict):
            raw_user_products_enabled = flow_config.get(
                "user_products_enabled",
                flow_config.get("enable_user_products"),
            )
            if raw_user_products_enabled is not None:
                self.flow_user_products_enabled = bool(raw_user_products_enabled)
            raw_blocked_behavior = flow_config.get(
                "blocked_behavior",
                flow_config.get("on_blocked"),
            )
            if isinstance(raw_blocked_behavior, str) and raw_blocked_behavior.strip():
                normalized_behavior = raw_blocked_behavior.strip().lower()
                if normalized_behavior in FLOW_BLOCKED_BEHAVIORS:
                    self.flow_blocked_behavior = normalized_behavior
                else:
                    logger.warning(
                        "Invalid flow blocked behavior '%s'; falling back to fail.",
                        normalized_behavior,
                    )

        self.image_diagnostics_gate_mode = "enforce"
        image_diagnostics_config = self.config.get("image_diagnostics")
        normalized_diag_mode: str | None = None
        if isinstance(image_diagnostics_config, dict):
            raw_diag_mode = image_diagnostics_config.get("gate_mode")
            if raw_diag_mode is None and "enabled" in image_diagnostics_config:
                raw_diag_mode = (
                    "enforce" if bool(image_diagnostics_config.get("enabled")) else "disabled"
                )
            if raw_diag_mode is None:
                raw_diag_mode = image_diagnostics_config.get("mode")
            if isinstance(raw_diag_mode, str) and raw_diag_mode.strip():
                normalized_diag_mode = raw_diag_mode.strip().lower()
        elif isinstance(image_diagnostics_config, str) and image_diagnostics_config.strip():
            normalized_diag_mode = image_diagnostics_config.strip().lower()

        if normalized_diag_mode in {"off", "skip"}:
            normalized_diag_mode = "disabled"
        elif normalized_diag_mode in {"report", "observe"}:
            normalized_diag_mode = "report_only"
        elif normalized_diag_mode in {"strict", "enabled", "on"}:
            normalized_diag_mode = "enforce"

        if normalized_diag_mode:
            if normalized_diag_mode in IMAGE_DIAGNOSTIC_GATE_MODES:
                self.image_diagnostics_gate_mode = normalized_diag_mode
            else:
                logger.warning(
                    "Invalid image diagnostics gate mode '%s'; falling back to enforce.",
                    normalized_diag_mode,
                )

        self.shipping_non_blocking_codes: set[str] = set()
        self.shipping_mandatory_free_shipping_tags: set[str] = set(
            DEFAULT_MANDATORY_FREE_SHIPPING_TAGS
        )
        self.shipping_enforce_mandatory_free_shipping = True
        self.shipping_allow_runtime_tag_overrides = True
        self.shipping_allow_runtime_free_shipping_override = True
        shipping_policy_config = self.config.get("shipping_policy")
        if not isinstance(shipping_policy_config, dict):
            shipping_config = self.config.get("shipping")
            if isinstance(shipping_config, dict):
                nested_policy = shipping_config.get("policy")
                if isinstance(nested_policy, dict):
                    shipping_policy_config = nested_policy

        if isinstance(shipping_policy_config, dict):
            raw_non_blocking_codes = shipping_policy_config.get("non_blocking_codes", [])
            if isinstance(raw_non_blocking_codes, str):
                raw_non_blocking_codes = [raw_non_blocking_codes]
            if isinstance(raw_non_blocking_codes, list):
                self.shipping_non_blocking_codes = {
                    str(code).strip().lower()
                    for code in raw_non_blocking_codes
                    if str(code).strip()
                }

            raw_mandatory_tags = shipping_policy_config.get(
                "mandatory_free_shipping_tags",
                sorted(DEFAULT_MANDATORY_FREE_SHIPPING_TAGS),
            )
            if isinstance(raw_mandatory_tags, str):
                raw_mandatory_tags = [raw_mandatory_tags]
            if isinstance(raw_mandatory_tags, list):
                normalized_tags = {
                    str(tag).strip().lower() for tag in raw_mandatory_tags if str(tag).strip()
                }
                if normalized_tags:
                    self.shipping_mandatory_free_shipping_tags = normalized_tags

            raw_enforce_mandatory = shipping_policy_config.get("enforce_mandatory_free_shipping")
            if isinstance(raw_enforce_mandatory, bool):
                self.shipping_enforce_mandatory_free_shipping = raw_enforce_mandatory

            raw_allow_tag_overrides = shipping_policy_config.get("allow_runtime_tag_overrides")
            if isinstance(raw_allow_tag_overrides, bool):
                self.shipping_allow_runtime_tag_overrides = raw_allow_tag_overrides

            raw_allow_free_shipping_override = shipping_policy_config.get(
                "allow_runtime_free_shipping_override"
            )
            if isinstance(raw_allow_free_shipping_override, bool):
                self.shipping_allow_runtime_free_shipping_override = (
                    raw_allow_free_shipping_override
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
        self.published = 0
        self.failed = 0
        self.errors = []
        self.fiscal_results = []
        self.clip_results = []
        self.item_results = []
        self._pending_fiscal = []
        self._category_policy_cache = {}
        self._category_schema_contract_cache = {}
        self._category_non_fillable_attribute_ids_cache = {}
        self._current_cause_codes = []
        self._current_preflight_artifact = {"identifier_gate": {"checked": False, "violations": []}}
        self._current_cause_taxonomy = []
        self._current_validation_decision = {}
        self._current_image_diagnostics = None
        self._current_shipping_policy = None
        self._current_flow_artifact = {}
        self._current_publish_category_id = None
        self._current_publish_sku = None
        self._current_variation_reference_attributes = []

    def _build_rollout_flags_artifact(self) -> dict[str, Any]:
        """Build static rollout feature flag snapshot for item/report metadata."""
        return {
            "validation_decision_mode": self.validation_decision_mode,
            "strict_warning_gate_mode": self.strict_warning_gate_mode,
            "strict_attribute_warnings": self.strict_attribute_warnings,
            "image_diagnostics_gate_mode": self.image_diagnostics_gate_mode,
            "flow_user_products_enabled": self.flow_user_products_enabled,
            "flow_blocked_behavior": self.flow_blocked_behavior,
            "shipping_non_blocking_codes": sorted(self.shipping_non_blocking_codes),
            "shipping_mandatory_free_shipping_tags": sorted(
                self.shipping_mandatory_free_shipping_tags
            ),
            "shipping_enforce_mandatory_free_shipping": (
                self.shipping_enforce_mandatory_free_shipping
            ),
            "shipping_allow_runtime_tag_overrides": self.shipping_allow_runtime_tag_overrides,
            "shipping_allow_runtime_free_shipping_override": (
                self.shipping_allow_runtime_free_shipping_override
            ),
        }

    def _annotate_image_diagnostics_artifact(self, artifact: dict[str, Any]) -> dict[str, Any]:
        """Attach gate decision metadata to image diagnostics artifact."""
        normalized = dict(artifact)
        raw_issues = normalized.get("issues", [])
        issues = (
            [str(issue) for issue in raw_issues if str(issue).strip()]
            if isinstance(raw_issues, list)
            else []
        )
        gate_blocks = self.image_diagnostics_gate_mode == "enforce"
        action = "allow"
        if self.image_diagnostics_gate_mode == "disabled":
            action = "skip"
        elif gate_blocks and issues:
            action = "block"

        normalized["gate_mode"] = self.image_diagnostics_gate_mode
        normalized["gate_blocks"] = gate_blocks
        normalized["gate_decision"] = {
            "action": action,
            "issue_count": len(issues),
        }
        return normalized

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

    @staticmethod
    def _build_resolution_artifact(context: dict[str, Any]) -> dict[str, Any]:
        """Build serializable category resolution fields for item results."""
        category_path = context.get("category_path")
        if not isinstance(category_path, list):
            category_path = []

        strategy = context.get("resolution_strategy")
        if not isinstance(strategy, str) or not strategy:
            strategy = "unresolved"

        category_input = context.get("category_input")
        if not isinstance(category_input, str):
            category_input = str(category_input or "").strip()

        resolved_id = context.get("category_resolved_id")
        if not isinstance(resolved_id, str) or not resolved_id:
            resolved_id = None

        return {
            "category_input": category_input,
            "category_resolved_id": resolved_id,
            "category_path": list(category_path),
            "resolution_strategy": strategy,
        }

    def _resolve_category_context(
        self, products: list[Product | dict[str, Any]], category_name: str
    ) -> dict[str, Any]:
        """Resolve category with deterministic strategy metadata."""
        category_input = str(category_name).strip()
        resolved_id: str | None = None
        strategy = "unresolved"

        # Strategy 0: Accept direct category IDs (e.g. MLB1234)
        if re.fullmatch(r"[A-Z]{3}\d+", category_input):
            resolved_id = category_input
            strategy = "direct_id"
        else:
            # Strategy 1: Find category by name (fast root match)
            resolved_id = self.category_resolver.find_category(category_input)
            if resolved_id:
                strategy = "name_match"
            else:
                logger.info(
                    "Category '%s' not found by name; falling back to predictor path match.",
                    category_input,
                )

        # Strategy 2: Use domain discovery with product titles
        if not resolved_id and products:
            titles: list[str] = []
            for product in products:
                title = self._extract_product_title(product)
                if title:
                    titles.append(title)

            if titles:
                logger.info("Extracted %s titles for prediction", len(titles))
                resolved_id = self.category_resolver.find_category_with_predictor(
                    category_input, titles
                )
                if resolved_id:
                    strategy = "predictor_path_match"
                else:
                    logger.info(
                        "Predictor path matching did not resolve '%s'; "
                        "falling back to title prediction.",
                        category_input,
                    )

        # Strategy 3: Fallback to simple title prediction (for backwards compatibility)
        if not resolved_id and products:
            logger.info("Trying simple domain discovery fallback...")
            for product in products:
                title_str = self._extract_product_title(product)
                if title_str:
                    resolved_id = self.category_resolver.predict_category_from_title(title_str)
                    if resolved_id:
                        strategy = "title_prediction"
                        logger.info(f"Found category from title '{title_str[:30]}...'")
                        break

        category_path: list[Any] = []
        if resolved_id:
            leaf_category_id = self.category_resolver.resolve_to_leaf(resolved_id)
            if leaf_category_id != resolved_id:
                logger.info(f"Resolved to leaf category: {leaf_category_id}")
            resolved_id = leaf_category_id

            category_data = self._get_policy_category_data(resolved_id)
            if isinstance(category_data, dict):
                raw_path = category_data.get("path_from_root")
                if isinstance(raw_path, list):
                    category_path = list(raw_path)

        return {
            "category_input": category_input,
            "category_resolved_id": resolved_id,
            "category_path": category_path,
            "resolution_strategy": strategy,
        }

    @staticmethod
    def _get_critical_attribute_warnings(warnings: list[str]) -> list[str]:
        """Return attribute-processing warnings that should block publication."""
        critical: list[str] = []
        for warning in warnings:
            normalized = str(warning).lower()
            if any(token in normalized for token in CRITICAL_ATTRIBUTE_WARNING_TOKENS):
                critical.append(str(warning))
        return critical

    @staticmethod
    def _get_critical_validation_warnings(warnings: list[str]) -> list[str]:
        """Return API validation warnings that indicate payload/data loss."""
        critical: list[str] = []
        for warning in warnings:
            normalized = str(warning).lower()
            if any(token in normalized for token in CRITICAL_VALIDATION_WARNING_TOKENS):
                critical.append(str(warning))
        return critical

    @staticmethod
    def _classify_validation_cause(cause: dict[str, Any]) -> str:
        """Classify validation causes for deterministic decisioning."""
        cause_type = str(cause.get("type", "")).strip().lower()
        cause_code = str(cause.get("code", "")).strip().lower()
        cause_message = str(cause.get("message", "")).strip().lower()
        normalized_payload = f"{cause_code} {cause_message}"

        if cause_type == "warning":
            if any(token in normalized_payload for token in CRITICAL_VALIDATION_WARNING_TOKENS):
                return "critical_warning"
            return "informational_warning"

        if any(token in normalized_payload for token in RETRYABLE_VALIDATION_ERROR_TOKENS):
            return "retryable_error"
        return "blocking_error"

    @classmethod
    def _build_validation_cause_taxonomy(cls, causes: list[dict[str, Any]]) -> list[dict[str, str]]:
        """Normalize raw validation causes into a persisted taxonomy."""
        taxonomy: list[dict[str, str]] = []
        for cause in causes:
            if not isinstance(cause, dict):
                continue
            raw_code = str(cause.get("code", "")).strip()
            taxonomy.append(
                {
                    "type": str(cause.get("type", "")).strip().lower(),
                    "code": raw_code.lower(),
                    "message": str(cause.get("message", "")).strip(),
                    "classification": cls._classify_validation_cause(cause),
                }
            )
        return taxonomy

    def _build_validation_decision(self, taxonomy: list[dict[str, str]]) -> dict[str, Any]:
        """Resolve deterministic strict/controlled decision from taxonomy."""
        classification_counts = {
            "blocking_error": 0,
            "retryable_error": 0,
            "critical_warning": 0,
            "informational_warning": 0,
        }
        classification_codes: dict[str, list[str]] = {
            "blocking_error": [],
            "retryable_error": [],
            "critical_warning": [],
            "informational_warning": [],
        }

        for cause in taxonomy:
            classification = str(cause.get("classification", "")).strip().lower()
            if classification not in classification_counts:
                continue
            classification_counts[classification] += 1
            code = str(cause.get("code", "")).strip().lower()
            if code and code not in classification_codes[classification]:
                classification_codes[classification].append(code)

        action = "allow"
        reason = "no_validation_causes"
        if classification_counts["blocking_error"] > 0:
            action = "block"
            reason = "blocking_error"
        elif classification_counts["retryable_error"] > 0:
            if self.validation_decision_mode == "controlled":
                action = "retry"
                reason = "retryable_error_controlled"
            else:
                action = "block"
                reason = "retryable_error_strict"
        elif classification_counts["critical_warning"] > 0:
            if self.validation_decision_mode == "strict" and self.strict_attribute_warnings:
                action = "block"
                reason = "critical_warning_strict"
            else:
                action = "allow"
                reason = "critical_warning_allowed"
        elif classification_counts["informational_warning"] > 0:
            action = "allow"
            reason = "informational_warning"

        return {
            "mode": self.validation_decision_mode,
            "strict_warning_gate_mode": self.strict_warning_gate_mode,
            "strict_attribute_warnings": self.strict_attribute_warnings,
            "action": action,
            "reason": reason,
            "classification_counts": classification_counts,
            "classification_codes": classification_codes,
        }

    @staticmethod
    def _is_shipping_cause(cause_code: str, cause_message: str) -> bool:
        """Check whether a cause row is shipping-related."""
        normalized_code = cause_code.lower()
        normalized_message = cause_message.lower()
        return (
            "shipping" in normalized_code
            or "shipping" in normalized_message
            or "envio" in normalized_message
        )

    def _classify_shipping_cause(self, cause_code: str, cause_message: str) -> str:
        """Classify shipping causes into blocking/retryable/unknown buckets."""
        normalized_code = cause_code.lower()
        normalized_message = cause_message.lower()

        if any(
            normalized_code == code or normalized_code.startswith(f"{code}.")
            for code in self.shipping_non_blocking_codes
        ):
            return "unknown"
        if any(token in normalized_code for token in SHIPPING_BLOCKING_CODE_TOKENS):
            return "blocking"
        if any(token in normalized_code for token in SHIPPING_RETRYABLE_CODE_TOKENS):
            return "retryable"
        if any(token in normalized_message for token in SHIPPING_BLOCKING_MESSAGE_TOKENS):
            return "blocking"
        if any(token in normalized_message for token in SHIPPING_RETRYABLE_MESSAGE_TOKENS):
            return "retryable"
        return "unknown"

    def _register_shipping_causes(self, causes: list[Any], *, stage: str) -> list[dict[str, str]]:
        """Extract and store shipping-cause classification metadata for current item."""
        decisions: list[dict[str, str]] = []
        for raw_cause in causes:
            if not isinstance(raw_cause, dict):
                continue
            cause_code = str(raw_cause.get("code", "") or "").strip()
            cause_message = str(raw_cause.get("message", "") or "").strip()
            if not self._is_shipping_cause(cause_code, cause_message):
                continue
            decision = {
                "stage": stage,
                "type": str(raw_cause.get("type", "") or "").strip().lower(),
                "code": cause_code,
                "message": cause_message,
                "classification": self._classify_shipping_cause(cause_code, cause_message),
            }
            decisions.append(decision)

        if decisions and self._current_shipping_policy is not None:
            existing = self._current_shipping_policy.setdefault("cause_decisions", [])
            if isinstance(existing, list):
                known = {
                    (
                        str(row.get("stage", "")),
                        str(row.get("type", "")),
                        str(row.get("code", "")),
                        str(row.get("message", "")),
                    )
                    for row in existing
                    if isinstance(row, dict)
                }
                for decision in decisions:
                    key = (
                        decision["stage"],
                        decision["type"],
                        decision["code"],
                        decision["message"],
                    )
                    if key in known:
                        continue
                    existing.append(decision)
                    known.add(key)
                self._current_shipping_policy["has_blocking_cause"] = any(
                    isinstance(row, dict) and row.get("classification") == "blocking"
                    for row in existing
                )
        return decisions

    @staticmethod
    def _normalize_seller_tags(raw_tags: Any) -> list[str]:
        """Normalize seller tag payload from users/me style responses."""
        normalized_tags: list[str] = []
        if isinstance(raw_tags, list):
            for tag in raw_tags:
                tag_name = str(tag).strip().lower()
                if tag_name:
                    normalized_tags.append(tag_name)
        elif isinstance(raw_tags, dict):
            for tag, enabled in raw_tags.items():
                if not enabled:
                    continue
                tag_name = str(tag).strip().lower()
                if tag_name:
                    normalized_tags.append(tag_name)
        return list(dict.fromkeys(normalized_tags))

    @staticmethod
    def _normalize_shipping_constraints(raw_constraints: Any) -> dict[str, Any]:
        """Normalize shipping constraints payload into a deterministic mapping."""
        if not isinstance(raw_constraints, dict):
            return {}
        return {
            str(key).strip(): value for key, value in raw_constraints.items() if str(key).strip()
        }

    @staticmethod
    def _coerce_shipping_bool(value: Any) -> bool | None:
        """Coerce supported shipping booleans into strict bool values."""
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"true", "1", "yes", "y", "on"}:
                return True
            if normalized in {"false", "0", "no", "n", "off"}:
                return False
        return None

    def _get_seller_capabilities_artifact(self) -> dict[str, Any]:
        """Read seller capability tags once and reuse within the use case instance."""
        if self._seller_capabilities_artifact is not None:
            return self._seller_capabilities_artifact

        seller_info: dict[str, Any] = {}
        source = "unavailable"
        for endpoint_name, method_name in (
            ("publisher/get_users_me", "get_publisher_users_me"),
            ("users/me", "get_users_me"),
        ):
            getter = getattr(self.publisher, method_name, None)
            if not callable(getter):
                continue
            try:
                payload = getter()
            except Exception as error:
                logger.warning(
                    "Could not fetch seller capabilities from %s: %s",
                    endpoint_name,
                    error,
                )
                continue
            if isinstance(payload, dict):
                seller_info = payload
                source = endpoint_name
                break
            logger.warning(
                "Unexpected seller capability payload from %s: %s",
                endpoint_name,
                type(payload).__name__,
            )

        tags = self._normalize_seller_tags(seller_info.get("tags"))
        has_user_products_tag = USER_PRODUCTS_SELLER_TAG in tags
        artifact = {
            "source": source,
            "seller_id": seller_info.get("id"),
            "tags": tags,
            "has_user_product_seller_tag": has_user_products_tag,
        }
        self._seller_capabilities_artifact = artifact
        return artifact

    def _get_flow_routing_artifact(self) -> dict[str, Any]:
        """Resolve deterministic publish flow routing metadata."""
        if self._flow_routing_artifact is not None:
            return self._flow_routing_artifact

        flow_config = self.config.get("flow_routing", {})
        mode = "auto"
        forced_flow: str | None = None
        if isinstance(flow_config, dict):
            raw_mode = flow_config.get("mode")
            if isinstance(raw_mode, str) and raw_mode.strip():
                mode = raw_mode.strip().lower()
            raw_forced_flow = flow_config.get("forced_flow", flow_config.get("flow"))
            if isinstance(raw_forced_flow, str) and raw_forced_flow.strip():
                forced_flow = raw_forced_flow.strip().lower()

        if forced_flow:
            mode = "forced"
        if mode not in {"auto", "forced"}:
            logger.warning("Invalid flow routing mode '%s'; falling back to auto", mode)
            mode = "auto"

        seller_capabilities = self._get_seller_capabilities_artifact()
        seller_has_tag = bool(seller_capabilities.get("has_user_product_seller_tag"))
        user_products_enabled = self.flow_user_products_enabled

        selected_flow = "legacy"
        reason = "Defaulting to legacy flow for backward compatibility."
        blocked = False
        error_message: str | None = None
        fallback_applied = False
        fallback_reason: str | None = None

        if mode == "forced":
            if forced_flow not in AVAILABLE_ROUTING_FLOWS:
                blocked = True
                error_message = (
                    f"Forced publish flow '{forced_flow or 'unset'}' is not supported. "
                    f"Supported values: {', '.join(sorted(AVAILABLE_ROUTING_FLOWS))}."
                )
                reason = "Configured forced flow is invalid."
                selected_flow = forced_flow or "legacy"
            elif forced_flow == "legacy":
                selected_flow = "legacy"
                reason = "Forced legacy flow selected by configuration."
            else:
                selected_flow = "user_products"
                if not user_products_enabled:
                    blocked = True
                    error_message = (
                        "Forced publish flow 'user_products' is disabled by rollout flag "
                        "'flow_routing.user_products_enabled'."
                    )
                    reason = "User-products flow was disabled by rollout controls."
                elif not seller_has_tag:
                    blocked = True
                    error_message = (
                        "Forced publish flow 'user_products' requires seller tag "
                        f"'{USER_PRODUCTS_SELLER_TAG}'."
                    )
                    reason = "Seller is not tagged for user-products flow."
                elif forced_flow not in IMPLEMENTED_ROUTING_FLOWS:
                    blocked = True
                    error_message = (
                        "Forced publish flow 'user_products' is not supported by this release."
                    )
                    reason = "User-products engine is not implemented yet."
        else:
            if seller_has_tag and user_products_enabled:
                selected_flow = "user_products"
                reason = "Seller has user_product_seller capability; using user-products flow."
            elif seller_has_tag:
                reason = (
                    "Seller has user_product_seller capability, but rollout disabled "
                    "user-products flow; using legacy flow."
                )
            else:
                reason = "Seller does not have user_product_seller capability; using legacy flow."

        if blocked and self.flow_blocked_behavior == "fallback_legacy":
            fallback_applied = True
            fallback_reason = error_message or reason
            selected_flow = "legacy"
            blocked = False
            error_message = None
            reason = (
                "Flow routing fallback applied to legacy flow due to rollout setting "
                "'flow_routing.blocked_behavior=fallback_legacy'."
            )

        flow_routing: dict[str, Any] = {
            "mode": mode,
            "selected_flow": selected_flow,
            "seller_has_user_product_seller_tag": seller_has_tag,
            "seller_capability_source": seller_capabilities.get("source"),
            "reason": reason,
            "supported_flows": sorted(IMPLEMENTED_ROUTING_FLOWS),
            "blocked": blocked,
            "user_products_enabled": user_products_enabled,
            "blocked_behavior": self.flow_blocked_behavior,
            "fallback_applied": fallback_applied,
        }
        if forced_flow:
            flow_routing["forced_flow"] = forced_flow
        if error_message:
            flow_routing["error"] = error_message
        if fallback_reason:
            flow_routing["fallback_reason"] = fallback_reason

        artifact = {"flow_routing": flow_routing}
        self._flow_routing_artifact = artifact
        return artifact

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

        flow_artifact = self._get_flow_routing_artifact()
        flow_routing = flow_artifact.get("flow_routing", {})
        if isinstance(flow_routing, dict) and flow_routing.get("blocked"):
            error_msg = str(
                flow_routing.get("error", "Forced publish flow configuration is unsupported.")
            )
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
                        "rollout_flags": deepcopy(self._rollout_flags_artifact),
                    }
                )
                item_results[-1].update(flow_artifact)
            return {
                "success": False,
                "published": 0,
                "failed": len(products),
                "errors": [error_msg],
                "item_results": item_results,
                "flow_routing": flow_routing,
                "rollout_flags": deepcopy(self._rollout_flags_artifact),
            }

        category_context = self._resolve_category_context(products, category_name)
        resolution_artifact = self._build_resolution_artifact(category_context)
        category_input = resolution_artifact["category_input"]
        category_id = resolution_artifact["category_resolved_id"]
        policy_artifact: dict[str, Any] | None = None
        schema_contract_artifact: dict[str, Any] | None = None

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
                        "rollout_flags": deepcopy(self._rollout_flags_artifact),
                    }
                )
                item_results[-1].update(flow_artifact)
                item_results[-1].update(resolution_artifact)
            return {
                "success": False,
                "published": 0,
                "failed": len(products),
                "errors": [error_msg],
                "item_results": item_results,
                "flow_routing": flow_routing,
                "rollout_flags": deepcopy(self._rollout_flags_artifact),
            }

        policy_artifact = self._get_policy_artifact(category_id)
        schema_contract_artifact = self._get_schema_contract_artifact(category_id)

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
                        "rollout_flags": deepcopy(self._rollout_flags_artifact),
                    }
                )
                item_results[-1].update(flow_artifact)
                item_results[-1].update(resolution_artifact)
                if policy_artifact:
                    item_results[-1].update(policy_artifact)
                if schema_contract_artifact:
                    item_results[-1].update(schema_contract_artifact)
            return {
                "success": False,
                "published": 0,
                "failed": len(products),
                "errors": [error_msg],
                "item_results": item_results,
                "flow_routing": flow_routing,
                "rollout_flags": deepcopy(self._rollout_flags_artifact),
            }

        logger.info(f"Publishing {len(products)} products to category {category_id}")

        # Initialize cache mapper for this category
        self._initialize_cache_mapper(category_id)

        for index, product in enumerate(products):
            self._current_cause_codes = []
            self._current_preflight_artifact = {
                "identifier_gate": {"checked": False, "violations": []}
            }
            self._current_cause_taxonomy = []
            self._current_validation_decision = {}
            self._current_image_diagnostics = None
            self._current_shipping_policy = None
            self._current_flow_artifact = {}
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
                            "rollout_flags": deepcopy(self._rollout_flags_artifact),
                        }
                    )
                    self.item_results[-1].update(flow_artifact)
                    self.item_results[-1].update(resolution_artifact)
                    if policy_artifact:
                        self.item_results[-1].update(policy_artifact)
                    if schema_contract_artifact:
                        self.item_results[-1].update(schema_contract_artifact)
                    continue
            previous_error_count = len(self.errors)
            success = self._publish_one(product, category_id)
            item_result: dict[str, Any] = {
                "index": index,
                "sku": product.sku,
                "title": product.title,
                "status": "success" if success else "failed",
                "rollout_flags": deepcopy(self._rollout_flags_artifact),
            }
            if self._current_cause_codes:
                item_result["cause_codes"] = list(dict.fromkeys(self._current_cause_codes))
            if self._current_preflight_artifact:
                item_result.update(self._current_preflight_artifact)
            if self._current_cause_taxonomy:
                item_result["cause_taxonomy"] = deepcopy(self._current_cause_taxonomy)
            if self._current_validation_decision:
                item_result["validation_decision"] = deepcopy(self._current_validation_decision)
            if isinstance(self._current_image_diagnostics, dict):
                item_result["image_diagnostics"] = deepcopy(self._current_image_diagnostics)
            if isinstance(self._current_shipping_policy, dict):
                item_result["shipping_policy"] = deepcopy(self._current_shipping_policy)
            new_errors = self.errors[previous_error_count:]
            if new_errors:
                item_result["error"] = "; ".join(new_errors)
            elif not success:
                item_result["error"] = f"{product.sku}: publish failed"
            item_result.update(flow_artifact)
            if self._current_flow_artifact and isinstance(item_result.get("flow_routing"), dict):
                flow_routing_item = dict(item_result["flow_routing"])
                flow_routing_item.update(self._current_flow_artifact)
                item_result["flow_routing"] = flow_routing_item
            item_result.update(resolution_artifact)
            if policy_artifact:
                item_result.update(policy_artifact)
            if schema_contract_artifact:
                item_result.update(schema_contract_artifact)
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
            "validated": self.published if self.validation_only else 0,
            "failed": self.failed,
            "errors": self.errors,
            "fiscal_submitted": len([r for r in self.fiscal_results if r.success]),
            "fiscal_failed": len([r for r in self.fiscal_results if not r.success]),
            "clips_uploaded": clip_success,
            "clips_failed": clip_failed,
            "clips_details": self.clip_results,
            "item_results": self.item_results,
            "flow_routing": flow_routing,
            "rollout_flags": deepcopy(self._rollout_flags_artifact),
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
        self._current_cause_codes = []
        self._current_cause_taxonomy = []
        self._current_validation_decision = {}
        self._current_publish_category_id = category_id
        self._current_publish_sku = str(product.sku).strip() if product.sku else None
        self._current_variation_reference_attributes = []
        selected_flow = self._resolve_selected_flow()
        self._current_flow_artifact = {
            "payload_builder": (
                "user_products_pxv" if selected_flow == "user_products" else "legacy_variations"
            )
        }

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
            critical_attr_warnings = self._get_critical_attribute_warnings(attr_warnings)
            if critical_attr_warnings and self.strict_attribute_warnings:
                summary = critical_attr_warnings[:5]
                logger.error(
                    "Blocking %s due to critical attribute warnings (%s): %s",
                    product.sku,
                    len(critical_attr_warnings),
                    summary,
                )
                self.errors.append(
                    f"{product.sku}: critical attribute warnings ({len(critical_attr_warnings)}): "
                    f"{summary}"
                )
                self.failed += 1
                return False

        logger.info(f"Final attribute count for {product.sku}: {len(ml_attributes)}")

        # Upload images
        picture_urls = self.image_uploader.upload_images(product.sku)
        picture_ids = self._resolve_picture_ids(picture_urls)

        # Build pictures list
        pictures = [{"source": url} for url in picture_urls]

        if not pictures:
            logger.warning(f"No pictures for {product.sku}")

        # Determine shipping mode from config
        shipping_config = self._build_shipping_config(category_id=category_id)

        logger.debug(f"Shipping config for {product.sku}: {shipping_config}")

        # Load defaults from config (config is the single source of truth)
        core_defaults = self.config.get("core_item_fields", {}).get("defaults", {})

        # Check if listing_type_id was explicitly mapped from spreadsheet
        explicit_listing_type: str | None = None
        variation_candidates: dict[str, list[dict[str, Any]]] = {}
        marker_indexes_to_remove: list[int] = []
        for index, attr in enumerate(ml_attributes):
            if not isinstance(attr, dict):
                continue

            if "_listing_type_id" in attr:
                marker_indexes_to_remove.append(index)
                mapped_listing_type = attr.get("_listing_type_id")
                if (
                    explicit_listing_type is None
                    and isinstance(mapped_listing_type, str)
                    and mapped_listing_type
                ):
                    explicit_listing_type = mapped_listing_type

            if "_variation_candidates" in attr:
                marker_indexes_to_remove.append(index)
                raw_candidates = attr.get("_variation_candidates")
                if not isinstance(raw_candidates, dict):
                    continue

                for attr_id, values in raw_candidates.items():
                    if not isinstance(attr_id, str) or not isinstance(values, list):
                        continue
                    bucket = variation_candidates.setdefault(attr_id, [])
                    existing = {
                        (value.get("id"), value.get("name"))
                        for value in bucket
                        if isinstance(value, dict)
                    }
                    for value in values:
                        if not isinstance(value, dict):
                            continue
                        key = (value.get("id"), value.get("name"))
                        if key in existing:
                            continue
                        existing.add(key)
                        bucket.append(value)
        if marker_indexes_to_remove:
            ml_attributes = [
                attr
                for index, attr in enumerate(ml_attributes)
                if index not in marker_indexes_to_remove
            ]
        self._current_variation_reference_attributes = [
            attr for attr in ml_attributes if isinstance(attr, dict)
        ]

        variations: list[dict[str, Any]] = []
        user_products_payload: dict[str, Any] | None = None
        if selected_flow == "legacy":
            if variation_candidates:
                variations = self._build_variations_from_candidates(
                    variation_candidates=variation_candidates,
                    quantity=product.available_quantity,
                    price=product.price,
                    picture_ids=picture_ids,
                )
                if variations:
                    legacy_variation_attr_ids = {
                        attr.get("id")
                        for variation in variations
                        if isinstance(variation, dict)
                        for attr in variation.get("attribute_combinations", [])
                        if isinstance(attr, dict) and isinstance(attr.get("id"), str)
                    }
                    ml_attributes = [
                        attr
                        for attr in ml_attributes
                        if not (
                            isinstance(attr, dict)
                            and isinstance(attr.get("id"), str)
                            and attr["id"] in legacy_variation_attr_ids
                        )
                    ]
        elif selected_flow == "user_products":
            try:
                user_products_payload = self._build_user_products_payload(
                    product=product,
                    ml_attributes=ml_attributes,
                    variation_candidates=variation_candidates,
                    quantity=product.available_quantity,
                    price=product.price,
                    picture_ids=picture_ids,
                )
            except ValueError as error:
                message = f"User-products flow blocked: {error}"
                logger.error(f"{product.sku}: {message}")
                self._current_cause_codes = ["flow_routing.user_products_payload"]
                self.errors.append(f"{product.sku}: {message}")
                self.failed += 1
                return False

            self._current_flow_artifact.update(
                {
                    "selected_model": user_products_payload.get("selected_model"),
                    "up_family_name": user_products_payload.get("family_name"),
                    "up_family_name_source": user_products_payload.get("family_name_source"),
                    "up_variation_count": len(user_products_payload.get("variations", [])),
                    "up_attribute_ids": user_products_payload.get("variation_attribute_ids", []),
                }
            )

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
        if selected_flow != "user_products":
            item["title"] = product.title

        channels = core_defaults.get("channels")
        if channels:
            item["channels"] = channels
        if selected_flow == "legacy" and variations:
            item["variations"] = variations
        if selected_flow == "user_products" and user_products_payload:
            item["family_name"] = user_products_payload["family_name"]

        # Log shipping section before validation
        logger.info(
            f"Final shipping config for {product.sku}: mode={shipping_config.get('mode')}, "
            f"free_shipping={shipping_config.get('free_shipping')}, "
            f"logistic_type={shipping_config.get('logistic_type')}, "
            f"local_pick_up={shipping_config.get('local_pick_up')}"
        )

        if self.dry_run and not self.validation_only:
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

        preflight_violations = self._run_schema_contract_preflight(
            category_id=category_id,
            item=item,
        )
        if preflight_violations:
            message = f"Schema preflight failed: {'; '.join(preflight_violations)}"
            logger.error(f"{product.sku}: {message}")
            self._current_cause_codes = ["schema_contract.preflight"]
            self._current_cause_taxonomy = [
                {
                    "type": "error",
                    "code": "schema_contract.preflight",
                    "message": message,
                    "classification": "blocking_error",
                }
            ]
            self._current_validation_decision = self._build_validation_decision(
                self._current_cause_taxonomy
            )
            self.errors.append(f"{product.sku}: {message}")
            self.failed += 1
            return False

        self._current_image_diagnostics = self._run_image_diagnostic_preflight(
            sku=product.sku,
            title=product.title,
            category_id=category_id,
            picture_urls=picture_urls,
            picture_ids=picture_ids,
        )
        raw_diagnostic_issues = (
            self._current_image_diagnostics.get("issues")
            if isinstance(self._current_image_diagnostics, dict)
            else []
        )
        diagnostic_issues = (
            [str(issue) for issue in raw_diagnostic_issues if str(issue).strip()]
            if isinstance(raw_diagnostic_issues, list)
            else []
        )
        if diagnostic_issues and self.image_diagnostics_gate_mode == "enforce":
            message = f"Image diagnostic preflight failed: {'; '.join(diagnostic_issues)}"
            logger.error(f"{product.sku}: {message}")
            self._current_cause_codes = ["image_diagnostic.preflight"]
            self._current_cause_taxonomy = [
                {
                    "type": "error",
                    "code": "image_diagnostic.preflight",
                    "message": message,
                    "classification": "blocking_error",
                }
            ]
            self._current_validation_decision = self._build_validation_decision(
                self._current_cause_taxonomy
            )
            self.errors.append(f"{product.sku}: {message}")
            self.failed += 1
            return False
        if diagnostic_issues:
            logger.warning(
                "Image diagnostic issues detected for %s but gate mode '%s' allows continuation.",
                product.sku,
                self.image_diagnostics_gate_mode,
            )

        logger.debug(f"Full item payload for {product.sku}: {item}")

        # Validate
        validation_result = None
        try:
            validation = self._validate_item_for_flow(item=item, selected_flow=selected_flow)
            logger.debug(f"Validation response for {product.sku}: {validation}")

            raw_causes = validation.get("cause", [])
            causes = [cause for cause in raw_causes if isinstance(cause, dict)]
            for cause in causes:
                logger.debug(f"Validation cause for {product.sku}: {cause}")
            shipping_cause_decisions = self._register_shipping_causes(causes, stage="validate")
            cause_taxonomy = self._build_validation_cause_taxonomy(causes)
            self._current_cause_taxonomy = cause_taxonomy
            self._current_cause_codes = list(
                dict.fromkeys(
                    str(cause.get("code", "")).strip().lower()
                    for cause in cause_taxonomy
                    if str(cause.get("code", "")).strip()
                )
            )
            self._current_validation_decision = (
                self._build_validation_decision(cause_taxonomy) if cause_taxonomy else {}
            )

            shipping_issues = [
                f"{decision['code']}: {decision['message']}"
                for decision in shipping_cause_decisions
            ]
            # Log shipping issues
            if shipping_issues:
                logger.info(f"Shipping validation issues for {product.sku}: {shipping_issues}")

            warnings = [
                f"{cause.get('code', '')}: {cause.get('message', '')}"
                for cause in cause_taxonomy
                if cause.get("classification") in {"critical_warning", "informational_warning"}
            ]
            if warnings:
                logger.warning(f"Validation warnings for {product.sku}: {warnings}")
            decision_action = str(self._current_validation_decision.get("action", "allow"))
            classification_codes = self._current_validation_decision.get("classification_codes", {})
            if not isinstance(classification_codes, dict):
                classification_codes = {}
            blocking_error_codes = classification_codes.get("blocking_error", [])
            retryable_error_codes = classification_codes.get("retryable_error", [])
            critical_warning_codes = classification_codes.get("critical_warning", [])

            if decision_action == "block":
                if blocking_error_codes:
                    logger.error(
                        "Validation failed for %s due to blocking errors: %s",
                        product.sku,
                        blocking_error_codes,
                    )
                    self.errors.append(
                        f"{product.sku}: blocking validation errors: {blocking_error_codes}"
                    )
                elif retryable_error_codes:
                    logger.error(
                        "Strict mode blocked %s due to retryable validation errors: %s",
                        product.sku,
                        retryable_error_codes,
                    )
                    self.errors.append(
                        f"{product.sku}: retryable validation errors blocked by strict mode: "
                        f"{retryable_error_codes}"
                    )
                elif critical_warning_codes:
                    summary = critical_warning_codes[:5]
                    logger.error(
                        "Blocking %s due to critical validation warnings (%s): %s",
                        product.sku,
                        len(critical_warning_codes),
                        summary,
                    )
                    self.errors.append(
                        f"{product.sku}: critical validation warnings "
                        f"({len(critical_warning_codes)}): {summary}"
                    )
                else:
                    self.errors.append(f"{product.sku}: validation blocked by decision policy")
                self.failed += 1
                if self.feedback:
                    self.feedback.record_validation_result(product.sku, ml_attributes, validation)
                return False

            if decision_action == "retry":
                logger.error(
                    "Validation for %s returned retryable errors (controlled mode): %s",
                    product.sku,
                    retryable_error_codes,
                )
                self.errors.append(
                    f"{product.sku}: retryable validation errors (retry suggested): "
                    f"{retryable_error_codes}"
                )
                self.failed += 1
                if self.feedback:
                    self.feedback.record_validation_result(product.sku, ml_attributes, validation)
                return False

            blocking_shipping_causes = [
                decision
                for decision in shipping_cause_decisions
                if decision.get("classification") == "blocking"
            ]
            if blocking_shipping_causes and decision_action == "allow":
                summary = [f"{d['code']}: {d['message']}" for d in blocking_shipping_causes[:5]]
                codes = [
                    str(decision.get("code", ""))
                    for decision in blocking_shipping_causes
                    if str(decision.get("code", "")).strip()
                ]
                self._current_cause_codes = list(dict.fromkeys(codes))
                self.errors.append(
                    f"{product.sku}: deterministic shipping policy violation "
                    f"({len(blocking_shipping_causes)}): {summary}"
                )
                self.failed += 1
                if self.feedback:
                    self.feedback.record_validation_result(product.sku, ml_attributes, validation)
                return False

            # Record validation result for feedback
            validation_result = validation
        except Exception as e:
            # Try to extract error details from exception
            error_msg = str(e)
            cause_codes: list[str] = []
            validation_exception_taxonomy: list[dict[str, str]] = []
            error_detail = None
            if hasattr(e, "response") and e.response is not None:
                try:
                    error_detail = e.response.json()
                    error_msg = f"{error_msg} - {error_detail}"
                    # Check for shipping-specific errors
                    causes_raw = (
                        error_detail.get("cause", []) if isinstance(error_detail, dict) else []
                    )
                    causes = causes_raw if isinstance(causes_raw, list) else []
                    shipping_cause_decisions = self._register_shipping_causes(
                        causes, stage="validate_exception"
                    )
                    normalized_causes = [cause for cause in causes if isinstance(cause, dict)]
                    validation_exception_taxonomy = self._build_validation_cause_taxonomy(
                        normalized_causes
                    )
                    for cause in causes:
                        if not isinstance(cause, dict):
                            continue
                        cause_code = str(cause.get("code", "")).strip()
                        if cause_code:
                            cause_codes.append(cause_code)
                    for shipping_cause in shipping_cause_decisions:
                        logger.error(
                            "Shipping validation error for %s: [%s] %s",
                            product.sku,
                            shipping_cause.get("classification"),
                            shipping_cause,
                        )
                except Exception:
                    error_msg = f"{error_msg} - {e.response.text[:200]}"
            self._current_cause_codes = list(
                dict.fromkeys(code.lower() for code in cause_codes if str(code).strip())
            )
            self._current_cause_taxonomy = validation_exception_taxonomy
            self._current_validation_decision = (
                self._build_validation_decision(validation_exception_taxonomy)
                if validation_exception_taxonomy
                else {}
            )
            logger.error(f"Validation error for {product.sku}: {error_msg}")
            self.errors.append(f"{product.sku}: {error_msg}")
            self.failed += 1
            return False

        if self.validation_only:
            logger.info(f"VALIDATION ONLY: Payload valid for {product.sku}")
            self.published += 1
            if self.feedback and validation_result:
                self.feedback.record_validation_result(
                    product.sku, ml_attributes, validation_result
                )
            return True

        # Publish
        published_item_id: str | None = None
        cbt_item_id: str | None = None
        try:
            result = self._create_item_for_flow(item=item, selected_flow=selected_flow)
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
            publish_cause_codes: list[str] = []
            if hasattr(e, "response") and e.response is not None:
                try:
                    error_detail = e.response.json()
                    error_msg = f"{error_msg} - {error_detail}"
                    # Check for shipping-specific errors
                    causes_raw = (
                        error_detail.get("cause", []) if isinstance(error_detail, dict) else []
                    )
                    causes = causes_raw if isinstance(causes_raw, list) else []
                    # Record publish failure feedback
                    if self.feedback:
                        self.feedback.record_validation_result(
                            product.sku,
                            ml_attributes,
                            error_detail if isinstance(error_detail, dict) else {},
                        )
                    for cause in causes:
                        if not isinstance(cause, dict):
                            continue
                        cause_code = str(cause.get("code", "")).strip()
                        if cause_code:
                            publish_cause_codes.append(cause_code)
                    shipping_cause_decisions = self._register_shipping_causes(
                        causes, stage="publish_exception"
                    )
                    for shipping_cause in shipping_cause_decisions:
                        logger.error(
                            "Shipping publish error for %s: [%s] %s",
                            product.sku,
                            shipping_cause.get("classification"),
                            shipping_cause,
                        )
                except Exception:
                    error_msg = f"{error_msg} - {e.response.text[:200]}"
            self._current_cause_codes = list(
                dict.fromkeys(code for code in publish_cause_codes if str(code).strip())
            )
            logger.error(f"Publish error for {product.sku}: {error_msg}")
            self.errors.append(f"{product.sku}: {error_msg}")
            self.failed += 1
            return False

    def _resolve_selected_flow(self) -> str:
        """Resolve currently selected publish flow with legacy fallback."""
        flow_artifact = self._get_flow_routing_artifact()
        flow_routing = flow_artifact.get("flow_routing", {})
        if isinstance(flow_routing, dict):
            selected_flow = flow_routing.get("selected_flow")
            if isinstance(selected_flow, str) and selected_flow in IMPLEMENTED_ROUTING_FLOWS:
                return selected_flow
        return "legacy"

    def _validate_item_for_flow(
        self, *, item: dict[str, Any], selected_flow: str
    ) -> dict[str, Any]:
        """Validate payload using the selected publish route."""
        if selected_flow == "user_products":
            validator = getattr(self.publisher, "validate_user_product_item", None)
            if callable(validator):
                return cast(dict[str, Any], validator(item))
        return self.publisher.validate_item(item)

    def _create_item_for_flow(self, *, item: dict[str, Any], selected_flow: str) -> dict[str, Any]:
        """Publish payload using the selected publish route."""
        if selected_flow == "user_products":
            creator = getattr(self.publisher, "create_user_product_item", None)
            if callable(creator):
                return cast(dict[str, Any], creator(item))
        return self.publisher.create_item(item)

    @staticmethod
    def _extract_user_products_family_name(product: Product) -> str | None:
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

    @staticmethod
    def _extract_selected_model(
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
        family_name = self._extract_user_products_family_name(product)
        family_name_source = "attribute"
        if not family_name:
            title_fallback = str(product.title).strip() if product.title else ""
            if title_fallback:
                family_name = title_fallback
                family_name_source = "title"
        if not family_name:
            raise ValueError("missing required field 'family_name' and no title fallback.")

        selected_model = self._extract_selected_model(ml_attributes, variation_candidates)

        normalized_candidates = self._normalize_variation_candidates(variation_candidates)
        variations: list[dict[str, Any]] = []
        if normalized_candidates:
            combinations = list(
                cartesian_product(*(values for _attr_id, values in normalized_candidates))
            )
            for combination in combinations:
                attributes: list[dict[str, Any]] = []
                for (attr_id, _values), value in zip(
                    normalized_candidates, combination, strict=True
                ):
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

    @staticmethod
    def _normalize_variation_candidates(
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

    @staticmethod
    def _variation_value_sort_key(value: dict[str, Any]) -> tuple[str, str]:
        """Return deterministic sort key for variation candidate values."""
        value_name = value.get("name")
        value_id = value.get("id")
        normalized_name = (
            PortugueseTextNormalizer.normalize(str(value_name))
            if isinstance(value_name, str)
            else ""
        )
        normalized_id = str(value_id).strip() if value_id is not None else ""
        return normalized_name, normalized_id

    def _get_legacy_variation_contract(self) -> tuple[list[str], dict[str, Any]]:
        """Return allow_variations IDs and limits for the current category."""
        category_id = self._current_publish_category_id
        if not category_id:
            return [], {}

        compiled = self._get_schema_contract_compiled(category_id)
        schema_contract = compiled.get("schema_contract", {})
        if not isinstance(schema_contract, dict):
            return [], {}

        allow_variations_raw = schema_contract.get("allow_variations_attribute_ids", [])
        allow_variations_attribute_ids = []
        if isinstance(allow_variations_raw, list):
            allow_variations_attribute_ids = [
                attr_id.strip()
                for attr_id in allow_variations_raw
                if isinstance(attr_id, str) and attr_id.strip()
            ]

        limits = schema_contract.get("limits", {})
        if not isinstance(limits, dict):
            limits = {}

        return allow_variations_attribute_ids, limits

    def _get_mapped_variation_candidate(self, attr_id: str) -> dict[str, Any] | None:
        """Resolve mapped attribute payload as preferred variation candidate."""
        for attribute in self._current_variation_reference_attributes:
            if not isinstance(attribute, dict):
                continue
            raw_attr_id = attribute.get("id")
            if not isinstance(raw_attr_id, str) or raw_attr_id != attr_id:
                continue

            value_name = attribute.get("value_name")
            value_id = attribute.get("value_id")
            if isinstance(value_name, str) and value_name.strip():
                return {"id": value_id, "name": value_name.strip()}
            if value_id is not None and str(value_id).strip():
                normalized_value_id = str(value_id).strip()
                return {"id": value_id, "name": normalized_value_id}
        return None

    def _build_legacy_variation_seller_sku(self, index: int) -> str | None:
        """Build deterministic SELLER_SKU value for legacy variation attributes."""
        base_sku = self._current_publish_sku
        if not isinstance(base_sku, str) or not base_sku.strip():
            return None
        normalized_sku = re.sub(r"\s+", "-", base_sku.strip())
        if not normalized_sku:
            return None
        return f"{normalized_sku}-{index:03d}"

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

    def _build_variations_from_candidates(
        self,
        variation_candidates: dict[str, list[dict[str, Any]]],
        quantity: int,
        price: float,
        picture_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Build variations payload from candidate values extracted during mapping."""
        normalized_candidates = self._normalize_variation_candidates(variation_candidates)
        if not normalized_candidates:
            return []

        allow_variations_attribute_ids, limits = self._get_legacy_variation_contract()
        candidates_by_id = dict(normalized_candidates)
        preferred_attr_ids = [
            attr_id for attr_id in allow_variations_attribute_ids if attr_id in candidates_by_id
        ]
        variation_attr_ids = preferred_attr_ids or [
            attr_id for attr_id, _values in normalized_candidates
        ]

        grouped_candidates: list[tuple[str, list[dict[str, Any]]]] = []
        for attr_id in variation_attr_ids:
            values = list(candidates_by_id.get(attr_id, []))
            if not values:
                continue
            values = sorted(values, key=self._variation_value_sort_key)
            mapped_candidate = self._get_mapped_variation_candidate(attr_id)
            if mapped_candidate is not None:
                normalized_mapped_name = PortugueseTextNormalizer.normalize(
                    mapped_candidate["name"]
                )
                preferred_index = next(
                    (
                        index
                        for index, candidate in enumerate(values)
                        if PortugueseTextNormalizer.normalize(str(candidate.get("name", "")))
                        == normalized_mapped_name
                    ),
                    None,
                )
                if preferred_index is not None:
                    preferred_candidate = values.pop(preferred_index)
                    if (
                        preferred_candidate.get("id") is None
                        and mapped_candidate.get("id") is not None
                    ):
                        preferred_candidate["id"] = mapped_candidate.get("id")
                    values.insert(0, preferred_candidate)
                else:
                    values.insert(0, mapped_candidate)
            grouped_candidates.append((attr_id, values))

        if not grouped_candidates:
            return []

        max_pictures = limits.get("max_pictures")
        max_picture_count = 10
        if isinstance(max_pictures, int) and max_pictures >= 0:
            max_picture_count = min(max_picture_count, max_pictures)

        unique_picture_ids = list(dict.fromkeys(picture_ids or []))
        scoped_picture_ids = unique_picture_ids[:max_picture_count]
        if not scoped_picture_ids:
            logger.warning(
                "Variation candidates detected but no scoped picture IDs are available; "
                "skipping variations payload."
            )
            return []

        max_variations_allowed = limits.get("max_variations_allowed")
        if (
            isinstance(max_variations_allowed, int)
            and max_variations_allowed >= 0
            and max_variations_allowed < 2
        ):
            logger.info(
                "Category variation limit %s prevents legacy variation payload generation.",
                max_variations_allowed,
            )
            return []

        combinations = list(cartesian_product(*(values for _attr_id, values in grouped_candidates)))
        if len(combinations) <= 1:
            return []
        if isinstance(max_variations_allowed, int) and max_variations_allowed >= 2:
            combinations = combinations[:max_variations_allowed]
            if len(combinations) <= 1:
                return []

        variations: list[dict[str, Any]] = []
        for index, combination in enumerate(combinations, start=1):
            attribute_combinations = []
            for (attr_id, _values), value in zip(grouped_candidates, combination, strict=True):
                mapped = {"id": attr_id, "value_name": value["name"]}
                value_id = value.get("id")
                if value_id is not None:
                    mapped["value_id"] = value_id
                attribute_combinations.append(mapped)

            variation: dict[str, Any] = {
                "attribute_combinations": attribute_combinations,
                "available_quantity": max(1, quantity),
                "price": price,
                "picture_ids": scoped_picture_ids,
            }
            seller_sku = self._build_legacy_variation_seller_sku(index)
            if seller_sku:
                variation["attributes"] = [{"id": "SELLER_SKU", "value_name": seller_sku}]

            variations.append(variation)

        return variations

    @staticmethod
    def _split_multi_value(raw_value: str | None) -> list[str]:
        """Split a multi-value cell string into normalized tokens."""
        if not isinstance(raw_value, str):
            return []
        return [part.strip() for part in re.split(r"[,;/|]", raw_value) if part.strip()]

    def _resolve_picture_ids(self, picture_urls: list[str]) -> list[str]:
        """Resolve ML picture IDs for current picture URLs from uploader history."""
        getter = getattr(self.image_uploader, "get_uploaded_images", None)
        if not callable(getter):
            return []

        try:
            uploaded_images = getter()
        except Exception as error:
            logger.warning("Could not read uploaded image IDs: %s", error)
            return []

        if not isinstance(uploaded_images, list):
            return []

        url_to_id: dict[str, str] = {}
        for image in uploaded_images:
            if not isinstance(image, dict):
                continue
            url = image.get("url")
            image_id = image.get("id")
            if isinstance(url, str) and isinstance(image_id, str) and url and image_id:
                url_to_id[url] = image_id

        return [url_to_id[url] for url in picture_urls if url in url_to_id]

    def _get_policy_category_data(self, category_id: str) -> dict[str, Any]:
        """Fetch category metadata for policy compilation."""
        getter = getattr(self.category_resolver, "get_category_data", None)
        if callable(getter):
            try:
                result = getter(category_id)
            except Exception as error:
                logger.warning(
                    "Could not fetch category metadata for policy snapshot %s: %s",
                    category_id,
                    error,
                )
                return {}
            if isinstance(result, dict):
                return result
            logger.warning(
                "Unexpected category metadata payload for policy snapshot %s: %s",
                category_id,
                type(result).__name__,
            )
            return {}

        cached_getter = getattr(self.category_resolver, "_get_category_cached", None)
        if callable(cached_getter):
            try:
                result = cached_getter(category_id)
            except Exception as error:
                logger.warning(
                    "Could not fetch cached category metadata for policy snapshot %s: %s",
                    category_id,
                    error,
                )
                return {}
            if isinstance(result, dict):
                return result

        logger.warning(
            "Category resolver does not expose category metadata for policy snapshot %s",
            category_id,
        )
        return {}

    def _build_policy_attribute_rows(self, attributes: list[Any]) -> list[dict[str, Any]]:
        """Normalize arbitrary attribute metadata payloads into dict rows."""
        normalized_rows: list[dict[str, Any]] = []
        for attribute in attributes:
            if isinstance(attribute, dict):
                attr_id = attribute.get("id")
                if isinstance(attr_id, str) and attr_id:
                    row: dict[str, Any] = {"id": attr_id, "tags": attribute.get("tags", {})}
                    raw_values = attribute.get("values")
                    normalized_values: list[dict[str, str]] = []
                    if isinstance(raw_values, list):
                        for raw_value in raw_values:
                            if not isinstance(raw_value, dict):
                                continue
                            value_row: dict[str, str] = {}
                            value_id = raw_value.get("id")
                            value_name = raw_value.get("name")
                            if value_id is not None:
                                normalized_value_id = str(value_id).strip()
                                if normalized_value_id:
                                    value_row["id"] = normalized_value_id
                            if value_name is not None:
                                normalized_value_name = str(value_name).strip()
                                if normalized_value_name:
                                    value_row["name"] = normalized_value_name
                            if value_row:
                                normalized_values.append(value_row)
                    if normalized_values:
                        row["values"] = normalized_values
                    normalized_rows.append(row)
                continue

            attr_id = getattr(attribute, "id", None)
            if not isinstance(attr_id, str) or not attr_id:
                continue
            raw_tags = getattr(attribute, "tags", {})
            if isinstance(raw_tags, set):
                tags_payload: Any = sorted(raw_tags)
            else:
                tags_payload = raw_tags
            row = {"id": attr_id, "tags": tags_payload}

            raw_values = getattr(attribute, "values", None)
            normalized_values = []
            if isinstance(raw_values, list):
                for raw_value in raw_values:
                    if not isinstance(raw_value, dict):
                        continue
                    fallback_value_row: dict[str, str] = {}
                    value_id = raw_value.get("id")
                    value_name = raw_value.get("name")
                    if value_id is not None:
                        normalized_value_id = str(value_id).strip()
                        if normalized_value_id:
                            fallback_value_row["id"] = normalized_value_id
                    if value_name is not None:
                        normalized_value_name = str(value_name).strip()
                        if normalized_value_name:
                            fallback_value_row["name"] = normalized_value_name
                    if fallback_value_row:
                        normalized_values.append(fallback_value_row)
            else:
                allowed_values = getattr(attribute, "allowed_values", None)
                if isinstance(allowed_values, set):
                    normalized_values = [
                        {"name": str(value).strip()}
                        for value in sorted(allowed_values)
                        if str(value).strip()
                    ]

            if normalized_values:
                row["values"] = normalized_values
            normalized_rows.append(row)

        return normalized_rows

    def _get_policy_attributes(self, category_id: str) -> list[dict[str, Any]]:
        """Fetch category attributes for policy compilation."""
        getter = getattr(self.category_resolver, "get_all_attributes", None)
        if callable(getter):
            try:
                result = getter(category_id)
            except Exception as error:
                logger.warning(
                    "Could not fetch category attributes for policy snapshot %s: %s",
                    category_id,
                    error,
                )
            else:
                if isinstance(result, list):
                    return self._build_policy_attribute_rows(result)
                logger.warning(
                    "Unexpected category attributes payload for policy snapshot %s: %s",
                    category_id,
                    type(result).__name__,
                )
                return []

        metadata_getter = getattr(self.category_resolver, "get_attribute_metadata", None)
        if callable(metadata_getter):
            try:
                result = metadata_getter(category_id)
            except Exception as error:
                logger.warning(
                    "Could not fetch attribute metadata for policy snapshot %s: %s",
                    category_id,
                    error,
                )
                return []
            if isinstance(result, list):
                return self._build_policy_attribute_rows(result)
            logger.warning(
                "Unexpected attribute metadata payload for policy snapshot %s: %s",
                category_id,
                type(result).__name__,
            )
            return []

        logger.warning(
            "Category resolver does not expose attributes for policy snapshot %s",
            category_id,
        )
        return []

    def _get_policy_artifact(self, category_id: str) -> dict[str, Any]:
        """Compile and cache policy hash/summary for a category."""
        cached = self._category_policy_cache.get(category_id)
        if cached is not None:
            return cached

        category_data = self._get_policy_category_data(category_id)
        attributes = self._get_policy_attributes(category_id)
        listing_types = self._get_available_listing_type_ids(category_id)
        sale_terms = list(self._get_category_sale_terms_map(category_id).values())
        try:
            compiled = compile_policy_snapshot(
                category_id=category_id,
                category_data=category_data,
                attributes=attributes,
                listing_types=listing_types,
                sale_terms=sale_terms,
            )
        except Exception as error:
            logger.error("Failed to compile policy snapshot for %s: %s", category_id, error)
            compiled = compile_policy_snapshot(
                category_id=category_id,
                category_data={},
                attributes=[],
                listing_types=[],
                sale_terms=[],
            )

        artifact = {
            "policy_hash": compiled["policy_hash"],
            "policy_summary": compiled["policy_summary"],
        }
        self._category_policy_cache[category_id] = artifact
        return artifact

    def _get_schema_contract_compiled(self, category_id: str) -> dict[str, Any]:
        """Compile and cache schema contract for a category."""
        cached = self._category_schema_contract_cache.get(category_id)
        if cached is not None:
            return cached

        category_data = self._get_policy_category_data(category_id)
        attributes = self._get_policy_attributes(category_id)
        sale_terms = list(self._get_category_sale_terms_map(category_id).values())

        try:
            compiled = compile_schema_contract(
                category_id=category_id,
                category_data=category_data,
                attributes=attributes,
                sale_terms=sale_terms,
            )
        except Exception as error:
            logger.error("Failed to compile schema contract for %s: %s", category_id, error)
            compiled = compile_schema_contract(
                category_id=category_id,
                category_data={},
                attributes=[],
                sale_terms=[],
            )

        summary = compiled.get("schema_contract_summary", {})
        if isinstance(summary, dict):
            if summary.get("required_attribute_count", 0) == 0:
                logger.info(
                    "Schema contract %s has no deterministic required attributes metadata.",
                    category_id,
                )
            if (
                summary.get("max_pictures") is None
                and summary.get("max_variations_allowed") is None
            ):
                logger.info(
                    "Schema contract %s has no category limits metadata for pictures/variations.",
                    category_id,
                )

        self._category_schema_contract_cache[category_id] = compiled
        return compiled

    def _get_schema_contract_artifact(self, category_id: str) -> dict[str, Any]:
        """Return compact schema contract metadata for reports."""
        compiled = self._get_schema_contract_compiled(category_id)
        artifact: dict[str, Any] = {}
        schema_contract_hash = compiled.get("schema_contract_hash")
        if isinstance(schema_contract_hash, str) and schema_contract_hash:
            artifact["schema_contract_hash"] = schema_contract_hash
        summary = compiled.get("schema_contract_summary")
        if isinstance(summary, dict):
            artifact["schema_contract_summary"] = summary
        return artifact

    def _run_image_diagnostic_preflight(
        self,
        *,
        sku: str,
        title: str,
        category_id: str,
        picture_urls: list[str],
        picture_ids: list[str],
    ) -> dict[str, Any]:
        """Run optional image diagnostics before validate/publish gates."""
        artifact: dict[str, Any] = {
            "status": "unavailable",
            "available": False,
            "checked": 0,
            "issues": [],
            "results": [],
        }

        if self.image_diagnostics_gate_mode == "disabled":
            artifact["status"] = "skipped"
            artifact["message"] = (
                "Image diagnostics gate disabled by rollout flag " "'image_diagnostics.gate_mode'."
            )
            return self._annotate_image_diagnostics_artifact(artifact)

        diagnose_images = getattr(self.image_uploader, "diagnose_images", None)
        if not callable(diagnose_images):
            message = (
                "Image diagnostics unavailable: image uploader does not expose diagnose_images."
            )
            logger.warning(message)
            artifact["message"] = message
            return self._annotate_image_diagnostics_artifact(artifact)

        try:
            diagnostic_result = diagnose_images(
                sku=sku,
                category_id=category_id,
                title=title,
                picture_urls=picture_urls,
                picture_ids=picture_ids,
            )
        except Exception as error:
            message = f"Image diagnostics preflight failed for {sku}: {error}"
            logger.warning(message)
            artifact["message"] = message
            return self._annotate_image_diagnostics_artifact(artifact)

        if isinstance(diagnostic_result, dict):
            return self._annotate_image_diagnostics_artifact(diagnostic_result)

        message = (
            "Image diagnostics preflight returned unexpected payload type: "
            f"{type(diagnostic_result).__name__}"
        )
        logger.warning(message)
        artifact["message"] = message
        return self._annotate_image_diagnostics_artifact(artifact)

    @staticmethod
    def _normalize_identifier_text(value: Any) -> str | None:
        """Normalize a generic identifier/fallback value."""
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        normalized_text = PortugueseTextNormalizer.normalize(text)
        if normalized_text in IDENTIFIER_EMPTY_TOKENS:
            return None
        return text

    def _normalize_gtin_value(self, value: Any) -> str | None:
        """Normalize GTIN into digits-only representation."""
        text = self._normalize_identifier_text(value)
        if text is None:
            return None
        digits_only = re.sub(r"\D", "", text)
        return digits_only or None

    def _collect_identifier_state(self, attributes: Any) -> dict[str, Any]:
        """Collect and normalize GTIN/EMPTY_GTIN_REASON state from attribute payload."""
        state: dict[str, Any] = {
            "gtin": None,
            "gtin_attribute_present": False,
            "empty_gtin_reason_attribute_present": False,
            "empty_gtin_reason_value_id": None,
            "empty_gtin_reason_value_name": None,
            "has_identifier_attribute": False,
        }
        if not isinstance(attributes, list):
            return state

        for attribute in attributes:
            if not isinstance(attribute, dict):
                continue
            attribute_id = attribute.get("id")
            if not isinstance(attribute_id, str) or not attribute_id:
                continue
            normalized_id = attribute_id.strip().upper()

            if normalized_id == "GTIN":
                state["gtin_attribute_present"] = True
                candidate_raw = attribute.get("value_name")
                if candidate_raw in (None, ""):
                    candidate_raw = attribute.get("value_id")
                normalized_gtin = self._normalize_gtin_value(candidate_raw)
                if normalized_gtin:
                    state["gtin"] = normalized_gtin
                    attribute["value_name"] = normalized_gtin
                    if "value_id" in attribute:
                        attribute["value_id"] = normalized_gtin
                continue

            if normalized_id != "EMPTY_GTIN_REASON":
                continue

            state["empty_gtin_reason_attribute_present"] = True
            normalized_reason_id = self._normalize_identifier_text(attribute.get("value_id"))
            normalized_reason_name = self._normalize_identifier_text(attribute.get("value_name"))
            if normalized_reason_id is not None:
                state["empty_gtin_reason_value_id"] = normalized_reason_id
                attribute["value_id"] = normalized_reason_id
            if normalized_reason_name is not None:
                state["empty_gtin_reason_value_name"] = normalized_reason_name
                attribute["value_name"] = normalized_reason_name

        state["has_identifier_attribute"] = bool(
            state["gtin_attribute_present"] or state["empty_gtin_reason_attribute_present"]
        )
        return state

    def _is_valid_empty_gtin_reason(
        self,
        *,
        state: dict[str, Any],
        allowed_reason_ids: set[str],
        allowed_reason_names: set[str],
    ) -> bool:
        """Validate fallback reason against local schema metadata when available."""
        reason_id = state.get("empty_gtin_reason_value_id")
        reason_name = state.get("empty_gtin_reason_value_name")
        has_reason = bool(reason_id or reason_name)
        if not has_reason:
            return False

        if not allowed_reason_ids and not allowed_reason_names:
            return True
        if isinstance(reason_id, str) and reason_id in allowed_reason_ids:
            return True
        if isinstance(reason_name, str):
            normalized_name = PortugueseTextNormalizer.normalize(reason_name)
            if normalized_name in allowed_reason_names:
                return True
        return False

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
        """Validate identifier coherence for item/variation scope."""
        violations: list[str] = []
        gtin = state.get("gtin")
        has_gtin = isinstance(gtin, str) and bool(gtin)
        has_reason = bool(
            state.get("empty_gtin_reason_value_id") or state.get("empty_gtin_reason_value_name")
        )

        if has_gtin and isinstance(gtin, str) and not (8 <= len(gtin) <= 14):
            violations.append(f"{scope} GTIN must contain between 8 and 14 digits")

        if enforce_identifier_coverage and not has_gtin and not has_reason:
            violations.append(f"{scope} missing GTIN/EMPTY_GTIN_REASON identifier coverage")
            return violations

        if gtin_required and not has_gtin:
            if fallback_reason_available:
                if not has_reason:
                    violations.append(f"{scope} missing GTIN; EMPTY_GTIN_REASON is required")
                    return violations
                if not self._is_valid_empty_gtin_reason(
                    state=state,
                    allowed_reason_ids=allowed_reason_ids,
                    allowed_reason_names=allowed_reason_names,
                ):
                    violations.append(f"{scope} has invalid EMPTY_GTIN_REASON metadata")
            else:
                violations.append(f"{scope} missing GTIN required by schema contract")
            return violations

        if has_reason and not self._is_valid_empty_gtin_reason(
            state=state,
            allowed_reason_ids=allowed_reason_ids,
            allowed_reason_names=allowed_reason_names,
        ):
            violations.append(f"{scope} has invalid EMPTY_GTIN_REASON metadata")

        return violations

    def _run_identifier_preflight_checks(
        self,
        *,
        schema_contract: dict[str, Any],
        item: dict[str, Any],
    ) -> tuple[list[str], dict[str, Any]]:
        """Run deterministic identifier preflight checks and return report artifact."""
        identifier_contract = schema_contract.get("identifier_contract", {})
        if not isinstance(identifier_contract, dict):
            identifier_contract = {}

        gtin_required = bool(identifier_contract.get("gtin_required"))
        empty_gtin_reason_attribute_id = identifier_contract.get("empty_gtin_reason_attribute_id")
        fallback_reason_available = isinstance(empty_gtin_reason_attribute_id, str) and bool(
            empty_gtin_reason_attribute_id
        )
        allowed_reason_ids = {
            str(value).strip()
            for value in identifier_contract.get("empty_gtin_reason_allowed_value_ids", [])
            if str(value).strip()
        }
        allowed_reason_names = {
            PortugueseTextNormalizer.normalize(str(value))
            for value in identifier_contract.get("empty_gtin_reason_allowed_value_names", [])
            if str(value).strip()
        }

        default_reason_artifact = self._inject_default_empty_gtin_reason(
            item=item,
            gtin_required=gtin_required,
            empty_gtin_reason_attribute_id=(
                empty_gtin_reason_attribute_id
                if isinstance(empty_gtin_reason_attribute_id, str)
                else None
            ),
            allowed_reason_ids=allowed_reason_ids,
        )

        item_state = self._collect_identifier_state(item.get("attributes"))
        variations = item.get("variations", [])
        variation_states: list[dict[str, Any]] = []
        if isinstance(variations, list):
            for variation in variations:
                attrs = variation.get("attributes") if isinstance(variation, dict) else None
                variation_states.append(self._collect_identifier_state(attrs))

        variation_identifier_present = any(
            bool(state.get("has_identifier_attribute")) for state in variation_states
        )

        identifier_violations: list[str] = []
        if variation_identifier_present:
            for index, state in enumerate(variation_states, start=1):
                identifier_violations.extend(
                    self._validate_identifier_state(
                        scope=f"Variation {index}",
                        state=state,
                        gtin_required=gtin_required,
                        fallback_reason_available=fallback_reason_available,
                        enforce_identifier_coverage=True,
                        allowed_reason_ids=allowed_reason_ids,
                        allowed_reason_names=allowed_reason_names,
                    )
                )
        else:
            identifier_violations.extend(
                self._validate_identifier_state(
                    scope="Item",
                    state=item_state,
                    gtin_required=gtin_required,
                    fallback_reason_available=fallback_reason_available,
                    enforce_identifier_coverage=False,
                    allowed_reason_ids=allowed_reason_ids,
                    allowed_reason_names=allowed_reason_names,
                )
            )

        artifact = {
            "checked": True,
            "gtin_required": gtin_required,
            "fallback_reason_available": fallback_reason_available,
            "variation_count": len(variations) if isinstance(variations, list) else 0,
            "variation_identifier_present": variation_identifier_present,
            "item_has_gtin": bool(item_state.get("gtin")),
            "item_has_empty_gtin_reason": bool(
                item_state.get("empty_gtin_reason_value_id")
                or item_state.get("empty_gtin_reason_value_name")
            ),
            "default_empty_gtin_reason": default_reason_artifact,
            "violations": identifier_violations,
        }
        return identifier_violations, artifact

    def _inject_default_empty_gtin_reason(
        self,
        *,
        item: dict[str, Any],
        gtin_required: bool,
        empty_gtin_reason_attribute_id: str | None,
        allowed_reason_ids: set[str],
    ) -> dict[str, Any]:
        """Inject configured EMPTY_GTIN_REASON when GTIN is missing."""
        artifact: dict[str, Any] = {
            "applied": False,
            "value_id": None,
            "value_name": None,
        }
        if not gtin_required:
            return artifact

        policy = self.config.get("identifier_policy")
        if not isinstance(policy, dict) or not bool(policy.get("auto_fill_empty_gtin_reason")):
            return artifact

        default_value_name = self._normalize_identifier_text(
            policy.get("default_empty_gtin_reason_value_name")
        )
        if default_value_name is None:
            return artifact

        attributes = item.get("attributes")
        if not isinstance(attributes, list):
            return artifact

        state = self._collect_identifier_state(attributes)
        if state.get("gtin"):
            return artifact
        if state.get("empty_gtin_reason_value_id") or state.get("empty_gtin_reason_value_name"):
            return artifact

        target_id = (
            empty_gtin_reason_attribute_id
            if isinstance(empty_gtin_reason_attribute_id, str) and empty_gtin_reason_attribute_id
            else "EMPTY_GTIN_REASON"
        )

        reason_attribute: dict[str, Any] | None = None
        for attribute in attributes:
            if not isinstance(attribute, dict):
                continue
            attribute_id = attribute.get("id")
            if (
                isinstance(attribute_id, str)
                and attribute_id.strip().upper() == "EMPTY_GTIN_REASON"
            ):
                reason_attribute = attribute
                break

        if reason_attribute is None:
            reason_attribute = {"id": target_id}
            attributes.append(reason_attribute)

        selected_reason_id: str | None = None
        if allowed_reason_ids:
            selected_reason_id = sorted(allowed_reason_ids)[0]
            reason_attribute["value_id"] = selected_reason_id
        reason_attribute["value_name"] = default_value_name

        artifact.update(
            {
                "applied": True,
                "value_id": selected_reason_id,
                "value_name": default_value_name,
            }
        )
        logger.warning(
            "Auto-filled EMPTY_GTIN_REASON with configured default value for missing GTIN."
        )
        return artifact

    def _run_schema_contract_preflight(
        self,
        *,
        category_id: str,
        item: dict[str, Any],
    ) -> list[str]:
        """Run deterministic preflight checks using compiled schema metadata."""
        compiled = self._get_schema_contract_compiled(category_id)
        schema_contract = compiled.get("schema_contract", {})
        if not isinstance(schema_contract, dict):
            self._current_preflight_artifact = {
                "identifier_gate": {"checked": False, "violations": []}
            }
            return []

        violations: list[str] = []
        identifier_violations, identifier_artifact = self._run_identifier_preflight_checks(
            schema_contract=schema_contract,
            item=item,
        )
        self._current_preflight_artifact = {"identifier_gate": identifier_artifact}

        required_ids_raw = schema_contract.get("required_attribute_ids", [])
        required_ids = {attr_id for attr_id in required_ids_raw if isinstance(attr_id, str)}
        required_ids.discard("")
        required_ids.discard("GTIN")
        required_ids.discard("EMPTY_GTIN_REASON")
        if required_ids:
            provided_ids = {
                attr.get("id")
                for attr in item.get("attributes", [])
                if isinstance(attr, dict) and isinstance(attr.get("id"), str)
            }
            missing = sorted(attr_id for attr_id in required_ids if attr_id not in provided_ids)
            if missing:
                violations.append(f"Missing required attributes: {', '.join(missing)}")

        limits = schema_contract.get("limits", {})
        if isinstance(limits, dict):
            pictures = item.get("pictures", [])
            picture_count = len(pictures) if isinstance(pictures, list) else 0
            max_pictures = limits.get("max_pictures")
            if isinstance(max_pictures, int) and max_pictures >= 0 and picture_count > max_pictures:
                violations.append(
                    f"Pictures count {picture_count} exceeds category max {max_pictures}"
                )

            variations = item.get("variations", [])
            if not isinstance(variations, list):
                variations = []
            if not variations:
                user_product = item.get("user_product", {})
                if isinstance(user_product, dict):
                    user_product_variations = user_product.get("variations", [])
                    if isinstance(user_product_variations, list):
                        variations = user_product_variations
            variation_count = len(variations)
            max_variations_allowed = limits.get("max_variations_allowed")
            if (
                isinstance(max_variations_allowed, int)
                and max_variations_allowed >= 0
                and variation_count > max_variations_allowed
            ):
                violations.append(
                    "Variations count "
                    f"{variation_count} exceeds category max {max_variations_allowed}"
                )

        violations.extend(identifier_violations)
        return violations

    def _get_available_listing_type_ids(self, category_id: str) -> list[str]:
        """Fetch available listing types for current seller and category."""
        cached = self._available_listing_types_cache.get(category_id)
        if cached is not None:
            return cached

        getter = getattr(self.publisher, "get_available_listing_types", None)
        if not callable(getter):
            logger.warning(
                "Publisher does not expose available listing types for category %s",
                category_id,
            )
            self._available_listing_types_cache[category_id] = []
            return []

        try:
            listing_types = getter(category_id)
        except Exception as e:
            logger.warning(f"Could not fetch available listing types for {category_id}: {e}")
            self._available_listing_types_cache[category_id] = []
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
            logger.warning(
                "Publisher does not expose category sale terms for category %s",
                category_id,
            )
            self._category_sale_terms_cache[category_id] = {}
            return {}

        try:
            sale_terms = getter(category_id)
        except Exception as e:
            logger.warning(f"Could not fetch category sale terms for {category_id}: {e}")
            self._category_sale_terms_cache[category_id] = {}
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

    def _get_non_fillable_attribute_ids(self, category_id: str) -> set[str]:
        """Return attribute IDs that should not be auto-filled or hard-required."""
        cache = getattr(self, "_category_non_fillable_attribute_ids_cache", None)
        if not isinstance(cache, dict):
            cache = {}
            self._category_non_fillable_attribute_ids_cache = cache

        cached = cache.get(category_id)
        if cached is not None:
            return cached

        try:
            metadata = self.category_resolver.get_attribute_metadata(category_id)
        except Exception as e:
            logger.warning(
                "Could not fetch attribute metadata for non-fillable filtering in %s: %s",
                category_id,
                e,
            )
            cache[category_id] = set()
            return set()

        non_fillable_attribute_ids: set[str] = set()
        for meta in metadata:
            attr_id = getattr(meta, "id", None)
            if not isinstance(attr_id, str) or not attr_id:
                continue
            tags = {
                _normalize_attribute_tag(tag)
                for tag in getattr(meta, "tags", set())
                if str(tag).strip()
            }
            if tags.intersection(NON_FILLABLE_ATTRIBUTE_TAGS):
                non_fillable_attribute_ids.add(attr_id)

        cache[category_id] = non_fillable_attribute_ids
        return non_fillable_attribute_ids

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

        required_ids = {
            attr_id
            for attr in conditional_attrs
            if isinstance(attr, dict)
            for attr_id in [attr.get("id")]
            if isinstance(attr_id, str) and attr_id
        }
        if not required_ids:
            return set()

        non_fillable_attribute_ids = self._get_non_fillable_attribute_ids(category_id)
        if non_fillable_attribute_ids:
            required_ids.difference_update(non_fillable_attribute_ids)
        return required_ids

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
            configured = {
                _normalize_attribute_tag(tag)
                for tag in configured_skip_tags
                if str(tag).strip()
            }
            if configured:
                skip_tags = skip_tags.union(configured)

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
                _normalize_attribute_tag(tag)
                for tag in getattr(meta, "tags", set())
                if str(tag).strip()
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

    def _build_shipping_config(self, category_id: str | None = None) -> dict[str, Any]:
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
        raw_shipping_config = self.config.get("shipping", {})
        shipping_config = raw_shipping_config if isinstance(raw_shipping_config, dict) else {}
        default_mode_raw = shipping_config.get("default_mode", "not_specified")
        default_mode = str(default_mode_raw).strip() or "not_specified"
        raw_modes = shipping_config.get("modes", {})
        modes_config = raw_modes if isinstance(raw_modes, dict) else {}

        requested_mode = default_mode
        decision_source = "config.default_mode"
        decision_reason = "Using configured default mode."
        resolved_logistic_type: str | None = None
        resolved_logistic_type_source: str | None = None
        resolved_runtime_tags: list[str] = []
        resolved_runtime_constraints: dict[str, Any] = {}
        resolved_runtime_free_shipping: bool | None = None

        if self.shipping_resolver:
            resolved_from_selection = False
            selection_getter = getattr(self.shipping_resolver, "get_best_shipping_selection", None)
            if callable(selection_getter):
                try:
                    selection_payload = selection_getter()
                except Exception as error:
                    logger.warning(
                        "Shipping resolver selection failed; fallback to mode-only resolver: %s",
                        error,
                    )
                else:
                    if isinstance(selection_payload, dict):
                        resolved_mode_raw = selection_payload.get("mode")
                        resolved_mode = (
                            str(resolved_mode_raw).strip() if resolved_mode_raw is not None else ""
                        )
                        if resolved_mode:
                            requested_mode = resolved_mode
                            decision_source = "shipping_resolver.selection"
                            decision_reason = (
                                "Resolved mode from seller shipping selection metadata."
                            )
                            resolved_from_selection = True

                        resolved_logistic_type_raw = selection_payload.get("logistic_type")
                        resolved_logistic_type = (
                            str(resolved_logistic_type_raw).strip()
                            if resolved_logistic_type_raw is not None
                            else ""
                        )
                        if resolved_logistic_type:
                            resolved_logistic_type_source = "shipping_resolver.selection"
                            logger.info(
                                "Using shipping logistic_type from resolver selection: %s",
                                resolved_logistic_type,
                            )
                        else:
                            resolved_logistic_type = None

                        resolved_runtime_tags = self._normalize_seller_tags(
                            selection_payload.get("tags")
                        )
                        if resolved_runtime_tags:
                            logger.info(
                                "Using shipping tags from resolver selection metadata: %s",
                                resolved_runtime_tags,
                            )

                        resolved_runtime_constraints = self._normalize_shipping_constraints(
                            selection_payload.get("constraints")
                        )
                        if resolved_runtime_constraints:
                            logger.info(
                                "Using shipping constraints from resolver selection metadata: %s",
                                resolved_runtime_constraints,
                            )

                        resolved_runtime_free_shipping = self._coerce_shipping_bool(
                            selection_payload.get("free_shipping")
                        )
                        if resolved_runtime_free_shipping is not None:
                            logger.info(
                                "Using shipping free_shipping from resolver selection metadata: %s",
                                resolved_runtime_free_shipping,
                            )

            if not resolved_from_selection:
                try:
                    resolved_mode_raw = self.shipping_resolver.get_best_shipping_mode()
                except Exception as error:
                    logger.warning(
                        "Shipping resolver failed; using default mode %s: %s",
                        default_mode,
                        error,
                    )
                    decision_reason = "Shipping resolver failed; using default mode."
                else:
                    resolved_mode = (
                        str(resolved_mode_raw).strip() if resolved_mode_raw is not None else ""
                    )
                    if resolved_mode:
                        requested_mode = resolved_mode
                        decision_source = "shipping_resolver"
                        decision_reason = "Resolved mode from seller shipping preferences."
                        logger.info("Using shipping mode from resolver: %s", requested_mode)

        shipping_mode = requested_mode or default_mode
        fallback_applied = False
        if modes_config and shipping_mode not in modes_config:
            fallback_mode = (
                default_mode
                if default_mode in modes_config
                else str(next(iter(modes_config), shipping_mode))
            )
            if fallback_mode != shipping_mode:
                fallback_applied = True
                decision_source = "config.modes_fallback"
                decision_reason = f"Mode '{shipping_mode}' not configured; using '{fallback_mode}'."
                shipping_mode = fallback_mode

        raw_mode_config = modes_config.get(shipping_mode, {})
        mode_config = raw_mode_config if isinstance(raw_mode_config, dict) else {}
        configured_tags = self._normalize_seller_tags(mode_config.get("tags", []))
        selected_tags = list(configured_tags)
        tags_source = "config.mode"
        policy_overrides: list[str] = []

        if self.shipping_allow_runtime_tag_overrides and resolved_runtime_tags:
            merged_tags = list(dict.fromkeys([*configured_tags, *resolved_runtime_tags]))
            if merged_tags != selected_tags:
                policy_overrides.append("runtime_tags_merged")
            selected_tags = merged_tags
            tags_source = "config.mode+shipping_resolver.selection"

        configured_free_shipping = self._coerce_shipping_bool(
            mode_config.get("free_shipping", False)
        )
        selected_free_shipping = (
            configured_free_shipping if configured_free_shipping is not None else False
        )
        free_shipping_source = "config.mode"
        if (
            self.shipping_allow_runtime_free_shipping_override
            and resolved_runtime_free_shipping is not None
        ):
            if selected_free_shipping != resolved_runtime_free_shipping:
                policy_overrides.append("runtime_free_shipping_override")
            selected_free_shipping = resolved_runtime_free_shipping
            free_shipping_source = "shipping_resolver.selection"

        mandatory_free_shipping_detected = bool(
            self.shipping_mandatory_free_shipping_tags.intersection(selected_tags)
        )
        mandatory_free_shipping_enforced = False
        if (
            self.shipping_enforce_mandatory_free_shipping
            and mandatory_free_shipping_detected
            and not selected_free_shipping
        ):
            selected_free_shipping = True
            free_shipping_source = "policy.mandatory_free_shipping_tag"
            mandatory_free_shipping_enforced = True
            policy_overrides.append("mandatory_free_shipping_enforced")

        # Build complete shipping config matching ML API format
        config_shipping: dict[str, Any] = {
            "mode": shipping_mode,
            "methods": mode_config.get("methods", []),
            "tags": selected_tags,
            "dimensions": mode_config.get("dimensions"),
            "local_pick_up": mode_config.get("local_pick_up", False),
            "free_shipping": selected_free_shipping,
            "logistic_type": mode_config.get("logistic_type"),
            "store_pick_up": mode_config.get("store_pick_up", False),
        }
        if resolved_logistic_type and shipping_mode == requested_mode:
            config_shipping["logistic_type"] = resolved_logistic_type

        # Remove None values to keep payload clean
        config_shipping = {k: v for k, v in config_shipping.items() if v is not None}
        selected_logistic_type = config_shipping.get("logistic_type")
        logistic_type_source = "config.mode"
        if (
            resolved_logistic_type
            and resolved_logistic_type_source
            and shipping_mode == requested_mode
            and selected_logistic_type == resolved_logistic_type
        ):
            logistic_type_source = resolved_logistic_type_source

        constraints: dict[str, Any] = {"category_id": category_id}
        if category_id:
            policy_summary = self._get_policy_artifact(category_id).get("policy_summary")
            if isinstance(policy_summary, dict):
                constraints.update(
                    {
                        "listing_allowed": policy_summary.get("listing_allowed"),
                        "category_status": policy_summary.get("status"),
                    }
                )
        if resolved_runtime_constraints:
            constraints["runtime"] = dict(resolved_runtime_constraints)
        constraints["mandatory_free_shipping_tags"] = sorted(
            self.shipping_mandatory_free_shipping_tags
        )
        constraints["mandatory_free_shipping_detected"] = mandatory_free_shipping_detected
        constraints["mandatory_free_shipping_enforced"] = mandatory_free_shipping_enforced

        self._current_shipping_policy = {
            "decision": {
                "source": decision_source,
                "reason": decision_reason,
                "requested_mode": requested_mode,
                "selected_mode": shipping_mode,
                "default_mode": default_mode,
                "fallback_applied": fallback_applied,
                "mode_configured": shipping_mode in modes_config if modes_config else False,
                "available_modes": sorted(str(mode) for mode in modes_config),
                "selected_logistic_type": selected_logistic_type,
                "logistic_type_source": logistic_type_source,
                "selected_tags": list(selected_tags),
                "tags_source": tags_source,
                "selected_free_shipping": selected_free_shipping,
                "free_shipping_source": free_shipping_source,
                "policy_overrides": policy_overrides,
                "constraints": constraints,
            },
            "payload": dict(config_shipping),
            "cause_decisions": [],
        }

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
