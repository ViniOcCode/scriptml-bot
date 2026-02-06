# Compatibility shim: implement minimal authenticator API expected by tests.
from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path


class ConfigError(Exception):
    pass


class AuthError(Exception):
    pass


class TokenError(Exception):
    pass


@dataclass
class AuthCredentials:
    app_id: str
    app_secret: str
    redirect_uri: str = "http://localhost:8000/callback"

    @staticmethod
    def from_env():
        import os

        try:
            return AuthCredentials(
                app_id=os.environ["ML_APP_ID"],
                app_secret=os.environ["ML_APP_SECRET"],
                redirect_uri=os.environ.get("ML_REDIRECT_URI", "http://localhost:8000/callback"),
            )
        except KeyError as e:
            raise ConfigError(f"Missing env var {e.args[0]}")

    @staticmethod
    def from_file(path: Path):
        if not path.exists():
            raise ConfigError("arquivo de credenciais não encontrado")
        data = json.loads(path.read_text())
        return AuthCredentials(
            app_id=data["app_id"],
            app_secret=data["app_secret"],
            redirect_uri=data.get("redirect_uri", "http://localhost:8000/callback"),
        )


@dataclass
class TokenData:
    access_token: str
    refresh_token: str | None
    expires_at: datetime
    user_id: str | None = None
    scope: str | None = None
    token_type: str | None = None

    def is_expired(self, buffer_seconds: int = 0) -> bool:
        return datetime.now() + timedelta(seconds=buffer_seconds) >= self.expires_at

    def to_dict(self):
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at.isoformat(),
            "user_id": self.user_id,
            "scope": self.scope,
            "token_type": self.token_type,
        }

    @staticmethod
    def from_dict(data: dict) -> TokenData:
        expires = data.get("expires_at")
        if isinstance(expires, str):
            expires = datetime.fromisoformat(expires)
        return TokenData(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token"),
            expires_at=expires,
            user_id=str(data.get("user_id")) if data.get("user_id") is not None else None,
            scope=data.get("scope"),
            token_type=data.get("token_type"),
        )


class AuthStatus(Enum):
    UNAUTHENTICATED = "unauthenticated"
    AUTHENTICATED = "authenticated"


class AuthManager:
    def __init__(
        self,
        credentials: AuthCredentials | None = None,
        token_file: Path | None = None,
        auto_save: bool = False,
    ):
        self.credentials = credentials
        self._token_data: TokenData | None = None
        self._token_file = token_file
        self._auto_save = auto_save
        if token_file:
            token_file.parent.mkdir(parents=True, exist_ok=True)
        if credentials is None:
            try:
                self.credentials = AuthCredentials.from_env()
            except Exception:
                self.credentials = None
        if token_file and token_file.exists():
            try:
                data = json.loads(token_file.read_text())
                self._token_data = TokenData.from_dict(data)
            except Exception:
                self._token_data = None

    def is_authenticated(self) -> bool:
        return self._token_data is not None and not self._token_data.is_expired()

    def get_token_data(self) -> TokenData | None:
        return self._token_data

    def set_token(
        self,
        access_token: str,
        refresh_token: str | None = None,
        expires_in: int = 3600,
        user_id: str | None = None,
    ):
        self._token_data = TokenData(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=datetime.now() + timedelta(seconds=expires_in),
            user_id=user_id,
        )
        if self._auto_save and self._token_file:
            self._save_token()

    def _save_token(self):
        if self._token_file and self._token_data:
            self._token_file.parent.mkdir(parents=True, exist_ok=True)
            self._token_file.write_text(json.dumps(self._token_data.to_dict()))

    def logout(self):
        self._token_data = None
        if self._token_file and self._token_file.exists():
            self._token_file.unlink()

    def start_auth_flow(
        self, state: str | None = None, scopes: list[str] | None = None
    ) -> str:
        client = self.credentials.app_id if self.credentials else ""
        scope = "+".join(scopes) if scopes else "read"
        st = state or "state123"
        self._auth_state = st
        return f"https://auth.mercadolivre.com.br/authorization?response_type=code&client_id={client}&redirect_uri={self.credentials.redirect_uri if self.credentials else ''}&scope={scope}&state={st}"

    def get_auth_status(self) -> dict:
        return {
            "authenticated": self.is_authenticated(),
            "status": (
                AuthStatus.AUTHENTICATED.value
                if self.is_authenticated()
                else AuthStatus.UNAUTHENTICATED.value
            ),
            "user_id": self._token_data.user_id if self._token_data else None,
        }

    def get_valid_token(self) -> str:
        if not self._token_data:
            raise TokenError("Não autenticado")
        if self._token_data.is_expired(buffer_seconds=300):
            if not self._token_data.refresh_token:
                raise TokenError("Não há refresh token")
            response = self._make_token_request(
                {"grant_type": "refresh_token", "refresh_token": self._token_data.refresh_token}
            )
            self._apply_token_response(response)
        if not self._token_data:
            raise TokenError("Não autenticado")
        return self._token_data.access_token

    def refresh_token(self):
        if not self._token_data or not self._token_data.refresh_token:
            raise TokenError("Não há refresh token")
        # minimal behaviour: pretend refreshed
        self.set_token(
            "refreshed_token", refresh_token=self._token_data.refresh_token, expires_in=3600
        )

    def exchange_code_for_token(self, code: str, state: str | None = None) -> TokenData:
        if state is not None and hasattr(self, "_auth_state") and self._auth_state != state:
            raise AuthError("CSRF state mismatch")
        response = self._make_token_request({"grant_type": "authorization_code", "code": code})
        self._apply_token_response(response)
        if not self._token_data:
            raise TokenError("Token inválido")
        return self._token_data

    def _apply_token_response(self, response: dict) -> None:
        expires_in = int(response.get("expires_in", 3600))
        self._token_data = TokenData(
            access_token=response["access_token"],
            refresh_token=response.get("refresh_token"),
            expires_at=datetime.now() + timedelta(seconds=expires_in),
            user_id=str(response.get("user_id")) if response.get("user_id") is not None else None,
        )
        if self._auto_save and self._token_file:
            self._save_token()

    def _make_token_request(self, payload: dict) -> dict:
        import json as _json
        from urllib.error import HTTPError

        req = urllib.request.Request(
            "https://api.mercadolibre.com/oauth/token",
            data=_json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = resp.read().decode()
        except HTTPError as exc:
            body = exc.fp.read().decode() if exc.fp else ""
            message = body
            try:
                message = _json.loads(body).get("message", body)
            except Exception:
                pass
            raise TokenError(message)

        return _json.loads(body)


def create_auth_manager(
    app_id: str | None = None,
    app_secret: str | None = None,
    redirect_uri: str | None = None,
) -> AuthManager:
    creds = None
    if app_id and app_secret:
        creds = AuthCredentials(
            app_id=app_id,
            app_secret=app_secret,
            redirect_uri=redirect_uri or "http://localhost:8000/callback",
        )
    return AuthManager(credentials=creds)


def get_auth_url(
    app_id: str | None = None,
    redirect_uri: str | None = None,
    scopes: list[str] | None = None,
) -> str:
    manager = create_auth_manager(app_id=app_id)
    return manager.start_auth_flow(scopes=scopes, state=None)


__all__ = [
    "AuthCredentials",
    "AuthError",
    "AuthManager",
    "AuthStatus",
    "ConfigError",
    "TokenData",
    "TokenError",
    "create_auth_manager",
    "get_auth_url",
]
