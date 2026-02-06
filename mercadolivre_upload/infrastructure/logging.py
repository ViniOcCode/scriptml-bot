"""Configuração de logging estruturado para o mercadolivre-upload.

Este módulo fornece logging configurável com:
- Handlers para arquivo e console
- Rotação de logs baseada em tamanho
- Níveis configuráveis (DEBUG, INFO, WARNING, ERROR)
- Formatação estruturada opcional (JSON)
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import sys
from datetime import datetime
from pathlib import Path
from typing import Literal, TextIO

# Diretório padrão para logs
DEFAULT_LOG_DIR = Path.home() / ".mercadolivre_upload" / "logs"
DEFAULT_LOG_FILE = "mercadolivre_upload.log"

# Níveis de log válidos
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class JSONFormatter(logging.Formatter):
    """Formatador JSON para logs estruturados."""

    def format(self, record: logging.LogRecord) -> str:
        """Formata o registro de log como JSON."""
        log_data = {
            "timestamp": datetime.fromtimestamp(record.created).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Adiciona informações de exceção se presentes
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        # Adiciona atributos extras
        for key, value in record.__dict__.items():
            if key not in {
                "name",
                "msg",
                "args",
                "levelname",
                "levelno",
                "pathname",
                "filename",
                "module",
                "exc_info",
                "exc_text",
                "stack_info",
                "lineno",
                "funcName",
                "created",
                "msecs",
                "relativeCreated",
                "thread",
                "threadName",
                "processName",
                "process",
                "message",
                "asctime",
            }:
                try:
                    # Tenta serializar o valor
                    json.dumps({key: value})
                    log_data[key] = value
                except (TypeError, ValueError):
                    log_data[key] = str(value)

        return json.dumps(log_data, ensure_ascii=False, default=str)


class ColoredFormatter(logging.Formatter):
    """Formatador com cores para console."""

    # Cores ANSI
    COLORS = {
        "DEBUG": "\033[36m",  # Cyan
        "INFO": "\033[32m",  # Green
        "WARNING": "\033[33m",  # Yellow
        "ERROR": "\033[31m",  # Red
        "CRITICAL": "\033[35m",  # Magenta
        "RESET": "\033[0m",
    }

    def __init__(self, fmt: str | None = None, use_colors: bool = True) -> None:
        """Inicializa o formatador.

        Args:
            fmt: Formato da mensagem. Se None, usa formato padrão.
            use_colors: Se True, adiciona códigos de cor ANSI.
        """
        super().__init__(fmt or "%(levelname)s: %(message)s")
        self.use_colors = use_colors and sys.stderr.isatty()

    def format(self, record: logging.LogRecord) -> str:
        """Formata o registro com cores opcionais."""
        if self.use_colors:
            color = self.COLORS.get(record.levelname, self.COLORS["RESET"])
            reset = self.COLORS["RESET"]
            record.levelname = f"{color}{record.levelname}{reset}"

        return super().format(record)


def setup_logging(
    level: LogLevel = "INFO",
    log_file: Path | str | None = None,
    log_dir: Path | str | None = None,
    max_bytes: int = 10 * 1024 * 1024,  # 10MB
    backup_count: int = 5,
    use_json: bool = False,
    use_colors: bool = True,
    console_output: TextIO = sys.stderr,
) -> None:
    """Configura o logging da aplicação.

    Args:
        level: Nível de log (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        log_file: Nome do arquivo de log. Se None, usa nome padrão.
        log_dir: Diretório para logs. Se None, usa diretório padrão.
        max_bytes: Tamanho máximo do arquivo de log antes da rotação.
        backup_count: Número de arquivos de backup a manter.
        use_json: Se True, usa formato JSON para o arquivo de log.
        use_colors: Se True, usa cores no console (quando suportado).
        console_output: Stream para saída do console (padrão: stderr).
    """
    # Obtém o nível de log
    log_level = getattr(logging, level.upper(), logging.INFO)

    # Configura o logger raiz da aplicação
    root_logger = logging.getLogger("mercadolivre_upload")
    root_logger.setLevel(log_level)

    # Remove handlers existentes para evitar duplicação
    root_logger.handlers.clear()

    # Handler para console
    console_handler = logging.StreamHandler(console_output)
    console_handler.setLevel(log_level)

    if use_json:
        console_formatter = JSONFormatter()
    else:
        console_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        console_formatter = ColoredFormatter(console_format, use_colors=use_colors)

    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)

    # Handler para arquivo (com rotação)
    if log_dir is not None or log_file is not None:
        # Determina o diretório de logs
        if log_dir is None:
            log_directory = DEFAULT_LOG_DIR
        else:
            log_directory = Path(log_dir)

        # Cria o diretório se não existir
        log_directory.mkdir(parents=True, exist_ok=True)

        # Determina o nome do arquivo
        if log_file is None:
            log_file_path = log_directory / DEFAULT_LOG_FILE
        else:
            log_file_path = log_directory / log_file

        # Cria o handler com rotação
        file_handler = logging.handlers.RotatingFileHandler(
            filename=log_file_path,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setLevel(log_level)

        # Formatação para arquivo
        if use_json:
            file_formatter = JSONFormatter()
        else:
            file_format = (
                "%(asctime)s - %(name)s - %(levelname)s - %(module)s:%(lineno)d - %(message)s"
            )
            file_formatter = logging.Formatter(file_format)

        file_handler.setFormatter(file_formatter)
        root_logger.addHandler(file_handler)

        root_logger.debug(f"Logging configurado em: {log_file_path}")

    # Configura níveis de log para bibliotecas de terceiros
    _configure_third_party_loggers()

    root_logger.debug(f"Logging inicializado com nível: {level}")


def _configure_third_party_loggers() -> None:
    """Configura níveis de log para bibliotecas de terceiros."""
    # Reduz verbosidade de bibliotecas comuns
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)
    logging.getLogger("aiohttp").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Obtém um logger configurado.

    Args:
        name: Nome do logger (geralmente __name__).

    Returns:
        Logger configurado.
    """
    return logging.getLogger(f"mercadolivre_upload.{name}")


def set_log_level(level: LogLevel) -> None:
    """Altera o nível de log em tempo de execução.

    Args:
        level: Novo nível de log.
    """
    log_level = getattr(logging, level.upper(), logging.INFO)
    logger = logging.getLogger("mercadolivre_upload")
    logger.setLevel(log_level)

    for handler in logger.handlers:
        handler.setLevel(log_level)

    logger.info(f"Nível de log alterado para: {level}")


def silence_logging() -> None:
    """Silencia completamente os logs (útil para testes)."""
    logger = logging.getLogger("mercadolivre_upload")
    logger.setLevel(logging.CRITICAL + 1)

    # Remove todos os handlers
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)


# Logger padrão para uso rápido
logger = get_logger("infrastructure")
