"""Canonical environment access for the integrated Mercado Livre pipeline."""

from __future__ import annotations

import os

from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv(usecwd=True), override=False)

PREFIX = "ML_PIPE_"


def get_pipeline_env(name: str, default: str | None = None) -> str | None:
    """Read one canonical ML_PIPE environment variable."""
    if not name.startswith(PREFIX):
        raise ValueError(f"Pipeline environment variable must use {PREFIX} prefix: {name}")
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return value.strip()


def get_pipeline_flag(name: str, *, default: bool) -> bool:
    """Read a canonical ML_PIPE boolean environment variable."""
    value = get_pipeline_env(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}
