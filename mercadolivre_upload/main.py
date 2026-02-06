"""Main entry point for Mercado Livre Bulk Upload."""

from __future__ import annotations

import sys
from importlib import import_module
from pathlib import Path


def setup_environment() -> None:
    """Ensure repository root is available on sys.path."""
    root = Path(__file__).resolve().parent.parent
    root_str = str(root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)


def main_entry() -> int:
    """Main entry point for CLI."""
    import_module("mercadolivre_upload.cli").app()
    return 0


def run_as_module() -> int:
    """Run entry point when invoked as a module."""
    setup_environment()
    return main_entry()


def main() -> None:
    """Main entry point."""
    run_as_module()


if __name__ == "__main__":
    sys.exit(run_as_module())
