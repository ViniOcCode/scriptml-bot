"""Tests for secure token manager persistence modes."""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from cryptography.fernet import Fernet

from mercadolivre_upload.auth.exceptions import AuthError
from mercadolivre_upload.auth.token_manager import TokenManager


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


def _sample_tokens() -> dict[str, object]:
    return {
        "access_token": "access-token",
        "refresh_token": "refresh-token",
        "expires_at": 9_999_999_999,
    }


def test_secure_storage_mode_saves_encrypted_tokens(tmp_path: Path, monkeypatch) -> None:
    """When secure mode is enabled, tokens should be persisted to .enc file."""
    monkeypatch.setenv("ML_PIPE_MERCADO_LIVRE_USE_SECURE_STORAGE", "1")
    monkeypatch.setenv("ML_PIPE_ENCRYPTION_KEY", Fernet.generate_key().decode())
    token_path = tmp_path / "tokens.json"
    tokens = _sample_tokens()

    manager = TokenManager(token_path=str(token_path), oauth_handler=MagicMock())
    manager.save_tokens(tokens)

    encrypted_path = tmp_path / "tokens.json.enc"
    assert encrypted_path.exists()
    assert not token_path.exists()
    assert encrypted_path.read_bytes() != json.dumps(tokens, indent=2).encode("utf-8")

    reloaded = TokenManager(token_path=str(token_path), oauth_handler=MagicMock())
    assert reloaded.load_tokens() == tokens


def test_secure_storage_default_is_enabled(tmp_path: Path, monkeypatch) -> None:
    """Secure mode should be enabled when no explicit env flag is provided."""
    monkeypatch.delenv("ML_PIPE_MERCADO_LIVRE_USE_SECURE_STORAGE", raising=False)
    monkeypatch.setenv("ML_PIPE_ENCRYPTION_KEY", Fernet.generate_key().decode())
    token_path = tmp_path / "tokens.json"

    manager = TokenManager(token_path=str(token_path), oauth_handler=MagicMock())
    manager.save_tokens(_sample_tokens())

    assert (tmp_path / "tokens.json.enc").exists()
    assert not token_path.exists()


def test_secure_storage_auto_migration(tmp_path: Path, monkeypatch) -> None:
    """Default auto-migration should move plaintext tokens to encrypted storage."""
    monkeypatch.setenv("ML_PIPE_MERCADO_LIVRE_USE_SECURE_STORAGE", "1")
    monkeypatch.delenv("ML_PIPE_MERCADO_LIVRE_AUTO_MIGRATE_TOKENS", raising=False)
    monkeypatch.setenv("ML_PIPE_ENCRYPTION_KEY", Fernet.generate_key().decode())

    token_path = tmp_path / "tokens.json"
    tokens = _sample_tokens()
    token_path.write_text(json.dumps(tokens), encoding="utf-8")

    manager = TokenManager(token_path=str(token_path), oauth_handler=MagicMock())

    encrypted_path = tmp_path / "tokens.json.enc"
    backup_path = tmp_path / "tokens.json.backup"
    assert encrypted_path.exists()
    assert backup_path.exists()
    assert not token_path.exists()
    assert manager.load_tokens() == tokens


def test_save_tokens_drops_non_persisted_fields(tmp_path: Path, monkeypatch) -> None:
    """Only access/refresh/expires_at should be persisted."""
    monkeypatch.setenv("ML_PIPE_MERCADO_LIVRE_USE_SECURE_STORAGE", "0")
    token_path = tmp_path / "tokens.json"
    manager = TokenManager(token_path=str(token_path), oauth_handler=MagicMock())
    manager.save_tokens(
        {
            "access_token": "access-token",
            "refresh_token": "refresh-token",
            "expires_at": 9_999_999_999,
            "user_id": "user-123",
            "unexpected": "ignored",
        }
    )

    persisted = json.loads(token_path.read_text(encoding="utf-8"))
    assert persisted == _sample_tokens()


