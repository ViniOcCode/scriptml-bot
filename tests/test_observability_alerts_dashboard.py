"""Testes para alertas e dashboard de observabilidade."""

import os
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

from mercadolivre_upload.infrastructure.observability import (
    Alert,
    AlertManager,
    BusinessMetricsCollector,
    Dashboard,
)


@pytest.fixture
def metrics_collector():
    """Cria BusinessMetricsCollector limpo."""
    return BusinessMetricsCollector(max_history_hours=24)


@pytest.fixture
def alert_manager_mock():
    """Cria AlertManager com mocks."""
    with patch.dict(os.environ, {}, clear=True):
        manager = AlertManager(enabled=False)
        manager._send_slack = AsyncMock(return_value=True)
        manager._send_discord = AsyncMock(return_value=True)
        return manager


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
        for _ in range(10):
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


class TestDashboard:
    """Testes para Dashboard."""

    def test_initialization_without_rich(self):
        """Testa erro quando rich não está disponível."""
        with (
            patch(
                "mercadolivre_upload.infrastructure.observability.RICH_AVAILABLE",
                False,
            ),
            pytest.raises(ImportError),
        ):
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
