"""Métricas e observability para o mercadolivre-upload.

Fornece:
- Contadores de operações
- Timers para medição de performance
- Histogramas para distribuição de valores
- Exportação Prometheus (opcional)
"""

from __future__ import annotations

import functools
import time
from collections import Counter, defaultdict
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, TypeVar

from mercadolivre_upload.infrastructure.metrics_helpers import (
    cap_metric_values,
    format_metric_labels,
    get_timer_statistics,
)

# Tentativa de importar prometheus_client (opcional)
try:
    from prometheus_client import (  # noqa: F401
        CONTENT_TYPE_LATEST,
        generate_latest,
        start_http_server,
    )
    from prometheus_client import Counter as PrometheusCounter
    from prometheus_client import Histogram as PrometheusHistogram
    from prometheus_client import Summary as PrometheusSummary

    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False


class MetricType(StrEnum):
    """Tipos de métricas suportadas."""

    COUNTER = "counter"
    TIMER = "timer"
    HISTOGRAM = "histogram"
    GAUGE = "gauge"


@dataclass
class MetricValue:
    """Valor de uma métrica."""

    name: str
    value: float
    labels: dict[str, str] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


class MetricsCollector:
    """Coletor de métricas da aplicação.

    Suporta tanto métricas em memória quanto exportação Prometheus.
    """

    def __init__(self, enable_prometheus: bool = False, prometheus_port: int = 9090) -> None:
        """Inicializa o coletor.

        Args:
            enable_prometheus: Se True, inicia servidor Prometheus.
            prometheus_port: Porta para o servidor Prometheus.
        """
        self._counters: dict[str, Counter[str]] = defaultdict(Counter)
        self._timers: dict[str, list[float]] = defaultdict(list)
        self._histograms: dict[str, list[float]] = defaultdict(list)
        self._gauges: dict[str, float] = {}

        # Prometheus metrics
        self._prometheus_metrics: dict[str, Any] = {}
        self._prometheus_enabled = enable_prometheus and PROMETHEUS_AVAILABLE

        if self._prometheus_enabled:
            try:
                start_http_server(prometheus_port)
                self._prometheus_port = prometheus_port
            except Exception as e:
                self._prometheus_enabled = False
                print(f"Erro ao iniciar servidor Prometheus: {e}")

    # =====================================================================
    # Counters
    # =====================================================================

    def increment(
        self,
        name: str,
        value: float = 1.0,
        labels: dict[str, str] | None = None,
        description: str | None = None,
    ) -> None:
        """Incrementa um contador.

        Args:
            name: Nome da métrica.
            value: Valor a incrementar.
            labels: Labels adicionais.
            description: Descrição da métrica (para Prometheus).
        """
        label_key = self._format_labels(labels or {})
        self._counters[name][label_key] += value  # type: ignore[assignment]

        # Prometheus
        if self._prometheus_enabled:
            prom_name = f"ml_upload_{name}"
            if prom_name not in self._prometheus_metrics:
                self._prometheus_metrics[prom_name] = PrometheusCounter(
                    prom_name, description or f"Counter for {name}", list((labels or {}).keys())
                )
            if labels:
                self._prometheus_metrics[prom_name].labels(**labels).inc(value)
            else:
                self._prometheus_metrics[prom_name].inc(value)

    def get_counter(self, name: str, labels: dict[str, str] | None = None) -> float:
        """Obtém valor de um contador.

        Args:
            name: Nome da métrica.
            labels: Labels para filtrar.

        Returns:
            Valor do contador.
        """
        if labels:
            label_key = self._format_labels(labels)
            return self._counters[name].get(label_key, 0)
        return sum(self._counters[name].values())

    # =====================================================================
    # Timers
    # =====================================================================

    @contextmanager
    def timer(
        self,
        name: str,
        labels: dict[str, str] | None = None,
        description: str | None = None,
    ) -> Any:
        """Context manager para medir tempo de execução.

        Args:
            name: Nome da métrica.
            labels: Labels adicionais.
            description: Descrição da métrica.

        Yields:
            Dicionário com informações do timer.
        """
        start = time.perf_counter()
        timer_info: dict[str, Any] = {"name": name, "start": start}

        try:
            yield timer_info
        finally:
            duration = time.perf_counter() - start
            timer_info["duration"] = duration
            self._record_timer(name, duration, labels, description)

    def _record_timer(
        self,
        name: str,
        duration: float,
        labels: dict[str, str] | None = None,
        description: str | None = None,
    ) -> None:
        """Registra um timer."""
        self._timers[name].append(duration)

        # Mantém apenas últimos 1000 valores para economizar memória
        self._timers[name] = cap_metric_values(self._timers[name])

        # Prometheus
        if self._prometheus_enabled:
            prom_name = f"ml_upload_{name}_duration_seconds"
            if prom_name not in self._prometheus_metrics:
                self._prometheus_metrics[prom_name] = PrometheusSummary(
                    prom_name,
                    description or f"Duration of {name}",
                    list((labels or {}).keys()),
                )
            if labels:
                self._prometheus_metrics[prom_name].labels(**labels).observe(duration)
            else:
                self._prometheus_metrics[prom_name].observe(duration)

    def get_timer_stats(self, name: str) -> dict[str, float]:
        """Obtém estatísticas de um timer.

        Args:
            name: Nome da métrica.

        Returns:
            Dicionário com count, sum, mean, min, max, p50, p95, p99.
        """
        values = self._timers.get(name, [])
        return get_timer_statistics(values)

    # =====================================================================
    # Histograms
    # =====================================================================

    def observe(
        self,
        name: str,
        value: float,
        labels: dict[str, str] | None = None,
        buckets: list[float] | None = None,
        description: str | None = None,
    ) -> None:
        """Registra uma observação em histograma.

        Args:
            name: Nome da métrica.
            value: Valor observado.
            labels: Labels adicionais.
            buckets: Buckets para histograma (opcional).
            description: Descrição da métrica.
        """
        self._histograms[name].append(value)

        # Mantém apenas últimos 1000 valores
        self._histograms[name] = cap_metric_values(self._histograms[name])

        # Prometheus
        if self._prometheus_enabled:
            prom_name = f"ml_upload_{name}"
            if prom_name not in self._prometheus_metrics:
                self._prometheus_metrics[prom_name] = PrometheusHistogram(
                    prom_name,
                    description or f"Histogram for {name}",
                    list((labels or {}).keys()),
                    buckets=buckets or [0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10],
                )
            if labels:
                self._prometheus_metrics[prom_name].labels(**labels).observe(value)
            else:
                self._prometheus_metrics[prom_name].observe(value)

    # =====================================================================
    # Gauges
    # =====================================================================

    def gauge(
        self,
        name: str,
        value: float,
        labels: dict[str, str] | None = None,
        description: str | None = None,
    ) -> None:
        """Define o valor de uma métrica gauge.

        Args:
            name: Nome da métrica.
            value: Valor atual.
            labels: Labels adicionais.
            description: Descrição da métrica.
        """
        label_key = self._format_labels(labels or {})
        self._gauges[f"{name}{label_key}"] = value

    def get_gauge(self, name: str, labels: dict[str, str] | None = None) -> float:
        """Obtém valor de uma métrica gauge.

        Args:
            name: Nome da métrica.
            labels: Labels para filtrar.

        Returns:
            Valor da métrica ou 0 se não existir.
        """
        label_key = self._format_labels(labels or {})
        return self._gauges.get(f"{name}{label_key}", 0.0)

    # =====================================================================
    # Utilitários
    # =====================================================================

    def _format_labels(self, labels: dict[str, str]) -> str:
        """Formata labels para chave."""
        return format_metric_labels(labels)

    def get_all_metrics(self) -> dict[str, Any]:
        """Obtém todas as métricas em formato serializável.

        Returns:
            Dicionário com todas as métricas.
        """
        return {
            "counters": dict(self._counters),
            "timers": {k: self.get_timer_stats(k) for k in self._timers},
            "gauges": self._gauges,
        }

    def reset(self) -> None:
        """Reseta todas as métricas."""
        self._counters.clear()
        self._timers.clear()
        self._histograms.clear()
        self._gauges.clear()


