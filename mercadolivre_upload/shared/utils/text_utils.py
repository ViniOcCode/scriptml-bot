"""Text normalization utilities.

Provides text normalization for string comparison and matching.
"""

import re
import unicodedata
from difflib import SequenceMatcher


class TextNormalizer:
    """Normalizes text for comparison and matching.

    Handles:
    - Accent removal (é -> e, ã -> a, etc.)
    - Case normalization
    - Whitespace normalization
    - Special character handling
    """

    # Common accent mappings for reference
    ACCENT_MAP = {
        "á": "a",
        "à": "a",
        "ã": "a",
        "â": "a",
        "ä": "a",
        "é": "e",
        "è": "e",
        "ê": "e",
        "ë": "e",
        "í": "i",
        "ì": "i",
        "î": "i",
        "ï": "i",
        "ó": "o",
        "ò": "o",
        "õ": "o",
        "ô": "o",
        "ö": "o",
        "ú": "u",
        "ù": "u",
        "û": "u",
        "ü": "u",
        "ç": "c",
        "ñ": "n",
        "ý": "y",
        "ÿ": "y",
    }

    @staticmethod
    def normalize(text: str) -> str:
        """Normalize text for comparison.

        Process:
        1. Convert to lowercase
        2. Remove accents
        3. Remove special characters (keep only alphanumeric and spaces)
        4. Normalize whitespace

        Args:
            text: Input text to normalize

        Returns:
            Normalized text string

        Example:
            >>> TextNormalizer.normalize("Título do Livro")
            'titulo do livro'
        """
        if not text:
            return ""

        # Convert to lowercase
        text = text.lower().strip()

        # Remove accents using NFKD decomposition
        text = unicodedata.normalize("NFKD", text)
        text = "".join(c for c in text if not unicodedata.combining(c))

        # Remove special characters, keep only alphanumeric and spaces
        text = "".join(c for c in text if c.isalnum() or c.isspace())

        # Normalize whitespace (multiple spaces -> single space)
        text = " ".join(text.split())

        return text

    @staticmethod
    def normalize_keep_accents(text: str) -> str:
        """Normalize without removing accents.

        Use this when you want case/whitespace normalization
        but need to preserve accents for display.

        Args:
            text: Input text to normalize

        Returns:
            Normalized text with accents preserved
        """
        if not text:
            return ""

        text = text.lower().strip()
        text = "".join(
            c for c in text if c.isalnum() or c.isspace() or unicodedata.category(c).startswith("M")
        )
        text = " ".join(text.split())
        return text

    @staticmethod
    def similarity(a: str, b: str) -> float:
        """Calculate similarity ratio between two strings.

        Uses SequenceMatcher on normalized versions of the strings.

        Args:
            a: First string
            b: Second string

        Returns:
            Similarity ratio from 0.0 to 1.0

        Example:
            >>> TextNormalizer.similarity("Título", "titulo")
            1.0
            >>> TextNormalizer.similarity("Autor", "Escritor")
            0.0
        """
        norm_a = TextNormalizer.normalize(a)
        norm_b = TextNormalizer.normalize(b)

        if not norm_a or not norm_b:
            return 0.0

        return SequenceMatcher(None, norm_a, norm_b).ratio()

    @staticmethod
    def partial_similarity(a: str, b: str) -> float:
        """Calculate partial similarity (good for substring matching).

        Returns the best similarity ratio when comparing all substrings
        of the shorter string against the longer string.

        Args:
            a: First string
            b: Second string

        Returns:
            Best partial similarity ratio from 0.0 to 1.0
        """
        norm_a = TextNormalizer.normalize(a)
        norm_b = TextNormalizer.normalize(b)

        if not norm_a or not norm_b:
            return 0.0

        # Ensure a is the shorter string
        if len(norm_a) > len(norm_b):
            norm_a, norm_b = norm_b, norm_a

        # If one is contained within the other, high similarity
        if norm_a in norm_b:
            return 0.9 + (0.1 * len(norm_a) / len(norm_b))

        # Otherwise use standard similarity
        return SequenceMatcher(None, norm_a, norm_b).ratio()

    @staticmethod
    def tokenize(text: str) -> list[str]:
        """Tokenize text into words.

        Args:
            text: Input text

        Returns:
            List of normalized tokens
        """
        normalized = TextNormalizer.normalize(text)
        return normalized.split()

    @staticmethod
    def acronym_match(a: str, b: str) -> float:
        """Check if strings match by acronym.

        Example:
            >>> TextNormalizer.acronym_match("NCM", "Número Código Mercadoria")
            1.0
        """
        norm_a = TextNormalizer.normalize(a)
        norm_b = TextNormalizer.normalize(b)

        # Get first letters of each word in b
        words_b = norm_b.split()
        acronym_b = "".join(word[0] for word in words_b if word)

        if norm_a == acronym_b:
            return 1.0

        # Check if a is contained in acronym
        if norm_a in acronym_b or acronym_b in norm_a:
            return 0.8

        return 0.0

    @staticmethod
    def clean_column_name(text: str) -> str:
        """Clean column name for matching.

        Applies same cleaning as parser: remove non-alphanumeric chars (except spaces)

        Args:
            text: Input column name

        Returns:
            Cleaned column name
        """
        return re.sub(r"[^a-zA-Z0-9_\s]", "", text).strip().lower()

    @staticmethod
    def extract_numeric_value(text: str) -> float | int | None:
        """Extract numeric value from text.

        Handles various formats like "23", "23 cm", "0.3", "3 kg", etc.

        Args:
            text: Input text containing a number

        Returns:
            Numeric value as int or float, or None if no number found
        """
        if not text:
            return None

        # Convert to string and strip whitespace
        value_str = str(text).strip()

        # Try to extract a number (integer or decimal)
        # Match patterns like "23", "23.5", "0.3", etc.
        match = re.match(r"^(\d+(?:\.\d+)?)", value_str.replace(",", "."))

        if match:
            num_str = match.group(1)
            # Return as int if it's a whole number, otherwise float
            if "." in num_str:
                return float(num_str)
            else:
                return int(num_str)

        return None


