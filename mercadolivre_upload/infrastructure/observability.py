"""Sistema completo de observabilidade para mercadolivre-upload.

Fornece:
- Logger estruturado em JSON para análise
- Métricas de negócio: uploads por hora, taxa de sucesso, tempo médio
- Alertas para erros críticos (webhook Slack/Discord)
- Rotação de logs automática
- Dashboard simples em terminal (rich live display)
"""

from __future__ import annotations

import asyncio
import json
import logging
import logging.handlers
import os
import sys
import time
import traceback
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Coroutine, Literal, TypeVar

# Verifica disponibilidade de bibliotecas opcionais
try:
    import aiohttp
    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False

try:
    from rich.console import Console
    from rich.layout import Layout
    from rich.live import Live
    from rich.panel import Panel
    from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn
    from rich.table import Table
    from rich.text import Text
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

# Importa infraestrutura existente
from mercadolivre_upload.infrastructure.config import get_settings
from mercadolivre_upload.infrastructure.logging import JSONFormatter, get_logger
from mercadolivre_upload.infrastructure.metrics import MetricsCollector, collector


# ============================================================================
# Constantes e Configurações
# ============================================================================

DEFAULT_LOG_DIR = Path.home() / ".mercadolivre_upload" / "logs"
MAX_LOG_RETENTION_DAYS = 30
MAX_ALERTS_PER_MINUTE = 10

AlertLevel = Literal["info", "warning", "error", "critical"]


# ============================================================================
# StructuredLogger - Logger JSON para Análise
# ============================================================================

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
        log_data = {
            **self._base_context,
            "level": level,
            "message": message,
            "component": component or self.name,
            "correlation_id": correlation_id,
        }
        
        if extra:
            log_data["extra"] = extra
            
        if exception:
            log_data["exception"] = {
                "type": type(exception).__name__,
                "message": str(exception),
                "traceback": traceback.format_exc() if exception else None,
            }
        
        # Remove campos None
        log_data = {k: v for k, v in log_data.items() if v is not None}
        
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
        log_extra = {
            "operation": operation,
            "success": success,
            "duration_ms": duration_ms,
            **(extra or {}),
        }
        level = "INFO" if success else "ERROR"
        self._log(level, f"Operation: {operation}", component, correlation_id, log_extra)


# ============================================================================
# BusinessMetrics - Métricas de Negócio
# ============================================================================

@dataclass
class HourlyStats:
    """Estatísticas por hora."""
    hour: str
    uploads: int = 0
    successes: int = 0
    failures: int = 0
    total_duration_ms: float = 0.0
    
    @property
    def success_rate(self) -> float:
        """Taxa de sucesso (0-1)."""
        if self.uploads == 0:
            return 0.0
        return self.successes / self.uploads
    
    @property
    def avg_duration_ms(self) -> float:
        """Duração média em ms."""
        if self.uploads == 0:
            return 0.0
        return self.total_duration_ms / self.uploads