# Instância global do coletor
collector = MetricsCollector()

# =============================================================================
# Decoradores e utilitários
# =============================================================================

F = TypeVar("F", bound=Callable[..., Any])


def timed(
    name: str | None = None,
    labels: dict[str, str] | None = None,
) -> Callable[[F], F]:
    """Decorador para medir tempo de função.

    Args:
        name: Nome da métrica (padrão: nome da função).
        labels: Labels adicionais.

    Returns:
        Decorador configurado.
    """

    def decorator(func: F) -> F:
        metric_name = name or func.__name__

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            with collector.timer(metric_name, labels):
                return func(*args, **kwargs)

        return wrapper  # type: ignore

    return decorator


def counted(
    name: str | None = None,
    labels: dict[str, str] | None = None,
) -> Callable[[F], F]:
    """Decorador para contar chamadas de função.

    Args:
        name: Nome da métrica (padrão: nome da função).
        labels: Labels adicionais.

    Returns:
        Decorador configurado.
    """

    def decorator(func: F) -> F:
        metric_name = name or f"{func.__name__}_calls"

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            collector.increment(metric_name, 1, labels)
            return func(*args, **kwargs)

        return wrapper  # type: ignore

    return decorator


# Métricas específicas do domínio
class Metrics:
    """Namespace para métricas da aplicação."""

    # API calls
    API_CALLS = "api_calls_total"
    API_ERRORS = "api_errors_total"
    API_LATENCY = "api_request_duration"

    # Upload
    UPLOADS_STARTED = "uploads_started_total"
    UPLOADS_COMPLETED = "uploads_completed_total"
    UPLOADS_FAILED = "uploads_failed_total"
    UPLOAD_DURATION = "upload_duration_seconds"

    # Products
    PRODUCTS_PROCESSED = "products_processed_total"
    PRODUCTS_PUBLISHED = "products_published_total"
    PRODUCTS_FAILED = "products_failed_total"

    # Images
    IMAGES_UPLOADED = "images_uploaded_total"
    IMAGES_FAILED = "images_failed_total"
    IMAGE_PROCESSING_TIME = "image_processing_seconds"

    # Cache
    CACHE_HITS = "cache_hits_total"
    CACHE_MISSES = "cache_misses_total"
    CACHE_SIZE = "cache_size_bytes"

    # Auth
    AUTH_REFRESHES = "auth_token_refreshes_total"
    AUTH_FAILURES = "auth_failures_total"


