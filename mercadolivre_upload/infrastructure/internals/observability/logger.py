"""Structured logging internals for observability."""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
from pathlib import Path
from typing import Any

from mercadolivre_upload.infrastructure.logging import JSONFormatter

from .helpers import (
    build_operation_extra,
    build_structured_log_data,
)

DEFAULT_LOG_DIR = Path.home() / ".mercadolivre_upload" / "logs"
MAX_LOG_RETENTION_DAYS = 30


class StructuredLogger:
    """Logger estruturado com saída em JSON para análise de logs.

    Features:
    - Formato JSON estruturado
    - Campos padronizados (timestamp, level, component, correlation_id)
    - Contexto automático (hostname, pid, thread)
    - Rotação de logs por tamanho e tempo
    - Compressão de arquivos antigos
    """

    def __init__(
        self,
        name: str,
        log_dir: Path | str | None = None,
        max_bytes: int = 10 * 1024 * 1024,  # 10MB
        backup_count: int = 10,
        level: str = "INFO",
    ) -> None:
        """Inicializa o logger estruturado.

        Args:
            name: Nome do logger.
            log_dir: Diretório para logs. Se None, usa padrão.
            max_bytes: Tamanho máximo do arquivo antes da rotação.
            backup_count: Número de arquivos de backup.
            level: Nível de log (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        """
        self.name = name
        self.log_dir = Path(log_dir) if log_dir else DEFAULT_LOG_DIR
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.max_bytes = max_bytes
        self.backup_count = backup_count

        # Cria logger
        self._logger = logging.getLogger(f"observability.{name}")
        self._logger.setLevel(getattr(logging, level.upper()))
        self._logger.handlers.clear()

        # Handler para arquivo JSON
        log_file = self.log_dir / f"{name}.jsonl"
        file_handler = logging.handlers.RotatingFileHandler(
            filename=log_file,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setFormatter(JSONFormatter())
        self._logger.addHandler(file_handler)

        # Handler para console (formato legível)
        console_handler = logging.StreamHandler(sys.stdout)
        console_format = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
        console_handler.setFormatter(logging.Formatter(console_format))
        self._logger.addHandler(console_handler)

        # Contexto base
        self._base_context = {
            "logger_name": name,
            "hostname": os.uname().nodename if hasattr(os, "uname") else "unknown",
            "pid": os.getpid(),
        }

        self._logger.info(f"StructuredLogger initialized: {name}")

    def _log(
        self,
        level: str,
        message: str,
        component: str | None = None,
        correlation_id: str | None = None,
        extra: dict[str, Any] | None = None,
        exception: Exception | None = None,
    ) -> None:
        """Registra um log estruturado.

        Args:
            level: Nível do log.
            message: Mensagem principal.
            component: Componente que gerou o log.
            correlation_id: ID de correlação para rastreamento.
            extra: Campos extras personalizados.
            exception: Exceção opcional para incluir stack trace.
        """
        log_data = build_structured_log_data(
            base_context=self._base_context,
            logger_name=self.name,
            level=level,
            message=message,
            component=component,
            correlation_id=correlation_id,
            extra=extra,
            exception=exception,
        )

        # Log com extra para JSONFormatter capturar
        log_method = getattr(self._logger, level.lower())
        log_method(message, extra={"_structured": log_data})

    def debug(
        self,
        message: str,
        component: str | None = None,
        correlation_id: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Log de nível DEBUG."""
        self._log("DEBUG", message, component, correlation_id, extra)

    def info(
        self,
        message: str,
        component: str | None = None,
        correlation_id: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Log de nível INFO."""
        self._log("INFO", message, component, correlation_id, extra)

    def warning(
        self,
        message: str,
        component: str | None = None,
        correlation_id: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Log de nível WARNING."""
        self._log("WARNING", message, component, correlation_id, extra)

    def error(
        self,
        message: str,
        component: str | None = None,
        correlation_id: str | None = None,
        extra: dict[str, Any] | None = None,
        exception: Exception | None = None,
    ) -> None:
        """Log de nível ERROR."""
        self._log("ERROR", message, component, correlation_id, extra, exception)

    def critical(
        self,
        message: str,
        component: str | None = None,
        correlation_id: str | None = None,
        extra: dict[str, Any] | None = None,
        exception: Exception | None = None,
    ) -> None:
        """Log de nível CRITICAL."""
        self._log("CRITICAL", message, component, correlation_id, extra, exception)

    def log_operation(
        self,
        operation: str,
        success: bool,
        duration_ms: float,
        component: str | None = None,
        correlation_id: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Log estruturado para operações de negócio.

        Args:
            operation: Nome da operação (ex: "product_upload", "image_process").
            success: Se a operação foi bem-sucedida.
            duration_ms: Duração em milissegundos.
            component: Componente que executou.
            correlation_id: ID de correlação.
            extra: Campos extras.
        """
        log_extra = build_operation_extra(operation, success, duration_ms, extra)
        level = "INFO" if success else "ERROR"
        self._log(level, f"Operation: {operation}", component, correlation_id, log_extra)
