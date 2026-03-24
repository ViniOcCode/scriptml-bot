"""CLI command implementations for JSON payload publishing.

Exposes publish_json() and publish_batch() plain functions which are called
by the Typer commands registered in cli/app.py.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import typer
from rich.console import Console

from mercadolivre_upload.adapters.json_payload_reader import (
    JsonPayloadReader,
    ReadPayloadResult,
)
from mercadolivre_upload.api.client import MLApiClient
from mercadolivre_upload.application.publish_json_use_case import (
    PublishJsonResult,
    PublishJsonUseCase,
)
from mercadolivre_upload.application.validators.seller_policy import (
    SellerPolicyValidator,
    default_seller_config,
    load_seller_config,
)
from mercadolivre_upload.auth import TokenManager

logger = logging.getLogger(__name__)
console = Console()
err_console = Console(stderr=True)

_DEFAULT_SELLER_CONFIG_PATH = Path("config/seller.yaml")


def _build_use_case(seller_config_path: Path | None = None) -> PublishJsonUseCase:
    """Wire up PublishJsonUseCase with its runtime dependencies."""
    config_path = seller_config_path or _DEFAULT_SELLER_CONFIG_PATH
    if config_path.exists():
        try:
            seller_config = load_seller_config(config_path)
        except Exception as exc:  # noqa: BLE001
            err_console.print(
                f"[yellow]Aviso: falha ao carregar {config_path}: {exc}. "
                "Usando configuração padrão permissiva.[/yellow]"
            )
            seller_config = default_seller_config()
    else:
        seller_config = default_seller_config()

    reader = JsonPayloadReader()
    policy = SellerPolicyValidator(seller_config)
    auth_manager = TokenManager()
    api_client = MLApiClient(auth_manager)
    return PublishJsonUseCase(reader=reader, policy=policy, publisher=api_client)


def _print_result(result: PublishJsonResult) -> None:
    """Print a single PublishJsonResult to the Rich console."""
    label = result.sku or Path(result.path).name
    if result.status == "published":
        console.print(f"[green]✓[/green] {label} → {result.item_id}")
    elif result.status == "skipped":
        console.print(f"[yellow]–[/yellow] {label}  (dry-run, não publicado)")
    else:
        console.print(f"[red]✗[/red] {label} → {result.error}")
    for warning in result.warnings:
        console.print(f"  [yellow]⚠[/yellow] {warning}")


def _write_report(
    results: list[PublishJsonResult],
    report_dir: Path,
    category_id: str = "json",
) -> Path:
    """Write a JSON summary report and return the path."""
    report_dir.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    report_path = report_dir / f"publish-summary-{category_id}-{run_id}.json"

    published = [r for r in results if r.status == "published"]
    failed = [r for r in results if r.status == "failed"]
    skipped = [r for r in results if r.status == "skipped"]

    report: dict[str, Any] = {
        "run_id": run_id,
        "category_id": category_id,
        "published_at": datetime.now(UTC).isoformat(),
        "dry_run": len(skipped) > 0 and len(published) == 0,
        "summary": {
            "total": len(results),
            "published": len(published),
            "failed": len(failed),
            "skipped": len(skipped),
        },
        "results": [
            {
                "sku": r.sku,
                "path": r.path,
                "status": r.status,
                "item_id": r.item_id,
                "error": r.error,
                "warnings": r.warnings,
            }
            for r in results
        ],
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report_path


def _read_batch_manifest(batch_dir: Path) -> dict[str, Any]:
    """Read batch_manifest.json from batch_dir, return empty dict if absent."""
    manifest_path = batch_dir / "batch_manifest.json"
    if manifest_path.exists():
        return json.loads(manifest_path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]
    return {}


def publish_json(
    path: Path,
    *,
    dry_run: bool = False,
    report_dir: Path = Path("cache/reports"),
) -> None:
    """Publish a single payload.json to Mercado Livre."""
    use_case = _build_use_case()
    result = use_case.execute(path, dry_run=dry_run)
    _print_result(result)
    report_path = _write_report([result], report_dir)
    console.print(f"[cyan]Relatório: {report_path}[/cyan]")
    if result.status == "failed":
        raise typer.Exit(1)


def publish_batch(
    batch_dir: Path,
    *,
    dry_run: bool = False,
    report_dir: Path = Path("cache/reports"),
) -> None:
    """Publish all payload.json files in a batch directory."""
    use_case = _build_use_case()
    reader = JsonPayloadReader()

    manifest = _read_batch_manifest(batch_dir)
    failed_skus: set[str] = set(manifest.get("failed_skus", []))
    ai_suggested_category: bool = bool(manifest.get("ai_suggested_category", False))
    human_reviewed: bool = bool(manifest.get("human_reviewed", False))

    # Safety gate: block batch if AI-suggested category was not reviewed
    if ai_suggested_category and not human_reviewed:
        config_path = _DEFAULT_SELLER_CONFIG_PATH
        try:
            seller_config = (
                load_seller_config(config_path) if config_path.exists() else default_seller_config()
            )
        except Exception:  # noqa: BLE001
            seller_config = default_seller_config()

        if seller_config.batch.human_review_required:
            category_id = manifest.get("category_id", batch_dir.name)
            err_console.print(
                f"[red]Erro:[/red] Batch {category_id} não foi revisado por humano. "
                "Defina [bold]human_reviewed: true[/bold] em batch_manifest.json "
                "ou [bold]human_review_required: false[/bold] em seller.yaml"
            )
            raise typer.Exit(1)

    payload_entries = reader.read_batch(batch_dir)
    if not payload_entries:
        console.print("[yellow]Nenhum payload.json encontrado.[/yellow]")
        return

    category_id_str = str(manifest.get("category_id", batch_dir.name))
    action = "Validando" if dry_run else "Publicando"
    console.print(f"{action} {len(payload_entries)} payload(s) em {category_id_str}/")

    results: list[PublishJsonResult] = []
    for payload_path, read_result in payload_entries:
        if isinstance(read_result, Exception):
            r = PublishJsonResult(
                sku=None,
                path=str(payload_path),
                status="failed",
                error=str(read_result),
            )
            results.append(r)
            _print_result(r)
            continue

        assert isinstance(read_result, ReadPayloadResult)
        # Skip SKUs that failed during ml-builder phase
        if read_result.sku and read_result.sku in failed_skus:
            console.print(f"[dim]– {read_result.sku}  (pulado: falhou no builder)[/dim]")
            continue

        result = use_case.execute(payload_path, dry_run=dry_run)
        results.append(result)
        _print_result(result)

    published_count = sum(1 for r in results if r.status == "published")
    failed_count = sum(1 for r in results if r.status == "failed")
    skipped_count = sum(1 for r in results if r.status == "skipped")

    if dry_run:
        console.print(
            f"\n{len(results)} validados — " f"{skipped_count} ok, " f"{failed_count} com erro"
        )
        console.print(
            "Para publicar os válidos: [cyan]ml-upload publish-batch[/cyan] (sem --dry-run)"
        )
    else:
        console.print(f"\nResultado: {published_count} publicados, " f"{failed_count} falha(s)")

    if results:
        report_path = _write_report(results, report_dir, category_id_str)
        console.print(f"[cyan]Relatório: {report_path}[/cyan]")

    if failed_count > 0:
        raise typer.Exit(1)