def record_api_call(
    endpoint: str,
    method: str,
    status_code: int,
    duration: float,
    error: bool = False,
) -> None:
    """Registra métrica de chamada API.

    Args:
        endpoint: Endpoint chamado.
        method: Método HTTP.
        status_code: Código de status HTTP.
        duration: Duração da requisição.
        error: Se houve erro.
    """
    labels = {"endpoint": endpoint, "method": method, "status": str(status_code)}

    collector.increment(Metrics.API_CALLS, 1, labels)
    collector.observe(f"{Metrics.API_LATENCY}", duration, labels)

    if error or status_code >= 400:
        collector.increment(Metrics.API_ERRORS, 1, labels)


def record_upload(success: bool, duration: float) -> None:
    """Registra métrica de upload.

    Args:
        success: Se o upload foi bem-sucedido.
        duration: Duração do upload.
    """
    collector.increment(Metrics.UPLOADS_STARTED)

    if success:
        collector.increment(Metrics.UPLOADS_COMPLETED)
    else:
        collector.increment(Metrics.UPLOADS_FAILED)

    collector.observe(Metrics.UPLOAD_DURATION, duration)


def record_product_processed(success: bool) -> None:
    """Registra métrica de processamento de produto.

    Args:
        success: Se o processamento foi bem-sucedido.
    """
    collector.increment(Metrics.PRODUCTS_PROCESSED)

    if success:
        collector.increment(Metrics.PRODUCTS_PUBLISHED)
    else:
        collector.increment(Metrics.PRODUCTS_FAILED)


def record_cache_operation(hit: bool) -> None:
    """Registra métrica de operação de cache.

    Args:
        hit: Se foi um cache hit.
    """
    if hit:
        collector.increment(Metrics.CACHE_HITS)
    else:
        collector.increment(Metrics.CACHE_MISSES)
