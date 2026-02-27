"""Compatibility entry point that delegates to the package CLI."""

from __future__ import annotations

import sys

from mercadolivre_upload.compat.entrypoints import run_repo_main


def main() -> int:
    """Run the package entrypoint from repository root."""
    return run_repo_main()


if __name__ == "__main__":
    sys.exit(main())