def test_vault_mode_loads_and_saves_tokens_without_legacy_files(tmp_path: Path) -> None:
    token_secret_path = "profiles/default/mercadolivre/tokens"
    store = _MemorySecretStore({token_secret_path: json.dumps(_sample_tokens())})

    manager = TokenManager(
        secret_store=store,
        token_secret_path=token_secret_path,
        oauth_handler=MagicMock(),
    )
    assert manager.load_tokens() == _sample_tokens()

    manager.save_tokens(
        {
            "access_token": "new-access",
            "refresh_token": "new-refresh",
            "expires_at": 9_999_999_999,
            "unexpected": "not persisted",
        }
    )

    assert json.loads(store.values[token_secret_path]) == {
        "access_token": "new-access",
        "refresh_token": "new-refresh",
        "expires_at": 9_999_999_999,
    }
    assert not (tmp_path / ".ml_token.enc").exists()


def test_vault_mode_refreshes_and_persists_tokens() -> None:
    token_secret_path = "profiles/default/mercadolivre/tokens"
    store = _MemorySecretStore(
        {
            token_secret_path: json.dumps(
                {
                    "access_token": "expired-access",
                    "refresh_token": "refresh-token",
                    "expires_at": 1,
                }
            )
        }
    )
    oauth_handler = MagicMock()
    oauth_handler.refresh_token.return_value = {
        "access_token": "refreshed-access",
        "expires_at": 9_999_999_999,
    }
    manager = TokenManager(
        secret_store=store,
        token_secret_path=token_secret_path,
        oauth_handler=oauth_handler,
    )

    tokens = manager.refresh_token()

    oauth_handler.refresh_token.assert_called_once_with("refresh-token")
    assert tokens["access_token"] == "refreshed-access"
    assert tokens["refresh_token"] == "refresh-token"
    assert json.loads(store.values[token_secret_path]) == {
        "access_token": "refreshed-access",
        "refresh_token": "refresh-token",
        "expires_at": 9_999_999_999,
    }


def test_secure_storage_load_failure_is_explicit(tmp_path: Path, monkeypatch) -> None:
    """Secure mode should raise AuthError when encrypted token file is unreadable."""
    monkeypatch.setenv("ML_PIPE_MERCADO_LIVRE_USE_SECURE_STORAGE", "1")
    monkeypatch.setenv("ML_PIPE_ENCRYPTION_KEY", Fernet.generate_key().decode())
    token_path = tmp_path / "tokens.json"
    encrypted_path = tmp_path / "tokens.json.enc"
    encrypted_path.write_bytes(b"invalid-encrypted-payload")

    manager = TokenManager(token_path=str(token_path), oauth_handler=MagicMock())

    with pytest.raises(AuthError, match="Secure token storage error"):
        manager.load_tokens()


def test_secure_storage_auto_migration_failure_is_explicit(tmp_path: Path, monkeypatch) -> None:
    """Auto migration failures must not silently continue in secure mode."""
    monkeypatch.setenv("ML_PIPE_MERCADO_LIVRE_USE_SECURE_STORAGE", "1")
    monkeypatch.setenv("ML_PIPE_MERCADO_LIVRE_AUTO_MIGRATE_TOKENS", "1")
    monkeypatch.setenv("ML_PIPE_ENCRYPTION_KEY", Fernet.generate_key().decode())

    token_path = tmp_path / "tokens.json"
    token_path.write_text("{invalid-json", encoding="utf-8")

    with pytest.raises(AuthError, match="Secure token migration failed"):
        TokenManager(token_path=str(token_path), oauth_handler=MagicMock())


def test_workspace_root_uses_dot_token_and_dot_fernet_key(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("ML_PIPE_ENCRYPTION_KEY", raising=False)
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir(parents=True, exist_ok=True)
    key_path = workspace_root / ".ml_fernet_key"
    key_path.write_text(Fernet.generate_key().decode(), encoding="utf-8")

    manager = TokenManager(workspace_root=workspace_root, oauth_handler=MagicMock())
    manager.save_tokens(_sample_tokens())

    assert (workspace_root / ".ml_token.enc").exists()
    assert manager.load_tokens() == _sample_tokens()


def test_workspace_root_fails_without_fernet_key_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("ML_PIPE_ENCRYPTION_KEY", raising=False)
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir(parents=True, exist_ok=True)
    manager = TokenManager(workspace_root=workspace_root, oauth_handler=MagicMock())

    with pytest.raises(AuthError, match="Secure token storage error"):
        manager.save_tokens(_sample_tokens())
