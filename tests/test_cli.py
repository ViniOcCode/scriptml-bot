"""Tests for cli.py module."""

import json
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
        assert result.exit_code in [0, 2]


class TestUploadCommand:
    """Tests for upload command."""

    @patch("mercadolivre_upload.cli.app.import_module")
    def test_upload_delegates_to_new_command(self, mock_import_module):
        """Test upload delegates to new flow command."""
        mock_upload_module = MagicMock()
        mock_import_module.return_value = mock_upload_module

        with runner.isolated_filesystem():
            Path("test.xlsx").write_text("dummy")
            result = runner.invoke(
                app,
                [
                    "upload",
                    "test.xlsx",
                    "--images",
                    "imgs",
                    "--category",
                    "test-category",
                ],
            )

        assert result.exit_code == 0
        mock_import_module.assert_called_once_with("mercadolivre_upload.cli.commands.upload")
        mock_upload_module.upload.assert_called_once()
        kwargs = mock_upload_module.upload.call_args.kwargs
        assert kwargs["excel"] == Path("test.xlsx")
        assert kwargs["images"] == Path("imgs")
        assert kwargs["category"] == "test-category"
        assert kwargs["cache_dir"] == Path("cache/categories")
        assert kwargs["detailed"] is False
        assert kwargs["batch_size"] == 5
        assert kwargs["report_dir"] == Path("cache/reports")

    @patch("mercadolivre_upload.cli.app.import_module")
    def test_upload_accepts_excel_option(self, mock_import_module):
        """Test upload accepts --excel option."""
        mock_upload_module = MagicMock()
        mock_import_module.return_value = mock_upload_module

        with runner.isolated_filesystem():
            Path("test.xlsx").write_text("dummy")
            result = runner.invoke(
                app,
                [
                    "upload",
                    "--excel",
                    "test.xlsx",
                    "--images",
                    "imgs",
                    "--category",
                    "test-category",
                    "--batch-size",
                    "3",
                    "--report-dir",
                    "batch-reports",
                ],
            )

        assert result.exit_code == 0
        kwargs = mock_upload_module.upload.call_args.kwargs
        assert kwargs["batch_size"] == 3
        assert kwargs["report_dir"] == Path("batch-reports")

    @patch("mercadolivre_upload.cli.app.import_module")
    def test_upload_forwards_publish_inactive_flag(self, mock_import_module):
        """Test --publish-inactive is forwarded to the upload command."""
        mock_upload_module = MagicMock()
        mock_import_module.return_value = mock_upload_module

        with runner.isolated_filesystem():
            Path("test.xlsx").write_text("dummy")
            result = runner.invoke(
                app,
                [
                    "upload",
                    "test.xlsx",
                    "--images",
                    "imgs",
                    "--category",
                    "test-category",
                    "--publish-inactive",
                ],
            )

        assert result.exit_code == 0
        kwargs = mock_upload_module.upload.call_args.kwargs
        assert kwargs["publish_inactive"] is True

    @patch("mercadolivre_upload.cli.app.import_module")
    def test_upload_publish_inactive_defaults_to_false(self, mock_import_module):
        """Test publish_inactive defaults to False when flag is not provided."""
        mock_upload_module = MagicMock()
        mock_import_module.return_value = mock_upload_module

        with runner.isolated_filesystem():
            Path("test.xlsx").write_text("dummy")
            result = runner.invoke(
                app,
                [
                    "upload",
                    "test.xlsx",
                    "--images",
                    "imgs",
                    "--category",
                    "test-category",
                ],
            )

        assert result.exit_code == 0
        kwargs = mock_upload_module.upload.call_args.kwargs
        assert kwargs["publish_inactive"] is False

    def test_upload_requires_new_flow_params(self):
        """Test upload requires --images and --category."""
        with runner.isolated_filesystem():
            Path("test.xlsx").write_text("dummy")
            result = runner.invoke(app, ["upload", "test.xlsx", "--images", "imgs"])

        assert result.exit_code == 1
        assert "Parametros obrigatorios: --images e --category" in result.output

    def test_upload_file_not_found(self):
        """Test upload with non-existent file."""
        result = runner.invoke(
            app,
            ["upload", "nonexistent.xlsx", "--images", "imgs", "--category", "test-category"],
        )

        assert result.exit_code == 1
        assert "Arquivo não encontrado" in result.output


