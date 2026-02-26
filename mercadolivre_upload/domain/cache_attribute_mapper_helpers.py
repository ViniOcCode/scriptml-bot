"""Helper utilities for cached attribute mapper matching and parsing."""

from __future__ import annotations

import re
from typing import Any

from mercadolivre_upload.shared.utils.text_utils import PortugueseTextNormalizer

ValueDef = dict[str, Any]

_STOPWORDS = {"de", "do", "da", "dos", "das", "e"}
_VARIATION_HINT_PREFIX = "varia por"
_BLOCKED_HEADER_PREFIXES = (
    "unidade de altura",
    "unidade de largura",
    "unidade de comprimento",
    "unidade de profundidade",
    "unidade de peso",
    "unidade de tempo de garantia",
)
_BLOCKED_HEADER_EXACT = {
    "forma de envio",
    "custo de envio",
    "tarifa de venda",
    "retirar pessoalmente",
    "quantidade de caracteres",
}


def simplify_match_text(text: str) -> str:
    """Remove low-signal stopwords from normalized text for matching."""
    tokens = [token for token in text.split() if token and token not in _STOPWORDS]
    return " ".join(tokens)


def token_overlap(a: str, b: str) -> float:
    """Compute token overlap ratio between two normalized strings."""
    a_tokens = {token for token in a.split() if token}
    b_tokens = {token for token in b.split() if token}
    if not a_tokens or not b_tokens:
        return 0.0
    intersection = len(a_tokens.intersection(b_tokens))
    denominator = max(len(a_tokens), len(b_tokens))
    return intersection / denominator


def extract_numeric_value(excel_value: str) -> float | int | None:
    """Extract numeric value from free text."""
    if not excel_value:
        return None

    value_str = str(excel_value).strip()
    match = re.match(r"^([\d]+(?:\.\d+)?)", value_str.replace(",", "."))
    if not match:
        return None

    num_str = match.group(1)
    return float(num_str) if "." in num_str else int(num_str)


def is_blocked_header(normalized_header: str) -> bool:
    """Return whether a header is operational metadata, not a product attribute."""
    if normalized_header in _BLOCKED_HEADER_EXACT:
        return True
    if normalized_header == _VARIATION_HINT_PREFIX:
        return True
    return any(normalized_header.startswith(prefix) for prefix in _BLOCKED_HEADER_PREFIXES)


def extract_variation_hint_from_normalized(normalized_header: str) -> str | None:
    """Extract normalized variation hint from a normalized header."""
    if not normalized_header.startswith(_VARIATION_HINT_PREFIX):
        return None
    hint = normalized_header[len(_VARIATION_HINT_PREFIX) :].strip()
    return hint or None


def match_candidate_to_allowed_value(
    candidate: str,
    value_map: dict[str, ValueDef],
) -> ValueDef | None:
    """Match a candidate string to the best allowed value."""
    normalized_candidate = PortugueseTextNormalizer.normalize(candidate)
    if normalized_candidate in value_map:
        return value_map[normalized_candidate]

    best_match: ValueDef | None = None
    best_score = 0.0
    for normalized_value, value_def in value_map.items():
        if normalized_candidate in normalized_value or normalized_value in normalized_candidate:
            score = 0.9
        else:
            score = PortugueseTextNormalizer.similarity(candidate, value_def.get("name", ""))
        if score > best_score:
            best_score = score
            best_match = value_def

    if best_match and best_score >= 0.8:
        return best_match

    return None


def build_value_candidates(excel_value: str) -> list[str]:
    """Build candidate values for enum matching from potentially multi-value cells."""
    value_str = str(excel_value).strip()
    if not value_str:
        return []
    parts = [part.strip() for part in re.split(r"[,;/|]", value_str) if part.strip()]
    if len(parts) > 1:
        return parts + [value_str]
    return [value_str]
