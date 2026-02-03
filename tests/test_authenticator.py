"""Testes para o módulo de autenticação OAuth2."""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from auth.authenticator import (
    AuthCredentials,
    AuthError,
    AuthManager,
    AuthStatus,
    ConfigError,
    TokenData,
    TokenError,
    create_auth_manager,
    get_auth_url,
)


class TestAuthCredentials:
    """Testes para AuthCredentials."""

    def test_from_env_success(self):
        """Testa carregamento de variáveis de ambiente."""
        with patch.dict(
            os.environ,
            {
                "ML_APP_ID": "test_app_id",
                "ML_APP_SECRET": "test_secret",
                "ML_REDIRECT_URI": "http://test.com/callback",
            },
        ):
            creds = AuthCredentials.from_env()
            assert creds.app_id == "test_app_id"
            assert creds.app_secret == "test_secret"
            assert creds.redirect_uri == "http://test.com/callback"

    def test_from_env_missing_vars(self):
        """Testa erro quando variáveis estão faltando."""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ConfigError) as exc_info:
                AuthCredentials.from_env()
            assert "ML_APP_ID" in str(exc_info.value)

    def test_from_env_default_redirect(self):
        """Testa URI padrão quando não especificada."""
        with patch.dict(
            os.environ,
            {
                "ML_APP_ID": "test_app_id",
                "ML_APP_SECRET": "test_secret",
            },
        ):
            creds = AuthCredentials.from_env()
            assert creds.redirect_uri == "http://localhost:8000/callback"

    def test_from_file_success(self, tmp_path):
        """Testa carregamento de arquivo."""
        creds_file = tmp_path / "creds.json"
        creds_file.write_text(
            json.dumps(
                {
                    "app_id": "file_app_id",
                    "app_secret": "file_secret",
                    "redirect_uri": "http://file.com/callback",
                }
            )
        )

        creds = AuthCredentials.from_file(creds_file)
        assert creds.app_id == "file_app_id"
        assert creds.redirect_uri == "http://file.com/callback"

    def test_from_file_not_found(self):
        """Testa erro quando arquivo não existe."""
        with pytest.raises(ConfigError) as exc_info:
            AuthCredentials.from_file(Path("/nonexistent/creds.json"))
        assert "não encontrado" in str(exc_info.value)


class TestTokenData:
    """Testes para TokenData."""

    def test_is_expired_true(self):
        """Testa detecção de token expirado."""
        token = TokenData(
            access_token="token",
            refresh_token="refresh",
            expires_at=datetime.now() - timedelta(hours=1),
            user_id="123",
        )
        assert token.is_expired() is True

    def test_is_expired_false(self):
        """Testa token não expirado."""
        token = TokenData(
            access_token="token",
            refresh_token="refresh",
            expires_at=datetime.now() + timedelta(hours=1),
            user_id="123",
        )
        assert token.is_expired() is False

    def test_is_expired_with_buffer(self):
        """Testa margem de segurança na expiração."""
        token = TokenData(
            access_token="token",
            refresh_token="refresh",
            expires_at=datetime.now() + timedelta(minutes=2),
            user_id="123",
        )
        # Com buffer de 5 minutos, token de 2 minutos está "expirado"
        assert token.is_expired(buffer_seconds=300) is True

    def test_to_dict(self):
        """Testa serialização para dict."""
        expires = datetime.now() + timedelta(hours=1)
        token = TokenData(
            access_token="access",
            refresh_token="refresh",
            expires_at=expires,
            user_id="123",
            scope="read write",
        )
        data = token.to_dict()
        assert data["access_token"] == "access"
        assert data["refresh_token"] == "refresh"
        assert data["user_id"] == "123"
        assert data["scope"] == "read write"

    def test_from_dict(self):
        """Testa desserialização de dict."""
        expires = datetime.now() + timedelta(hours=1)
        data = {
            "access_token": "access",
            "refresh_token": "refresh",
            "expires_at": expires.isoformat(),
            "user_id": "123",
            "token_type": "Bearer",
            "scope": "read",
        }
        token = TokenData.from_dict(data)
        assert token.access_token == "access"
        assert token.user_id == "123"
        assert token.token_type == "Bearer"