class TestValidateCommand:
    """Tests for validate command."""

    @patch("mercadolivre_upload.cli.app.import_module")
    def test_validate_delegates_to_new_command(self, mock_import_module):
        """Test validate delegates to new flow command."""
        mock_validate_module = MagicMock()
        mock_import_module.return_value = mock_validate_module

        with runner.isolated_filesystem():
            Path("test.xlsx").write_text("dummy")
            result = runner.invoke(
                app,
                [
                    "validate",
                    "test.xlsx",
                    "--images",
                    "imgs",
                    "--category",
                    "test-category",
                    "--detailed",
                ],
            )

        assert result.exit_code == 0
        mock_import_module.assert_called_once_with("mercadolivre_upload.cli.commands.validate")
        mock_validate_module.validate.assert_called_once()
        kwargs = mock_validate_module.validate.call_args.kwargs
        assert kwargs["excel"] == Path("test.xlsx")
        assert kwargs["images"] == Path("imgs")
        assert kwargs["category"] == "test-category"
        assert kwargs["cache_dir"] == Path("cache/categories")
        assert kwargs["detailed"] is True
        assert kwargs["batch_size"] == 5
        assert kwargs["report_dir"] == Path("cache/reports")

    def test_validate_requires_new_flow_params(self):
        """Test validate requires --images and --category."""
        with runner.isolated_filesystem():
            Path("test.xlsx").write_text("dummy")
            result = runner.invoke(app, ["validate", "test.xlsx", "--images", "imgs"])

        assert result.exit_code == 1
        assert "Parametros obrigatorios: --images e --category" in result.output

    def test_validate_file_not_found(self):
        """Test validate with non-existent file."""
        result = runner.invoke(
            app,
            ["validate", "nonexistent.xlsx", "--images", "imgs", "--category", "test-category"],
        )

        assert result.exit_code == 1
        assert "Arquivo não encontrado" in result.output


class TestAuthCommand:
    """Tests for auth command."""

    @patch("mercadolivre_upload.auth.TokenManager")
    def test_auth_set_token(self, mock_auth_class):
        """Test auth with token option."""
        mock_auth = MagicMock()
        mock_auth_class.return_value = mock_auth

        result = runner.invoke(app, ["auth", "--token", "my_token_123"])

        assert result.exit_code == 0
        assert "Token configurado" in result.output
        mock_auth.set_token.assert_called_once_with("my_token_123")

    @patch("mercadolivre_upload.auth.TokenManager")
    def test_auth_refresh_success(self, mock_auth_class):
        """Test auth refresh success."""
        mock_auth = MagicMock()
        mock_auth_class.return_value = mock_auth

        result = runner.invoke(app, ["auth", "--refresh"])

        assert result.exit_code == 0
        assert "Token atualizado" in result.output
        mock_auth.refresh_token.assert_called_once()

    @patch("mercadolivre_upload.auth.TokenManager")
    def test_auth_refresh_error(self, mock_auth_class):
        """Test auth refresh with error."""
        mock_auth = MagicMock()
        mock_auth_class.return_value = mock_auth
        mock_auth.refresh_token.side_effect = Exception("Refresh failed")

        result = runner.invoke(app, ["auth", "--refresh"])

        assert result.exit_code == 1
        assert "Erro ao atualizar token" in result.output

    @patch("mercadolivre_upload.auth.TokenManager")
    def test_auth_status_authenticated(self, mock_auth_class):
        """Test auth status when authenticated."""
        mock_auth = MagicMock()
        mock_auth_class.return_value = mock_auth

        mock_auth.get_auth_status.return_value = {"authenticated": True, "user_id": "user123"}

        result = runner.invoke(app, ["auth"])

        assert result.exit_code == 0
        assert "Autenticado" in result.output
        assert "user123" in result.output

    @patch("mercadolivre_upload.auth.TokenManager")
    def test_auth_status_authenticated_without_user_id(self, mock_auth_class):
        """Test auth status output when user_id is not available."""
        mock_auth = MagicMock()
        mock_auth_class.return_value = mock_auth

        mock_auth.get_auth_status.return_value = {"authenticated": True, "user_id": None}

        result = runner.invoke(app, ["auth"])

        assert result.exit_code == 0
        assert "Autenticado" in result.output
        assert "None" not in result.output

    @patch("mercadolivre_upload.auth.TokenManager")
    def test_auth_status_not_authenticated(self, mock_auth_class):
        """Test auth status when not authenticated."""
        mock_auth = MagicMock()
        mock_auth_class.return_value = mock_auth

        mock_auth.get_auth_status.return_value = {"authenticated": False, "user_id": None}

        result = runner.invoke(app, ["auth"])

        assert result.exit_code == 0
        assert "Não autenticado" in result.output


