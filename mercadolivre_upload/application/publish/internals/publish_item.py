"""Single-item publish pipeline helpers extracted from publish use case."""

from __future__ import annotations

import logging
from typing import Any

from mercadolivre_upload.domain.product.model import Product

from .decisioning import (
    build_validation_decision,
    extract_exception_error_detail,
    extract_exception_response_excerpt,
    register_shipping_causes,
)
from .shipping import build_shipping_config
from .validation import build_validation_cause_taxonomy, get_critical_attribute_warnings

logger = logging.getLogger(__name__)


def _build_blocking_taxonomy(code: str, message: str) -> list[dict[str, str]]:
    return [
        {
            "type": "error",
            "code": code,
            "message": message,
            "classification": "blocking_error",
        }
    ]


def _extract_listing_and_variation_markers(
    ml_attributes: list[Any],
) -> tuple[list[Any], str | None, dict[str, list[dict[str, Any]]]]:
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

    return ml_attributes, explicit_listing_type, variation_candidates


def _inject_item_condition_attribute(
    *,
    ml_attributes: list[Any],
    item_condition_config: Any,
    product_condition: str,
) -> None:
    if not isinstance(item_condition_config, dict):
        return

    item_condition_id = item_condition_config.get("id")
    item_condition_values = item_condition_config.get("values", {})
    condition_payload = (
        item_condition_values.get(product_condition)
        if isinstance(item_condition_values, dict)
        else None
    )
    if not item_condition_id or not isinstance(condition_payload, dict):
        return

    existing_ids = {
        attr.get("id") for attr in ml_attributes if isinstance(attr, dict) and attr.get("id")
    }
    if item_condition_id in existing_ids:
        return

    item_condition_attr: dict[str, Any] = {"id": item_condition_id}
    value_id = condition_payload.get("value_id")
    value_name = condition_payload.get("value_name")
    if value_id is not None:
        item_condition_attr["value_id"] = value_id
    if value_name is not None:
        item_condition_attr["value_name"] = value_name
    if len(item_condition_attr) > 1:
        ml_attributes.append(item_condition_attr)


def _extract_image_diagnostic_issues(image_diagnostics: dict[str, Any] | None) -> list[str]:
    raw_diagnostic_issues = (
        image_diagnostics.get("issues") if isinstance(image_diagnostics, dict) else []
    )
    if not isinstance(raw_diagnostic_issues, list):
        return []
    return [str(issue) for issue in raw_diagnostic_issues if str(issue).strip()]


def _extract_decision_codes(
    validation_decision: dict[str, Any],
) -> tuple[list[Any], list[Any], list[Any]]:
    classification_codes = validation_decision.get("classification_codes", {})
    if not isinstance(classification_codes, dict):
        classification_codes = {}
    blocking_error_codes = classification_codes.get("blocking_error", [])
    retryable_error_codes = classification_codes.get("retryable_error", [])
    critical_warning_codes = classification_codes.get("critical_warning", [])
    return blocking_error_codes, retryable_error_codes, critical_warning_codes


def _build_validation_decision_for_use_case(
    use_case: Any, taxonomy: list[dict[str, str]]
) -> dict[str, Any]:
    return build_validation_decision(
        taxonomy=taxonomy,
        validation_decision_mode=use_case.validation_decision_mode,
        strict_warning_gate_mode=use_case.strict_warning_gate_mode,
        strict_attribute_warnings=use_case.strict_attribute_warnings,
    )


def _register_shipping_cause_decisions(
    use_case: Any, causes: list[Any], *, stage: str
) -> list[dict[str, str]]:
    return register_shipping_causes(
        causes,
        stage=stage,
        current_shipping_policy=use_case._current_shipping_policy,
        shipping_non_blocking_codes=use_case.shipping_non_blocking_codes,
    )


