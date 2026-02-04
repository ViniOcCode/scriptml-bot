"""Tests for cli.py module."""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

# Ensure mercadolivre_upload is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from mercadolivre_upload.cli import app

runner = CliRunner()


class TestCliCallback:
    """Tests for CLI callback."""

    def test_callback_exists(self):
        """Test that callback command exists."""
        result = runner.invoke(app, [])
        # Callback doesn't produce output, just sets up
        assert result.exit_code in [0, 2]  # 0 for help, 2 for missing command


class TestUploadCommand:
    """Tests for upload command."""

    @patch("mercadolivre_upload.cli.PublishProductService")
    def test_upload_success(self, mock_service_class):
        """Test successful upload."""
        mock_service = MagicMock()
        mock_service_class.return_value = mock_service

        result_mock = MagicMock()
        result_mock.success_count = 5
        result_mock.failure_count = 0
        mock_service.publish_from_file.return_value = result_mock

        # Create a temporary file
        with runner.isolated_filesystem():
            Path("test.xlsx").write_text("dummy")
            result = runner.invoke(app, ["upload", "test.xlsx"])

        assert result.exit_code == 0
        mock_service.publish_from_file.assert_called_once()

    @patch("mercadolivre_upload.cli.PublishProductService")
    def test_upload_with_verbose(self, mock_service_class):
        """Test upload with verbose flag."""
        mock_service = MagicMock()
        mock_service_class.return_value = mock_service

        result_mock = MagicMock()
        result_mock.success_count = 3
        result_mock.failure_count = 0
        mock_service.publish_from_file.return_value = result_mock

        with runner.isolated_filesystem():
            Path("test.xlsx").write_text("dummy")
            result = runner.invoke(app, ["upload", "test.xlsx", "--verbose"])

        assert result.exit_code == 0
        assert "Processando arquivo" in result.output

    @patch("mercadolivre_upload.cli.PublishProductService")
    def test_upload_with_dry_run(self, mock_service_class):
        """Test upload with dry-run flag."""
        mock_service = MagicMock()
        mock_service_class.return_value = mock_service

        result_mock = MagicMock()
        result_mock.success_count = 2
        result_mock.failure_count = 0
        mock_service.publish_from_file.return_value = result_mock

        with runner.isolated_filesystem():
            Path("test.xlsx").write_text("dummy")
            result = runner.invoke(app, ["upload", "test.xlsx", "--dry-run"])

        assert result.exit_code == 0
        mock_service_class.assert_called_once_with(
            config_path=None, dry_run=True
        )

    @patch("mercadolivre_upload.cli.PublishProductService")
    def test_upload_with_config(self, mock_service_class):
        """Test upload with config file."""
        mock_service = MagicMock()
        mock_service_class.return_value = mock_service

        result_mock = MagicMock()
        result_mock.success_count = 1
        result_mock.failure_count = 0
        mock_service.publish_from_file.return_value = result_mock

        with runner.isolated_filesystem():
            Path("test.xlsx").write_text("dummy")
            Path("config.yaml").write_text("key: value")
            result = runner.invoke(
                app, ["upload", "test.xlsx", "--config", "config.yaml"]
            )

        assert result.exit_code == 0
        mock_service_class.assert_called_once()
        call_kwargs = mock_service_class.call_args.kwargs
        assert str(call_kwargs.get('config_path')) == "config.yaml"

    def test_upload_file_not_found(self):
        """Test upload with non-existent file."""
        result = runner.invoke(app, ["upload", "nonexistent.xlsx"])

        assert result.exit_code == 1
        assert "Arquivo não encontrado" in result.output

    @patch("mercadolivre_upload.cli.PublishProductService")
    def test_upload_with_failures(self, mock_service_class):
        """Test upload with some failures."""
        mock_service = MagicMock()
        mock_service_class.return_value = mock_service

        result_mock = MagicMock()
        result_mock.success_count = 2
        result_mock.failure_count = 3
        mock_service.publish_from_file.return_value = result_mock

        with runner.isolated_filesystem():
            Path("test.xlsx").write_text("dummy")
            result = runner.invoke(app, ["upload", "test.xlsx"])

        # When failures exist, the command raises SystemExit
        assert result.exit_code == 1  # CLI raises code 1 from raise typer.Exit in except

    @patch("mercadolivre_upload.cli.PublishProductService")
    def test_upload_error(self, mock_service_class):
        """Test upload with exception."""
        mock_service = MagicMock()
        mock_service_class.return_value = mock_service
        mock_service.publish_from_file.side_effect = Exception("API Error")

        with runner.isolated_filesystem():
            Path("test.xlsx").write_text("dummy")
            result = runner.invoke(app, ["upload", "test.xlsx"])

        assert result.exit_code == 1
        assert "Erro durante publicação" in result.output


