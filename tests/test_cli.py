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


def _assert_removed_command(*arguments: str) -> None:
    result = runner.invoke(app, list(arguments))
    assert result.exit_code == 2
    assert "No such command" in result.output


class TestCliCallback:
    """Tests for CLI callback."""

    def test_callback_exists(self):
        """Test that callback command exists."""
        result = runner.invoke(app, [])
        assert result.exit_code in [0, 2]


class TestUploadCommand:
    """The unsafe spreadsheet publisher is not part of the production CLI."""

    def test_upload_delegates_to_new_command(self):
        _assert_removed_command("upload")

    def test_upload_accepts_excel_option(self):
        _assert_removed_command("upload", "--excel", "test.xlsx")

    def test_upload_forwards_publish_inactive_flag(self):
        _assert_removed_command("upload", "--publish-inactive")

    def test_upload_publish_inactive_defaults_to_false(self):
        _assert_removed_command("upload", "test.xlsx")

    def test_upload_requires_new_flow_params(self):
        _assert_removed_command("upload", "--images", "imgs")

    def test_upload_file_not_found(self):
        _assert_removed_command("upload", "nonexistent.xlsx")


class TestValidateCommand:
    """The legacy spreadsheet validator is not part of the production CLI."""

    def test_validate_delegates_to_new_command(self):
        _assert_removed_command("validate")

    def test_validate_requires_new_flow_params(self):
        _assert_removed_command("validate", "--images", "imgs")

    def test_validate_file_not_found(self):
        _assert_removed_command("validate", "nonexistent.xlsx")


class TestAuthCommand:
    """OAuth tokens are managed only by the dashboard's encrypted repository."""

    def test_auth_set_token(self):
        _assert_removed_command("auth", "--token", "redacted")

    def test_auth_refresh_success(self):
        _assert_removed_command("auth", "--refresh")

    def test_auth_refresh_error(self):
        _assert_removed_command("auth", "--refresh")

    def test_auth_status_authenticated(self):
        _assert_removed_command("auth")

    def test_auth_status_authenticated_without_user_id(self):
        _assert_removed_command("auth")

    def test_auth_status_not_authenticated(self):
        _assert_removed_command("auth")


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
            result = runner.invoke(
                app,
                ["publish-manifest", "run_manifest.json", "--workspace", "workspace"],
            )

        assert result.exit_code == 0
        mock_manifest_module.publish_manifest.assert_called_once()
        kwargs = mock_manifest_module.publish_manifest.call_args.kwargs
        assert kwargs["manifest_path"] == Path("run_manifest.json")
        assert kwargs["dry_run"] is False
        assert kwargs["publish_inactive"] is False
        assert kwargs["seller_config"] == Path(".canonical-publisher-config")


class TestReconcileCommand:
    """Tests for reconcile command wiring."""

    @patch("mercadolivre_upload.cli.app.import_module")
    def test_reconcile_delegates_to_command_module(self, mock_import_module):
        mock_runtime_module = MagicMock()
        mock_runtime_module.resolve_workspace_root.return_value = Path("/tmp/workspace")
        mock_reconcile_module = MagicMock()
        mock_import_module.side_effect = [mock_runtime_module, mock_reconcile_module]

        with runner.isolated_filesystem():
            result = runner.invoke(
                app,
                [
                    "reconcile",
                    "--workspace",
                    "workspace",
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
        assert kwargs["seller_config"] == Path(".canonical-publisher-config")
        assert kwargs["from_manifest"] is True
        assert kwargs["run_id"] == "run-1"
        assert kwargs["execution_profile"] == "paid"
        assert kwargs["output"] == "json"
        assert kwargs["save_report"] is True

    @patch("mercadolivre_upload.cli.app.import_module")
    def test_reconcile_accepts_explicit_dev_profile(self, mock_import_module):
        mock_runtime_module = MagicMock()
        mock_runtime_module.resolve_workspace_root.return_value = Path("/tmp/workspace")
        mock_reconcile_module = MagicMock()
        mock_import_module.side_effect = [mock_runtime_module, mock_reconcile_module]

        with runner.isolated_filesystem():
            result = runner.invoke(
                app,
                [
                    "reconcile",
                    "--workspace",
                    "workspace",
                    "--execution-profile",
                    "dev",
                    "--from-artifacts",
                ],
            )

        assert result.exit_code == 0
        assert mock_reconcile_module.reconcile.call_args.kwargs["execution_profile"] == "dev"
        assert mock_reconcile_module.reconcile.call_args.kwargs["from_manifest"] is False

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
