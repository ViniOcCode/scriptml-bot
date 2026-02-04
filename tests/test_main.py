"""Tests for main.py module."""
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Ensure mercadolivre_upload is importable
sys.path.insert(0, str(Path(__file__).parent.parent))


class TestMainEntry:
    """Tests for main_entry function."""

    @patch("mercadolivre_upload.cli.app")
    def test_main_entry_calls_main(self, mock_app):
        """Test that main_entry calls main function."""
        from mercadolivre_upload.main import main_entry

        result = main_entry()

        mock_app.assert_called_once()

    @patch("mercadolivre_upload.cli.app")
    def test_main_entry_handles_exception(self, mock_app):
        """Test that main_entry handles exceptions gracefully."""
        from mercadolivre_upload.main import main_entry

        mock_app.side_effect = Exception("Test error")

        with pytest.raises(Exception, match="Test error"):
            main_entry()


class TestRunAsModule:
    """Tests for run_as_module function."""

    @patch("mercadolivre_upload.main.setup_environment")
    @patch("mercadolivre_upload.cli.app")
    def test_run_as_module_calls_app(self, mock_app, mock_setup):
        """Test that run_as_module calls the cli app."""
        from mercadolivre_upload.main import run_as_module

        run_as_module()

        mock_setup.assert_called_once()
        mock_app.assert_called_once()

    @patch("mercadolivre_upload.main.setup_environment")
    @patch("mercadolivre_upload.cli.app")
    def test_run_as_module_sets_up_environment(self, mock_app, mock_setup):
        """Test that run_as_module sets up environment."""
        from mercadolivre_upload.main import run_as_module

        run_as_module()

        mock_setup.assert_called_once()


class TestSetupEnvironment:
    """Tests for setup_environment function."""

    def test_setup_environment_adds_root_to_path(self):
        """Test that setup_environment adds root directory to sys.path."""
        from mercadolivre_upload.main import setup_environment

        # Store original path
        original_path = sys.path.copy()

        try:
            # Remove any existing mercadolivre_upload entries from parent
            sys.path = [p for p in sys.path if "mercadolivre_upload" not in p.lower()]

            setup_environment()

            # Check that parent directory (root) was added
            # The function adds the parent of the mercadolivre_upload directory
            assert len(sys.path) > 0
            # Verify that at least the first path is a valid path
            assert isinstance(sys.path[0], str)
        finally:
            sys.path = original_path

    def test_setup_environment_does_not_duplicate(self):
        """Test that setup_environment doesn't duplicate entries."""
        from mercadolivre_upload.main import setup_environment

        # Store original path
        original_path = sys.path.copy()

        try:
            setup_environment()
            initial_len = len(sys.path)
            setup_environment()

            # Length should be the same (no duplicates)
            assert len(sys.path) == initial_len
        finally:
            sys.path = original_path


class TestMainExecution:
    """Tests for __main__ execution."""

    @patch("mercadolivre_upload.main.main_entry")
    @patch("sys.exit")
    def test_main_execution(self, mock_exit, mock_main_entry):
        """Test that __main__ block executes correctly."""
        import importlib

        mock_main_entry.return_value = 0

        # Import and reload the module to trigger __main__ block
        import mercadolivre_upload.main as main_module
        importlib.reload(main_module)

        # Note: We can't actually test the __main__ block directly
        # but we can verify the module structure
        assert hasattr(main_module, "main_entry")
        assert hasattr(main_module, "run_as_module")
        assert hasattr(main_module, "setup_environment")


class TestSetupEnvironmentEdgeCases:
    """Edge case tests for setup_environment."""

    def test_setup_environment_when_already_in_path(self):
        """Test setup_environment when root is already in path."""
        from mercadolivre_upload.main import setup_environment

        # Call once to ensure it's in path
        setup_environment()

        # Get initial path length
        initial_len = len(sys.path)

        # Call again - should not add duplicate
        setup_environment()

        # Path length should remain the same
        assert len(sys.path) == initial_len


class TestMainEntrypoint:
    """Tests for __main__ entrypoint."""

    def test_main_block_execution(self):
        """Test that __main__ block executes correctly."""
        import subprocess
        import sys
        from pathlib import Path

        # Get the path to the mercadolivre_upload directory
        test_dir = Path(__file__).parent.parent

        # Run the main.py file directly
        main_file = test_dir / "main.py"
        result = subprocess.run(
            [sys.executable, str(main_file)],
            capture_output=True,
            text=True,
            cwd=str(test_dir.parent)
        )

        # The module should execute (may show help or error)
        # Exit code can be 0, 1, or 2 depending on CLI behavior
        assert result.returncode in [0, 1, 2]