class TestAuthManager:
    """Testes para AuthManager."""

    @pytest.fixture
    def temp_token_file(self, tmp_path):
        """Fixture para arquivo de token temporário."""
        return tmp_path / "tokens.json"

    @pytest.fixture
    def credentials(self):
        """Fixture para credenciais de teste."""
        return AuthCredentials(
            app_id="test_app",
            app_secret="test_secret",
            redirect_uri="http://localhost:8000/callback",
        )

    @pytest.fixture
    def auth_manager(self, credentials, temp_token_file):
        """Fixture para AuthManager configurado."""
        return AuthManager(
            credentials=credentials,
            token_file=temp_token_file,
            auto_save=False,
        )

    def test_init_creates_directories(self, tmp_path, credentials):
        """Testa criação de diretórios no init."""
        token_file = tmp_path / "subdir" / "tokens.json"
        auth = AuthManager(
            credentials=credentials,
            token_file=token_file,
            auto_save=False,
        )
        assert token_file.parent.exists()

    def test_load_credentials_from_env(self):
        """Testa carregamento automático de credenciais."""
        with patch.dict(
            os.environ,
            {
                "ML_APP_ID": "env_app_id",
                "ML_APP_SECRET": "env_secret",
            },
        ):
            auth = AuthManager(auto_save=False)
            assert auth.credentials.app_id == "env_app_id"

    def test_load_saved_token(self, credentials, temp_token_file):
        """Testa carregamento de token salvo."""
        expires = datetime.now() + timedelta(hours=1)
        token_data = {
            "access_token": "saved_token",
            "refresh_token": "saved_refresh",
            "expires_at": expires.isoformat(),
            "user_id": "user123",
        }
        temp_token_file.write_text(json.dumps(token_data))

        auth = AuthManager(
            credentials=credentials,
            token_file=temp_token_file,
            auto_save=False,
        )

        assert auth.is_authenticated()
        assert auth.get_token_data().access_token == "saved_token"

    def test_is_authenticated_false_initially(self, auth_manager):
        """Testa estado inicial não autenticado."""
        assert auth_manager.is_authenticated() is False

    def test_get_auth_status_unauthenticated(self, auth_manager):
        """Testa status quando não autenticado."""
        status = auth_manager.get_auth_status()
        assert status["authenticated"] is False
        assert status["status"] == AuthStatus.UNAUTHENTICATED.value

    def test_set_token_manual(self, auth_manager):
        """Testa definição manual de token."""
        auth_manager.set_token("manual_token", expires_in=3600)
        assert auth_manager.is_authenticated()
        assert auth_manager.get_token_data().access_token == "manual_token"

    def test_logout(self, auth_manager):
        """Testa logout."""
        auth_manager.set_token("token", expires_in=3600)
        auth_manager.logout()
        assert auth_manager.is_authenticated() is False
        assert auth_manager.get_token_data() is None

    def test_start_auth_flow_generates_url(self, auth_manager):
        """Testa geração de URL de autorização."""
        url = auth_manager.start_auth_flow()
        assert "https://auth.mercadolivre.com.br/authorization" in url
        assert "response_type=code" in url
        assert "client_id=test_app" in url
        assert "state=" in url

    def test_start_auth_flow_custom_scopes(self, auth_manager):
        """Testa URL com escopos personalizados."""
        url = auth_manager.start_auth_flow(scopes=["read", "offline_access"])
        assert "scope=read+offline_access" in url

    def test_start_auth_flow_preserves_state(self, auth_manager):
        """Testa preservação do state para validação CSRF."""
        url = auth_manager.start_auth_flow(state="my_custom_state")
        assert "state=my_custom_state" in url

    def test_get_valid_token_not_authenticated(self, auth_manager):
        """Testa erro ao obter token sem autenticação."""
        with pytest.raises(TokenError) as exc_info:
            auth_manager.get_valid_token()
        assert "Não autenticado" in str(exc_info.value)

    def test_get_valid_token_refreshes_if_expired(self, auth_manager):
        """Testa renovação automática de token expirado."""
        # Cria token expirado
        expires = datetime.now() - timedelta(hours=1)
        auth_manager._token_data = TokenData(
            access_token="old_token",
            refresh_token="refresh_token",
            expires_at=expires,
            user_id="123",
        )

        # Mock da resposta de refresh
        mock_response = {
            "access_token": "new_token",
            "refresh_token": "new_refresh",
            "expires_in": 21600,
            "user_id": 123,
        }

        with patch.object(
            auth_manager, "_make_token_request", return_value=mock_response
        ):
            token = auth_manager.get_valid_token()
            assert token == "new_token"

    def test_refresh_token_no_refresh_token(self, auth_manager):
        """Testa erro quando não há refresh token."""
        auth_manager.set_token("token", expires_in=3600)
        with pytest.raises(TokenError) as exc_info:
            auth_manager.refresh_token()
        assert "Não há refresh token" in str(exc_info.value)

    def test_exchange_code_invalid_state(self, auth_manager):
        """Testa erro de state mismatch."""
        auth_manager.start_auth_flow(state="expected_state")
        with pytest.raises(AuthError) as exc_info:
            auth_manager.exchange_code_for_token("code", state="wrong_state")
        assert "CSRF" in str(exc_info.value)

    def test_save_token_creates_file(self, auth_manager, temp_token_file):
        """Testa salvamento de token em arquivo."""
        auth_manager._auto_save = True
        auth_manager.set_token("test_token", expires_in=3600)
        auth_manager._save_token()

        assert temp_token_file.exists()
        data = json.loads(temp_token_file.read_text())
        assert data["access_token"] == "test_token"

    @patch("auth.authenticator.urllib.request.urlopen")
    def test_make_token_request_success(self, mock_urlopen, auth_manager):
        """Testa requisição de token bem-sucedida."""
        mock_response = Mock()
        mock_response.read.return_value = json.dumps(
            {"access_token": "token", "refresh_token": "refresh"}
        ).encode()
        mock_urlopen.return_value.__enter__ = Mock(return_value=mock_response)
        mock_urlopen.return_value.__exit__ = Mock(return_value=False)

        result = auth_manager._make_token_request({"grant_type": "test"})
        assert result["access_token"] == "token"

    @patch("auth.authenticator.urllib.request.urlopen")
    def test_make_token_request_http_error(self, mock_urlopen, auth_manager):
        """Testa erro HTTP na requisição de token."""
        from urllib.error import HTTPError
        from io import BytesIO

        # Cria um mock de HTTPError que funciona como contexto
        mock_error = HTTPError(
            url="https://api.mercadolibre.com/oauth/token",
            code=400,
            msg="Bad Request",
            hdrs={},
            fp=BytesIO(json.dumps({"message": "Invalid code"}).encode()),
        )
        mock_urlopen.side_effect = mock_error

        with pytest.raises(TokenError) as exc_info:
            auth_manager._make_token_request({"grant_type": "test"})
        assert "Invalid code" in str(exc_info.value)


