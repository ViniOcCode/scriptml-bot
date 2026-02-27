"""Tests for infrastructure package import behavior."""

from __future__ import annotations

import importlib
import sys


def test_infrastructure_import_is_lazy_for_observability_exports() -> None:
    """Importing infrastructure package should not eagerly import observability module."""
    original_infrastructure = sys.modules.get("mercadolivre_upload.infrastructure")
    original_observability = sys.modules.get("mercadolivre_upload.infrastructure.observability")
    try:
        sys.modules.pop("mercadolivre_upload.infrastructure", None)
        sys.modules.pop("mercadolivre_upload.infrastructure.observability", None)

        infrastructure = importlib.import_module("mercadolivre_upload.infrastructure")
        assert "mercadolivre_upload.infrastructure.observability" not in sys.modules

        _ = infrastructure.observability_logger
        assert "mercadolivre_upload.infrastructure.observability" in sys.modules
    finally:
        if original_infrastructure is not None:
            sys.modules["mercadolivre_upload.infrastructure"] = original_infrastructure
        if original_observability is not None:
            sys.modules["mercadolivre_upload.infrastructure.observability"] = original_observability