class BusinessMetricsCollector:
    """Coletor de métricas de negócio.
    
    Métricas coletadas:
    - Uploads por hora
    - Taxa de sucesso
    - Tempo médio de processamento
    - Produtos por status
    - Erros por categoria
    """

    def __init__(self, max_history_hours: int = 24) -> None:
        """Inicializa o coletor.
        
        Args:
            max_history_hours: Horas de histórico a manter.
        """
        self.max_history_hours = max_history_hours
        self._hourly_stats: dict[str, HourlyStats] = {}
        self._error_counts: dict[str, int] = {}
        self._product_status: dict[str, int] = {}
        self._recent_operations: deque[dict[str, Any]] = deque(maxlen=1000)
        self._start_time = datetime.now()
        
    def record_upload(
        self,
        success: bool,
        duration_ms: float,
        product_id: str | None = None,
        error_category: str | None = None,
    ) -> None:
        """Registra uma operação de upload.
        
        Args:
            success: Se o upload foi bem-sucedido.
            duration_ms: Duração em milissegundos.
            product_id: ID do produto (opcional).
            error_category: Categoria do erro se falhou.
        """
        hour = datetime.now().strftime("%Y-%m-%d %H:00")
        
        if hour not in self._hourly_stats:
            self._cleanup_old_hours()
            self._hourly_stats[hour] = HourlyStats(hour=hour)
        
        stats = self._hourly_stats[hour]
        stats.uploads += 1
        stats.total_duration_ms += duration_ms
        
        if success:
            stats.successes += 1
        else:
            stats.failures += 1
            if error_category:
                self._error_counts[error_category] = self._error_counts.get(error_category, 0) + 1
        
        # Registra operação recente
        self._recent_operations.append({
            "timestamp": datetime.now().isoformat(),
            "success": success,
            "duration_ms": duration_ms,
            "product_id": product_id,
            "error_category": error_category,
        })
    
    def record_product_status(self, status: str, count: int = 1) -> None:
        """Registra produtos por status.
        
        Args:
            status: Status do produto (ex: "pending", "published", "failed").
            count: Quantidade.
        """
        self._product_status[status] = self._product_status.get(status, 0) + count
    
    def _cleanup_old_hours(self) -> None:
        """Remove horas antigas do histórico."""
        cutoff = (datetime.now() - timedelta(hours=self.max_history_hours)).strftime("%Y-%m-%d %H:00")
        self._hourly_stats = {
            k: v for k, v in self._hourly_stats.items() 
            if k >= cutoff
        }
    
    # Métricas calculadas
    
    @property
    def total_uploads(self) -> int:
        """Total de uploads no período."""
        return sum(s.uploads for s in self._hourly_stats.values())
    
    @property
    def total_successes(self) -> int:
        """Total de sucessos."""
        return sum(s.successes for s in self._hourly_stats.values())
    
    @property
    def total_failures(self) -> int:
        """Total de falhas."""
        return sum(s.failures for s in self._hourly_stats.values())
    
    @property
    def overall_success_rate(self) -> float:
        """Taxa de sucesso geral (0-1)."""
        total = self.total_uploads
        if total == 0:
            return 0.0
        return self.total_successes / total
    
    @property
    def avg_duration_ms(self) -> float:
        """Duração média geral em ms."""
        total_duration = sum(s.total_duration_ms for s in self._hourly_stats.values())
        total_uploads = self.total_uploads
        if total_uploads == 0:
            return 0.0
        return total_duration / total_uploads
    
    @property
    def uploads_per_hour(self) -> list[HourlyStats]:
        """Lista de estatísticas por hora ordenadas."""
        return sorted(self._hourly_stats.values(), key=lambda x: x.hour)
    
    @property
    def error_breakdown(self) -> dict[str, int]:
        """Contagem de erros por categoria."""
        return dict(self._error_counts)
    
    @property
    def product_status_breakdown(self) -> dict[str, int]:
        """Contagem de produtos por status."""
        return dict(self._product_status)
    
    @property
    def recent_failures(self) -> list[dict[str, Any]]:
        """Últimas operações com falha."""
        return [op for op in self._recent_operations if not op["success"]][-10:]
    
    @property
    def uptime_seconds(self) -> float:
        """Tempo de execução em segundos."""
        return (datetime.now() - self._start_time).total_seconds()
    
    def get_summary(self) -> dict[str, Any]:
        """Retorna resumo completo das métricas."""
        return {
            "uptime_seconds": self.uptime_seconds,
            "total_uploads": self.total_uploads,
            "total_successes": self.total_successes,
            "total_failures": self.total_failures,
            "success_rate": self.overall_success_rate,
            "avg_duration_ms": self.avg_duration_ms,
            "uploads_per_hour": [
                {
                    "hour": s.hour,
                    "uploads": s.uploads,
                    "success_rate": s.success_rate,
                    "avg_duration_ms": s.avg_duration_ms,
                }
                for s in self.uploads_per_hour[-6:]  # Últimas 6 horas
            ],
            "error_breakdown": self.error_breakdown,
            "product_status": self.product_status_breakdown,
        }


# ============================================================================
# AlertManager - Alertas via Webhook
# ============================================================================