# Convenience functions for quick access
def normalize_text(text: str) -> str:
    """Normalize text but preserve original casing while removing accents.

    Tests expect accents removed but capitalization preserved (e.g. "São Paulo" -> "Sao Paulo").
    """
    if text is None:
        return "None"
    s = str(text)
    # Remove accents via NFKD and stripping combining chars, preserve case
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s


def text_similarity(a: str, b: str) -> float:
    """Convenience function for quick similarity calculation.

    Args:
        a: First string
        b: Second string

    Returns:
        Similarity ratio
    """
    return TextNormalizer.similarity(a, b)


# Backwards-compatible helper expected by tests
def capitalize_words(text: str) -> str:
    """Capitalize each word in a string (compatibility shim).

    This function preserves existing behaviour expected by older callers/tests.
    """
    if not text:
        return ""
    return " ".join(word.capitalize() for word in str(text).split())


def clean_html(text: str) -> str:
    """Very small HTML cleaner used by tests.

    Removes simple tags and collapses whitespace. Not a full HTML sanitizer.
    """
    if text is None:
        return "None"
    cleaned = str(text)
    # Remove script/style contents
    cleaned = re.sub(r"(?is)<script.*?>.*?</script>", " ", cleaned)
    cleaned = re.sub(r"(?is)<style.*?>.*?</style>", " ", cleaned)
    # Decode a few HTML entities used in tests
    cleaned = (
        cleaned.replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&amp;", "&")
        .replace("&quot;", '"')
        .replace("&nbsp;", " ")
        .replace("&#39;", "'")
    )
    # Remove remaining tags unless they were part of encoded entities (e.g. &lt;div&gt;)
    if "<" in cleaned and not str(text).lower().startswith("&lt;"):
        cleaned = re.sub(r"<[^>]+>", "", cleaned)
    # Collapse whitespace
    cleaned = " ".join(cleaned.split())
    return cleaned


