from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from mercadolivre_upload.auth.token_manager import TokenManager


def test_default_token_path_uses_shared_auth_root(monkeypatch) -> None:
    monkeypatch.delenv("ML_BOT_HOME", raising=False)
    manager = TokenManager(oauth_handler=MagicMock())
    assert str(manager.token_path).endswith(".ml-bot/auth/mercadolivre/tokens.json.enc")


def test_ml_bot_home_overrides_default_token_root(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ML_BOT_HOME", str(tmp_path / "bot-home"))
    manager = TokenManager(oauth_handler=MagicMock())
    expected = tmp_path / "bot-home" / "auth" / "mercadolivre" / "tokens.json.enc"
    assert manager.token_path == expected
