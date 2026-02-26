"""Business metrics internals for observability."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any


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
        self._recent_operations.append(
            {
                "timestamp": datetime.now().isoformat(),
                "success": success,
                "duration_ms": duration_ms,
                "product_id": product_id,
                "error_category": error_category,
            }
        )

    def record_product_status(self, status: str, count: int = 1) -> None:
        """Registra produtos por status.

        Args:
            status: Status do produto (ex: "pending", "published", "failed").
            count: Quantidade.
        """
        self._product_status[status] = self._product_status.get(status, 0) + count

    def _cleanup_old_hours(self) -> None:
        """Remove horas antigas do histórico."""
        cutoff = (datetime.now() - timedelta(hours=self.max_history_hours)).strftime(
            "%Y-%m-%d %H:00"
        )
        self._hourly_stats = {k: v for k, v in self._hourly_stats.items() if k >= cutoff}

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
