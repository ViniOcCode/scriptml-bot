"""Centralized YAML configuration loading utility.

Consolidates the _load_yaml_config helper that was duplicated across 8 files.
"""

from pathlib import Path
from typing import Any

import yaml

DEFAULT_LEGACY_CONFIG_PATH = Path("config/generic_mappings.yaml")


def load_yaml_config(primary: Path, fallback: Path | None = None) -> dict[str, Any]:
    """Load YAML configuration from file with fallback support.

    Args:
        primary: Primary config file path
        fallback: Optional fallback config file path

    Returns:
        Dictionary with loaded config, or empty dict if no files exist
    """
    for path in (primary, fallback):
        if path and path.exists():
            with open(path, encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
    return {}


def load_merged_yaml_config(
    *primary_paths: Path,
    fallback: Path | None = DEFAULT_LEGACY_CONFIG_PATH,
) -> dict[str, Any]:
    """Load YAML files and merge them with deterministic precedence.

    Precedence (lowest -> highest):
    1. fallback file (when provided and available)
    2. each primary file in the order passed

    Merge is top-level only to preserve existing application semantics.
    """
    merged: dict[str, Any] = {}
    if fallback:
        merged.update(load_yaml_config(fallback))
    for path in primary_paths:
        merged.update(load_yaml_config(path))
    return merged
