"""Tests for secure token manager persistence modes."""

import json
from pathlib import Path
from unittest.mock import MagicMock

from cryptography.fernet import Fernet

from mercadolivre_upload.auth.token_manager import TokenManager


def _sample_tokens() -> dict[str, object]:
    return {
        "access_token": "access-token",
        "refresh_token": "refresh-token",
        "expires_at": 9_999_999_999,
        "user_id": "123",
    }


def test_secure_storage_mode_saves_encrypted_tokens(tmp_path: Path, monkeypatch) -> None:
    """When secure mode is enabled, tokens should be persisted to .enc file."""
    monkeypatch.setenv("MERCADO_LIVRE_USE_SECURE_STORAGE", "1")
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
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


def test_secure_storage_auto_migration(tmp_path: Path, monkeypatch) -> None:
    """Opt-in auto-migration should move plaintext tokens to encrypted storage."""
    monkeypatch.setenv("MERCADO_LIVRE_USE_SECURE_STORAGE", "1")
    monkeypatch.setenv("MERCADO_LIVRE_AUTO_MIGRATE_TOKENS", "1")
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())

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
