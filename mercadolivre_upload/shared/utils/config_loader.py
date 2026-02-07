"""Centralized YAML configuration loading utility.

Consolidates the _load_yaml_config helper that was duplicated across 8 files.
"""

from pathlib import Path
from typing import Any

import yaml


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
