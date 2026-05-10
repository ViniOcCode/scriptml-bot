"""Tests for secure token manager persistence modes."""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from cryptography.fernet import Fernet

from mercadolivre_upload.auth.exceptions import AuthError
from mercadolivre_upload.auth.token_manager import TokenManager


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