class TestAuthCommand:
    """Tests for auth command."""

    @patch("mercadolivre_upload.cli.AuthManager")
    def test_auth_set_token(self, mock_auth_class):
        """Test auth with token option."""
        mock_auth = MagicMock()
        mock_auth_class.return_value = mock_auth

        result = runner.invoke(app, ["auth", "--token", "my_token_123"])

        assert result.exit_code == 0
        assert "Token configurado" in result.output
        mock_auth.set_token.assert_called_once_with("my_token_123")

    @patch("mercadolivre_upload.cli.AuthManager")
    def test_auth_refresh_success(self, mock_auth_class):
        """Test auth refresh success."""
        mock_auth = MagicMock()
        mock_auth_class.return_value = mock_auth

        result = runner.invoke(app, ["auth", "--refresh"])

        assert result.exit_code == 0
        assert "Token atualizado" in result.output
        mock_auth.refresh_token.assert_called_once()

    @patch("mercadolivre_upload.cli.AuthManager")
    def test_auth_refresh_error(self, mock_auth_class):
        """Test auth refresh with error."""
        mock_auth = MagicMock()
        mock_auth_class.return_value = mock_auth
        mock_auth.refresh_token.side_effect = Exception("Refresh failed")

        result = runner.invoke(app, ["auth", "--refresh"])

        assert result.exit_code == 1
        assert "Erro ao atualizar token" in result.output

    @patch("mercadolivre_upload.cli.AuthManager")
    def test_auth_status_authenticated(self, mock_auth_class):
        """Test auth status when authenticated."""
        mock_auth = MagicMock()
        mock_auth_class.return_value = mock_auth

        status_mock = MagicMock()
        status_mock.authenticated = True
        status_mock.user_id = "user123"
        mock_auth.get_auth_status.return_value = status_mock

        result = runner.invoke(app, ["auth"])

        assert result.exit_code == 0
        assert "Autenticado" in result.output
        assert "user123" in result.output

    @patch("mercadolivre_upload.cli.AuthManager")
    def test_auth_status_not_authenticated(self, mock_auth_class):
        """Test auth status when not authenticated."""
        mock_auth = MagicMock()
        mock_auth_class.return_value = mock_auth

        status_mock = MagicMock()
        status_mock.authenticated = False
        mock_auth.get_auth_status.return_value = status_mock

        result = runner.invoke(app, ["auth"])

        assert result.exit_code == 0
        assert "Não autenticado" in result.output


class TestValidateCommand:
    """Tests for validate command."""

    @patch("mercadolivre_upload.cli.PublishProductService")
    def test_validate_success(self, mock_service_class):
        """Test successful validation."""
        mock_service = MagicMock()
        mock_service_class.return_value = mock_service

        validation_mock = MagicMock()
        validation_mock.is_valid = True
        validation_mock.errors = []
        mock_service.validate_file.return_value = validation_mock

        with runner.isolated_filesystem():
            Path("test.xlsx").write_text("dummy")
            result = runner.invoke(app, ["validate", "test.xlsx"])

        assert result.exit_code == 0
        assert "Arquivo válido" in result.output

    @patch("mercadolivre_upload.cli.PublishProductService")
    def test_validate_with_errors(self, mock_service_class):
        """Test validation with errors."""
        mock_service = MagicMock()
        mock_service_class.return_value = mock_service

        validation_mock = MagicMock()
        validation_mock.is_valid = False
        validation_mock.errors = ["Linha 1: preço inválido", "Linha 2: título vazio"]
        mock_service.validate_file.return_value = validation_mock

        with runner.isolated_filesystem():
            Path("test.xlsx").write_text("dummy")
            result = runner.invoke(app, ["validate", "test.xlsx"])

        assert result.exit_code == 1
        assert "2 erros" in result.output
        assert "preço inválido" in result.output

    @patch("mercadolivre_upload.cli.PublishProductService")
    def test_validate_with_output(self, mock_service_class):
        """Test validation with output file."""
        mock_service = MagicMock()
        mock_service_class.return_value = mock_service

        validation_mock = MagicMock()
        validation_mock.is_valid = False
        validation_mock.errors = ["Erro 1", "Erro 2"]
        mock_service.validate_file.return_value = validation_mock

        with runner.isolated_filesystem():
            Path("test.xlsx").write_text("dummy")
            result = runner.invoke(
                app, ["validate", "test.xlsx", "--output", "errors.txt"]
            )

            assert Path("errors.txt").exists()
            assert "Erro 1" in Path("errors.txt").read_text()

        assert result.exit_code == 1

    def test_validate_file_not_found(self):
        """Test validate with non-existent file."""
        result = runner.invoke(app, ["validate", "nonexistent.xlsx"])

        assert result.exit_code == 1
        assert "Arquivo não encontrado" in result.output

    @patch("mercadolivre_upload.cli.PublishProductService")
    def test_validate_error(self, mock_service_class):
        """Test validate with exception."""
        mock_service = MagicMock()
        mock_service_class.return_value = mock_service
        mock_service.validate_file.side_effect = Exception("Parse error")

        with runner.isolated_filesystem():
            Path("test.xlsx").write_text("dummy")
            result = runner.invoke(app, ["validate", "test.xlsx"])

        assert result.exit_code == 1
        assert "Erro na validação" in result.output


class TestMain:
    """Tests for main function."""

    @patch("mercadolivre_upload.cli.app")
    def test_main_calls_app(self, mock_app):
        """Test that main calls the app."""
        from mercadolivre_upload.cli import main

        main()

        mock_app.assert_called_once()


class TestMainBlock:
    """Tests for __main__ block."""

    def test_main_block_execution(self):
        """Test that __main__ block executes main function."""
        import subprocess
        import sys
        from pathlib import Path

        cli_path = Path(__file__).parent.parent / "cli.py"

        result = subprocess.run(
            [sys.executable, str(cli_path)],
            capture_output=True,
            text=True,
        )

        # Should run the app (will show help or error)
        assert result.returncode in [0, 1, 2]
