"""CLI support helpers for single JSON payload publishing."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import typer
from rich.console import Console

from mercadolivre_upload.adapters.json_payload_reader import JsonPayloadReader
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
from mercadolivre_upload.domain.fiscal.service import FiscalService

logger = logging.getLogger(__name__)
console = Console()
err_console = Console(stderr=True)

_DEFAULT_SELLER_CONFIG_PATH = Path("config/publisher.yaml")


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
    fiscal_service = FiscalService(api_client)
    return PublishJsonUseCase(
        reader=reader,
        policy=policy,
        publisher=api_client,
        fiscal_service=fiscal_service,
        publish_inactive=seller_config.batch.publish_inactive,
    )


def _print_result(result: PublishJsonResult) -> None:
    """Print a single PublishJsonResult to the Rich console."""
    label = result.sku or Path(result.path).name
    if result.status == "published":
        published_item_ids = result.item_ids or ([result.item_id] if result.item_id else [])
        if len(published_item_ids) > 1:
            target = f"{published_item_ids[0]} (+{len(published_item_ids) - 1})"
            if result.user_product_id:
                target = f"{target} | UP {result.user_product_id}"
        else:
            target = result.item_id or "sem item_id"
        console.print(f"[green]✓[/green] {label} → {target}")
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
                "item_ids": r.item_ids,
                "user_product_id": r.user_product_id,
                "error": r.error,
                "warnings": r.warnings,
            }
            for r in results
        ],
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report_path


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