class TestHelperFunctions:
    """Testes para funções utilitárias."""

    def test_create_auth_manager_with_params(self):
        """Testa criação com parâmetros explícitos."""
        auth = create_auth_manager(
            app_id="explicit_id",
            app_secret="explicit_secret",
            redirect_uri="http://explicit.com",
        )
        assert auth.credentials.app_id == "explicit_id"
        assert auth.credentials.redirect_uri == "http://explicit.com"

    def test_create_auth_manager_fallback_to_env(self):
        """Testa fallback para variáveis de ambiente."""
        with patch.dict(
            os.environ,
            {
                "ML_APP_ID": "env_id",
                "ML_APP_SECRET": "env_secret",
            },
        ):
            auth = create_auth_manager()
            assert auth.credentials.app_id == "env_id"

    @patch("auth.authenticator.AuthManager")
    def test_get_auth_url(self, mock_manager_class):
        """Testa função utilitária get_auth_url."""
        # Configura o mock
        mock_instance = Mock()
        mock_instance.start_auth_flow.return_value = (
            "https://auth.mercadolivre.com.br/authorization?"
            "response_type=code&client_id=test_id&"
            "redirect_uri=http%3A%2F%2Ftest.com%2Fcallback&"
            "scope=read"
        )
        mock_manager_class.return_value = mock_instance

        url = get_auth_url(
            app_id="test_id",
            redirect_uri="http://test.com/callback",
            scopes=["read"],
        )
        assert "client_id=test_id" in url
        assert "redirect_uri=http%3A%2F%2Ftest.com%2Fcallback" in url
        assert "scope=read" in url


class TestBackwardCompatibility:
    """Testes para compatibilidade com código anterior."""

    def test_old_set_token_interface(self):
        """Testa interface antiga de set_token."""
        auth = AuthManager(auto_save=False)
        auth.set_token("old_style_token")
        assert auth.is_authenticated()
        assert auth.get_token_data().access_token == "old_style_token"

    def test_old_get_auth_status_returns_dict(self):
        """Testa que get_auth_status retorna dict compatível."""
        auth = AuthManager(auto_save=False)
        auth.set_token("token", expires_in=3600)
        
        status = auth.get_auth_status()
        assert isinstance(status, dict)
        assert "authenticated" in status
        assert "user_id" in status