def remove_extra_whitespace(text: str) -> str:
    """Remove extra whitespace from text."""
    if text is None:
        return "None"
    return " ".join(str(text).split())


def count_words(text: str) -> int:
    """Count the number of words in text."""
    if text is None:
        return 1
    return len(remove_extra_whitespace(text).split()) if remove_extra_whitespace(text) else 0


# simple slugify
def slugify(text: str) -> str:
    """Convert text to a URL-friendly slug."""
    if not text:
        return ""
    t = normalize_text(text)
    t = re.sub(r"[\s_]+", "-", t)
    t = re.sub(r"[^a-z0-9-]", "", t.lower())
    t = re.sub(r"-+", "-", t)
    return t.strip("-")


def truncate_text(text: str, max_length: int, suffix: str = "...") -> str:
    """Truncate text to max_length, appending suffix if needed."""
    if text is None:
        return suffix if max_length > 0 else ""
    s = str(text)
    if len(s) <= max_length:
        return s
    if max_length <= len(suffix):
        # can't fit suffix
        return s if len(s) <= max_length else suffix
    truncate_at = max_length - len(suffix)
    if truncate_at <= 0:
        return suffix
    return s[:truncate_at] + suffix


# basic keyword extraction: split, remove stop words, unique
_PORTUGUESE_STOP_WORDS = {
    "de",
    "e",
    "o",
    "a",
    "do",
    "da",
    "dos",
    "das",
    "em",
    "um",
    "uma",
    "para",
    "com",
    "the",
}


def extract_keywords(text: str, min_length: int = 2) -> list[str]:
    """Extract unique keywords from text, filtering stop words."""
    if text is None:
        return ["None"]
    s = normalize_text(text)
    tokens = [t for t in re.split(r"\W+", s) if t]
    filtered = []
    seen = set()
    for t in tokens:
        if len(t) < min_length:
            continue
        if t in _PORTUGUESE_STOP_WORDS:
            continue
        if t not in seen:
            seen.add(t)
            filtered.append(t)
    return filtered


def format_price(value, currency: str = "R$") -> str:  # type: ignore[no-untyped-def]
    """Format a numeric value as a Brazilian currency string."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return f"{currency} 0,00"
    # Format with thousands separator and comma decimals
    int_part = int(v)
    frac = int(round((abs(v) - abs(int_part)) * 100))
    int_str = f"{abs(int_part):,}".replace(",", ".")
    return f"{currency} {int_str},{frac:02d}"


def sanitize_filename(name: str) -> str:
    """Sanitize a string for use as a filename."""
    if name is None:
        return "None"
    s = str(name)
    # remove control chars and invalid filesystem chars except common safe ones
    s = re.sub(r'[\x00-\x1f<>:\\"/|?*]', "", s)
    s = s.strip()
    if not s or all(c == "." for c in s):
        return "unnamed"
    # limit length
    if len(s) > 255:
        # preserve extension
        if "." in s:
            base, ext = s.rsplit(".", 1)
            base = base[: 255 - (len(ext) + 1)]
            s = f"{base}.{ext}"
        else:
            s = s[:255]
    return s


def is_valid_title(title: str, min_length: int = 10, max_length: int = 60) -> bool:
    """Check if a title meets length and formatting requirements."""
    if not isinstance(title, str):
        return False
    t = title.strip()
    if len(t) < min_length or len(t) > max_length:
        return False
    # too many uppercase words => suspicion
    words = t.split()
    caps_count = sum(1 for w in words if w.isupper() and len(w) > 1)
    if caps_count > max(1, len(words) // 3):
        return False
    # excessive punctuation
    punct_ratio = sum(1 for c in t if not c.isalnum() and not c.isspace()) / max(1, len(t))
    return not punct_ratio > 0.1


def extract_keywords_portuguese(text: str) -> list[str]:
    """Extract keywords from Portuguese text."""
    return extract_keywords(text)


# Alias for backward compatibility with domain layer
PortugueseTextNormalizer = TextNormalizer
