from __future__ import annotations

from pathlib import Path

import pytest

from mercadolivre_upload.auth.exceptions import OAuthError
from mercadolivre_upload.auth.oauth import OAuthHandler


class _MemorySecretStore:
    def __init__(self, values: dict[str, str] | None = None) -> None:
        self.values = dict(values or {})

    def get_secret(self, path: str) -> str | None:
        return self.values.get(path)

    def set_secret(self, path: str, value: str) -> None:
        self.values[path] = value

    def delete_secret(self, path: str) -> None:
        self.values.pop(path, None)

    def status(self) -> dict[str, object]:
        return {"backend": "memory", "status": "pronto"}


def test_oauth_handler_reads_client_id_from_publisher_yaml(tmp_path: Path, monkeypatch) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "publisher.yaml").write_text(
        "auth:\n"
        "  ml_app_id: app-123\n",
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
    assert handler.client_secret == "secret-xyz"


def test_oauth_handler_prefers_explicit_args_over_file_defaults(tmp_path: Path, monkeypatch) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "publisher.yaml").write_text(
        "auth:\n"
        "  ml_app_id: app-file\n",
        encoding="utf-8",
    )
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir(parents=True, exist_ok=True)
    (secrets_dir / "ml_app_secret").write_text("secret-file\n", encoding="utf-8")

    monkeypatch.chdir(tmp_path)

    handler = OAuthHandler(client_id="app-explicit", client_secret="secret-explicit")
    assert handler.client_id == "app-explicit"
    assert handler.client_secret == "secret-explicit"


def test_oauth_handler_reads_secret_relative_to_settings_file(tmp_path: Path, monkeypatch) -> None:
    repo_root = tmp_path / "repo"
    config_dir = repo_root / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    settings_file = config_dir / "publisher.yaml"
    settings_file.write_text(
        "auth:\n"
        "  ml_app_id: app-789\n",
        encoding="utf-8",
    )
    secrets_dir = repo_root / "secrets"
    secrets_dir.mkdir(parents=True, exist_ok=True)
    (secrets_dir / "ml_app_secret").write_text("secret-789\n", encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    handler = OAuthHandler(settings_file=settings_file)
    assert handler.client_id == "app-789"
    assert handler.client_secret == "secret-789"


def test_oauth_handler_vault_mode_does_not_fallback_to_legacy_secret(
    tmp_path: Path, monkeypatch
) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    settings_file = config_dir / "publisher.yaml"
    settings_file.write_text(
        "auth:\n"
        "  ml_app_id: app-vault\n",
        encoding="utf-8",
    )
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir(parents=True, exist_ok=True)
    (secrets_dir / "ml_app_secret").write_text("legacy-secret\n", encoding="utf-8")

    monkeypatch.setenv("MLBOT_SECRET_BACKEND", "openbao")
    monkeypatch.setenv("ML_PIPE_MERCADO_LIVRE_CLIENT_SECRET", "env-secret")
    monkeypatch.setattr(
        "mercadolivre_upload.auth.oauth.build_secret_store_from_env",
        lambda: _MemorySecretStore(),
    )

    handler = OAuthHandler(settings_file=settings_file)

    assert handler.client_id == "app-vault"
    assert handler.client_secret is None
    with pytest.raises(OAuthError, match="Client ID and Client Secret are required"):
        handler.refresh_token("refresh-token")
