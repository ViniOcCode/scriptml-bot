"""Compatibility entrypoints for repository-level scripts."""

from __future__ import annotations

from importlib import import_module


def run_repo_main() -> int:
    """Run package entrypoint from repository root main.py shim."""
    return int(import_module("mercadolivre_upload.main").run_as_module())
