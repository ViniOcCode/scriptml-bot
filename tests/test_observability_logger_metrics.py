"""Testes para logger e métricas de observabilidade."""

import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from mercadolivre_upload.infrastructure.observability import (
    BusinessMetricsCollector,
    HourlyStats,
    StructuredLogger,
)


@pytest.fixture
def temp_log_dir():
    """Cria diretório temporário para logs."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def structured_logger(temp_log_dir):
    """Cria StructuredLogger com diretório temporário."""
    return StructuredLogger(
        name="test_logger",
        log_dir=temp_log_dir,
        level="DEBUG",
    )


@pytest.fixture
def metrics_collector():
    """Cria BusinessMetricsCollector limpo."""
    return BusinessMetricsCollector(max_history_hours=24)


class TestStructuredLogger:
    """Testes para StructuredLogger."""

    def test_initialization(self, temp_log_dir):
        """Testa inicialização do logger."""
        logger = StructuredLogger(
            name="test_init",
            log_dir=temp_log_dir,
            max_bytes=1024,
            backup_count=3,
            level="INFO",
        )

        assert logger.name == "test_init"
        assert logger.log_dir == temp_log_dir
        assert logger.max_bytes == 1024
        assert logger.backup_count == 3
        assert temp_log_dir.exists()

    def test_log_levels(self, structured_logger, temp_log_dir):
        """Testa diferentes níveis de log."""
        # Força flush dos handlers
        for handler in structured_logger._logger.handlers:
            handler.flush()

        structured_logger.debug("debug message", component="test", correlation_id="123")
        structured_logger.info("info message", component="test")
        structured_logger.warning("warning message")
        structured_logger.error("error message", exception=ValueError("test error"))
        structured_logger.critical("critical message")

        # Força flush novamente
        for handler in structured_logger._logger.handlers:
            handler.flush()

        # Verifica se arquivo foi criado
        log_files = list(temp_log_dir.glob("*.jsonl"))
        assert len(log_files) > 0

    def test_log_operation(self, structured_logger, temp_log_dir):
        """Testa log de operações de negócio."""
        structured_logger.log_operation(
            operation="product_upload",
            success=True,
            duration_ms=150.5,
            component="publisher",
            correlation_id="corr-123",
            extra={"product_id": "MLB123"},
        )

        # Força flush
        for handler in structured_logger._logger.handlers:
            handler.flush()

        # Verifica arquivo
        log_file = temp_log_dir / "test_logger.jsonl"
        assert log_file.exists()

    def test_extra_fields(self, structured_logger):
        """Testa campos extras nos logs."""
        extra = {
            "custom_field": "value",
            "number": 42,
            "nested": {"key": "value"},
        }

        structured_logger.info(
            "test message",
            component="test",
            correlation_id="abc",
            extra=extra,
        )

        # Verifica que não lança exceção
        assert True


class TestBusinessMetricsCollector:
    """Testes para BusinessMetricsCollector."""

    def test_initialization(self):
        """Testa inicialização."""
        collector = BusinessMetricsCollector(max_history_hours=12)
        assert collector.max_history_hours == 12
        assert collector.total_uploads == 0

    def test_record_upload_success(self, metrics_collector):
        """Testa registro de upload bem-sucedido."""
        metrics_collector.record_upload(
            success=True,
            duration_ms=100.0,
            product_id="MLB123",
        )

        assert metrics_collector.total_uploads == 1
        assert metrics_collector.total_successes == 1
        assert metrics_collector.total_failures == 0
        assert metrics_collector.overall_success_rate == 1.0

    def test_record_upload_failure(self, metrics_collector):
        """Testa registro de upload com falha."""
        metrics_collector.record_upload(
            success=False,
            duration_ms=50.0,
            product_id="MLB456",
            error_category="api_error",
        )

        assert metrics_collector.total_uploads == 1
        assert metrics_collector.total_successes == 0
        assert metrics_collector.total_failures == 1
        assert metrics_collector.overall_success_rate == 0.0

    def test_avg_duration(self, metrics_collector):
        """Testa cálculo de duração média."""
        metrics_collector.record_upload(success=True, duration_ms=100.0)
        metrics_collector.record_upload(success=True, duration_ms=200.0)
        metrics_collector.record_upload(success=True, duration_ms=300.0)

        assert metrics_collector.avg_duration_ms == 200.0

    def test_uploads_per_hour(self, metrics_collector):
        """Testa uploads por hora."""
        # Simula uploads
        metrics_collector.record_upload(success=True, duration_ms=100.0)
        metrics_collector.record_upload(success=False, duration_ms=50.0, error_category="timeout")

        hourly = metrics_collector.uploads_per_hour
        assert len(hourly) >= 1

        current_hour = hourly[-1]
        assert current_hour.uploads == 2
        assert current_hour.successes == 1
        assert current_hour.failures == 1

    def test_error_breakdown(self, metrics_collector):
        """Testa contagem de erros por categoria."""
        metrics_collector.record_upload(success=False, duration_ms=50.0, error_category="api_error")
        metrics_collector.record_upload(success=False, duration_ms=50.0, error_category="api_error")
        metrics_collector.record_upload(success=False, duration_ms=50.0, error_category="timeout")

        errors = metrics_collector.error_breakdown
        assert errors["api_error"] == 2
        assert errors["timeout"] == 1

    def test_product_status(self, metrics_collector):
        """Testa registro de status de produtos."""
        metrics_collector.record_product_status("pending", 5)
        metrics_collector.record_product_status("published", 10)
        metrics_collector.record_product_status("failed", 2)

        status = metrics_collector.product_status_breakdown
        assert status["pending"] == 5
        assert status["published"] == 10
        assert status["failed"] == 2

    def test_recent_failures(self, metrics_collector):
        """Testa listagem de falhas recentes."""
        metrics_collector.record_upload(
            success=False,
            duration_ms=50.0,
            product_id="MLB123",
            error_category="api_error",
        )

        failures = metrics_collector.recent_failures
        assert len(failures) == 1
        assert failures[0]["product_id"] == "MLB123"
        assert failures[0]["error_category"] == "api_error"

    def test_cleanup_old_hours(self, metrics_collector):
        """Testa limpeza de horas antigas."""
        # Cria dados antigos manualmente
        old_hour = (datetime.now() - timedelta(hours=25)).strftime("%Y-%m-%d %H:00")
        metrics_collector._hourly_stats[old_hour] = HourlyStats(hour=old_hour, uploads=10)

        # Cria dados recentes
        metrics_collector.record_upload(success=True, duration_ms=100.0)

        # Limpa horas antigas
        metrics_collector._cleanup_old_hours()

        # Verifica que hora antiga foi removida
        assert old_hour not in metrics_collector._hourly_stats

    def test_get_summary(self, metrics_collector):
        """Testa geração de resumo."""
        metrics_collector.record_upload(success=True, duration_ms=100.0)

        summary = metrics_collector.get_summary()

        assert "uptime_seconds" in summary
        assert "total_uploads" in summary
        assert "success_rate" in summary
        assert "avg_duration_ms" in summary
        assert "uploads_per_hour" in summary
        assert "error_breakdown" in summary


class TestHourlyStats:
    """Testes para HourlyStats."""

    def test_success_rate_calculation(self):
        """Testa cálculo de taxa de sucesso."""
        stats = HourlyStats(hour="2024-01-01 12:00", uploads=10, successes=8)
        assert stats.success_rate == 0.8

    def test_success_rate_zero_uploads(self):
        """Testa taxa de sucesso com zero uploads."""
        stats = HourlyStats(hour="2024-01-01 12:00")
        assert stats.success_rate == 0.0

    def test_avg_duration_calculation(self):
        """Testa cálculo de duração média."""
        stats = HourlyStats(
            hour="2024-01-01 12:00",
            uploads=3,
            total_duration_ms=300.0,
        )
        assert stats.avg_duration_ms == 100.0
