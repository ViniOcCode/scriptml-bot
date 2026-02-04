"""Configuração da aplicação via Pydantic Settings.

Suporta carregamento de:
- Variáveis de ambiente (.env)
- Arquivos JSON
- Arquivos YAML
- Valores padrão sensíveis
"""

from __future__ import annotations

import json
import os
from enum import Enum
from pathlib import Path
from typing import Any, Literal, Self

import yaml
from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class LogLevel(str, Enum):
    """Níveis de log suportados."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class Environment(str, Enum):
    """Ambientes de execução."""

    DEVELOPMENT = "development"
    TESTING = "testing"
    STAGING = "staging"
    PRODUCTION = "production"


class CacheBackend(str, Enum):
    """Backends de cache suportados."""

    MEMORY = "memory"
    DISK = "disk"
    REDIS = "redis"


class Settings(BaseSettings):
    """Configurações da aplicação.

    Prioridade de carregamento (maior para menor):
    1. Variáveis de ambiente
    2. Arquivo .env
    3. Valores padrão
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="ML_UPLOAD_",
        case_sensitive=False,
        extra="ignore",
        validate_assignment=True,
    )

    # =========================================================================
    # Configurações Gerais
    # =========================================================================
    app_name: str = Field(default="mercadolivre-upload", description="Nome da aplicação")
    version: str = Field(default="1.0.0", description="Versão da aplicação")
    environment: Environment = Field(
        default=Environment.DEVELOPMENT,
        description="Ambiente de execução",
    )
    debug: bool = Field(default=False, description="Modo debug")

    # =========================================================================
    # Configurações de Logging
    # =========================================================================
    log_level: LogLevel = Field(default=LogLevel.INFO, description="Nível de log")
    log_file: str | None = Field(default=None, description="Nome do arquivo de log")
    log_dir: Path = Field(
        default=Path.home() / ".mercadolivre_upload" / "logs",
        description="Diretório para logs",
    )
    log_max_bytes: int = Field(
        default=10 * 1024 * 1024,  # 10MB
        description="Tamanho máximo do arquivo de log",
    )
    log_backup_count: int = Field(default=5, description="Número de backups de log")
    log_use_json: bool = Field(default=False, description="Usar formato JSON para logs")
    log_use_colors: bool = Field(default=True, description="Usar cores no console")

    # =========================================================================
    # Configurações da API Mercado Livre
    # =========================================================================
    ml_client_id: str | None = Field(default=None, description="Client ID da aplicação ML")
    ml_client_secret: SecretStr | None = Field(
        default=None,
        description="Client Secret da aplicação ML",
    )
    ml_redirect_uri: str = Field(
        default="http://localhost:8000/callback",
        description="URI de redirecionamento OAuth",
    )
    ml_base_url: str = Field(
        default="https://api.mercadolibre.com",
        description="URL base da API",
    )
    ml_auth_url: str = Field(
        default="https://auth.mercadolibre.com",
        description="URL de autenticação",
    )

    # =========================================================================
    # Configurações de Cache
    # =========================================================================
    cache_backend: CacheBackend = Field(default=CacheBackend.MEMORY, description="Backend de cache")
    cache_ttl: int = Field(default=3600, description="Tempo de vida do cache em segundos")
    cache_dir: Path = Field(
        default=Path.home() / ".mercadolivre_upload" / "cache",
        description="Diretório para cache em disco",
    )
    cache_redis_url: str | None = Field(default=None, description="URL do Redis")

    # =========================================================================
    # Configurações de HTTP/Retry
    # =========================================================================
    http_timeout: int = Field(default=30, description="Timeout de requisições HTTP")
    http_max_retries: int = Field(default=3, description="Número máximo de retries")
    http_backoff_factor: float = Field(default=0.5, description="Fator de backoff")
    http_pool_connections: int = Field(default=10, description="Conexões no pool")
    http_pool_maxsize: int = Field(default=10, description="Tamanho máximo do pool")

    # =========================================================================
    # Configurações de Upload
    # =========================================================================
    upload_max_images: int = Field(default=10, description="Máximo de imagens por produto")
    upload_max_image_size: int = Field(
        default=10 * 1024 * 1024,  # 10MB
        description="Tamanho máximo de imagem em bytes",
    )
    upload_allowed_formats: list[str] = Field(
        default=["jpg", "jpeg", "png", "webp"],
        description="Formatos de imagem permitidos",
    )
    upload_concurrent: int = Field(default=3, description="Uploads simultâneos")

    # =========================================================================
    # Configurações de Rate Limiting
    # =========================================================================
    rate_limit_enabled: bool = Field(default=True, description="Habilitar rate limiting")
    rate_limit_requests_per_second: float = Field(
        default=2.0,
        description="Requisições por segundo",
    )
    rate_limit_burst: int = Field(default=5, description="Burst de requisições")

    # =========================================================================
    # Configurações de Planilhas
    # =========================================================================
    spreadsheet_default_sheet: str = Field(default="Produtos", description="Aba padrão")
    spreadsheet_header_row: int = Field(default=1, description="Linha do cabeçalho")
    spreadsheet_required_columns: list[str] = Field(
        default=["title", "price", "category_id"],
        description="Colunas obrigatórias",
    )

    # =========================================================================
    # Configurações de Sentry (opcional)
    # =========================================================================
    sentry_dsn: str | None = Field(default=None, description="DSN do Sentry")
    sentry_traces_sample_rate: float = Field(default=0.1, description="Taxa de amostragem")

    # =========================================================================
    # Validadores
    # =========================================================================

    @field_validator("log_dir", "cache_dir", mode="before")
    @classmethod
    def _parse_path(cls, value: str | Path | None) -> Path | None:
        """Converte string para Path."""
        if value is None:
            return None
        if isinstance(value, str):
            # Expande variáveis de ambiente e ~ (home)
            expanded = os.path.expandvars(os.path.expanduser(value))
            return Path(expanded)
        return value

    @field_validator("upload_allowed_formats", mode="before")
    @classmethod
    def _parse_formats(cls, value: str | list[str]) -> list[str]:
        """Converte string de formatos para lista."""
        if isinstance(value, str):
            return [f.strip().lower() for f in value.split(",")]
        return [f.lower() for f in value]

    @model_validator(mode="after")
    def _validate_directories(self) -> Self:
        """Garante que diretórios existam."""
        # Cria diretórios se necessário
        for path_attr in ["log_dir", "cache_dir"]:
            path = getattr(self, path_attr)
            if path is not None and not path.exists():
                try:
                    path.mkdir(parents=True, exist_ok=True)
                except OSError as e:
                    raise ValueError(f"Não foi possível criar diretório {path}: {e}")
        return self

    @model_validator(mode="after")
    def _validate_redis(self) -> Self:
        """Valida configuração do Redis quando necessário."""
        if self.cache_backend == CacheBackend.REDIS and not self.cache_redis_url:
            raise ValueError("cache_redis_url é obrigatório quando cache_backend='redis'")
        return self

    # =========================================================================
    # Métodos
    # =========================================================================

    def to_dict(self, hide_secrets: bool = True) -> dict[str, Any]:
        """Converte configurações para dicionário.

        Args:
            hide_secrets: Se True, oculta valores secretos.

        Returns:
            Dicionário com configurações.
        """
        data = self.model_dump()

        if hide_secrets:
            # Oculta secrets
            for key, value in data.items():
                if isinstance(value, SecretStr):
                    data[key] = "***" if value.get_secret_value() else None
                elif "secret" in key.lower() or "password" in key.lower() or "token" in key.lower():
                    if value:
                        data[key] = "***"

        return data

    def save_to_file(self, path: Path | str, format: Literal["json", "yaml"] = "json") -> None:
        """Salva configurações em arquivo.

        Args:
            path: Caminho do arquivo.
            format: Formato do arquivo (json ou yaml).
        """
        file_path = Path(path)
        data = self.to_dict(hide_secrets=True)

        # Converte Path para string
        for key, value in data.items():
            if isinstance(value, Path):
                data[key] = str(value)
            elif isinstance(value, Enum):
                data[key] = value.value

        if format == "json":
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        elif format == "yaml":
            with open(file_path, "w", encoding="utf-8") as f:
                yaml.dump(data, f, default_flow_style=False, allow_unicode=True)
        else:
            raise ValueError(f"Formato não suportado: {format}")


