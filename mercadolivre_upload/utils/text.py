"""Funções de normalização de texto centralizadas.

Consolida todas as funções normalize() que estavam duplicadas em:
- domain/text_normalizer.py
- domain/attribute_mapper.py
- adapters/spreadsheet/header_detector.py
"""

import re
import unicodedata


def normalize_column_name(name: str) -> str:
    """Normaliza nome de coluna para matching.

    Converte para lowercase, remove acentos e caracteres especiais.
    Substitui espaços por underscores.

    Args:
        name: Nome da coluna original

    Returns:
        Nome normalizado

    Example:
        >>> normalize_column_name("Título do Anúncio")
        'titulo_do_anuncio'
    """
    if not name:
        return ""

    # Lowercase e strip
    text = name.lower().strip()

    # Remove acentos
    text = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))

    # Substitui não-alfanuméricos por underscore
    text = re.sub(r"[^a-z0-9]+", "_", text)

    # Remove underscores duplicados
    text = re.sub(r"_+", "_", text)

    return text.strip("_")


def normalize_text(text: str, keep_accents: bool = False) -> str:
    """Normaliza texto para comparação.

    Args:
        text: Texto a normalizar
        keep_accents: Se True, mantém acentos

    Returns:
        Texto normalizado (lowercase, strip)
    """
    if not text:
        return ""

    text = text.lower().strip()

    if not keep_accents:
        text = "".join(
            c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)
        )

    return text


def normalize_for_fuzzy_matching(text: str) -> str:
    """Normaliza texto para fuzzy matching.

    Remove acentos, pontuação e caracteres especiais.
    Ideal para comparar títulos de produtos.

    Args:
        text: Texto a normalizar

    Returns:
        Texto normalizado para comparação
    """
    if not text:
        return ""

    # Lowercase
    text = text.lower()

    # Remove acentos
    text = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))

    # Remove pontuação
    text = re.sub(r"[^\w\s]", "", text)

    # Remove múltiplos espaços
    text = re.sub(r"\s+", " ", text)

    return text.strip()
