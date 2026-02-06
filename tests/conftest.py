"""
Pytest configuration and shared fixtures.
"""

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


# ==================== Fixtures de Credenciais Mockadas ====================


@pytest.fixture(autouse=True)
def mock_credentials():
    """
    Fixture que garante que as variáveis de ambiente ML_APP_ID e ML_APP_SECRET
    estejam configuradas para todos os testes.
    """
    # Seta variáveis de ambiente mock
    original_app_id = os.environ.get("ML_APP_ID")
    original_app_secret = os.environ.get("ML_APP_SECRET")
    original_redirect_uri = os.environ.get("ML_REDIRECT_URI")

    os.environ["ML_APP_ID"] = "mock_app_id_12345"
    os.environ["ML_APP_SECRET"] = "mock_app_secret_67890"
    os.environ["ML_REDIRECT_URI"] = "http://localhost:8000/callback"

    yield

    # Restaura valores originais
    if original_app_id is not None:
        os.environ["ML_APP_ID"] = original_app_id
    elif "ML_APP_ID" in os.environ:
        del os.environ["ML_APP_ID"]

    if original_app_secret is not None:
        os.environ["ML_APP_SECRET"] = original_app_secret
    elif "ML_APP_SECRET" in os.environ:
        del os.environ["ML_APP_SECRET"]

    if original_redirect_uri is not None:
        os.environ["ML_REDIRECT_URI"] = original_redirect_uri
    elif "ML_REDIRECT_URI" in os.environ:
        del os.environ["ML_REDIRECT_URI"]


@pytest.fixture
def mock_auth_manager():
    """
    Retorna um AuthManager mockado com credenciais e token válidos.
    """
    with patch("mercadolivre_upload.application.publish_product.AuthManager") as mock_auth_class:
        mock_auth = MagicMock()
        mock_auth.is_authenticated.return_value = True
        mock_auth.get_valid_token.return_value = "mock_access_token_12345"
        mock_auth.get_auth_status.return_value = {
            "status": "authenticated",
            "authenticated": True,
            "user_id": "123456789",
        }
        mock_auth_class.return_value = mock_auth
        yield mock_auth


@pytest.fixture(autouse=True)
def mock_auth_manager_global():
    """
    Fixture autouse que garante que AuthManager seja mockado em todos os testes.
    Isso evita que o AuthManager tente carregar credenciais reais.
    """
    with patch("mercadolivre_upload.auth.authenticator.AuthManager") as mock_auth_class:
        mock_auth = MagicMock()
        mock_auth.is_authenticated.return_value = True
        mock_auth.get_valid_token.return_value = "mock_access_token_12345"
        mock_auth.get_auth_status.return_value = {
            "status": "authenticated",
            "authenticated": True,
            "user_id": "123456789",
        }
        mock_auth_class.return_value = mock_auth
        yield


# ==================== Fixtures de Autenticação Mockada ====================


@pytest.fixture
def mock_oauth_manager():
    """Retorna um OAuthManager mockado com token válido."""
    oauth = Mock()
    oauth.get_access_token.return_value = "mock_access_token_12345"
    oauth.refresh_access_token.return_value = "new_mock_token_67890"
    oauth.is_token_valid.return_value = True
    return oauth


@pytest.fixture
def mock_oauth_expired():
    """Retorna um OAuthManager mockado com token expirado."""
    oauth = Mock()
    oauth.get_access_token.return_value = None
    oauth.refresh_access_token.return_value = "refreshed_token_12345"
    oauth.is_token_valid.return_value = False
    return oauth


