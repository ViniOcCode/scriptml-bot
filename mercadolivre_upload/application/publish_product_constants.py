"""Constants and shared helpers for publish_product use case."""

from typing import Any

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
SHIPPING_EXPLICIT_NON_BLOCKING_CODES = {
    "item.shipping.mandatory_free_shipping",
}
ROW_SHIPPING_MODE_HEADERS = (
    "forma de envio",
    "forma envio",
    "modo de envio",
    "shipping mode",
)
ROW_SHIPPING_COST_HEADERS = (
    "custo de envio",
    "custo envio",
    "frete",
    "shipping cost",
)
ROW_SHIPPING_PICKUP_HEADERS = (
    "retirar pessoalmente",
    "retirada pessoalmente",
    "retirada em maos",
    "local pick up",
    "local pickup",
)
ROW_SHIPPING_MARKETPLACE_TOKENS = (
    "mercado envios",
    "mercado envio",
    "mercadoenvios",
)
ROW_SHIPPING_CUSTOM_TOKENS = (
    "custom",
    "personalizado",
    "envio personalizado",
)
ROW_SHIPPING_NOT_SPECIFIED_TOKENS = (
    "a combinar",
    "not specified",
    "nao especificado",
    "não especificado",
    "sem envio",
)
ROW_SHIPPING_TRUE_TOKENS = ("sim", "yes", "true", "1", "aceito")
ROW_SHIPPING_FALSE_TOKENS = ("nao", "não", "no", "false", "0", "nao aceito", "não aceito")
ROW_SHIPPING_FREE_TRUE_TOKENS = (
    "por conta do vendedor",
    "vendedor",
    "frete gratis",
    "frete grátis",
    "gratis",
    "grátis",
    *ROW_SHIPPING_TRUE_TOKENS,
)
ROW_SHIPPING_FREE_FALSE_TOKENS = (
    "por conta do comprador",
    "comprador",
    *ROW_SHIPPING_FALSE_TOKENS,
)


def normalize_attribute_tag(tag: Any) -> str:
    """Normalize API/config attribute tags into a canonical token."""
    return str(tag).strip().lower().replace("-", "_")
