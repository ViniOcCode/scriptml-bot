from __future__ import annotations

from pathlib import Path

import pytest

from mercadolivre_upload.auth.exceptions import OAuthError
from mercadolivre_upload.auth.oauth import OAuthHandler


def test_oauth_handler_reads_only_client_id_from_development_config(
    tmp_path: Path, monkeypatch
) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "publisher.yaml").write_text(
        "auth:\n" "  ml_app_id: app-123\n",
        encoding="utf-8",
    )
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir(parents=True, exist_ok=True)
    (secrets_dir / "ml_app_secret").write_text("secret-xyz\n", encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ML_PIPE_MERCADO_LIVRE_CLIENT_ID", raising=False)
    monkeypatch.delenv("ML_PIPE_MERCADO_LIVRE_CLIENT_SECRET", raising=False)

    handler = OAuthHandler()
    assert handler.client_id == "app-123"
    assert handler.client_secret is None


def test_oauth_handler_prefers_explicit_args_over_file_defaults(
    tmp_path: Path, monkeypatch
) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "publisher.yaml").write_text(
        "auth:\n" "  ml_app_id: app-file\n",
        encoding="utf-8",
    )
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir(parents=True, exist_ok=True)
    (secrets_dir / "ml_app_secret").write_text("secret-file\n", encoding="utf-8")

    monkeypatch.chdir(tmp_path)

    handler = OAuthHandler(client_id="app-explicit", client_secret="secret-explicit")
    assert handler.client_id == "app-explicit"
    assert handler.client_secret == "secret-explicit"


def test_oauth_handler_never_reads_secret_relative_to_settings_file(
    tmp_path: Path, monkeypatch
) -> None:
    repo_root = tmp_path / "repo"
    config_dir = repo_root / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    settings_file = config_dir / "publisher.yaml"
    settings_file.write_text(
        "auth:\n" "  ml_app_id: app-789\n",
        encoding="utf-8",
    )
    secrets_dir = repo_root / "secrets"
    secrets_dir.mkdir(parents=True, exist_ok=True)
    (secrets_dir / "ml_app_secret").write_text("secret-789\n", encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ML_PIPE_MERCADO_LIVRE_CLIENT_SECRET", raising=False)
    handler = OAuthHandler(settings_file=settings_file)
    assert handler.client_id == "app-789"
    assert handler.client_secret is None


def test_oauth_handler_production_ignores_legacy_secret_environment(
    tmp_path: Path, monkeypatch
) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    settings_file = config_dir / "publisher.yaml"
    settings_file.write_text(
        "auth:\n" "  ml_app_id: app-vault\n",
        encoding="utf-8",
    )
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir(parents=True, exist_ok=True)
    (secrets_dir / "ml_app_secret").write_text("legacy-secret\n", encoding="utf-8")

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("ML_PIPE_MERCADO_LIVRE_CLIENT_SECRET", "env-secret")

    handler = OAuthHandler(client_id="app-current", settings_file=settings_file)

    assert handler.client_id == "app-current"
    assert handler.client_secret is None
    with pytest.raises(OAuthError, match="Client ID and Client Secret are required"):
        handler.refresh_token("refresh-token")
