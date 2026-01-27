"""Tests for authentication module."""

import json
import os
import time
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from mercadolivre_upload.auth import OAuthHandler, TokenManager
from mercadolivre_upload.auth.exceptions import OAuthError, TokenExpiredError


class TestTokenManager:
    """Test cases for TokenManager."""

    @pytest.fixture
    def temp_token_file(self, tmp_path):
        """Create a temporary token file."""
        token_file = tmp_path / "tokens.json"
        tokens = {
            "access_token": "APP_USR-test-access-token",
            "refresh_token": "TG-test-refresh-token",
            "expires_at": int(time.time()) + 3600,
        }
        token_file.write_text(json.dumps(tokens))
        return token_file

    @pytest.fixture
    def expired_token_file(self, tmp_path):
        """Create an expired token file."""
        token_file = tmp_path / "tokens.json"
        tokens = {
            "access_token": "APP_USR-test-access-token",
            "refresh_token": "TG-test-refresh-token",
            "expires_at": int(time.time()) - 3600,
        }
        token_file.write_text(json.dumps(tokens))
        return token_file

    def test_load_tokens(self, temp_token_file):
        """Test loading tokens from file."""
        manager = TokenManager(str(temp_token_file))
        tokens = manager.load_tokens()

        assert tokens["access_token"] == "APP_USR-test-access-token"
        assert tokens["refresh_token"] == "TG-test-refresh-token"
        assert "expires_at" in tokens

    def test_load_tokens_caches_result(self, temp_token_file):
        """Test that tokens are cached after first load."""
        manager = TokenManager(str(temp_token_file))
        tokens1 = manager.load_tokens()
        tokens2 = manager.load_tokens()

        assert tokens1 is tokens2

    def test_save_tokens(self, tmp_path):
        """Test saving tokens to file."""
        token_file = tmp_path / "tokens.json"
        manager = TokenManager(str(token_file))

        tokens = {
            "access_token": "new-token",
            "refresh_token": "new-refresh",
            "expires_at": 1234567890,
        }
        manager.save_tokens(tokens)

        saved = json.loads(token_file.read_text())
        assert saved["access_token"] == "new-token"
        assert saved["refresh_token"] == "new-refresh"

    def test_is_token_expired_false(self, temp_token_file):
        """Test expiration check for valid token."""
        manager = TokenManager(str(temp_token_file))
        assert not manager.is_token_expired()

    def test_is_token_expired_true(self, expired_token_file):
        """Test expiration check for expired token."""
        manager = TokenManager(str(expired_token_file))
        assert manager.is_token_expired()

    def test_is_token_expired_with_buffer(self, temp_token_file):
        """Test expiration with buffer time."""
        token_file = temp_token_file
        tokens = {
            "access_token": "test",
            "refresh_token": "test",
            "expires_at": int(time.time()) + 60,  # 1 minute from now
        }
        token_file.write_text(json.dumps(tokens))

        manager = TokenManager(str(token_file))
        # With 5 minute buffer, this should be expired
        assert manager.is_token_expired(buffer_seconds=300)

    def test_is_token_expired_no_file(self, tmp_path):
        """Test expiration check when file doesn't exist."""
        manager = TokenManager(str(tmp_path / "nonexistent.json"))
        assert manager.is_token_expired()

    def test_get_access_token_valid(self, temp_token_file):
        """Test getting valid access token."""
        manager = TokenManager(str(temp_token_file))
        token = manager.get_access_token(auto_refresh=False)

        assert token == "APP_USR-test-access-token"

    def test_get_access_token_expired_no_refresh(self, expired_token_file):
        """Test getting expired token without auto-refresh."""
        manager = TokenManager(str(expired_token_file))

        with pytest.raises(TokenExpiredError):
            manager.get_access_token(auto_refresh=False)

    def test_get_access_token_auto_refresh(self, expired_token_file):
        """Test auto-refresh of expired token."""
        mock_oauth = Mock()
        mock_oauth.refresh_token.return_value = {
            "access_token": "new-access-token",
            "refresh_token": "new-refresh-token",
            "expires_at": int(time.time()) + 3600,
        }

        manager = TokenManager(str(expired_token_file), oauth_handler=mock_oauth)
        token = manager.get_access_token(auto_refresh=True)

        assert token == "new-access-token"
        mock_oauth.refresh_token.assert_called_once_with("TG-test-refresh-token")

    def test_get_access_token_no_refresh_token(self, tmp_path):
        """Test behavior when no refresh token is available."""
        token_file = tmp_path / "tokens.json"
        tokens = {
            "access_token": "test",
            "expires_at": int(time.time()) - 3600,
        }
        token_file.write_text(json.dumps(tokens))

        manager = TokenManager(str(token_file))

        with pytest.raises(TokenExpiredError, match="No refresh token"):
            manager.get_access_token(auto_refresh=True)

    def test_get_refresh_token(self, temp_token_file):
        """Test getting refresh token."""
        manager = TokenManager(str(temp_token_file))
        refresh_token = manager.get_refresh_token()

        assert refresh_token == "TG-test-refresh-token"

    def test_invalidate_cache(self, temp_token_file):
        """Test cache invalidation."""
        manager = TokenManager(str(temp_token_file))
        tokens1 = manager.load_tokens()
        manager.invalidate_cache()
        tokens2 = manager.load_tokens()

        assert tokens1 is not tokens2
        assert tokens1 == tokens2


