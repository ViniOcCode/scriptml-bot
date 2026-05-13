"""Shared app-settings adapter for scriptml-bot runtime consumers."""

from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path
from typing import Any


def _resolve_loader_root() -> Path:
    nearest_with_loader: Path | None = None
    for ancestor in Path(__file__).resolve().parents:
        if (ancestor / "ml_app_settings").is_dir():
            if nearest_with_loader is None:
                nearest_with_loader = ancestor
            if (ancestor / "config/settings.yaml").exists():
                return ancestor
    if nearest_with_loader is not None:
        return nearest_with_loader
    raise RuntimeError("Could not locate ml_app_settings package root for scriptml-bot")


_REPO_ROOT = _resolve_loader_root()
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from ml_app_settings import AppSettings, load_app_settings


@lru_cache(maxsize=1)
def get_app_settings() -> AppSettings:
    return load_app_settings(app="bot")


def reload_app_settings() -> AppSettings:
    get_app_settings.cache_clear()
    return get_app_settings()


def get_shipping_config() -> dict[str, Any]:
    return get_app_settings().shipping.model_dump()


def get_fiscal_config() -> dict[str, Any]:
    return get_app_settings().fiscal.model_dump()


def get_mapping_config() -> dict[str, Any]:
    settings = get_app_settings().mapping
    return {
        **settings.standard_fields,
        **settings.attribute_rules,
        "scoring": settings.scoring,
        "sanitizer": settings.sanitizer,
    }


def get_standard_fields_config() -> dict[str, Any]:
    return get_app_settings().mapping.standard_fields


def get_attribute_rules_config() -> dict[str, Any]:
    return get_app_settings().mapping.attribute_rules


def get_seller_section() -> dict[str, Any]:
    return get_app_settings().seller.model_dump()
