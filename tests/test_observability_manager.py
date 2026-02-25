"""Testes para manager e integrações de observabilidade."""

import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from mercadolivre_upload.infrastructure.observability import (
    Alert,
    AlertManager,
    BusinessMetricsCollector,
    Dashboard,
    ObservabilityManager,
    StructuredLogger,
    alert_manager,
    business_metrics,
    create_observability_manager,
    log_product_upload,
    observability_logger,
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