class TestOAuthHandler:
    """Test cases for OAuthHandler."""

    @pytest.fixture
    def oauth_handler(self):
        """Create OAuth handler with test credentials."""
        return OAuthHandler(
            client_id="test-client-id",
            client_secret="test-client-secret",
            redirect_uri="http://localhost:8000/callback",
        )

    def test_init_from_env(self):
        """Test initialization from environment variables."""
        env_vars = {
            "MERCADO_LIVRE_CLIENT_ID": "env-client-id",
            "MERCADO_LIVRE_CLIENT_SECRET": "env-client-secret",
            "MERCADO_LIVRE_REDIRECT_URI": "http://example.com/callback",
        }

        with patch.dict(os.environ, env_vars, clear=True):
            handler = OAuthHandler()
            assert handler.client_id == "env-client-id"
            assert handler.client_secret == "env-client-secret"
            assert handler.redirect_uri == "http://example.com/callback"

    def test_get_authorization_url(self, oauth_handler):
        """Test authorization URL generation."""
        url = oauth_handler.get_authorization_url()

        assert url.startswith("https://auth.mercadolivre.com.br/authorization")
        assert "response_type=code" in url
        assert "client_id=test-client-id" in url
        assert "redirect_uri=http%3A%2F%2Flocalhost%3A8000%2Fcallback" in url

    def test_get_authorization_url_with_state(self, oauth_handler):
        """Test authorization URL with state parameter."""
        url = oauth_handler.get_authorization_url(state="random-state-123")

        assert "state=random-state-123" in url

    def test_get_authorization_url_no_client_id(self):
        """Test error when client_id is missing."""
        handler = OAuthHandler(client_id=None, client_secret="secret")

        with pytest.raises(OAuthError, match="Client ID is required"):
            handler.get_authorization_url()

    @patch("mercadolivre_upload.auth.oauth.requests.post")
    def test_exchange_code_success(self, mock_post, oauth_handler):
        """Test successful code exchange."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "access_token": "new-access",
            "refresh_token": "new-refresh",
            "expires_in": 21600,
        }
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        result = oauth_handler.exchange_code("auth-code-123")

        assert result["access_token"] == "new-access"
        assert result["refresh_token"] == "new-refresh"
        assert "expires_at" in result

        # Verify request
        call_args = mock_post.call_args
        assert call_args[0][0] == OAuthHandler.TOKEN_URL
        assert call_args[1]["data"]["grant_type"] == "authorization_code"
        assert call_args[1]["data"]["code"] == "auth-code-123"

    @patch("mercadolivre_upload.auth.oauth.requests.post")
    def test_refresh_token_success(self, mock_post, oauth_handler):
        """Test successful token refresh."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "access_token": "refreshed-access",
            "refresh_token": "refreshed-refresh",
            "expires_in": 21600,
        }
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        result = oauth_handler.refresh_token("old-refresh-token")

        assert result["access_token"] == "refreshed-access"
        assert result["refresh_token"] == "refreshed-refresh"
        assert "expires_at" in result

        # Verify request
        call_args = mock_post.call_args
        assert call_args[0][0] == OAuthHandler.TOKEN_URL
        assert call_args[1]["data"]["grant_type"] == "refresh_token"
        assert call_args[1]["data"]["refresh_token"] == "old-refresh-token"

    @patch("mercadolivre_upload.auth.oauth.requests.post")
    def test_token_request_failure(self, mock_post, oauth_handler):
        """Test handling of failed token request."""
        import requests

        mock_post.side_effect = requests.exceptions.RequestException("Connection error")

        with pytest.raises(OAuthError, match="Token request failed"):
            oauth_handler.refresh_token("token")

    @patch("mercadolivre_upload.auth.oauth.requests.post")
    def test_token_request_invalid_response(self, mock_post, oauth_handler):
        """Test handling of invalid token response."""
        mock_response = Mock()
        mock_response.json.return_value = {"error": "invalid_grant", "message": "Invalid refresh token"}
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        with pytest.raises(OAuthError, match="Invalid token response"):
            oauth_handler.refresh_token("invalid-token")

    def test_add_auth_header(self, oauth_handler):
        """Test adding authorization header."""
        headers = oauth_handler.add_auth_header(token="test-token")

        assert headers["Authorization"] == "Bearer test-token"

    def test_add_auth_header_to_existing(self, oauth_handler):
        """Test adding auth header to existing headers."""
        existing = {"Content-Type": "application/json"}
        headers = oauth_handler.add_auth_header(existing, "test-token")

        assert headers["Content-Type"] == "application/json"
        assert headers["Authorization"] == "Bearer test-token"

    def test_add_auth_header_no_token(self, oauth_handler):
        """Test adding auth header without token."""
        headers = oauth_handler.add_auth_header()

        assert "Authorization" not in headers


class TestIntegration:
    """Integration tests using real tokens.json structure."""

    def test_token_structure_matches_real_file(self):
        """Verify our code handles the real tokens.json format."""
        # This test uses the actual tokens.json in the repo
        if not Path("tokens.json").exists():
            pytest.skip("No tokens.json file found")

        manager = TokenManager("tokens.json")
        tokens = manager.load_tokens()

        # Verify required fields exist
        assert "access_token" in tokens
        assert "refresh_token" in tokens
        assert "expires_at" in tokens

        # Verify types
        assert isinstance(tokens["access_token"], str)
        assert isinstance(tokens["refresh_token"], str)
        assert isinstance(tokens["expires_at"], (int, float))

    def test_oauth_handler_requires_credentials(self):
        """Verify OAuth handler requires client credentials."""
        with patch.dict(os.environ, {}, clear=True):
            handler = OAuthHandler()

            with pytest.raises(OAuthError):
                handler.get_authorization_url()

            with pytest.raises(OAuthError):
                handler.refresh_token("token")
