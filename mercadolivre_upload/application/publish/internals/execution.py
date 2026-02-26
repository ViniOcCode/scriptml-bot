"""Execution orchestration helpers extracted from publish use case."""

from __future__ import annotations

import logging
from copy import deepcopy
from typing import Any

from mercadolivre_upload.application.builders.product_builder import ProductBuilder
from mercadolivre_upload.domain.fiscal.data import FiscalData
from mercadolivre_upload.domain.product.model import Product
from mercadolivre_upload.shared.utils.text_utils import PortugueseTextNormalizer

logger = logging.getLogger(__name__)


def build_product_from_dict(data: dict[str, Any]) -> Product:
    """Build a Product entity from a spreadsheet-style row dictionary."""

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


def _build_terminal_item_results(
    use_case: Any,
    *,
    products: list[Product | dict[str, Any]],
    error_msg: str,
    flow_artifact: dict[str, Any],
    resolution_artifact: dict[str, Any],
    policy_artifact: dict[str, Any] | None = None,
    schema_contract_artifact: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    item_results: list[dict[str, Any]] = []
    for index, product in enumerate(products):
        sku, title = use_case._extract_item_identity(product)
        item_result = {
            "index": index,
            "sku": sku,
            "title": title,
            "status": "failed",
            "error": error_msg,
            "rollout_flags": deepcopy(use_case._rollout_flags_artifact),
        }
        item_result.update(flow_artifact)
        item_result.update(resolution_artifact)
        if policy_artifact:
            item_result.update(policy_artifact)
        if schema_contract_artifact:
            item_result.update(schema_contract_artifact)
        item_results.append(item_result)
    return item_results


def _build_terminal_result(
    use_case: Any,
    *,
    products: list[Product | dict[str, Any]],
    error_msg: str,
    flow_artifact: dict[str, Any],
    resolution_artifact: dict[str, Any],
    category_resolution_artifact: dict[str, Any],
    flow_routing: dict[str, Any],
    policy_artifact: dict[str, Any] | None = None,
    schema_contract_artifact: dict[str, Any] | None = None,
) -> dict[str, Any]:
    item_results = _build_terminal_item_results(
        use_case,
        products=products,
        error_msg=error_msg,
        flow_artifact=flow_artifact,
        resolution_artifact=resolution_artifact,
        policy_artifact=policy_artifact,
        schema_contract_artifact=schema_contract_artifact,
    )
    return {
        "success": False,
        "published": 0,
        "failed": len(products),
        "errors": [error_msg],
        "item_results": item_results,
        "flow_routing": flow_routing,
        "rollout_flags": deepcopy(use_case._rollout_flags_artifact),
        "category_resolution": deepcopy(category_resolution_artifact),
    }


def _build_row_build_failed_item_result(
    use_case: Any,
    *,
    index: int,
    source_sku: str | None,
    source_title: str | None,
    error_message: str,
    flow_artifact: dict[str, Any],
    resolution_artifact: dict[str, Any],
    policy_artifact: dict[str, Any] | None,
    schema_contract_artifact: dict[str, Any] | None,
) -> dict[str, Any]:
    build_error_code = "input.row_build_failed"
    build_error_taxonomy = [
        {
            "type": "error",
            "code": build_error_code,
            "message": error_message,
            "classification": "blocking_error",
        }
    ]
    item_result: dict[str, Any] = {
        "index": index,
        "sku": source_sku,
        "title": source_title,
        "status": "failed",
        "error": error_message,
        "cause_codes": [build_error_code],
        "cause_taxonomy": build_error_taxonomy,
        "validation_decision": use_case._build_validation_decision(build_error_taxonomy),
        "rollout_flags": deepcopy(use_case._rollout_flags_artifact),
    }
    item_result.update(flow_artifact)
    item_result.update(resolution_artifact)
    if policy_artifact:
        item_result.update(policy_artifact)
    if schema_contract_artifact:
        item_result.update(schema_contract_artifact)
    return item_result


def _build_item_result(
    use_case: Any,
    *,
    index: int,
    product: Product,
    success: bool,
    previous_error_count: int,
    flow_artifact: dict[str, Any],
    resolution_artifact: dict[str, Any],
    policy_artifact: dict[str, Any] | None,
    schema_contract_artifact: dict[str, Any] | None,
) -> dict[str, Any]:
    item_result: dict[str, Any] = {
        "index": index,
        "sku": product.sku,
        "title": product.title,
        "status": "success" if success else "failed",
        "rollout_flags": deepcopy(use_case._rollout_flags_artifact),
    }
    if use_case._current_cause_codes:
        item_result["cause_codes"] = list(dict.fromkeys(use_case._current_cause_codes))
    if use_case._current_preflight_artifact:
        item_result.update(use_case._current_preflight_artifact)
    if use_case._current_cause_taxonomy:
        item_result["cause_taxonomy"] = deepcopy(use_case._current_cause_taxonomy)
    if use_case._current_validation_decision:
        item_result["validation_decision"] = deepcopy(use_case._current_validation_decision)
    if isinstance(use_case._current_image_diagnostics, dict):
        item_result["image_diagnostics"] = deepcopy(use_case._current_image_diagnostics)
    if isinstance(use_case._current_shipping_policy, dict):
        item_result["shipping_policy"] = deepcopy(use_case._current_shipping_policy)

    new_errors = use_case.errors[previous_error_count:]
    if new_errors:
        item_result["error"] = "; ".join(new_errors)
    elif not success:
        item_result["error"] = f"{product.sku}: publish failed"

    item_result.update(flow_artifact)
    if use_case._current_flow_artifact and isinstance(item_result.get("flow_routing"), dict):
        flow_routing_item = dict(item_result["flow_routing"])
        flow_routing_item.update(use_case._current_flow_artifact)
        item_result["flow_routing"] = flow_routing_item

    item_result.update(resolution_artifact)
    if policy_artifact:
        item_result.update(policy_artifact)
    if schema_contract_artifact:
        item_result.update(schema_contract_artifact)
    return item_result


def _build_execution_summary(
    use_case: Any,
    *,
    flow_routing: dict[str, Any],
    category_resolution_artifact: dict[str, Any],
) -> dict[str, Any]:
    clip_success = sum(result.get("clips_uploaded", 0) for result in use_case.clip_results)
    clip_failed = sum(result.get("clips_failed", 0) for result in use_case.clip_results)

    return {
        "success": use_case.failed == 0,
        "published": use_case.published,
        "validated": use_case.published if use_case.validation_only else 0,
        "failed": use_case.failed,
        "errors": use_case.errors,
        "fiscal_submitted": len([result for result in use_case.fiscal_results if result.success]),
        "fiscal_failed": len([result for result in use_case.fiscal_results if not result.success]),
        "clips_uploaded": clip_success,
        "clips_failed": clip_failed,
        "clips_details": use_case.clip_results,
        "item_results": use_case.item_results,
        "flow_routing": flow_routing,
        "rollout_flags": deepcopy(use_case._rollout_flags_artifact),
        "category_resolution": deepcopy(category_resolution_artifact),
    }


def execute_publish(
    use_case: Any,
    products: list[Product | dict[str, Any]],
    category_name: str,
) -> dict[str, Any]:
    """Execute publishing flow preserving public use-case behavior."""
    use_case._reset_execution_state()

    flow_artifact = use_case._get_flow_routing_artifact()
    flow_routing = flow_artifact.get("flow_routing", {})
    if isinstance(flow_routing, dict) and flow_routing.get("blocked"):
        blocked_resolution_artifact = use_case._build_resolution_artifact(
            {
                "category_input": str(category_name).strip(),
                "category_resolved_id": None,
                "category_path": [],
                "resolution_strategy": "unresolved",
                "predictor_attempted": False,
                "predictor_titles_count": 0,
                "predictor_matched": False,
                "fallback_attempted": False,
                "fallback_reason": "flow_routing_blocked",
            }
        )
        category_resolution_artifact = use_case._build_category_resolution_observability(
            blocked_resolution_artifact,
            len(products),
        )
        use_case._log_category_resolution_observability(category_resolution_artifact)
        error_msg = str(
            flow_routing.get("error", "Forced publish flow configuration is unsupported.")
        )
        logger.error(error_msg)
        return _build_terminal_result(
            use_case,
            products=products,
            error_msg=error_msg,
            flow_artifact=flow_artifact,
            resolution_artifact=blocked_resolution_artifact,
            category_resolution_artifact=category_resolution_artifact,
            flow_routing=flow_routing,
        )

    category_context = use_case._resolve_category_context(products, category_name)
    resolution_artifact = use_case._build_resolution_artifact(category_context)
    category_resolution_artifact = use_case._build_category_resolution_observability(
        resolution_artifact,
        len(products),
    )
    use_case._log_category_resolution_observability(category_resolution_artifact)

    category_input = resolution_artifact["category_input"]
    category_id = resolution_artifact["category_resolved_id"]

    if not category_id:
        error_msg = f"Category not found: {category_input}"
        logger.error(error_msg)
        return _build_terminal_result(
            use_case,
            products=products,
            error_msg=error_msg,
            flow_artifact=flow_artifact,
            resolution_artifact=resolution_artifact,
            category_resolution_artifact=category_resolution_artifact,
            flow_routing=flow_routing,
        )

    policy_artifact = use_case._get_policy_artifact(category_id)
    schema_contract_artifact = use_case._get_schema_contract_artifact(category_id)

    is_listing_allowed = getattr(use_case.category_resolver, "is_listing_allowed", None)
    if callable(is_listing_allowed) and not is_listing_allowed(category_id):
        error_msg = f"Category not available for listing: {category_id}"
        logger.error(error_msg)
        return _build_terminal_result(
            use_case,
            products=products,
            error_msg=error_msg,
            flow_artifact=flow_artifact,
            resolution_artifact=resolution_artifact,
            category_resolution_artifact=category_resolution_artifact,
            flow_routing=flow_routing,
            policy_artifact=policy_artifact,
            schema_contract_artifact=schema_contract_artifact,
        )

    logger.info("Publishing %s products to category %s", len(products), category_id)
    use_case._initialize_cache_mapper(category_id)

    for index, product in enumerate(products):
        use_case._current_cause_codes = []
        use_case._current_preflight_artifact = {
            "identifier_gate": {"checked": False, "violations": []}
        }
        use_case._current_cause_taxonomy = []
        use_case._current_validation_decision = {}
        use_case._current_image_diagnostics = None
        use_case._current_shipping_policy = None
        use_case._current_flow_artifact = {}

        if isinstance(product, dict):
            source_sku, source_title = use_case._extract_item_identity(product)
            try:
                product = use_case._build_product_from_dict(product)
            except Exception as exc:
                logger.error("Failed to build product from row: %s", exc)
                error_message = str(exc)
                use_case.errors.append(error_message)
                use_case.failed += 1
                use_case.item_results.append(
                    _build_row_build_failed_item_result(
                        use_case,
                        index=index,
                        source_sku=source_sku,
                        source_title=source_title,
                        error_message=error_message,
                        flow_artifact=flow_artifact,
                        resolution_artifact=resolution_artifact,
                        policy_artifact=policy_artifact,
                        schema_contract_artifact=schema_contract_artifact,
                    )
                )
                continue

        previous_error_count = len(use_case.errors)
        success = use_case._publish_one(product, category_id)
        use_case.item_results.append(
            _build_item_result(
                use_case,
                index=index,
                product=product,
                success=success,
                previous_error_count=previous_error_count,
                flow_artifact=flow_artifact,
                resolution_artifact=resolution_artifact,
                policy_artifact=policy_artifact,
                schema_contract_artifact=schema_contract_artifact,
            )
        )

    if not use_case.dry_run and use_case._pending_fiscal:
        use_case._submit_fiscal_batch(use_case._pending_fiscal)

    return _build_execution_summary(
        use_case,
        flow_routing=flow_routing,
        category_resolution_artifact=category_resolution_artifact,
    )


__all__ = ["execute_publish"]
