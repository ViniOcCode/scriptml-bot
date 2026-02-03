"""Utilitários compartilhados."""

from .text import (
    normalize_column_name,
    normalize_text,
    normalize_for_fuzzy_matching,
)

__all__ = [
    "normalize_column_name",
    "normalize_text",
    "normalize_for_fuzzy_matching",
]
