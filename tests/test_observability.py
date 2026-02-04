"""Testes para o sistema de observabilidade.

Testa:
- StructuredLogger (JSON logging)
- BusinessMetricsCollector (métricas de negócio)
- AlertManager (alertas via webhook)
- Dashboard (display em tempo real)
- ObservabilityManager (integração)
"""

import sys
from pathlib import Path

# Ensure mercadolivre_upload is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# Ensure mercadolivre_upload is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

# Importa do módulo de infraestrutura (conftest.py já adiciona o path)
from mercadolivre_upload.infrastructure.observability import (
    Alert,
    AlertManager,
    BusinessMetricsCollector,
    Dashboard,
    HourlyStats,
    ObservabilityManager,
    StructuredLogger,
    alert_manager,
    business_metrics,
    create_observability_manager,
    log_product_upload,
    observability_logger,
)

# =============================================================================
# Fixtures
# =============================================================================

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
    collector = BusinessMetricsCollector(max_history_hours=24)
    return collector


@pytest.fixture
def alert_manager_mock():
    """Cria AlertManager com mocks."""
    with patch.dict(os.environ, {}, clear=True):
        manager = AlertManager(enabled=False)
        manager._send_slack = AsyncMock(return_value=True)
        manager._send_discord = AsyncMock(return_value=True)
        return manager


@pytest.fixture
def mock_aiohttp():
    """Mock para aiohttp."""
    with patch(
        "mercadolivre_upload.infrastructure.observability.AIOHTTP_AVAILABLE",
        True,
    ), patch("aiohttp.ClientSession") as mock_session:
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_context = AsyncMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_response)
        mock_context.__aexit__ = AsyncMock(return_value=None)
        mock_session.return_value.__aenter__ = AsyncMock(
            return_value=MagicMock(
                post=MagicMock(return_value=mock_context)
            )
        )
        mock_session.return_value.__aexit__ = AsyncMock(return_value=None)
        yield mock_session


# =============================================================================
# StructuredLogger Tests
# =============================================================================

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


# =============================================================================
# BusinessMetricsCollector Tests
# =============================================================================

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
        metrics_collector.record_upload(
            success=False, duration_ms=50.0, error_category="api_error"
        )
        metrics_collector.record_upload(
            success=False, duration_ms=50.0, error_category="api_error"
        )
        metrics_collector.record_upload(
            success=False, duration_ms=50.0, error_category="timeout"
        )

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


# =============================================================================
# HourlyStats Tests
# =============================================================================

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


# =============================================================================
# Alert Tests
# =============================================================================

class TestAlert:
    """Testes para Alert."""

    def test_alert_creation(self):
        """Testa criação de alerta."""
        alert = Alert(
            level="error",
            title="Test Alert",
            message="This is a test",
            component="test_component",
            details={"key": "value"},
        )

        assert alert.level == "error"
        assert alert.title == "Test Alert"
        assert alert.component == "test_component"

    def test_to_slack_format(self):
        """Testa conversão para formato Slack."""
        alert = Alert(
            level="critical",
            title="Critical Error",
            message="Something went wrong",
            component="api",
            details={"endpoint": "/products"},
        )

        slack_data = alert.to_slack()

        assert "attachments" in slack_data
        assert slack_data["attachments"][0]["color"] == "#990000"
        assert "Critical Error" in slack_data["attachments"][0]["title"]

    def test_to_discord_format(self):
        """Testa conversão para formato Discord."""
        alert = Alert(
            level="warning",
            title="Warning",
            message="Check this out",
            component="worker",
        )

        discord_data = alert.to_discord()

        assert "embeds" in discord_data
        assert discord_data["embeds"][0]["color"] == 0xFF9900


# =============================================================================
# AlertManager Tests
# =============================================================================

