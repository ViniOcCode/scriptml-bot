"""Tests for the public publish_payload API and CLI command."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from mercadolivre_upload.adapters.json_payload_reader import JsonPayloadReader
from mercadolivre_upload.application import publish_payload as publish_payload_api
from mercadolivre_upload.application.publish_payload_use_case import PublishPayloadResult
from mercadolivre_upload.auth.exceptions import AuthError
from mercadolivre_upload.auth.publisher_context import build_publisher_auth_context
from mercadolivre_upload.cli.commands.publish_runtime import resolve_workspace_root
from mercadolivre_upload.cli import app


def _publisher_config(tmp_path: Path, *, include_credentials: bool = True) -> Path:
    workspace = tmp_path / "workspace"
    secrets = tmp_path / "secrets"
    secrets.mkdir(parents=True, exist_ok=True)
    if include_credentials:
        (secrets / "ml_app_secret").write_text("secret-from-file", encoding="utf-8")
    config = tmp_path / "config" / "publisher.yaml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(
        "runtime:\n"
        f"  workspace_root: {workspace}\n"
        "auth:\n"
        f"  ml_app_id: {'app-from-config' if include_credentials else ''}\n"
        "seller:\n"
        "  listing:\n"
        "    allowed_types: [gold_special]\n"
        "    default_type: gold_special\n"
        "  pricing:\n"
        "    min_price: 1\n"
        "    max_price: 999999\n"
        "  categories:\n"
        "    blocked: []\n"
        "    overrides: {}\n"
        "  batch:\n"
        "    human_review_required: false\n",
        encoding="utf-8",
    )
    return config


def _minimal_builder_payload() -> dict[str, object]:
    return {
        "payload": {
            "title": "Produto Teste",
            "category_id": "MLB271599",
            "price": 50.0,
            "currency_id": "BRL",
            "available_quantity": 10,
            "buying_mode": "buy_it_now",
            "listing_type_id": "gold_special",
            "condition": "new",
            "pictures": [{"id": "PIC123"}],
            "attributes": [{"id": "SELLER_SKU", "value_name": "ABC-001"}],
        },
        "description": "Descricao do produto",
        "_meta": {
            "sku": "ABC-001",
            "publication": {"publication_ready": True},
            "traceability": {"publish_item_skus": ["ABC-001"]},
        },
    }


def test_invalid_payload_file_returns_clear_error(tmp_path: Path) -> None:
    payload_path = tmp_path / "70_payload.json"
    payload_path.write_text("{invalid", encoding="utf-8")

    result = publish_payload_api.publish_payload_file(
        payload_path,
        seller_config_path=_publisher_config(tmp_path),
        workspace_root=tmp_path / "workspace",
    )

    assert result["status"] == "failed"
    assert "Invalid JSON payload" in result["errors"][0]


def test_minimal_valid_builder_payload_normalizes(tmp_path: Path) -> None:
    payload_path = tmp_path / "70_payload.json"
    payload_path.write_text(json.dumps(_minimal_builder_payload()), encoding="utf-8")

    result = JsonPayloadReader().read(payload_path)

    assert result.sku == "ABC-001"
    assert result.payload["category_id"] == "MLB271599"
    assert result.publication_ready is True
    assert result.description == "Descricao do produto"


def test_publish_payload_file_uses_mocked_use_case(tmp_path: Path, monkeypatch) -> None:
    payload_path = tmp_path / "70_payload.json"
    payload_path.write_text(json.dumps(_minimal_builder_payload()), encoding="utf-8")
    mock_use_case = MagicMock()
    mock_use_case.execute.return_value = PublishPayloadResult(
        sku="ABC-001",
        path=str(payload_path),
        status="published",
        item_id="MLB123",
    )
    build_use_case = MagicMock(return_value=mock_use_case)
    monkeypatch.setattr(publish_payload_api, "_build_use_case", build_use_case)

    result = publish_payload_api.publish_payload_file(
        payload_path,
        report_dir=tmp_path / "reports",
        dry_run=False,
        publish_inactive=True,
        seller_config_path=tmp_path / "publisher.yaml",
        workspace_root=tmp_path / "workspace",
    )

    build_use_case.assert_called_once_with(
        publish_inactive=True,
        seller_config_path=tmp_path / "publisher.yaml",
        workspace_root=tmp_path / "workspace",
    )
    mock_use_case.execute.assert_called_once_with(payload_path, dry_run=False)
    assert result["status"] == "published"
    assert result["item_id"] == "MLB123"
    assert result["errors"] == []
    assert Path(result["report_path"]).exists()

def test_publish_payload_report_keeps_validation_warnings(tmp_path: Path, monkeypatch) -> None:
    payload_path = tmp_path / "70_payload.json"
    payload_path.write_text(json.dumps(_minimal_builder_payload()), encoding="utf-8")
    mock_use_case = MagicMock()
    mock_use_case.execute.return_value = PublishPayloadResult(
        sku="ABC-001",
        path=str(payload_path),
        status="published",
        item_id="MLB123",
        warnings=[
            "ML validation warning: [shipping.lost_me1_by_user] | department=shipping | User has not mode me1 | references=item.shipping.mode"
        ],
        validation_status="validation_passed_with_warnings",
        validation_report={
            "status": "validation_passed_with_warnings",
            "should_block": False,
            "warnings": [
                {
                    "type": "warning",
                    "code": "shipping.lost_me1_by_user",
                    "message": "User has not mode me1",
                    "department": "shipping",
                    "references": ["item.shipping.mode"],
                }
            ],
            "errors": [],
        },
        fiscal_status="failed",
        fiscal_report=[
            {
                "item_id": "MLB123",
                "sku": "ABC-001",
                "raw_origin_type": "reseller",
                "normalized_origin_type": "reseller",
                "raw_origin_detail": "2",
                "normalized_origin_detail": "2",
                "ncm": "39263000",
                "missing_fields": [],
                "validation_errors": ["erro fiscal"],
                "api_response": {"error_code": "10086"},
                "published_item_exists": True,
                "final_fiscal_status": "failed",
            }
        ],
    )
    monkeypatch.setattr(publish_payload_api, "_build_use_case", MagicMock(return_value=mock_use_case))

    result = publish_payload_api.publish_payload_file(
        payload_path,
        report_dir=tmp_path / "reports",
        seller_config_path=tmp_path / "publisher.yaml",
        workspace_root=tmp_path / "workspace",
    )

    report_payload = json.loads(Path(result["report_path"]).read_text(encoding="utf-8"))
    assert report_payload["results"][0]["status"] == "published"
    assert report_payload["results"][0]["validation_status"] == "validation_passed_with_warnings"
    assert (
        report_payload["results"][0]["validation_report"]["warnings"][0]["code"]
        == "shipping.lost_me1_by_user"
    )
    assert report_payload["results"][0]["fiscal_status"] == "failed"
    assert report_payload["results"][0]["fiscal_report"][0]["raw_origin_type"] == "reseller"
    assert "ML validation warning" in report_payload["results"][0]["warnings"][0]


def test_publish_payload_passes_resolved_config_and_workspace_to_auth(
    tmp_path: Path, monkeypatch
) -> None:
    payload_path = tmp_path / "70_payload.json"
    payload_path.write_text(json.dumps(_minimal_builder_payload()), encoding="utf-8")
    config = _publisher_config(tmp_path)
    workspace = tmp_path / "workspace"
    captured: dict[str, object] = {}
    mock_context = MagicMock()
    mock_context.token_manager = MagicMock()

    def _fake_context(**kwargs: object) -> object:
        captured.update(kwargs)
        return mock_context

    monkeypatch.setattr(publish_payload_api, "build_publisher_auth_context", _fake_context)
    result = publish_payload_api.publish_payload_file(
        payload_path,
        dry_run=True,
        seller_config_path=config,
        workspace_root=workspace,
    )

    assert result["status"] == "skipped"
    assert captured == {
        "settings_file": config.resolve(),
        "workspace_root": workspace,
        "strict": True,
    }


def test_publish_payload_uses_explicit_config_from_unrelated_cwd(
    tmp_path: Path, monkeypatch
) -> None:
    payload_path = tmp_path / "70_payload.json"
    payload_path.write_text(json.dumps(_minimal_builder_payload()), encoding="utf-8")
    config = _publisher_config(tmp_path)
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    monkeypatch.chdir(unrelated)
    monkeypatch.delenv("ML_PIPE_MERCADO_LIVRE_CLIENT_ID", raising=False)
    monkeypatch.delenv("ML_PIPE_MERCADO_LIVRE_CLIENT_SECRET", raising=False)

    result = publish_payload_api.publish_payload_file(
        payload_path,
        dry_run=True,
        seller_config_path=config,
        workspace_root=tmp_path / "workspace",
    )

    assert result["status"] == "skipped"


def test_missing_client_credentials_names_resolved_config_and_secret_paths(tmp_path: Path) -> None:
    config = _publisher_config(tmp_path, include_credentials=False)

    with pytest.raises(AuthError) as exc:
        build_publisher_auth_context(
            settings_file=config,
            workspace_root=tmp_path / "workspace",
            strict=True,
        )

    message = str(exc.value)
    assert "client_id" in message
    assert "client_secret" in message
    assert str(config.resolve()) in message
    assert str((tmp_path / "secrets" / "ml_app_secret").resolve()) in message


def test_missing_workspace_root_hard_fails(tmp_path: Path) -> None:
    config = tmp_path / "publisher.yaml"
    config.write_text("seller: {}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Missing workspace_root"):
        resolve_workspace_root(workspace=None, seller_config=config)


def test_publication_auth_ignores_fallback_token_sources(tmp_path: Path, monkeypatch) -> None:
    config = _publisher_config(tmp_path)
    workspace = tmp_path / "workspace"
    monkeypatch.setenv("ML_PIPE_MERCADO_LIVRE_TOKEN_PATH", str(tmp_path / "legacy_tokens.json"))

    context = build_publisher_auth_context(
        settings_file=config,
        workspace_root=workspace,
        strict=True,
    )

    assert context.token_path == workspace.resolve() / ".ml_token.enc"
    assert context.key_path == workspace.resolve() / ".ml_fernet_key"
    assert context.token_manager.token_path == workspace.resolve() / ".ml_token.enc"
    assert not (tmp_path / "legacy_tokens.json").exists()


def test_publication_code_does_not_instantiate_plain_token_manager() -> None:
    root = Path(__file__).resolve().parents[1] / "mercadolivre_upload"
    publication_files = [
        root / "application" / "publish_payload.py",
        root / "cli" / "commands" / "publish_manifest.py",
        root / "cli" / "app.py",
    ]
    offenders = [
        str(path.relative_to(root))
        for path in publication_files
        if "TokenManager()" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []


def test_cli_help_exposes_current_publication_commands_only() -> None:
    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "publish-payload" in result.output
    assert "publish-manifest" in result.output
    assert "publish-json" not in result.output


def test_publish_payload_cli_delegates_to_public_api(tmp_path: Path) -> None:
    payload_path = tmp_path / "70_payload.json"
    payload_path.write_text(json.dumps(_minimal_builder_payload()), encoding="utf-8")
    seller_config = tmp_path / "publisher.yaml"
    seller_config.write_text("seller: {}\n", encoding="utf-8")
    mock_api_module = MagicMock()
    mock_api_module.publish_payload_file.return_value = {
        "status": "published",
        "sku": "ABC-001",
        "item_id": "MLB123",
        "item_ids": [],
        "user_product_id": None,
        "errors": [],
        "warnings": [],
        "validation_status": "validation_passed_with_warnings",
        "report_path": None,
    }
    mock_runtime_module = MagicMock()
    mock_runtime_module.resolve_workspace_root.return_value = tmp_path / "workspace"
    mock_runtime_module.build_attempt_report_dir.return_value = tmp_path / "workspace" / "cache" / "report" / "20260514-010203"

    with patch(
        "mercadolivre_upload.cli.app.import_module",
        side_effect=[mock_runtime_module, mock_api_module],
    ):
        result = CliRunner().invoke(
            app, ["publish-payload", str(payload_path), "--config", str(seller_config)]
        )

    assert result.exit_code == 0
    assert "Validation passed with warnings; continuing publication." in result.output
    mock_api_module.publish_payload_file.assert_called_once()
    call_args = mock_api_module.publish_payload_file.call_args
    assert call_args.args == (payload_path,)
    assert call_args.kwargs["dry_run"] is False
    assert call_args.kwargs["publish_inactive"] is False
    assert call_args.kwargs["seller_config_path"] == seller_config
    assert call_args.kwargs["workspace_root"] == tmp_path / "workspace"