def publish_one(use_case: Any, product: Product, category_id: str) -> bool:
    """Publish one product preserving existing behavior and artifacts."""
    logger.info("Publishing product: %s (title: %s...)", product.sku, product.title[:50])
    use_case._current_cause_codes = []
    use_case._current_cause_taxonomy = []
    use_case._current_validation_decision = {}
    use_case._current_publish_category_id = category_id
    use_case._current_publish_sku = str(product.sku).strip() if product.sku else None
    use_case._current_variation_reference_attributes = []
    selected_flow = use_case._resolve_selected_flow()
    use_case._current_flow_artifact = {
        "payload_builder": (
            "user_products_pxv" if selected_flow == "user_products" else "legacy_variations"
        )
    }

    (
        ml_attributes,
        sale_terms_from_mapping,
        attr_warnings,
        attr_errors,
    ) = use_case._attribute_builder.build_attributes(
        product,
        category_id,
    )

    if attr_errors:
        logger.error("Attribute validation failed for %s: %s", product.sku, attr_errors)
        use_case.errors.append(f"{product.sku}: {attr_errors}")
        use_case.failed += 1
        return False

    if attr_warnings:
        logger.warning("Attribute warnings for %s: %s", product.sku, attr_warnings)
        critical_attr_warnings = get_critical_attribute_warnings(attr_warnings)
        if critical_attr_warnings and use_case.strict_attribute_warnings:
            summary = critical_attr_warnings[:5]
            logger.error(
                "Blocking %s due to critical attribute warnings (%s): %s",
                product.sku,
                len(critical_attr_warnings),
                summary,
            )
            use_case.errors.append(
                f"{product.sku}: critical attribute warnings ({len(critical_attr_warnings)}): "
                f"{summary}"
            )
            use_case.failed += 1
            return False

    logger.info("Final attribute count for %s: %s", product.sku, len(ml_attributes))

    picture_urls = use_case.image_uploader.upload_images(product.sku)
    picture_ids = use_case._resolve_picture_ids(picture_urls)
    pictures = [{"source": url} for url in picture_urls]
    if not pictures:
        logger.warning("No pictures for %s", product.sku)

    shipping_config = build_shipping_config(
        use_case,
        category_id=category_id,
        row_attributes=product.attributes,
    )
    logger.debug("Shipping config for %s: %s", product.sku, shipping_config)

    core_defaults = use_case.config.get("core_item_fields", {}).get("defaults", {})

    ml_attributes, explicit_listing_type, variation_candidates = (
        _extract_listing_and_variation_markers(ml_attributes)
    )
    use_case._current_variation_reference_attributes = [
        attr for attr in ml_attributes if isinstance(attr, dict)
    ]

    variations: list[dict[str, Any]] = []
    user_products_payload: dict[str, Any] | None = None
    if selected_flow == "legacy":
        if variation_candidates:
            variations = use_case._build_variations_from_candidates(
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
            user_products_payload = use_case._build_user_products_payload(
                product=product,
                ml_attributes=ml_attributes,
                variation_candidates=variation_candidates,
                quantity=product.available_quantity,
                price=product.price,
                picture_ids=picture_ids,
            )
        except ValueError as error:
            message = f"User-products flow blocked: {error}"
            logger.error("%s: %s", product.sku, message)
            use_case._current_cause_codes = ["flow_routing.user_products_payload"]
            use_case.errors.append(f"{product.sku}: {message}")
            use_case.failed += 1
            return False

        use_case._current_flow_artifact.update(
            {
                "selected_model": user_products_payload.get("selected_model"),
                "up_family_name": user_products_payload.get("family_name"),
                "up_family_name_source": user_products_payload.get("family_name_source"),
                "up_variation_count": len(user_products_payload.get("variations", [])),
                "up_attribute_ids": user_products_payload.get("variation_attribute_ids", []),
            }
        )

    available_listing_types = use_case._get_available_listing_type_ids(category_id)
    listing_type_id = use_case._resolve_listing_type_id(
        category_id=category_id,
        explicit_listing_type=explicit_listing_type,
        default_listing_type=core_defaults.get("listing_type_id"),
        has_pictures=bool(pictures),
        available_listing_types=available_listing_types,
    )

    default_sale_terms = core_defaults.get("sale_terms", [])
    if not isinstance(default_sale_terms, list):
        default_sale_terms = []

    sale_terms = use_case._resolve_sale_terms(
        category_id=category_id,
        sale_terms_from_mapping=sale_terms_from_mapping,
        default_sale_terms=default_sale_terms,
    )

    _inject_item_condition_attribute(
        ml_attributes=ml_attributes,
        item_condition_config=core_defaults.get("item_condition", {}),
        product_condition=product.condition,
    )

    item: dict[str, Any] = {
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

    logger.info(
        "Final shipping config for %s: mode=%s, free_shipping=%s, "
        "logistic_type=%s, local_pick_up=%s",
        product.sku,
        shipping_config.get("mode"),
        shipping_config.get("free_shipping"),
        shipping_config.get("logistic_type"),
        shipping_config.get("local_pick_up"),
    )

    use_case._normalize_item_attributes(item)

    conditional_required_ids = use_case._inject_optional_na_attributes(
        category_id=category_id,
        item=item,
        sku=product.sku,
        description=product.description,
    )

    missing_conditional_attributes = use_case._get_missing_conditional_attributes(
        category_id=category_id,
        item=item,
        description=product.description,
        conditional_required_ids=conditional_required_ids,
    )
    if missing_conditional_attributes:
        message = f"Missing conditional attributes: {', '.join(missing_conditional_attributes)}"
        logger.error("%s: %s", product.sku, message)
        use_case.errors.append(f"{product.sku}: {message}")
        use_case.failed += 1
        return False

    preflight_violations = use_case._run_schema_contract_preflight(
        category_id=category_id,
        item=item,
    )
    if preflight_violations:
        message = f"Schema preflight failed: {'; '.join(preflight_violations)}"
        logger.error("%s: %s", product.sku, message)
        use_case._current_cause_codes = ["schema_contract.preflight"]
        use_case._current_cause_taxonomy = _build_blocking_taxonomy(
            "schema_contract.preflight",
            message,
        )
        use_case._current_validation_decision = _build_validation_decision_for_use_case(
            use_case,
            use_case._current_cause_taxonomy,
        )
        use_case.errors.append(f"{product.sku}: {message}")
        use_case.failed += 1
        return False

    use_case._current_image_diagnostics = use_case._run_image_diagnostic_preflight(
        sku=product.sku,
        title=product.title,
        category_id=category_id,
        picture_urls=picture_urls,
        picture_ids=picture_ids,
    )
    diagnostic_issues = _extract_image_diagnostic_issues(use_case._current_image_diagnostics)
    if diagnostic_issues and use_case.image_diagnostics_gate_mode == "enforce":
        message = f"Image diagnostic preflight failed: {'; '.join(diagnostic_issues)}"
        logger.error("%s: %s", product.sku, message)
        use_case._current_cause_codes = ["image_diagnostic.preflight"]
        use_case._current_cause_taxonomy = _build_blocking_taxonomy(
            "image_diagnostic.preflight",
            message,
        )
        use_case._current_validation_decision = _build_validation_decision_for_use_case(
            use_case,
            use_case._current_cause_taxonomy,
        )
        use_case.errors.append(f"{product.sku}: {message}")
        use_case.failed += 1
        return False
    if diagnostic_issues:
        logger.warning(
            "Image diagnostic issues detected for %s but gate mode '%s' allows continuation.",
            product.sku,
            use_case.image_diagnostics_gate_mode,
        )

    logger.debug("Full item payload for %s: %s", product.sku, item)

    validation_result = None
    try:
        validation = use_case._validate_item_for_flow(item=item, selected_flow=selected_flow)
        logger.debug("Validation response for %s: %s", product.sku, validation)

        raw_causes = validation.get("cause", [])
        causes = [cause for cause in raw_causes if isinstance(cause, dict)]
        for cause in causes:
            logger.debug("Validation cause for %s: %s", product.sku, cause)
        shipping_cause_decisions = _register_shipping_cause_decisions(
            use_case,
            causes,
            stage="validate",
        )
        cause_taxonomy = build_validation_cause_taxonomy(causes)
        use_case._current_cause_taxonomy = cause_taxonomy
        use_case._current_cause_codes = list(
            dict.fromkeys(
                str(cause.get("code", "")).strip().lower()
                for cause in cause_taxonomy
                if str(cause.get("code", "")).strip()
            )
        )
        use_case._current_validation_decision = (
            _build_validation_decision_for_use_case(use_case, cause_taxonomy)
            if cause_taxonomy
            else {}
        )

        shipping_issues = [
            f"{decision['code']}: {decision['message']}" for decision in shipping_cause_decisions
        ]
        if shipping_issues:
            logger.info("Shipping validation issues for %s: %s", product.sku, shipping_issues)

        warnings = [
            f"{cause.get('code', '')}: {cause.get('message', '')}"
            for cause in cause_taxonomy
            if cause.get("classification") in {"critical_warning", "informational_warning"}
        ]
        if warnings:
            logger.warning("Validation warnings for %s: %s", product.sku, warnings)

        decision_action = str(use_case._current_validation_decision.get("action", "allow"))
        (
            blocking_error_codes,
            retryable_error_codes,
            critical_warning_codes,
        ) = _extract_decision_codes(use_case._current_validation_decision)

        if decision_action == "block":
            if blocking_error_codes:
                logger.error(
                    "Validation failed for %s due to blocking errors: %s",
                    product.sku,
                    blocking_error_codes,
                )
                use_case.errors.append(
                    f"{product.sku}: blocking validation errors: {blocking_error_codes}"
                )
            elif retryable_error_codes:
                logger.error(
                    "Strict mode blocked %s due to retryable validation errors: %s",
                    product.sku,
                    retryable_error_codes,
                )
                use_case.errors.append(
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
                use_case.errors.append(
                    f"{product.sku}: critical validation warnings "
                    f"({len(critical_warning_codes)}): {summary}"
                )
            else:
                use_case.errors.append(f"{product.sku}: validation blocked by decision policy")
            use_case.failed += 1
            if use_case.feedback:
                use_case.feedback.record_validation_result(product.sku, ml_attributes, validation)
            return False

        if decision_action == "retry":
            logger.error(
                "Validation for %s returned retryable errors (controlled mode): %s",
                product.sku,
                retryable_error_codes,
            )
            use_case.errors.append(
                f"{product.sku}: retryable validation errors (retry suggested): "
                f"{retryable_error_codes}"
            )
            use_case.failed += 1
            if use_case.feedback:
                use_case.feedback.record_validation_result(product.sku, ml_attributes, validation)
            return False

        blocking_shipping_causes = [
            decision
            for decision in shipping_cause_decisions
            if decision.get("classification") == "blocking"
        ]
        if blocking_shipping_causes and decision_action == "allow":
            summary = [
                f"{decision['code']}: {decision['message']}"
                for decision in blocking_shipping_causes[:5]
            ]
            codes = [
                str(decision.get("code", ""))
                for decision in blocking_shipping_causes
                if str(decision.get("code", "")).strip()
            ]
            use_case._current_cause_codes = list(dict.fromkeys(codes))
            use_case.errors.append(
                f"{product.sku}: deterministic shipping policy violation "
                f"({len(blocking_shipping_causes)}): {summary}"
            )
            use_case.failed += 1
            if use_case.feedback:
                use_case.feedback.record_validation_result(product.sku, ml_attributes, validation)
            return False

        validation_result = validation
    except Exception as error:
        error_msg = str(error)
        cause_codes: list[str] = []
        validation_exception_taxonomy: list[dict[str, str]] = []
        error_detail = extract_exception_error_detail(error)
        if error_detail is not None:
            error_msg = f"{error_msg} - {error_detail}"
            causes_raw = error_detail.get("cause", [])
            causes = causes_raw if isinstance(causes_raw, list) else []
            shipping_cause_decisions = _register_shipping_cause_decisions(
                use_case,
                causes,
                stage="validate_exception",
            )
            normalized_causes = [cause for cause in causes if isinstance(cause, dict)]
            validation_exception_taxonomy = build_validation_cause_taxonomy(normalized_causes)
            for cause in normalized_causes:
                cause_code = str(cause.get("code", "")).strip().lower()
                if cause_code:
                    cause_codes.append(cause_code)
            for shipping_cause in shipping_cause_decisions:
                logger.error(
                    "Shipping validation error for %s: [%s] %s",
                    product.sku,
                    shipping_cause.get("classification"),
                    shipping_cause,
                )
        else:
            response_excerpt = extract_exception_response_excerpt(error)
            if response_excerpt:
                error_msg = f"{error_msg} - {response_excerpt}"
        use_case._current_cause_codes = list(
            dict.fromkeys(code.lower() for code in cause_codes if str(code).strip())
        )
        use_case._current_cause_taxonomy = validation_exception_taxonomy
        use_case._current_validation_decision = (
            _build_validation_decision_for_use_case(use_case, validation_exception_taxonomy)
            if validation_exception_taxonomy
            else {}
        )
        logger.error("Validation error for %s: %s", product.sku, error_msg)
        use_case.errors.append(f"{product.sku}: {error_msg}")
        use_case.failed += 1
        return False

    if use_case.dry_run and not use_case.validation_only:
        logger.info("DRY RUN: Payload valid for %s, skipping create step.", product.sku)
        use_case.published += 1
        if use_case.feedback and validation_result:
            use_case.feedback.record_validation_result(
                product.sku, ml_attributes, validation_result
            )
        return True

    if use_case.validation_only:
        logger.info("VALIDATION ONLY: Payload valid for %s", product.sku)
        use_case.published += 1
        if use_case.feedback and validation_result:
            use_case.feedback.record_validation_result(
                product.sku, ml_attributes, validation_result
            )
        return True

    published_item_id: str | None = None
    cbt_item_id: str | None = None
    try:
        result = use_case._create_item_for_flow(item=item, selected_flow=selected_flow)
        published_item_id = result.get("id")

        cbt_item_id = use_case.cbt_extractor.extract_cbt_id(result)

        logger.info("Published %s: %s", product.sku, published_item_id)
        if cbt_item_id and cbt_item_id != published_item_id:
            logger.debug("CBT parent item ID for %s: %s", product.sku, cbt_item_id)

        description_text = product.description.strip()
        if published_item_id and description_text:
            use_case._publish_item_description(
                item_id=published_item_id,
                description=description_text,
                sku=product.sku,
            )

        use_case.published += 1

        if use_case.feedback and validation_result:
            use_case.feedback.record_validation_result(
                product.sku, ml_attributes, validation_result
            )

        if (
            use_case.enable_fiscal_submission
            and use_case.fiscal_service
            and published_item_id
            and product.fiscal
            and product.fiscal.is_valid
        ):
            logger.info("Queueing fiscal data for %s (item: %s)", product.sku, published_item_id)
            use_case._pending_fiscal.append((published_item_id, product.fiscal))

        if use_case.clip_uploader and cbt_item_id:
            sku = product.sku or ""
            if sku:
                logger.info("Uploading clips for %s (CBT item: %s)", sku, cbt_item_id)
                clip_summary = use_case.clip_uploader.upload_clips(
                    sku=sku,
                    item_id=cbt_item_id,
                )
                use_case.clip_results.append(
                    {
                        "sku": sku,
                        "item_id": cbt_item_id,
                        "clips_uploaded": clip_summary.clips_uploaded,
                        "clips_failed": clip_summary.clips_failed,
                        "clips_skipped": clip_summary.clips_skipped,
                        "results": [
                            {
                                "file": result.file,
                                "clip_uuid": result.clip_uuid,
                                "status": result.status,
                                "error": result.error,
                            }
                            for result in clip_summary.results
                        ],
                    }
                )
                if clip_summary.clips_uploaded > 0:
                    logger.info(
                        "Clips uploaded for %s: %s success", sku, clip_summary.clips_uploaded
                    )
                if clip_summary.clips_failed > 0:
                    logger.warning(
                        "Clip upload failures for %s: %s failed (item will still be published)",
                        sku,
                        clip_summary.clips_failed,
                    )

        return True
    except Exception as error:
        error_msg = str(error)
        publish_cause_codes: list[str] = []
        publish_exception_taxonomy: list[dict[str, str]] = []
        error_detail = extract_exception_error_detail(error)
        if error_detail is not None:
            error_msg = f"{error_msg} - {error_detail}"
            causes_raw = error_detail.get("cause", [])
            causes = causes_raw if isinstance(causes_raw, list) else []
            normalized_causes = [cause for cause in causes if isinstance(cause, dict)]
            publish_exception_taxonomy = build_validation_cause_taxonomy(normalized_causes)
            if use_case.feedback:
                use_case.feedback.record_validation_result(
                    product.sku,
                    ml_attributes,
                    error_detail,
                )
            for cause in normalized_causes:
                cause_code = str(cause.get("code", "")).strip().lower()
                if cause_code:
                    publish_cause_codes.append(cause_code)
            shipping_cause_decisions = _register_shipping_cause_decisions(
                use_case,
                causes,
                stage="publish_exception",
            )
            for shipping_cause in shipping_cause_decisions:
                logger.error(
                    "Shipping publish error for %s: [%s] %s",
                    product.sku,
                    shipping_cause.get("classification"),
                    shipping_cause,
                )
        else:
            response_excerpt = extract_exception_response_excerpt(error)
            if response_excerpt:
                error_msg = f"{error_msg} - {response_excerpt}"
        use_case._current_cause_codes = list(
            dict.fromkeys(code.lower() for code in publish_cause_codes if str(code).strip())
        )
        use_case._current_cause_taxonomy = publish_exception_taxonomy
        use_case._current_validation_decision = (
            _build_validation_decision_for_use_case(use_case, publish_exception_taxonomy)
            if publish_exception_taxonomy
            else {}
        )
        logger.error("Publish error for %s: %s", product.sku, error_msg)
        use_case.errors.append(f"{product.sku}: {error_msg}")
        use_case.failed += 1
        return False


__all__ = ["publish_one"]
