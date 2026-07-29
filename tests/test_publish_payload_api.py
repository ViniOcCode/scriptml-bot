"""Tests for the public publish_payload API and CLI command."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from unittest.mock import ANY, MagicMock, patch

import pytest
import requests
import typer
from cryptography.fernet import Fernet
from ml_app_settings_core import OAuthCredentialRepository
from typer.testing import CliRunner

from mercadolivre_upload.adapters.json_payload_reader import JsonPayloadReader
from mercadolivre_upload.application import publish_payload as publish_payload_api
from mercadolivre_upload.application.dashboard_api import (
    apply_remote_item_update,
    complete_existing_item_fiscal_file,
    fetch_authenticated_seller_identity,
    publish_effective_payload_outcome,
    publish_manifest_file,
    validate_effective_payload_file,
)
from mercadolivre_upload.application.publish_payload import PublisherRuntime
from mercadolivre_upload.auth.exceptions import AuthError
from mercadolivre_upload.auth.publisher_context import build_publisher_auth_context
from mercadolivre_upload.cli import app
from mercadolivre_upload.cli.commands.publish_runtime import resolve_workspace_root
from mercadolivre_upload.contracts.publication import PublicationOutcome
from mercadolivre_upload.domain.fiscal.service import (
    FiscalSubmissionResult,
    FiscalSubmissionStatus,
)


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
        "fiscal": {"items": []},
        "_meta": {
            "category_decision": {
                "schema_version": 1,
                "category_id": "MLB271599",
                "source": "ai",
                "resolution_mode": "llm_authoritative",
                "review": {"status": "unreviewed", "evidence": None},
            },
            "sku": "ABC-001",
            "publication": {
                "seller_model": "items",
                "publication_ready": True,
            },
            "traceability": {"publish_item_skus": ["ABC-001"]},
        },
    }


def _canonical_oauth_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, str]:
    database = tmp_path / "settings.sqlite3"
    with closing(sqlite3.connect(database)) as connection:
        connection.executescript("""
            CREATE TABLE integration_profiles (
                id TEXT PRIMARY KEY, slug TEXT NOT NULL, active INTEGER NOT NULL
            );
            CREATE TABLE dashboard_settings (
                key TEXT PRIMARY KEY, value_json TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            """)
        connection.execute(
            "INSERT INTO integration_profiles(id,slug,active) VALUES (?,?,1)",
            ("profile-default", "default"),
        )
        connection.execute(
            "INSERT INTO dashboard_settings(key,value_json,updated_at) VALUES (?,?,?)",
            (
                "ml_oauth_active_identity:profile-default",
                json.dumps({"seller_id": "seller-expected", "document_type": "CNPJ"}),
                "now",
            ),
        )
        connection.execute(
            "INSERT INTO dashboard_settings(key,value_json,updated_at) VALUES (?,?,?)",
            (
                "runtime_config:publisher_config",
                json.dumps(
                    {
                        "auth": {"ml_app_id": "app-current"},
                        "seller": {
                            "listing": {
                                "allowed_types": ["gold_special"],
                                "default_type": "gold_special",
                            },
                            "pricing": {"min_price": 1, "max_price": 999999},
                        },
                    }
                ),
                "now",
            ),
        )
        connection.commit()
    encryption_key = Fernet.generate_key().decode("ascii")
    repository = OAuthCredentialRepository(database, encryption_key)
    repository.initialize_schema()
    pending = repository.put_pending(
        flow_id="flow-1",
        state_hash="state-1",
        profile_id="profile-default",
        provider="mercadolivre",
        external_account_id="seller-expected",
        credential_kind="tokens",
        payload={
            "access_token": "access-from-sqlite",
            "refresh_token": "refresh-from-sqlite",
            "expires_at": 9_999_999_999,
        },
        expires_at=9_999_999_999,
    )
    repository.promote_pending("flow-1", expected_row_version=pending.row_version)
    client_id_file = tmp_path / "ml-client-id"
    client_id_file.write_text("app-current", encoding="utf-8")
    client_secret_file = tmp_path / "ml-client-secret"
    client_secret_file.write_text("client-secret-from-snapshot", encoding="utf-8")
    encryption_key_file = tmp_path / "oauth-encryption-key"
    encryption_key_file.write_text(encryption_key, encoding="utf-8")
    monkeypatch.setenv("MLBOT_SETTINGS_DB", str(database))
    monkeypatch.setenv("ML_CLIENT_ID_FILE", str(client_id_file))
    monkeypatch.setenv("ML_CLIENT_SECRET_FILE", str(client_secret_file))
    monkeypatch.setenv("OAUTH_TOKEN_ENCRYPTION_KEY_FILE", str(encryption_key_file))
    monkeypatch.delenv("ML_CLIENT_ID", raising=False)
    monkeypatch.delenv("ML_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("OAUTH_TOKEN_ENCRYPTION_KEY", raising=False)
    return database, encryption_key


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


def test_publish_payload_rejects_legacy_root_shape_before_auth(
    tmp_path: Path,
    monkeypatch,
) -> None:
    canonical = _minimal_builder_payload()
    legacy = dict(canonical["payload"])
    legacy["_meta"] = canonical["_meta"]
    payload_path = tmp_path / "legacy.json"
    payload_path.write_text(json.dumps(legacy), encoding="utf-8")
    runtime_builder = MagicMock()
    monkeypatch.setattr(PublisherRuntime, "build", runtime_builder)

    result = publish_payload_api.publish_payload_file(
        payload_path,
        seller_config_path=tmp_path / "publisher.yaml",
        workspace_root=tmp_path / "workspace",
    )

    assert result["status"] == "failed"
    assert "envelope" in result["errors"][0]
    runtime_builder.assert_not_called()


def test_minimal_valid_builder_payload_normalizes(tmp_path: Path) -> None:
    payload_path = tmp_path / "70_payload.json"
    payload_path.write_text(json.dumps(_minimal_builder_payload()), encoding="utf-8")

    result = JsonPayloadReader().read(payload_path)

    assert result.sku == "ABC-001"
    assert result.payload["category_id"] == "MLB271599"
    assert result.publication_ready is True
    assert result.description == "Descricao do produto"


def test_publisher_runtime_reuses_prepared_payload_within_one_invocation(
    tmp_path: Path,
) -> None:
    payload_path = tmp_path / "70_payload.json"
    payload_path.write_text(json.dumps(_minimal_builder_payload()), encoding="utf-8")
    reader = JsonPayloadReader()
    reader.read = MagicMock(wraps=reader.read)  # type: ignore[method-assign]
    use_case = MagicMock()
    use_case.execute.return_value = PublicationOutcome(
        sku="ABC-001",
        path=str(payload_path),
        status="published",
        side_effect_state="confirmed",
        item_id="MLB123",
        item_ids=["MLB123"],
    )
    runtime = PublisherRuntime(reader=reader, use_case=use_case)

    first = runtime.publish(payload_path, dry_run=False, execute=True, confirmation="PUBLICAR")
    second = runtime.publish(payload_path, dry_run=False, execute=True, confirmation="PUBLICAR")

    assert first.status == second.status == "published"
    assert reader.read.call_count == 1
    prepared_payloads = [
        call.kwargs["prepared_payload"] for call in use_case.execute.call_args_list
    ]
    assert prepared_payloads[0] is prepared_payloads[1]


def test_publish_payload_file_uses_mocked_use_case(tmp_path: Path, monkeypatch) -> None:
    payload_path = tmp_path / "70_payload.json"
    payload_path.write_text(json.dumps(_minimal_builder_payload()), encoding="utf-8")
    mock_use_case = MagicMock()
    mock_use_case.execute.return_value = PublicationOutcome(
        sku="ABC-001",
        path=str(payload_path),
        status="published",
        side_effect_state="confirmed",
        item_id="MLB123",
        item_ids=["MLB123"],
    )
    build_use_case = MagicMock(return_value=mock_use_case)
    monkeypatch.setattr(publish_payload_api, "_build_use_case", build_use_case)

    result = publish_payload_api.publish_payload_file(
        payload_path,
        report_dir=tmp_path / "reports",
        dry_run=False,
        execute=True,
        confirmation="PUBLICAR",
        publish_inactive=True,
        seller_config_path=tmp_path / "publisher.yaml",
        workspace_root=tmp_path / "workspace",
    )

    build_use_case.assert_called_once_with(
        publish_inactive=True,
        seller_config_path=tmp_path / "publisher.yaml",
        workspace_root=tmp_path / "workspace",
        reader=ANY,
        ml_client_id=None,
        expected_seller_id=None,
        expected_document_type=None,
    )
    mock_use_case.execute.assert_called_once_with(
        payload_path,
        dry_run=False,
        prepared_payload=ANY,
    )
    assert result["status"] == "published"
    assert result["item_id"] == "MLB123"
    assert result["errors"] == []
    assert Path(result["report_path"]).exists()


def test_publish_payload_outcome_keeps_typed_contract_until_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload_path = tmp_path / "70_payload.json"
    payload_path.write_text(json.dumps(_minimal_builder_payload()), encoding="utf-8")
    mock_use_case = MagicMock()
    mock_use_case.execute.return_value = PublicationOutcome(
        sku="ABC-001",
        path=str(payload_path),
        status="published",
        side_effect_state="confirmed",
        item_id="MLB123",
        item_ids=["MLB123"],
    )
    monkeypatch.setattr(
        publish_payload_api,
        "_build_use_case",
        MagicMock(return_value=mock_use_case),
    )

    outcome = publish_payload_api.publish_payload_outcome(
        payload_path,
        report_dir=tmp_path / "reports",
        dry_run=False,
        execute=True,
        confirmation="PUBLICAR",
        seller_config_path=tmp_path / "publisher.yaml",
        workspace_root=tmp_path / "workspace",
    )

    assert isinstance(outcome, PublicationOutcome)
    assert outcome.status == "published"
    assert outcome.report_path == str(tmp_path / "reports" / "report.json")


def test_dashboard_effective_payload_has_typed_internal_entrypoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    payload_path = workspace / "payload.json"
    payload_path.write_text(json.dumps(_minimal_builder_payload()), encoding="utf-8")
    expected = PublicationOutcome(
        sku="ABC-001",
        path=str(payload_path),
        status="published",
        side_effect_state="confirmed",
        item_id="MLB123",
        item_ids=["MLB123"],
    )
    typed_publish = MagicMock(return_value=expected)
    monkeypatch.setattr(
        "mercadolivre_upload.application.dashboard_api.publish_payload_outcome",
        typed_publish,
    )
    monkeypatch.setattr(
        "mercadolivre_upload.application.dashboard_api._build_authenticated_client",
        MagicMock(),
    )

    outcome = publish_effective_payload_outcome(
        payload_path,
        seller_config_path=tmp_path / "publisher.yaml",
        workspace_root=workspace,
    )

    assert outcome is expected


def test_dashboard_effective_payload_outside_workspace_is_rejected_before_auth(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    payload_path = tmp_path / "outside.json"
    payload_path.write_text(json.dumps(_minimal_builder_payload()), encoding="utf-8")
    with patch(
        "mercadolivre_upload.application.dashboard_api._build_authenticated_client"
    ) as authenticate:
        outcome = publish_effective_payload_outcome(
            payload_path,
            seller_config_path=tmp_path / "publisher.yaml",
            workspace_root=workspace,
        )

    assert outcome.status == "failed"
    assert outcome.side_effect_state == "none"
    assert outcome.reconciliation_required is False
    authenticate.assert_not_called()


def test_publish_payload_report_keeps_validation_warnings(tmp_path: Path, monkeypatch) -> None:
    payload_path = tmp_path / "70_payload.json"
    payload_path.write_text(json.dumps(_minimal_builder_payload()), encoding="utf-8")
    mock_use_case = MagicMock()
    mock_use_case.execute.return_value = PublicationOutcome(
        sku="ABC-001",
        path=str(payload_path),
        status="published",
        side_effect_state="confirmed",
        item_id="MLB123",
        item_ids=["MLB123"],
        warnings=[
            "ML validation warning: [shipping.lost_me1_by_user] | "
            "department=shipping | User has not mode me1 | "
            "references=item.shipping.mode"
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
    monkeypatch.setattr(
        publish_payload_api,
        "_build_use_case",
        MagicMock(return_value=mock_use_case),
    )

    result = publish_payload_api.publish_payload_file(
        payload_path,
        report_dir=tmp_path / "reports",
        dry_run=False,
        execute=True,
        confirmation="PUBLICAR",
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
    remote_client = MagicMock()
    remote_client.get_available_listing_types.return_value = [{"id": "gold_special"}]
    remote_client.validate_item.return_value = {}
    monkeypatch.setattr(publish_payload_api, "MLApiClient", MagicMock(return_value=remote_client))
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
        "ml_client_id": None,
        "expected_seller_id": None,
        "expected_document_type": None,
    }


def test_seller_policy_forces_paused_publication_even_without_cli_flag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _publisher_config(tmp_path)
    auth_context = MagicMock()
    auth_context.token_manager = MagicMock()
    monkeypatch.setattr(
        publish_payload_api,
        "build_publisher_auth_context",
        MagicMock(return_value=auth_context),
    )

    use_case = publish_payload_api._build_use_case(
        publish_inactive=False,
        seller_config_path=config,
        workspace_root=tmp_path / "workspace",
    )

    assert use_case._publish_inactive is True


def test_publish_payload_uses_explicit_config_from_unrelated_cwd(
    tmp_path: Path, monkeypatch
) -> None:
    payload_path = tmp_path / "70_payload.json"
    payload_path.write_text(json.dumps(_minimal_builder_payload()), encoding="utf-8")
    config = _publisher_config(tmp_path)
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    monkeypatch.chdir(unrelated)
    monkeypatch.setattr(
        publish_payload_api,
        "build_publisher_auth_context",
        MagicMock(return_value=MagicMock(token_manager=MagicMock())),
    )
    remote_client = MagicMock()
    remote_client.get_available_listing_types.return_value = [{"id": "gold_special"}]
    remote_client.validate_item.return_value = {}
    monkeypatch.setattr(publish_payload_api, "MLApiClient", MagicMock(return_value=remote_client))

    result = publish_payload_api.publish_payload_file(
        payload_path,
        dry_run=True,
        seller_config_path=config,
        workspace_root=tmp_path / "workspace",
    )

    assert result["status"] == "skipped"


def test_missing_runtime_secret_snapshot_fails_closed(tmp_path: Path, monkeypatch) -> None:
    config = _publisher_config(tmp_path)
    _canonical_oauth_runtime(tmp_path, monkeypatch)
    monkeypatch.delenv("ML_CLIENT_SECRET_FILE")

    with pytest.raises(AuthError) as exc:
        build_publisher_auth_context(
            settings_file=config,
            workspace_root=tmp_path / "workspace",
            strict=True,
            expected_seller_id="seller-expected",
            expected_document_type="CNPJ",
        )

    assert "runtime secret snapshot" in str(exc.value)


def test_missing_workspace_root_hard_fails(tmp_path: Path) -> None:
    config = tmp_path / "publisher.yaml"
    config.write_text("seller: {}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Missing workspace_root"):
        resolve_workspace_root(workspace=None, seller_config=config)


def test_publication_auth_uses_encrypted_sqlite_and_secret_files(
    tmp_path: Path, monkeypatch
) -> None:
    config = _publisher_config(tmp_path)
    workspace = tmp_path / "workspace"
    _canonical_oauth_runtime(tmp_path, monkeypatch)
    monkeypatch.setenv("ML_PIPE_MERCADO_LIVRE_TOKEN_PATH", str(tmp_path / "legacy_tokens.json"))

    context = build_publisher_auth_context(
        settings_file=config,
        workspace_root=workspace,
        strict=True,
        expected_seller_id="seller-expected",
        expected_document_type="CNPJ",
    )

    assert context.token_path == "sqlite:oauth_credentials"
    assert context.key_path is None
    assert str(context.token_manager.token_path) == "sqlite-oauth-credentials"
    assert context.token_manager.load_tokens()["access_token"] == "access-from-sqlite"
    assert context.expected_seller_id == "seller-expected"
    assert context.expected_document_type == "CNPJ"
    assert not (tmp_path / "legacy_tokens.json").exists()


def test_dashboard_publication_flow_does_not_reference_legacy_token_sources() -> None:
    root = Path(__file__).resolve().parents[3]
    flow_files = [
        root / "apps/scriptml-bot/mercadolivre_upload/auth/publisher_context.py",
        root / "apps/scriptml-bot/mercadolivre_upload/application/publish_payload.py",
        root / "apps/scriptml-bot/mercadolivre_upload/application/dashboard_api.py",
        root / "apps/ml-dashboard/ml_dashboard/app.py",
        root / "apps/ml-dashboard/ml_dashboard/worker.py",
    ]
    forbidden = [
        ".ml_token.enc",
        ".ml_fernet_key",
        "ML_PIPE_MERCADO_LIVRE_TOKEN_PATH",
        "ml_app_secret",
        "tokens.json",
    ]
    offenders = {
        str(path.relative_to(root)): [
            marker for marker in forbidden if marker in path.read_text(encoding="utf-8")
        ]
        for path in flow_files
    }
    assert {path: markers for path, markers in offenders.items() if markers} == {}


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


def test_dashboard_account_identity_returns_only_stable_remote_identifiers(
    tmp_path: Path,
) -> None:
    auth_context = MagicMock()
    with (
        patch(
            "mercadolivre_upload.application.dashboard_api.build_publisher_auth_context",
            return_value=auth_context,
        ),
        patch("mercadolivre_upload.application.dashboard_api.MLApiClient") as client_class,
    ):
        client_class.return_value.get.return_value = {
            "id": 123456789,
            "site_id": "mlb",
            "nickname": "must-not-leak",
            "email": "must-not-leak@example.invalid",
        }
        identity = fetch_authenticated_seller_identity(
            seller_config_path=tmp_path / "publisher.yaml",
            workspace_root=tmp_path / "workspace",
        )

    assert identity == {
        "status": "authenticated",
        "seller_id": "123456789",
        "site_id": "MLB",
    }
    client_class.return_value.get.assert_called_once_with("/users/me")


def test_dashboard_account_identity_rejects_incomplete_provider_response(
    tmp_path: Path,
) -> None:
    with (
        patch(
            "mercadolivre_upload.application.dashboard_api.build_publisher_auth_context",
            return_value=MagicMock(),
        ),
        patch("mercadolivre_upload.application.dashboard_api.MLApiClient") as client_class,
    ):
        client_class.return_value.get.return_value = {"id": 123456789}
        with pytest.raises(AuthError, match="identity is incomplete"):
            fetch_authenticated_seller_identity(
                seller_config_path=tmp_path / "publisher.yaml",
                workspace_root=tmp_path / "workspace",
            )


def test_dashboard_account_identity_enforces_expected_taxpayer_document(
    tmp_path: Path,
) -> None:
    auth_context = MagicMock()
    with (
        patch(
            "mercadolivre_upload.application.dashboard_api.build_publisher_auth_context",
            return_value=auth_context,
        ) as build_context,
        patch("mercadolivre_upload.application.dashboard_api.MLApiClient") as client_class,
    ):
        client_class.return_value.get.return_value = {
            "id": 123456789,
            "site_id": "MLB",
            "identification": {"type": "CPF"},
        }
        with pytest.raises(AuthError, match="taxpayer document"):
            fetch_authenticated_seller_identity(
                seller_config_path=tmp_path / "publisher.yaml",
                workspace_root=tmp_path / "workspace",
                expected_seller_id="123456789",
                expected_document_type="CNPJ",
            )

    assert build_context.call_args.kwargs["expected_document_type"] == "CNPJ"


def test_dashboard_validation_rejects_payload_outside_workspace(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    payload = tmp_path / "outside.json"
    payload.write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="outside the allowed workspace"):
        validate_effective_payload_file(
            payload,
            seller_config_path=tmp_path / "publisher.yaml",
            workspace_root=workspace,
        )


def test_dashboard_remote_update_requires_explicit_lifecycle_operation_for_status(
    tmp_path: Path,
) -> None:
    blocked = apply_remote_item_update(
        "MLB123",
        {"status": "closed"},
        operation="update",
        seller_config_path=tmp_path / "publisher.yaml",
        workspace_root=tmp_path / "workspace",
        dry_run=True,
    )
    finalized = apply_remote_item_update(
        "MLB123",
        {"status": "closed"},
        operation="finalize",
        seller_config_path=tmp_path / "publisher.yaml",
        workspace_root=tmp_path / "workspace",
        dry_run=True,
    )

    assert blocked == {
        "status": "failed",
        "side_effect_state": "none",
        "reconciliation_required": False,
        "errors": ["Status changes require pause, activate, finalize, or delete operation."],
    }
    assert finalized == {
        "status": "dry_run",
        "side_effect_state": "none",
        "reconciliation_required": False,
        "item_id": "MLB123",
        "operation": "finalize",
        "patch": {"status": "closed"},
    }


def test_dashboard_manifest_exit_without_report_returns_client_safe_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _exit_without_report(**_kwargs: object) -> None:
        raise typer.Exit(1)

    monkeypatch.setattr(
        "mercadolivre_upload.cli.commands.publish_manifest.publish_manifest",
        _exit_without_report,
    )
    monkeypatch.setattr(
        "mercadolivre_upload.application.dashboard_api._build_authenticated_client",
        MagicMock(),
    )

    result = publish_manifest_file(
        tmp_path / "run_manifest.json",
        seller_config_path=tmp_path / "publisher.yaml",
        workspace_root=tmp_path / "workspace",
        report_dir=tmp_path / "reports",
    )

    assert result == {
        "status": "failed",
        "result_code": "publication_unavailable",
        "errors": ["Este lote não está disponível para publicação."],
        "report_path": str(tmp_path / "reports" / "report.json"),
        "cli_exit_code": 1,
    }


def test_dashboard_remote_update_timeout_requires_reconciliation(tmp_path: Path) -> None:
    with (
        patch(
            "mercadolivre_upload.application.dashboard_api.build_publisher_auth_context",
            return_value=MagicMock(),
        ),
        patch("mercadolivre_upload.application.dashboard_api.MLApiClient") as client_class,
    ):
        client_class.return_value.get.return_value = {
            "id": "123456789",
            "site_id": "MLB",
            "identification": {"type": "CNPJ"},
        }
        client_class.return_value.update_item.side_effect = requests.Timeout("timed out")

        outcome = apply_remote_item_update(
            "MLB123",
            {"status": "paused"},
            operation="pause",
            seller_config_path=tmp_path / "publisher.yaml",
            workspace_root=tmp_path / "workspace",
        )

    assert outcome == {
        "status": "unknown",
        "side_effect_state": "unknown",
        "reconciliation_required": True,
        "item_id": "MLB123",
        "errors": [
            "Não foi possível confirmar a atualização. "
            "Verifique o anúncio antes de tentar novamente."
        ],
    }
    client_class.return_value.update_item.assert_called_once_with("MLB123", {"status": "paused"})


def test_dashboard_remote_update_connection_error_requires_reconciliation(
    tmp_path: Path,
) -> None:
    with (
        patch(
            "mercadolivre_upload.application.dashboard_api.build_publisher_auth_context",
            return_value=MagicMock(),
        ),
        patch("mercadolivre_upload.application.dashboard_api.MLApiClient") as client_class,
    ):
        client_class.return_value.get.return_value = {
            "id": "123456789",
            "site_id": "MLB",
            "identification": {"type": "CNPJ"},
        }
        client_class.return_value.update_item.side_effect = requests.ConnectionError(
            "connection dropped after send"
        )

        outcome = apply_remote_item_update(
            "MLB123",
            {"status": "paused"},
            operation="pause",
            seller_config_path=tmp_path / "publisher.yaml",
            workspace_root=tmp_path / "workspace",
        )

    assert outcome["status"] == "unknown"
    assert outcome["side_effect_state"] == "unknown"
    assert outcome["reconciliation_required"] is True
    client_class.return_value.update_item.assert_called_once_with("MLB123", {"status": "paused"})


def test_dashboard_remote_update_success_is_confirmed_and_auditable(
    tmp_path: Path,
) -> None:
    with (
        patch(
            "mercadolivre_upload.application.dashboard_api.build_publisher_auth_context",
            return_value=MagicMock(),
        ),
        patch("mercadolivre_upload.application.dashboard_api.MLApiClient") as client_class,
    ):
        client_class.return_value.get.return_value = {
            "id": "123456789",
            "site_id": "MLB",
            "identification": {"type": "CNPJ"},
        }
        client_class.return_value.update_item.return_value = {
            "id": "MLB123",
            "status": "paused",
        }

        outcome = apply_remote_item_update(
            "MLB123",
            {"status": "paused"},
            operation="pause",
            seller_config_path=tmp_path / "publisher.yaml",
            workspace_root=tmp_path / "workspace",
        )

    assert outcome == {
        "status": "updated",
        "side_effect_state": "confirmed",
        "reconciliation_required": False,
        "item_id": "MLB123",
        "operation": "pause",
        "patch": {"status": "paused"},
        "response": {"id": "MLB123", "status": "paused"},
    }


def test_dashboard_fiscal_recovery_requires_terminal_invoice_confirmation(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    payload_path = workspace / "effective.json"
    payload = _minimal_builder_payload()
    payload["fiscal"] = {
        "items": [
            {
                "sku": "ABC-001",
                "type": "single",
                "measurement_unit": "UN",
                "cost": 10,
                "tax_information": {
                    "ncm": "39263000",
                    "origin_type": "reseller",
                    "origin_detail": "2",
                },
            }
        ]
    }
    payload_path.write_text(json.dumps(payload), encoding="utf-8")
    client = MagicMock()
    client.get.return_value = {
        "id": "MLB123",
        "seller_id": "seller-expected",
        "status": "paused",
        "attributes": [{"id": "SELLER_SKU", "value_name": "ABC-001"}],
    }
    fiscal_result = FiscalSubmissionResult(
        success=True,
        item_id="MLB123",
        sku="ABC-001",
        status=FiscalSubmissionStatus.VERIFIED,
        side_effect_state="confirmed",
        invoice_ready=True,
    )
    with (
        patch(
            "mercadolivre_upload.application.dashboard_api._build_authenticated_client",
            return_value=(
                client,
                {"seller_id": "seller-expected", "site_id": "MLB", "document_type": "CNPJ"},
            ),
        ),
        patch("mercadolivre_upload.application.dashboard_api.FiscalService") as fiscal_service,
    ):
        fiscal_service.return_value.submit_fiscal_data_workflow.return_value = fiscal_result
        result = complete_existing_item_fiscal_file(
            payload_path,
            "MLB123",
            seller_config_path=tmp_path / "publisher.yaml",
            workspace_root=workspace,
            expected_seller_id="seller-expected",
            expected_document_type="CNPJ",
        )

    assert result["status"] == result["fiscal_status"] == "completed"
    assert result["side_effect_state"] == "confirmed"
    assert result["reconciliation_required"] is False
    assert result["invoice_ready"] is True
    assert result["payload_path"] == str(payload_path)
    assert result["remote_item_id"] == "MLB123"


def test_dashboard_fiscal_recovery_rejects_symlinked_payload(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps(_minimal_builder_payload()), encoding="utf-8")
    symlink = workspace / "effective.json"
    symlink.symlink_to(outside)

    with (
        patch(
            "mercadolivre_upload.application.dashboard_api._build_authenticated_client"
        ) as authenticate,
        pytest.raises(ValueError, match="outside the allowed workspace|Symlinked"),
    ):
        complete_existing_item_fiscal_file(
            symlink,
            "MLB123",
            seller_config_path=tmp_path / "publisher.yaml",
            workspace_root=workspace,
        )

    authenticate.assert_not_called()


def test_remote_update_rejects_invalid_item_id_before_auth(tmp_path: Path) -> None:
    with (
        patch(
            "mercadolivre_upload.application.dashboard_api.build_publisher_auth_context"
        ) as build_context,
        pytest.raises(ValueError, match="Invalid item_id format"),
    ):
        apply_remote_item_update(
            "../MLB123",
            {"status": "paused"},
            operation="pause",
            seller_config_path=tmp_path / "publisher.yaml",
            workspace_root=tmp_path / "workspace",
        )

    build_context.assert_not_called()


def test_remote_update_blocks_authenticated_seller_mismatch_before_mutation(
    tmp_path: Path,
) -> None:
    auth_context = MagicMock()
    with (
        patch(
            "mercadolivre_upload.application.dashboard_api.build_publisher_auth_context",
            return_value=auth_context,
        ) as build_context,
        patch("mercadolivre_upload.application.dashboard_api.MLApiClient") as client_class,
    ):
        client_class.return_value.get.return_value = {
            "id": "seller-other",
            "site_id": "MLB",
            "identification": {"type": "CNPJ"},
        }

        with pytest.raises(AuthError, match="expected seller"):
            apply_remote_item_update(
                "MLB123",
                {"status": "paused"},
                operation="pause",
                seller_config_path=tmp_path / "publisher.yaml",
                workspace_root=tmp_path / "workspace",
                ml_client_id="app-current",
                expected_seller_id="seller-expected",
            )

    build_context.assert_called_once_with(
        settings_file=tmp_path / "publisher.yaml",
        workspace_root=tmp_path / "workspace",
        strict=True,
        ml_client_id="app-current",
        expected_seller_id="seller-expected",
        expected_document_type=None,
    )
    client_class.return_value.update_item.assert_not_called()


def test_remote_update_blocks_item_from_another_site(tmp_path: Path) -> None:
    with (
        patch(
            "mercadolivre_upload.application.dashboard_api.build_publisher_auth_context",
            return_value=MagicMock(),
        ),
        patch("mercadolivre_upload.application.dashboard_api.MLApiClient") as client_class,
    ):
        client_class.return_value.get.return_value = {
            "id": "seller-expected",
            "site_id": "MLA",
            "identification": {"type": "CUIT"},
        }

        with pytest.raises(AuthError, match="item site"):
            apply_remote_item_update(
                "MLB123",
                {"status": "paused"},
                operation="pause",
                seller_config_path=tmp_path / "publisher.yaml",
                workspace_root=tmp_path / "workspace",
                expected_seller_id="seller-expected",
            )

    client_class.return_value.update_item.assert_not_called()


def test_effective_validation_blocks_taxpayer_mismatch_before_item_validation(
    tmp_path: Path,
) -> None:
    seller_config = _publisher_config(tmp_path)
    (tmp_path / "workspace").mkdir()
    payload_path = tmp_path / "workspace" / "70_payload.json"
    payload_path.write_text(json.dumps(_minimal_builder_payload()), encoding="utf-8")
    with (
        patch(
            "mercadolivre_upload.application.dashboard_api.build_publisher_auth_context",
            return_value=MagicMock(),
        ),
        patch("mercadolivre_upload.application.dashboard_api.MLApiClient") as client_class,
    ):
        client_class.return_value.get.return_value = {
            "id": "seller-expected",
            "site_id": "MLB",
            "identification": {"type": "CPF"},
        }

        with pytest.raises(AuthError, match="expected document"):
            validate_effective_payload_file(
                payload_path,
                seller_config_path=seller_config,
                workspace_root=tmp_path / "workspace",
                expected_seller_id="seller-expected",
                expected_document_type="CNPJ",
            )

    client_class.return_value.validate_item.assert_not_called()


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
    mock_runtime_module.build_attempt_report_dir.return_value = (
        tmp_path / "workspace" / "cache" / "report" / "20260514-010203"
    )

    with patch(
        "mercadolivre_upload.cli.app.import_module",
        side_effect=[mock_runtime_module, mock_api_module],
    ):
        result = CliRunner().invoke(
            app,
            [
                "publish-payload",
                str(payload_path),
                "--workspace",
                str(tmp_path / "workspace"),
                "--config",
                str(seller_config),
            ],
        )

    assert result.exit_code == 0
    assert "Validation passed with warnings; continuing publication." in result.output
    mock_api_module.publish_payload_file.assert_called_once()
    call_args = mock_api_module.publish_payload_file.call_args
    assert call_args.args == (payload_path,)
    assert call_args.kwargs["dry_run"] is True
    assert call_args.kwargs["publish_inactive"] is True
    assert call_args.kwargs["execute"] is False
    assert call_args.kwargs["confirmation"] is None
    assert call_args.kwargs["seller_config_path"] == seller_config
    assert call_args.kwargs["workspace_root"] == tmp_path / "workspace"


def test_public_api_rejects_real_publish_without_explicit_intent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload_path = tmp_path / "70_payload.json"
    payload_path.write_text(json.dumps(_minimal_builder_payload()), encoding="utf-8")
    runtime_builder = MagicMock()
    monkeypatch.setattr(PublisherRuntime, "build", runtime_builder)

    result = publish_payload_api.publish_payload_file(
        payload_path,
        dry_run=False,
        seller_config_path=tmp_path / "publisher.yaml",
        workspace_root=tmp_path / "workspace",
    )

    assert result["status"] == "failed"
    assert "--execute" in result["errors"][0]
    runtime_builder.assert_not_called()


def test_public_api_requires_exact_publicar_confirmation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload_path = tmp_path / "70_payload.json"
    payload_path.write_text(json.dumps(_minimal_builder_payload()), encoding="utf-8")
    runtime_builder = MagicMock()
    monkeypatch.setattr(PublisherRuntime, "build", runtime_builder)

    result = publish_payload_api.publish_payload_file(
        payload_path,
        dry_run=False,
        execute=True,
        confirmation="publicar",
        seller_config_path=tmp_path / "publisher.yaml",
        workspace_root=tmp_path / "workspace",
    )

    assert result["status"] == "failed"
    assert "PUBLICAR" in result["errors"][0]
    runtime_builder.assert_not_called()
