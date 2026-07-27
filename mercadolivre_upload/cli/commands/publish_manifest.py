"""CLI command implementation for manifest-driven publishing."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import typer
from rich.console import Console

from mercadolivre_upload.adapters.json_payload_reader import (
    InvalidPayloadError,
    JsonPayloadReader,
    ReadPayloadResult,
)
from mercadolivre_upload.application.publish_payload import (
    PublisherRuntime,
    publish_payload_outcome,
)
from mercadolivre_upload.application.workspace_artifacts import resolve_workspace_artifact
from mercadolivre_upload.contracts.run_manifest import load_run_manifest

console = Console()
err_console = Console(stderr=True)


def _has_text(value: str | None) -> bool:
    return bool(isinstance(value, str) and value.strip())


def _is_within_root(*, path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _resolve_manifest_payload_path(
    *,
    manifest_path: Path,
    workspace_root: Path,
    raw_path: str,
) -> Path:
    path = Path(raw_path).expanduser()
    resolved_workspace = workspace_root.expanduser().resolve()
    if path.is_absolute():
        candidates = [path.resolve()]
    elif path.parts and path.parts[0] == resolved_workspace.name:
        candidates = [
            (resolved_workspace.parent / path).resolve(),
            (manifest_path.parent / path).resolve(),
        ]
    else:
        candidates = [
            (manifest_path.parent / path).resolve(),
            (resolved_workspace / path).resolve(),
        ]

    valid_candidates = [
        candidate
        for candidate in candidates
        if _is_within_root(path=candidate, root=resolved_workspace)
    ]
    if not valid_candidates:
        raise ValueError(f"Payload path escapes workspace root: {candidates[0]}")

    for candidate in valid_candidates:
        if candidate.exists():
            return candidate
    return valid_candidates[0]


def _prepared_listing_type_id(prepared: ReadPayloadResult) -> tuple[str | None, str | None]:
    """Return the one listing type used by every concrete publish item."""
    if prepared.upload_mode == "user_products":
        raw_items = prepared.payload.get("payload")
        if not isinstance(raw_items, list):
            raw_items = prepared.payload.get("items")
        publish_items = raw_items if isinstance(raw_items, list) else []
    else:
        publish_items = [prepared.payload]

    listing_type_ids = {
        value.strip()
        for item in publish_items
        if isinstance(item, dict)
        if isinstance((value := item.get("listing_type_id")), str) and value.strip()
    }
    if not publish_items or not listing_type_ids:
        return None, "Effective publish payload missing listing_type_id"
    if len(listing_type_ids) != 1:
        return None, "Effective publish payload contains divergent listing_type_id values"
    return next(iter(listing_type_ids)), None


def _selected_payloads(manifest: Any) -> list[Any]:
    return [
        payload
        for candidate in manifest.publication_candidates
        for payload in candidate.payloads
        if payload.publishable
        and _has_text(payload.payload_path)
        and not _has_text(payload.block_reason)
        and not _has_text(payload.skip_reason)
    ]


def _build_payload_result_row(
    *,
    run_id: str,
    candidate: Any,
    payload_variant: Any,
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "group_id": candidate.group_id,
        "family_id": candidate.family_id,
        "sku_scope": list(candidate.sku_scope),
        "topology": candidate.topology,
        "variant": payload_variant.variant,
        "manifest_listing_type_id": payload_variant.listing_type_id,
        "actual_payload_listing_type_id": None,
        "manifest_payload_path": payload_variant.payload_path,
        "resolved_payload_path": None,
        "publishable": payload_variant.publishable,
        "block_reason": payload_variant.block_reason,
        "skip_reason": payload_variant.skip_reason,
        "validation_result": None,
        "publish_result": None,
        "side_effect_state": "none",
        "phases": [],
        "reconciliation_required": False,
        "item_id": None,
        "item_ids": [],
        "user_product_id": None,
        "publish_endpoints": [],
        "api_warnings": [],
        "api_errors": [],
        "fiscal_result": None,
        "skipped_build_failure": False,
    }


def _build_failure_row(*, run_id: str, failure: Any) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "group_id": getattr(failure, "group_id", None),
        "family_id": getattr(failure, "family_id", None),
        "sku_scope": [failure.sku] if getattr(failure, "sku", None) else [],
        "topology": None,
        "variant": None,
        "manifest_listing_type_id": None,
        "actual_payload_listing_type_id": None,
        "manifest_payload_path": None,
        "resolved_payload_path": None,
        "publishable": False,
        "block_reason": ":".join(
            part
            for part in [getattr(failure, "stage", None), getattr(failure, "reason", None)]
            if part
        )
        or "build_failure",
        "skip_reason": "build_failure",
        "validation_result": {"status": "not_publishable"},
        "publish_result": "skipped",
        "side_effect_state": "none",
        "phases": [],
        "reconciliation_required": False,
        "item_id": None,
        "item_ids": [],
        "user_product_id": None,
        "publish_endpoints": [],
        "api_warnings": [],
        "api_errors": [],
        "fiscal_result": None,
        "skipped_build_failure": True,
    }


def _variant_counts(results: list[dict[str, Any]], variant: str) -> dict[str, int]:
    rows = [row for row in results if row.get("variant") == variant]
    selected = [row for row in rows if row.get("selected")]
    return {
        "selected": len(selected),
        "published": len([row for row in rows if row.get("publish_result") == "published"]),
        "published_but_not_grouped": len(
            [row for row in rows if row.get("publish_result") == "published_but_not_grouped"]
        ),
        "failed": len([row for row in rows if row.get("publish_result") == "failed"]),
        "skipped": len([row for row in rows if row.get("publish_result") == "skipped"]),
        "unknown": len([row for row in rows if row.get("publish_result") == "unknown"]),
    }


def _final_status(
    results: list[dict[str, Any]], selected_count: int, build_failure_count: int
) -> str:
    selected_rows = [row for row in results if row.get("selected")]
    published = [row for row in selected_rows if row.get("publish_result") == "published"]
    published_but_not_grouped = [
        row for row in selected_rows if row.get("publish_result") == "published_but_not_grouped"
    ]
    failed_or_skipped_selected = [
        row
        for row in selected_rows
        if row.get("publish_result") in {"failed", "skipped", "unknown"}
    ]
    skipped_unselected = [
        row
        for row in results
        if not row.get("selected")
        and row.get("publish_result") == "skipped"
        and not row.get("skipped_build_failure")
    ]
    if selected_count > 0 and not published and not published_but_not_grouped:
        return "failed"
    if (
        failed_or_skipped_selected
        or skipped_unselected
        or build_failure_count
        or published_but_not_grouped
    ):
        return "partial_success"
    return "success"


def _write_manifest_report(
    *,
    run_id: str,
    report_dir: Path,
    manifest_path: Path,
    dry_run: bool,
    manifest_status: str,
    build_failures: list[dict[str, Any]],
    diagnostics: dict[str, str | None],
    total_candidates: int,
    total_payload_variants: int,
    selected_payload_variants: int,
    results: list[dict[str, Any]],
) -> tuple[Path, str]:
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "report.json"
    skipped = [item for item in results if item.get("publish_result") == "skipped"]
    failed = [item for item in results if item.get("publish_result") == "failed"]
    final_status = _final_status(results, selected_payload_variants, len(build_failures))
    report_payload = {
        "run_id": run_id,
        "manifest_path": str(manifest_path.resolve()),
        "manifest_status": manifest_status,
        "published_at": datetime.now(UTC).isoformat(),
        "dry_run": dry_run,
        "build_failures": build_failures,
        "diagnostics": diagnostics,
        "summary": {
            "total_candidates": total_candidates,
            "total_payload_variants": total_payload_variants,
            "selected_payload_variants": selected_payload_variants,
            "skipped_payload_variants": len(skipped),
            "classic": _variant_counts(results, "classic"),
            "premium": _variant_counts(results, "premium"),
            "build_failures": len(build_failures),
            "diagnostics_paths": diagnostics,
            "failed_payload_variants": len(failed),
            "final_status": final_status,
        },
        "results": results,
    }
    report_path.write_text(
        json.dumps(report_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report_path, final_status


def publish_manifest(
    manifest_path: Path,
    *,
    dry_run: bool = False,
    publish_inactive: bool = False,
    workspace_root: Path,
    report_dir: Path = Path("cache/reports"),
    seller_config: Path = Path("config/publisher.yaml"),
    ml_client_id: str | None = None,
    expected_seller_id: str | None = None,
    expected_document_type: str | None = None,
) -> None:
    """Publish payload variants declared in the current run_manifest.json contract."""
    try:
        manifest_path = resolve_workspace_artifact(
            manifest_path,
            workspace_root=workspace_root,
            suffixes=frozenset({".json"}),
        )
    except (OSError, ValueError) as exc:
        err_console.print(f"[red]Erro:[/red] manifesto fora do workspace: {exc}")
        raise typer.Exit(1) from exc
    manifest = load_run_manifest(manifest_path)
    if not (
        manifest.trust_profile == "production"
        and manifest.run_mode == "autonomous"
        and manifest.generation_outcome == "complete"
        and manifest.quality_gate_status == "passed"
        and manifest.publication_ready
        and not manifest.blocking_gaps
    ):
        err_console.print("[red]Erro:[/red] o manifesto não passou os gates comuns de publicação")
        raise typer.Exit(1)
    all_payload_variants = [
        payload for c in manifest.publication_candidates for payload in c.payloads
    ]
    selected_payloads = _selected_payloads(manifest)
    selected_classic = [p for p in selected_payloads if p.variant == "classic"]
    selected_premium = [p for p in selected_payloads if p.variant == "premium"]
    skipped_or_build_failed_entries = (
        len(all_payload_variants) - len(selected_payloads) + len(manifest.build_failures)
    )
    report_path = report_dir / "report.json"

    console.print(f"[cyan]Manifest:[/cyan] {manifest_path}")
    console.print(f"[cyan]Run ID:[/cyan] {manifest.run_id}")
    console.print(f"[cyan]Manifest status:[/cyan] {manifest.status}")
    console.print(f"[cyan]Total candidates:[/cyan] {len(manifest.publication_candidates)}")
    console.print(f"[cyan]Total payload variants:[/cyan] {len(all_payload_variants)}")
    console.print(f"[cyan]Selected payload variants:[/cyan] {len(selected_payloads)}")
    console.print(f"[cyan]Skipped/build-failed entries:[/cyan] {skipped_or_build_failed_entries}")
    console.print(f"[cyan]Selected classic:[/cyan] {len(selected_classic)}")
    console.print(f"[cyan]Selected premium:[/cyan] {len(selected_premium)}")
    console.print(f"[cyan]Report path:[/cyan] {report_path}")

    results: list[dict[str, Any]] = [
        _build_failure_row(run_id=manifest.run_id, failure=failure)
        for failure in manifest.build_failures
    ]

    if manifest.status == "failed" and selected_payloads:
        report_path, final_status = _write_manifest_report(
            run_id=manifest.run_id,
            report_dir=report_dir,
            manifest_path=manifest_path,
            dry_run=dry_run,
            manifest_status=manifest.status,
            build_failures=[failure.model_dump() for failure in manifest.build_failures],
            diagnostics=manifest.diagnostics,
            total_candidates=len(manifest.publication_candidates),
            total_payload_variants=len(all_payload_variants),
            selected_payload_variants=len(selected_payloads),
            results=results,
        )
        err_console.print(
            "[red]Erro:[/red] run_manifest status='failed' contains publishable "
            "payloads; manifest is inconsistent"
        )
        console.print(f"[cyan]Final status:[/cyan] {final_status}")
        console.print(f"[cyan]Report path:[/cyan] {report_path}")
        raise typer.Exit(1)

    if manifest.status == "failed" and not selected_payloads:
        for candidate in manifest.publication_candidates:
            for payload_variant in candidate.payloads:
                row = _build_payload_result_row(
                    run_id=manifest.run_id,
                    candidate=candidate,
                    payload_variant=payload_variant,
                )
                row["selected"] = False
                row["validation_result"] = {"status": "not_publishable"}
                row["publish_result"] = "skipped"
                if not row["block_reason"]:
                    row["block_reason"] = "manifest_failed"
                results.append(row)
        report_path, final_status = _write_manifest_report(
            run_id=manifest.run_id,
            report_dir=report_dir,
            manifest_path=manifest_path,
            dry_run=dry_run,
            manifest_status=manifest.status,
            build_failures=[failure.model_dump() for failure in manifest.build_failures],
            diagnostics=manifest.diagnostics,
            total_candidates=len(manifest.publication_candidates),
            total_payload_variants=len(all_payload_variants),
            selected_payload_variants=0,
            results=results,
        )
        err_console.print("[red]Erro:[/red] run_manifest status='failed' sem payloads publicáveis")
        console.print(f"[cyan]Final status:[/cyan] {final_status}")
        console.print(f"[cyan]Report path:[/cyan] {report_path}")
        raise typer.Exit(1)

    if not selected_payloads:
        err_console.print("[red]Erro:[/red] run_manifest sem payloads publicáveis")

    selected_payload_ids = {id(payload) for payload in selected_payloads}
    payload_reader = JsonPayloadReader(strict_publisher_contract=True)
    runtime: PublisherRuntime | None = None

    for candidate in manifest.publication_candidates:
        for payload_variant in candidate.payloads:
            result_row = _build_payload_result_row(
                run_id=manifest.run_id,
                candidate=candidate,
                payload_variant=payload_variant,
            )
            is_selected = id(payload_variant) in selected_payload_ids
            result_row["selected"] = is_selected

            if not is_selected:
                result_row["validation_result"] = {"status": "not_publishable"}
                result_row["publish_result"] = "skipped"
                if not payload_variant.publishable and not result_row["block_reason"]:
                    result_row["block_reason"] = "manifest_marked_not_publishable"
                if not _has_text(payload_variant.payload_path):
                    result_row["skip_reason"] = result_row["skip_reason"] or "payload_path_missing"
                results.append(result_row)
                continue

            try:
                payload_path = _resolve_manifest_payload_path(
                    manifest_path=manifest_path,
                    workspace_root=workspace_root,
                    raw_path=payload_variant.payload_path or "",
                )
                if payload_path.exists():
                    payload_path = resolve_workspace_artifact(
                        payload_path,
                        workspace_root=workspace_root,
                        suffixes=frozenset({".json"}),
                    )
            except (OSError, ValueError) as exc:
                result_row["validation_result"] = {"status": "failed"}
                result_row["publish_result"] = "failed"
                result_row["api_errors"] = [str(exc)]
                result_row["block_reason"] = "payload_path_invalid"
                results.append(result_row)
                continue

            result_row["resolved_payload_path"] = str(payload_path)
            if not payload_path.exists() or not payload_path.is_file():
                result_row["validation_result"] = {"status": "failed"}
                result_row["publish_result"] = "failed"
                result_row["api_errors"] = [f"Payload file not found: {payload_path}"]
                result_row["block_reason"] = "payload_missing"
                results.append(result_row)
                continue

            prepared_payload: ReadPayloadResult | None = None
            payload_listing_type_id: str | None = None
            payload_error: str | None = None
            try:
                prepared_payload = payload_reader.read(payload_path)
            except json.JSONDecodeError as exc:
                payload_listing_type_id = None
                payload_error = f"Invalid JSON payload: {exc}"
            except InvalidPayloadError as exc:
                payload_listing_type_id = None
                payload_error = str(exc)
            except OSError as exc:
                payload_listing_type_id = None
                payload_error = f"Could not read payload file: {exc}"
            else:
                payload_listing_type_id, payload_error = _prepared_listing_type_id(prepared_payload)
            result_row["actual_payload_listing_type_id"] = payload_listing_type_id
            if payload_error:
                result_row["validation_result"] = {"status": "failed"}
                result_row["publish_result"] = "failed"
                result_row["api_errors"] = [payload_error]
                result_row["block_reason"] = "payload_invalid"
                results.append(result_row)
                continue

            if payload_listing_type_id != payload_variant.listing_type_id:
                result_row["validation_result"] = {"status": "not_publishable"}
                result_row["publish_result"] = "skipped"
                result_row["block_reason"] = (
                    "listing_type_id_mismatch: "
                    f"manifest={payload_variant.listing_type_id} payload={payload_listing_type_id}"
                )
                results.append(result_row)
                continue

            if runtime is None:
                runtime = PublisherRuntime.build(
                    publish_inactive=publish_inactive,
                    seller_config_path=seller_config,
                    workspace_root=workspace_root,
                    reader=payload_reader,
                    ml_client_id=ml_client_id,
                    expected_seller_id=expected_seller_id,
                    expected_document_type=expected_document_type,
                )
            runtime.remember(payload_path, cast(ReadPayloadResult, prepared_payload))
            outcome = publish_payload_outcome(
                payload_path,
                report_dir=None,
                dry_run=dry_run,
                publish_inactive=publish_inactive,
                seller_config_path=seller_config,
                workspace_root=workspace_root,
                runtime=runtime,
                ml_client_id=ml_client_id,
                expected_seller_id=expected_seller_id,
                expected_document_type=expected_document_type,
            )
            result_row["validation_result"] = outcome.validation_report or {
                "status": outcome.validation_status
            }
            result_row["publish_result"] = outcome.status
            result_row["side_effect_state"] = outcome.side_effect_state
            result_row["phases"] = [phase.model_dump(mode="json") for phase in outcome.phases]
            result_row["reconciliation_required"] = outcome.reconciliation_required
            result_row["item_id"] = outcome.item_id
            result_row["item_ids"] = outcome.item_ids
            result_row["user_product_id"] = outcome.user_product_id
            result_row["publish_endpoints"] = outcome.publish_endpoints
            result_row["api_errors"] = [outcome.error] if outcome.error else []
            result_row["api_warnings"] = outcome.warnings
            result_row["fiscal_result"] = outcome.fiscal_report or outcome.fiscal_status

            if outcome.validation_status == "validation_passed_with_warnings":
                console.print(
                    "[yellow]Validation passed with warnings; continuing publication.[/yellow]"
                )

            results.append(result_row)

    report_path, final_status = _write_manifest_report(
        run_id=manifest.run_id,
        report_dir=report_dir,
        manifest_path=manifest_path,
        dry_run=dry_run,
        manifest_status=manifest.status,
        build_failures=[failure.model_dump() for failure in manifest.build_failures],
        diagnostics=manifest.diagnostics,
        total_candidates=len(manifest.publication_candidates),
        total_payload_variants=len(all_payload_variants),
        selected_payload_variants=len(selected_payloads),
        results=results,
    )

    published_classic = len(
        [
            r
            for r in results
            if r.get("variant") == "classic" and r.get("publish_result") == "published"
        ]
    )
    published_premium = len(
        [
            r
            for r in results
            if r.get("variant") == "premium" and r.get("publish_result") == "published"
        ]
    )
    failed_or_skipped = len(
        [r for r in results if r.get("publish_result") in {"failed", "skipped", "unknown"}]
    )

    console.print(f"[cyan]Published classic:[/cyan] {published_classic}")
    console.print(f"[cyan]Published premium:[/cyan] {published_premium}")
    console.print(f"[cyan]Failed/skipped count:[/cyan] {failed_or_skipped}")
    console.print(f"[cyan]Final status:[/cyan] {final_status}")
    console.print(f"[cyan]Report path:[/cyan] {report_path}")

    if not selected_payloads:
        raise typer.Exit(1)
    if dry_run:
        return
    if final_status != "success":
        raise typer.Exit(1)