class TestAlertManager:
    """Testes para AlertManager."""

    def test_initialization_disabled(self):
        """Testa inicialização desabilitada."""
        manager = AlertManager(enabled=False)
        assert not manager.enabled

    def test_initialization_with_env_vars(self):
        """Testa inicialização com variáveis de ambiente."""
        with patch.dict(
            os.environ,
            {
                "SLACK_WEBHOOK_URL": "https://hooks.slack.com/test",
                "DISCORD_WEBHOOK_URL": "https://discord.com/api/webhooks/test",
            },
        ):
            manager = AlertManager()
            assert manager.slack_webhook == "https://hooks.slack.com/test"
            assert manager.discord_webhook == "https://discord.com/api/webhooks/test"

    def test_rate_limit(self, alert_manager_mock):
        """Testa rate limiting."""
        assert alert_manager_mock._check_rate_limit()

        # Adiciona alertas até o limite
        for _ in range(MAX_ALERTS_PER_MINUTE := 10):
            alert_manager_mock._alert_history.append(datetime.now())

        assert not alert_manager_mock._check_rate_limit()

    @pytest.mark.asyncio
    async def test_send_alert_disabled(self):
        """Testa envio quando desabilitado."""
        manager = AlertManager(enabled=False)
        alert = Alert(level="info", title="Test", message="Test")

        result = await manager.send_alert(alert)
        assert result is False

    @pytest.mark.asyncio
    async def test_alert_methods(self, alert_manager_mock):
        """Testa métodos de conveniência para alertas."""
        with patch.object(alert_manager_mock, "send_alert", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True

            await alert_manager_mock.info("Info Title", "Info message")
            await alert_manager_mock.warning("Warning Title", "Warning message")
            await alert_manager_mock.error("Error Title", "Error message")
            await alert_manager_mock.critical("Critical Title", "Critical message")

            assert mock_send.call_count == 4


# =============================================================================
# Dashboard Tests
# =============================================================================

class TestDashboard:
    """Testes para Dashboard."""

    def test_initialization_without_rich(self):
        """Testa erro quando rich não está disponível."""
        with patch(
            "mercadolivre_upload.infrastructure.observability.RICH_AVAILABLE",
            False,
        ), pytest.raises(ImportError):
            Dashboard()

    @pytest.mark.skipif(
        not pytest.importorskip("rich", reason="rich não instalado"),
        reason="rich não instalado",
    )
    def test_initialization_with_rich(self):
        """Testa inicialização com rich."""
        with patch(
            "mercadolivre_upload.infrastructure.observability.RICH_AVAILABLE",
            True,
        ):
            metrics = BusinessMetricsCollector()
            dashboard = Dashboard(metrics)

            assert dashboard.metrics == metrics
            assert dashboard.refresh_rate == 1.0

    def test_create_layout(self, metrics_collector):
        """Testa criação de layout."""
        with patch(
            "mercadolivre_upload.infrastructure.observability.RICH_AVAILABLE",
            True,
        ):
            dashboard = Dashboard(metrics_collector)
            layout = dashboard._create_layout()

            assert "header" in layout
            assert "main" in layout
            assert "footer" in layout

    def test_create_metrics_table(self, metrics_collector):
        """Testa criação de tabela de métricas."""
        with patch(
            "mercadolivre_upload.infrastructure.observability.RICH_AVAILABLE",
            True,
        ):
            metrics_collector.record_upload(success=True, duration_ms=100.0)
            metrics_collector.record_upload(success=False, duration_ms=50.0)

            dashboard = Dashboard(metrics_collector)
            table = dashboard._create_metrics_table()

            assert table is not None

    def test_create_hourly_chart(self, metrics_collector):
        """Testa criação de gráfico por hora."""
        with patch(
            "mercadolivre_upload.infrastructure.observability.RICH_AVAILABLE",
            True,
        ):
            metrics_collector.record_upload(success=True, duration_ms=100.0)

            dashboard = Dashboard(metrics_collector)
            table = dashboard._create_hourly_chart()

            assert table is not None


# =============================================================================
# ObservabilityManager Tests
# =============================================================================

class TestObservabilityManager:
    """Testes para ObservabilityManager."""

    def test_initialization(self):
        """Testa inicialização."""
        manager = ObservabilityManager(
            component_name="test_component",
            enable_alerts=False,
            enable_dashboard=False,
        )

        assert manager.component == "test_component"
        assert manager.logger is not None
        assert manager.metrics is not None
        assert manager.alerts is None

    def test_initialization_with_alerts(self):
        """Testa inicialização com alertas."""
        with patch.dict(os.environ, {}, clear=True):
            manager = ObservabilityManager(
                component_name="test",
                enable_alerts=False,  # Desabilitado para não precisar de webhook
            )
            assert manager.alerts is None

    @pytest.mark.asyncio
    async def test_record_upload_success(self):
        """Testa registro de upload bem-sucedido."""
        manager = ObservabilityManager(
            component_name="publisher",
            enable_alerts=False,
        )

        await manager.record_upload(
            success=True,
            duration_ms=100.0,
            product_id="MLB123",
            correlation_id="corr-123",
        )

        assert manager.metrics.total_uploads == 1
        assert manager.metrics.total_successes == 1

    @pytest.mark.asyncio
    async def test_record_upload_failure_with_alert(self):
        """Testa registro de falha com alerta."""
        manager = ObservabilityManager(
            component_name="publisher",
            enable_alerts=False,  # Mock para não enviar realmente
        )

        # Mock do alert manager
        manager.alerts = AsyncMock()
        manager.alerts.error = AsyncMock(return_value=True)

        await manager.record_upload(
            success=False,
            duration_ms=50.0,
            product_id="MLB456",
            error_category="api_error",
            correlation_id="corr-456",
        )

        assert manager.metrics.total_uploads == 1
        assert manager.metrics.total_failures == 1

    def test_get_health_status(self):
        """Testa obtenção de status de saúde."""
        manager = ObservabilityManager(enable_alerts=False)

        # Cenário saudável
        manager.metrics.record_upload(success=True, duration_ms=100.0)
        manager.metrics.record_upload(success=True, duration_ms=100.0)

        health = manager.get_health_status()

        assert health["component"] == "publish_product"
        assert health["healthy"] is True
        assert health["success_rate"] == 1.0
        assert health["total_uploads"] == 2

    def test_get_health_status_unhealthy(self):
        """Testa status de saúde quando não saudável."""
        manager = ObservabilityManager(enable_alerts=False)

        # Cenário não saudável (< 80% sucesso)
        for _ in range(5):
            manager.metrics.record_upload(success=False, duration_ms=50.0)

        health = manager.get_health_status()

        assert health["healthy"] is False


# =============================================================================
# Integration Tests
# =============================================================================

class TestObservabilityIntegration:
    """Testes de integração."""

    @pytest.mark.asyncio
    async def test_full_workflow(self):
        """Testa workflow completo de observabilidade."""
        # Cria manager
        manager = create_observability_manager(
            component="integration_test",
            enable_alerts=False,
        )

        # Simula uploads
        for i in range(10):
            await manager.record_upload(
                success=i < 8,  # 80% sucesso
                duration_ms=100.0 + i * 10,
                product_id=f"MLB{i}",
                correlation_id=f"corr-{i}",
            )

        # Verifica métricas
        assert manager.metrics.total_uploads == 10
        assert manager.metrics.total_successes == 8
        assert manager.metrics.total_failures == 2
        assert manager.metrics.overall_success_rate == 0.8

    @pytest.mark.asyncio
    async def test_log_product_upload_convenience(self):
        """Testa função de conveniência log_product_upload."""
        # Limpa métricas globais
        business_metrics._hourly_stats.clear()

        await log_product_upload(
            success=True,
            duration_ms=150.0,
            product_id="MLB789",
            error_category=None,
            correlation_id="test-corr",
        )

        assert business_metrics.total_uploads >= 1


# =============================================================================
# Global Instances Tests
# =============================================================================

class TestGlobalInstances:
    """Testes para instâncias globais."""

    def test_observability_logger_exists(self):
        """Testa que logger global existe."""
        assert observability_logger is not None
        assert isinstance(observability_logger, StructuredLogger)

    def test_business_metrics_exists(self):
        """Testa que métricas globais existem."""
        assert business_metrics is not None
        assert isinstance(business_metrics, BusinessMetricsCollector)

    def test_alert_manager_exists(self):
        """Testa que alert manager global existe."""
        assert alert_manager is not None
        assert isinstance(alert_manager, AlertManager)


# =============================================================================
# Error Handling Tests
# =============================================================================

class TestErrorHandling:
    """Testes para tratamento de erros."""

    def test_logger_with_exception(self, structured_logger):
        """Testa logging de exceção."""
        try:
            raise ValueError("Test exception")
        except Exception as e:
            structured_logger.error(
                "Error occurred",
                exception=e,
            )

        assert True  # Não deve lançar exceção

    def test_metrics_with_invalid_duration(self, metrics_collector):
        """Testa métricas com duração inválida."""
        metrics_collector.record_upload(
            success=True,
            duration_ms=-100.0,  # Valor negativo
        )

        # Deve aceitar mas resultados podem ser estranhos
        assert metrics_collector.total_uploads == 1

    @pytest.mark.asyncio
    async def test_alert_send_failure(self):
        """Testa falha no envio de alerta."""
        manager = AlertManager(
            slack_webhook="https://invalid.url",
            enabled=True,
        )

        alert = Alert(level="error", title="Test", message="Test")

        # Deve retornar False em caso de erro
        result = await manager.send_alert(alert)
        assert result is False

    def test_dashboard_without_rich_error(self):
        """Testa erro ao criar dashboard sem rich."""
        with patch(
            "mercadolivre_upload.infrastructure.observability.RICH_AVAILABLE",
            False,
        ):
            with pytest.raises(ImportError) as exc_info:
                Dashboard()

            assert "Rich é necessário" in str(exc_info.value)