# Instância global de configurações (lazy loading)
_settings: Settings | None = None


def get_settings(
    config_file: Path | str | None = None,
    **overrides: Any,
) -> Settings:
    """Obtém instância de configurações.

    Carrega configurações de:
    1. Arquivo de configuração (se fornecido)
    2. Variáveis de ambiente
    3. Valores padrão

    Args:
        config_file: Caminho para arquivo de configuração (JSON ou YAML).
        **overrides: Valores para sobrescrever.

    Returns:
        Instância de Settings configurada.
    """
    global _settings

    # Se já existe instância e não há overrides, retorna ela
    if _settings is not None and not config_file and not overrides:
        return _settings

    # Carrega de arquivo se fornecido
    file_config: dict[str, Any] = {}
    if config_file is not None:
        file_path = Path(config_file)
        if file_path.exists():
            with open(file_path, encoding="utf-8") as f:
                if file_path.suffix in [".yaml", ".yml"]:
                    file_config = yaml.safe_load(f) or {}
                elif file_path.suffix == ".json":
                    file_config = json.load(f)
                else:
                    raise ValueError(f"Formato de arquivo não suportado: {file_path.suffix}")

    # Mescla com overrides
    file_config.update(overrides)

    # Cria nova instância
    _settings = Settings(**file_config)

    return _settings


def reload_settings() -> Settings:
    """Recarrega configurações do ambiente.

    Returns:
        Nova instância de Settings.
    """
    global _settings
    _settings = None
    return get_settings()


def reset_settings() -> None:
    """Reseta configurações para estado inicial."""
    global _settings
    _settings = None