@dataclass
class Alert:
    """Representa um alerta."""
    level: AlertLevel
    title: str
    message: str
    timestamp: datetime = field(default_factory=datetime.now)
    component: str = ""
    correlation_id: str | None = None
    details: dict[str, Any] = field(default_factory=dict)
    
    def to_slack(self) -> dict[str, Any]:
        """Converte para formato Slack webhook."""
        colors = {
            "info": "#36a64f",
            "warning": "#ff9900",
            "error": "#ff0000",
            "critical": "#990000",
        }
        
        return {
            "attachments": [{
                "color": colors.get(self.level, "#808080"),
                "title": f"[{self.level.upper()}] {self.title}",
                "text": self.message,
                "fields": [
                    {"title": "Component", "value": self.component, "short": True},
                    {"title": "Time", "value": self.timestamp.isoformat(), "short": True},
                    *[{"title": k, "value": str(v), "short": True} 
                      for k, v in self.details.items()],
                ],
                "footer": "mercadolivre-upload",
                "ts": int(self.timestamp.timestamp()),
            }]
        }
    
    def to_discord(self) -> dict[str, Any]:
        """Converte para formato Discord webhook."""
        colors = {
            "info": 0x36a64f,
            "warning": 0xff9900,
            "error": 0xff0000,
            "critical": 0x990000,
        }
        
        embed = {
            "title": f"[{self.level.upper()}] {self.title}",
            "description": self.message,
            "color": colors.get(self.level, 0x808080),
            "timestamp": self.timestamp.isoformat(),
            "footer": {"text": "mercadolivre-upload"},
            "fields": [
                {"name": "Component", "value": self.component, "inline": True},
            ],
        }
        
        for k, v in self.details.items():
            embed["fields"].append({"name": k, "value": str(v)[:1024], "inline": True})
        
        return {"embeds": [embed]}


