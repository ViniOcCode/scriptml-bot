"""Shared utilities package."""

from .text_utils import TextNormalizer, normalize_text, text_similarity

__all__ = [
    "TextNormalizer",
    "normalize_text",
    "text_similarity",
]
