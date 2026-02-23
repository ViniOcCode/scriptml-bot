"""Compatibility entry point that delegates to the package CLI."""

from __future__ import annotations

import sys
from importlib import import_module


def main() -> int:
    """Run the package entrypoint from repository root."""
    return int(import_module("mercadolivre_upload.main").run_as_module())


if __name__ == "__main__":
    sys.exit(main())