class AlertManager:
    """Gerenciador de alertas via webhooks.
    
    Suporta:
    - Slack webhooks
    - Discord webhooks
    - Rate limiting de alertas
    - Fila de alertas assíncrona
    """

    def __init__(
        self,
        slack_webhook: str | None = None,
        discord_webhook: str | None = None,
        rate_limit_per_minute: int = MAX_ALERTS_PER_MINUTE,
        enabled: bool = True,
    ) -> None:
        """Inicializa o gerenciador de alertas.
        
        Args:
            slack_webhook: URL do webhook do Slack.
            discord_webhook: URL do webhook do Discord.
            rate_limit_per_minute: Máximo de alertas por minuto.
            enabled: Se o envio está habilitado.
        """
        self.slack_webhook = slack_webhook or os.getenv("SLACK_WEBHOOK_URL")
        self.discord_webhook = discord_webhook or os.getenv("DISCORD_WEBHOOK_URL")
        self.rate_limit = rate_limit_per_minute
        self.enabled = enabled and (self.slack_webhook or self.discord_webhook)
        
        self._alert_history: deque[datetime] = deque()
        self._alert_queue: asyncio.Queue[Alert] | None = None
        self._logger = get_logger("observability.alerts")
    
    def _check_rate_limit(self) -> bool:
        """Verifica se pode enviar alerta respeitando rate limit."""
        now = datetime.now()
        one_minute_ago = now - timedelta(minutes=1)
        
        # Remove alertas antigos
        while self._alert_history and self._alert_history[0] < one_minute_ago:
            self._alert_history.popleft()
        
        return len(self._alert_history) < self.rate_limit
    
    async def send_alert(self, alert: Alert) -> bool:
        """Envia um alerta via webhooks configurados.
        
        Args:
            alert: O alerta a ser enviado.
            
        Returns:
            True se enviado com sucesso.
        """
        if not self.enabled:
            self._logger.debug(f"Alertas desabilitados: {alert.title}")
            return False
        
        if not self._check_rate_limit():
            self._logger.warning(f"Rate limit excedido para alertas: {alert.title}")
            return False
        
        success = True
        
        if self.slack_webhook and AIOHTTP_AVAILABLE:
            success = await self._send_slack(alert) and success
            
        if self.discord_webhook and AIOHTTP_AVAILABLE:
            success = await self._send_discord(alert) and success
        
        if success:
            self._alert_history.append(datetime.now())
        
        return success
    
    async def _send_slack(self, alert: Alert) -> bool:
        """Envia alerta para Slack."""
        if not self.slack_webhook:
            return True
            
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.slack_webhook,
                    json=alert.to_slack(),
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as response:
                    if response.status == 200:
                        self._logger.info(f"Alerta enviado ao Slack: {alert.title}")
                        return True
                    else:
                        self._logger.error(
                            f"Falha ao enviar alerta Slack: {response.status}"
                        )
                        return False
        except Exception as e:
            self._logger.error(f"Erro ao enviar alerta Slack: {e}")
            return False
    
    async def _send_discord(self, alert: Alert) -> bool:
        """Envia alerta para Discord."""
        if not self.discord_webhook:
            return True
            
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.discord_webhook,
                    json=alert.to_discord(),
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as response:
                    if response.status in (200, 204):
                        self._logger.info(f"Alerta enviado ao Discord: {alert.title}")
                        return True
                    else:
                        self._logger.error(
                            f"Falha ao enviar alerta Discord: {response.status}"
                        )
                        return False
        except Exception as e:
            self._logger.error(f"Erro ao enviar alerta Discord: {e}")
            return False
    
    async def alert(
        self,
        level: AlertLevel,
        title: str,
        message: str,
        component: str = "",
        correlation_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> bool:
        """Cria e envia um alerta.
        
        Args:
            level: Nível do alerta.
            title: Título do alerta.
            message: Mensagem detalhada.
            component: Componente que gerou.
            correlation_id: ID de correlação.
            details: Detalhes adicionais.
            
        Returns:
            True se enviado com sucesso.
        """
        alert = Alert(
            level=level,
            title=title,
            message=message,
            component=component,
            correlation_id=correlation_id,
            details=details or {},
        )
        return await self.send_alert(alert)
    
    async def info(
        self,
        title: str,
        message: str,
        component: str = "",
        **kwargs: Any,
    ) -> bool:
        """Envia alerta informativo."""
        return await self.alert("info", title, message, component, **kwargs)
    
    async def warning(
        self,
        title: str,
        message: str,
        component: str = "",
        **kwargs: Any,
    ) -> bool:
        """Envia alerta de aviso."""
        return await self.alert("warning", title, message, component, **kwargs)
    
    async def error(
        self,
        title: str,
        message: str,
        component: str = "",
        **kwargs: Any,
    ) -> bool:
        """Envia alerta de erro."""
        return await self.alert("error", title, message, component, **kwargs)
    
    async def critical(
        self,
        title: str,
        message: str,
        component: str = "",
        **kwargs: Any,
    ) -> bool:
        """Envia alerta crítico."""
        return await self.alert("critical", title, message, component, **kwargs)


# ============================================================================
# Dashboard - Display em Tempo Real
# ============================================================================

class Dashboard:
    """Dashboard em tempo real no terminal usando Rich.
    
    Features:
    - Display ao vivo com atualização periódica
    - Métricas de negócio
    - Logs recentes
    - Status de operações
    """

    def __init__(
        self,
        metrics_collector: BusinessMetricsCollector | None = None,
        refresh_rate: float = 1.0,
    ) -> None:
        """Inicializa o dashboard.
        
        Args:
            metrics_collector: Coletor de métricas a exibir.
            refresh_rate: Taxa de atualização em segundos.
        """
        if not RICH_AVAILABLE:
            raise ImportError("Rich é necessário para o Dashboard. Instale com: pip install rich")
        
        self.metrics = metrics_collector or BusinessMetricsCollector()
        self.refresh_rate = refresh_rate
        self.console = Console()
        self._running = False
        self._logger = get_logger("observability.dashboard")

    def _create_layout(self) -> Layout:
        """Cria o layout do dashboard."""
        layout = Layout()
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="main"),
            Layout(name="footer", size=5),
        )
        layout["main"].split_row(
            Layout(name="left", ratio=2),
            Layout(name="right", ratio=1),
        )
        return layout

    def _create_header(self) -> Panel:
        """Cria o cabeçalho."""
        title = Text("Mercado Livre Upload - Dashboard", style="bold cyan")
        subtitle = Text(f"Atualizado: {datetime.now().strftime('%H:%M:%S')}", style="dim")
        return Panel(
            f"{title}\n{subtitle}",
            border_style="cyan",
        )

    def _create_metrics_table(self) -> Table:
        """Cria tabela de métricas principais."""
        table = Table(title="Métricas de Negócio", border_style="blue")
        table.add_column("Métrica", style="cyan")
        table.add_column("Valor", justify="right", style="green")
        
        # Métricas principais
        table.add_row("Total Uploads", str(self.metrics.total_uploads))
        table.add_row(
            "Taxa de Sucesso", 
            f"{self.metrics.overall_success_rate * 100:.1f}%"
        )
        table.add_row(
            "Tempo Médio", 
            f"{self.metrics.avg_duration_ms:.0f} ms"
        )
        table.add_row("Sucessos", str(self.metrics.total_successes))
        table.add_row("Falhas", str(self.metrics.total_failures))
        
        uptime = self.metrics.uptime_seconds
        hours = int(uptime // 3600)
        minutes = int((uptime % 3600) // 60)
        table.add_row("Uptime", f"{hours}h {minutes}m")
        
        return table

    def _create_hourly_chart(self) -> Table:
        """Cria gráfico de uploads por hora."""
        table = Table(title="Uploads por Hora", border_style="yellow")
        table.add_column("Hora", style="cyan")
        table.add_column("Uploads", justify="right")
        table.add_column("Taxa Sucesso", justify="right")
        table.add_column("Tempo Médio", justify="right")
        
        for stats in self.metrics.uploads_per_hour[-8:]:  # Últimas 8 horas
            success_color = "green" if stats.success_rate >= 0.9 else "yellow" if stats.success_rate >= 0.7 else "red"
            table.add_row(
                stats.hour[-5:],  # Mostra apenas HH:00
                str(stats.uploads),
                Text(f"{stats.success_rate * 100:.1f}%", style=success_color),
                f"{stats.avg_duration_ms:.0f}ms",
            )
        
        return table

    def _create_status_table(self) -> Table:
        """Cria tabela de status dos produtos."""
        table = Table(title="Status dos Produtos", border_style="green")
        table.add_column("Status", style="cyan")
        table.add_column("Quantidade", justify="right", style="green")
        
        for status, count in self.metrics.product_status_breakdown.items():
            table.add_row(status, str(count))
        
        if not self.metrics.product_status_breakdown:
            table.add_row("-", "0")
        
        return table

    def _create_errors_table(self) -> Table:
        """Cria tabela de erros."""
        table = Table(title="Erros por Categoria", border_style="red")
        table.add_column("Categoria", style="cyan")
        table.add_column("Contagem", justify="right", style="red")
        
        for category, count in sorted(
            self.metrics.error_breakdown.items(), 
            key=lambda x: x[1], 
            reverse=True
        )[:5]:
            table.add_row(category, str(count))
        
        if not self.metrics.error_breakdown:
            table.add_row("-", "0")
        
        return table

    def _create_footer(self) -> Panel:
        """Cria o rodapé com operações recentes."""
        recent = self.metrics.recent_failures[-5:]
        
        if not recent:
            content = "Nenhuma falha recente"
        else:
            lines = []
            for op in recent:
                time_str = op["timestamp"][11:19]  # HH:MM:SS
                error = op.get("error_category", "unknown")
                lines.append(f"[{time_str}] {error}")
            content = "\n".join(lines)
        
        return Panel(content, title="Últimas Falhas", border_style="red")

    def _render(self) -> Layout:
        """Renderiza o dashboard completo."""
        layout = self._create_layout()
        
        layout["header"].update(self._create_header())
        
        # Painel esquerdo: métricas principais e por hora
        left_layout = Layout()
        left_layout.split_column(
            Layout(self._create_metrics_table(), size=12),
            Layout(self._create_hourly_chart()),
        )
        layout["left"].update(left_layout)
        
        # Painel direito: status e erros
        right_layout = Layout()
        right_layout.split_column(
            Layout(self._create_status_table(), size=8),
            Layout(self._create_errors_table()),
        )
        layout["right"].update(right_layout)
        
        layout["footer"].update(self._create_footer())
        
        return layout

    async def start(self) -> None:
        """Inicia o dashboard em tempo real."""
        self._running = True
        self._logger.info("Iniciando dashboard")
        
        with Live(
            self._render(),
            console=self.console,
            refresh_per_second=1.0 / self.refresh_rate,
            screen=True,
        ) as live:
            while self._running:
                live.update(self._render())
                await asyncio.sleep(self.refresh_rate)

    def stop(self) -> None:
        """Para o dashboard."""
        self._running = False
        self._logger.info("Dashboard parado")

    def run_sync(self) -> None:
        """Executa o dashboard de forma síncrona."""
        try:
            asyncio.run(self.start())
        except KeyboardInterrupt:
            self.stop()
            self.console.print("\n[yellow]Dashboard encerrado[/yellow]")


# ============================================================================
# Integração com Publish Product
# ============================================================================

class ObservabilityManager:
    """Gerenciador central de observabilidade.
    
    Integra logger, métricas, alertas e dashboard.
    """

    def __init__(
        self,
        component_name: str = "publish_product",
        enable_alerts: bool = True,
        enable_dashboard: bool = False,
    ) -> None:
        """Inicializa o gerenciador de observabilidade.
        
        Args:
            component_name: Nome do componente.
            enable_alerts: Se deve habilitar alertas.
            enable_dashboard: Se deve habilitar dashboard.
        """
        self.component = component_name
        self.logger = StructuredLogger(component_name)
        self.metrics = BusinessMetricsCollector()
        self.alerts = AlertManager(enabled=enable_alerts) if enable_alerts else None
        
        self._dashboard: Dashboard | None = None
        if enable_dashboard and RICH_AVAILABLE:
            self._dashboard = Dashboard(self.metrics)
        
        self._logger = get_logger("observability.manager")

    async def record_upload(
        self,
        success: bool,
        duration_ms: float,
        product_id: str | None = None,
        error_category: str | None = None,
        correlation_id: str | None = None,
    ) -> None:
        """Registra um upload e dispara alerta se necessário.
        
        Args:
            success: Se o upload foi bem-sucedido.
            duration_ms: Duração em ms.
            product_id: ID do produto.
            error_category: Categoria do erro.
            correlation_id: ID de correlação.
        """
        # Registra métrica
        self.metrics.record_upload(success, duration_ms, product_id, error_category)
        
        # Log estruturado
        self.logger.log_operation(
            operation="product_upload",
            success=success,
            duration_ms=duration_ms,
            component=self.component,
            correlation_id=correlation_id,
            extra={
                "product_id": product_id,
                "error_category": error_category,
            },
        )
        
        # Alerta em caso de falha crítica
        if not success and error_category in ["api_error", "auth_error", "timeout"]:
            if self.alerts:
                await self.alerts.error(
                    title="Falha no Upload de Produto",
                    message=f"Upload falhou para produto {product_id}: {error_category}",
                    component=self.component,
                    correlation_id=correlation_id,
                    details={
                        "product_id": product_id,
                        "error_category": error_category,
                        "duration_ms": duration_ms,
                    },
                )

    def start_dashboard(self) -> None:
        """Inicia o dashboard se habilitado."""
        if self._dashboard:
            self._dashboard.run_sync()
        else:
            self._logger.warning("Dashboard não habilitado")

    def get_health_status(self) -> dict[str, Any]:
        """Retorna status de saúde do sistema."""
        return {
            "component": self.component,
            "healthy": self.metrics.overall_success_rate >= 0.8,
            "success_rate": self.metrics.overall_success_rate,
            "total_uploads": self.metrics.total_uploads,
            "recent_failures": len(self.metrics.recent_failures),
            "uptime_seconds": self.metrics.uptime_seconds,
        }


# ============================================================================
# Instâncias Globais
# ============================================================================

# Logger estruturado padrão
observability_logger = StructuredLogger("observability")

# Coletor de métricas de negócio
business_metrics = BusinessMetricsCollector()

# Gerenciador de alertas
alert_manager = AlertManager()


# ============================================================================
# Funções de Conveniência
# ============================================================================

def create_observability_manager(
    component: str = "publish_product",
    enable_alerts: bool = True,
    enable_dashboard: bool = False,
) -> ObservabilityManager:
    """Cria um gerenciador de observabilidade configurado.
    
    Args:
        component: Nome do componente.
        enable_alerts: Se deve habilitar alertas.
        enable_dashboard: Se deve habilitar dashboard.
        
    Returns:
        ObservabilityManager configurado.
    """
    return ObservabilityManager(
        component_name=component,
        enable_alerts=enable_alerts,
        enable_dashboard=enable_dashboard,
    )


async def log_product_upload(
    success: bool,
    duration_ms: float,
    product_id: str | None = None,
    error_category: str | None = None,
    correlation_id: str | None = None,
) -> None:
    """Função de conveniência para logar upload de produto.
    
    Args:
        success: Se o upload foi bem-sucedido.
        duration_ms: Duração em ms.
        product_id: ID do produto.
        error_category: Categoria do erro.
        correlation_id: ID de correlação.
    """
    # Registra métricas
    business_metrics.record_upload(success, duration_ms, product_id, error_category)
    
    # Log estruturado
    observability_logger.log_operation(
        operation="product_upload",
        success=success,
        duration_ms=duration_ms,
        correlation_id=correlation_id,
        extra={
            "product_id": product_id,
            "error_category": error_category,
        },
    )