@pytest.fixture
def mock_auth_headers():
    """Retorna headers de autenticação mockados."""
    return {
        "Authorization": "Bearer mock_access_token_12345",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


@pytest.fixture
def mock_user_info():
    """Retorna informações de usuário mockadas."""
    return {
        "id": 123456789,
        "nickname": "TESTUSER",
        "registration_date": "2020-01-01",
        "country_id": "BR",
        "address": {
            "city": "São Paulo",
            "state": "SP",
        },
        "seller_reputation": {
            "level_id": "5_green",
            "power_seller_status": "platinum",
        },
    }


@pytest.fixture
def mock_item_data():
    """Retorna dados de um item/produto mockado."""
    return {
        "id": "MLB123456789",
        "title": "Produto Teste",
        "category_id": "MLB1055",
        "price": 199.99,
        "currency_id": "BRL",
        "available_quantity": 10,
        "condition": "new",
        "description": "Descrição do produto teste",
        "pictures": [
            {"source": "https://example.com/image1.jpg"},
            {"source": "https://example.com/image2.jpg"},
        ],
        "attributes": [
            {"id": "BRAND", "value_name": "Marca Teste"},
        ],
    }


@pytest.fixture
def mock_category_data():
    """Retorna dados de categoria mockados."""
    return {
        "id": "MLB1055",
        "name": "Celulares e Smartphones",
        "path_from_root": [
            {"id": "MLB1051", "name": "Celulares e Telefones"},
            {"id": "MLB1055", "name": "Celulares e Smartphones"},
        ],
        "attributes": [
            {
                "id": "BRAND",
                "name": "Marca",
                "tags": {"required": True},
                "values": [
                    {"id": "MLB27695", "name": "Samsung"},
                    {"id": "MLB27696", "name": "Apple"},
                ],
            },
        ],
    }


# ==================== Fixtures de Resposta HTTP Mockada ====================


@pytest.fixture
def mock_api_response():
    """Factory fixture para criar respostas HTTP mockadas."""

    def _create_response(status_code=200, json_data=None, text="", raise_error=None):
        response = Mock()
        response.status_code = status_code
        response.json.return_value = json_data or {}
        response.text = text or str(json_data)

        if raise_error:
            response.raise_for_status.side_effect = raise_error
        else:
            response.raise_for_status.return_value = None

        return response

    return _create_response


@pytest.fixture
def mock_session_factory():
    """Factory fixture para criar sessions mockadas do requests."""

    def _create_session(responses_dict=None):
        """
        Args:
            responses_dict: Dict mapeando (method, url) -> response mock
        """
        session = Mock()

        def mock_request(method, url, **kwargs):
            key = (method.upper(), url)
            # Tentar match exato
            if responses_dict and key in responses_dict:
                return responses_dict[key]
            # Match por URL parcial
            if responses_dict:
                for (m, u), resp in responses_dict.items():
                    if m == method.upper() and u in url:
                        return resp
            # Default response
            default = Mock()
            default.status_code = 404
            default.json.return_value = {"message": "Not found"}
            return default

        session.request = mock_request
        session.get = lambda url, **kw: mock_request("GET", url, **kw)
        session.post = lambda url, **kw: mock_request("POST", url, **kw)
        session.put = lambda url, **kw: mock_request("PUT", url, **kw)
        session.delete = lambda url, **kw: mock_request("DELETE", url, **kw)

        return session

    return _create_session


# ==================== Fixtures de Arquivo ====================


@pytest.fixture
def sample_csv_file(tmp_path):
    """Cria um arquivo CSV de exemplo para testes."""
    csv_file = tmp_path / "sample_products.csv"
    content = """titulo,preco,quantidade,categoria
Produto A,99.99,10,MLB1055
Produto B,149.90,5,MLB1055
Produto C,299.00,20,MLB1234
"""
    csv_file.write_text(content, encoding="utf-8")
    return csv_file


@pytest.fixture
def sample_json_file(tmp_path):
    """Cria um arquivo JSON de exemplo para testes."""
    json_file = tmp_path / "sample_products.json"
    content = """[
    {"titulo": "Produto A", "preco": 99.99, "quantidade": 10},
    {"titulo": "Produto B", "preco": 149.90, "quantidade": 5}
]"""
    json_file.write_text(content, encoding="utf-8")
    return json_file


# ==================== Fixtures de Configuração ====================


@pytest.fixture
def mock_config():
    """Retorna configuração mockada do aplicativo."""
    return {
        "client_id": "mock_client_id",
        "client_secret": "mock_client_secret",
        "redirect_uri": "http://localhost:8000/callback",
        "access_token": "mock_access_token",
        "refresh_token": "mock_refresh_token",
        "user_id": "123456789",
        "site_id": "MLB",
    }


@pytest.fixture(autouse=True)
def clear_caches():
    """Limpa caches entre testes para evitar interferência."""
    yield
    # Caches são limpos automaticamente em cada sessão de teste