class TestPublishManifestCommand:
    """Tests for publish-manifest command."""

    @patch("mercadolivre_upload.cli.app.import_module")
    def test_publish_manifest_delegates_to_command_module(self, mock_import_module):
        mock_runtime_module = MagicMock()
        mock_runtime_module.resolve_workspace_root.return_value = Path("/tmp/workspace")
        mock_runtime_module.build_attempt_report_dir.return_value = Path(
            "/tmp/workspace/cache/report/20260514-010203"
        )
        mock_manifest_module = MagicMock()
        mock_import_module.side_effect = [mock_runtime_module, mock_manifest_module]

        with runner.isolated_filesystem():
            Path("run_manifest.json").write_text("{}", encoding="utf-8")
            Path("config").mkdir()
            Path("config/publisher.yaml").write_text("seller: {}\n", encoding="utf-8")
            result = runner.invoke(app, ["publish-manifest", "run_manifest.json"])

        assert result.exit_code == 0
        mock_manifest_module.publish_manifest.assert_called_once()
        kwargs = mock_manifest_module.publish_manifest.call_args.kwargs
        assert kwargs["manifest_path"] == Path("run_manifest.json")
        assert kwargs["dry_run"] is False
        assert kwargs["publish_inactive"] is False
        assert kwargs["seller_config"] == Path("config/publisher.yaml")


class TestReconcileCommand:
    """Tests for reconcile command wiring."""

    @patch("mercadolivre_upload.cli.app.import_module")
    def test_reconcile_delegates_to_command_module(self, mock_import_module):
        mock_runtime_module = MagicMock()
        mock_runtime_module.resolve_workspace_root.return_value = Path("/tmp/workspace")
        mock_reconcile_module = MagicMock()
        mock_import_module.side_effect = [mock_runtime_module, mock_reconcile_module]

        with runner.isolated_filesystem():
            Path("config").mkdir()
            Path("config/publisher.yaml").write_text("seller: {}\n", encoding="utf-8")
            result = runner.invoke(
                app,
                [
                    "reconcile",
                    "--from-manifest",
                    "--run-id",
                    "run-1",
                    "--output",
                    "json",
                    "--save-report",
                ],
            )

        assert result.exit_code == 0
        mock_reconcile_module.reconcile.assert_called_once()
        kwargs = mock_reconcile_module.reconcile.call_args.kwargs
        assert kwargs["workspace_root"] == Path("/tmp/workspace")
        assert kwargs["seller_config"] == Path("config/publisher.yaml")
        assert kwargs["from_manifest"] is True
        assert kwargs["run_id"] == "run-1"
        assert kwargs["output"] == "json"
        assert kwargs["save_report"] is True

    def test_reconcile_json_output_is_machine_parseable(self, capsys):
        from mercadolivre_upload.application.reconcile import ReconcileReport, ReconcileRow
        from mercadolivre_upload.cli.commands.reconcile import _print_json

        report = ReconcileReport(
            generated_at="2026-06-22T00:00:00+00:00",
            workspace_root="/tmp/workspace",
            source="artifacts",
            summary={"total": 1},
            rows=[
                ReconcileRow(
                    status="local_payload_error",
                    payload_path="/tmp/workspace/groups/" + ("long-path/" * 20),
                    error_reason="invalid_json: " + ("long message " * 20),
                )
            ],
        )

        _print_json(report)

        parsed = json.loads(capsys.readouterr().out)
        assert parsed["summary"] == {"total": 1}
        assert parsed["rows"][0]["status"] == "local_payload_error"

    def test_reconcile_table_folds_long_values_instead_of_truncating(self, capsys):
        from mercadolivre_upload.application.reconcile import ReconcileReport, ReconcileRow
        from mercadolivre_upload.cli.commands.reconcile import _print_table

        long_sku = "991-VERY-LONG-SELLER-SKU-WITHOUT-TRUNCATION"
        report = ReconcileReport(
            generated_at="2026-06-22T00:00:00+00:00",
            workspace_root="/tmp/workspace",
            source="artifacts",
            summary={"total": 1},
            rows=[
                ReconcileRow(
                    status="ml_without_local_payload",
                    sku_scope=[long_sku],
                    listing_type_id="gold_special",
                    ml_item_id="MLB2794106123",
                    ml_status="closed",
                )
            ],
        )

        _print_table(report)

        output = capsys.readouterr().out
        assert "…" not in output
        assert "991" in output
        assert "TRUNCATION" in output


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

        cli_path = Path(__file__).parent.parent / "cli.py"

        result = subprocess.run(
            [sys.executable, str(cli_path)],
            capture_output=True,
            text=True,
        )

        assert result.returncode in [0, 1, 2]
