"""CLI command implementation for manifest-driven publishing."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import typer
from rich.console import Console

from mercadolivre_upload.application.publish_payload import publish_payload_file
from mercadolivre_upload.contracts.run_manifest import load_run_manifest

console = Console()
err_console = Console(stderr=True)


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
    if path.is_absolute():
        resolved = path.resolve()
    else:
        resolved = (manifest_path.parent / path).resolve()

    manifest_root = manifest_path.parent.resolve()
    if not (
        _is_within_root(path=resolved, root=workspace_root)
        or _is_within_root(path=resolved, root=manifest_root)
    ):
        raise ValueError(f"Payload path escapes allowed roots: {resolved}")
    return resolved


def _write_manifest_report(
    *,
    run_id: str,
    report_dir: Path,
    manifest_path: Path,
    dry_run: bool,
    results: list[dict[str, Any]],
) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"publish-manifest-summary-{run_id}.json"
    failed = [item for item in results if item.get("status") == "failed"]
    skipped = [item for item in results if item.get("status") == "skipped"]
    published = [item for item in results if item.get("status") == "published"]
    report_payload = {
        "run_id": run_id,
        "manifest_path": str(manifest_path),
        "published_at": datetime.now(UTC).isoformat(),
        "dry_run": dry_run,
        "summary": {
            "total": len(results),
            "failed": len(failed),
            "published": len(published),
            "skipped": len(skipped),
            "published_or_skipped": len(results) - len(failed),
        },
        "results": results,
    }
    report_path.write_text(json.dumps(report_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return report_path


def publish_manifest(
    manifest_path: Path,
    *,
    dry_run: bool = False,
    publish_inactive: bool = False,
    report_dir: Path = Path("cache/reports"),
    seller_config: Path = Path("config/publisher.yaml"),
) -> None:
    """Publish one or many payloads declared in run_manifest.json."""
    manifest = load_run_manifest(manifest_path)
    workspace_root = Path(manifest.workspace_path).expanduser()
    if not workspace_root.is_absolute():
        workspace_root = workspace_root.resolve()

    if manifest.blocking_issues:
        details = "\n".join(f"- {issue}" for issue in manifest.blocking_issues)
        err_console.print(
            "[red]Erro:[/red] run_manifest possui blocking_issues e não pode ser publicado:\n"
            f"{details}"
        )
        raise typer.Exit(1)

    results: list[dict[str, Any]] = []
    for artifact in manifest.artifacts:
        if artifact.status != "done":
            results.append(
                {
                    "status": "skipped",
                    "sku": artifact.sku,
                    "artifact_status": artifact.status,
                    "errors": [],
                    "warnings": [f"Artifact skipped due to status={artifact.status}"],
                }
            )
            continue
        for raw_path in artifact.payload_paths:
            try:
                payload_path = _resolve_manifest_payload_path(
                    manifest_path=manifest_path,
                    workspace_root=workspace_root,
                    raw_path=raw_path,
                )
            except ValueError as exc:
                results.append(
                    {
                        "status": "failed",
                        "sku": artifact.sku,
                        "payload_path": raw_path,
                        "errors": [str(exc)],
                        "warnings": [],
                    }
                )
                continue
            if not payload_path.exists() or not payload_path.is_file():
                results.append(
                    {
                        "status": "failed",
                        "sku": artifact.sku,
                        "payload_path": str(payload_path),
                        "errors": [f"Payload file not found: {payload_path}"],
                        "warnings": [],
                    }
                )
                continue
            result = publish_payload_file(
                payload_path,
                report_dir=None,
                dry_run=dry_run,
                publish_inactive=publish_inactive,
                seller_config_path=seller_config,
            )
            result["payload_path"] = str(payload_path)
            results.append(result)

    report_path = _write_manifest_report(
        run_id=manifest.run_id,
        report_dir=report_dir,
        manifest_path=manifest_path,
        dry_run=dry_run,
        results=results,
    )
    console.print(f"[cyan]Manifest report: {report_path}[/cyan]")

    failures = [item for item in results if item.get("status") == "failed"]
    if failures:
        raise typer.Exit(1)
