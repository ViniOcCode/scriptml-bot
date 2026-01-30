"""Portuguese text normalization utilities.

Provides text normalization specifically designed for Portuguese language
handling in Excel column mapping scenarios.
"""

import unicodedata
from difflib import SequenceMatcher


class PortugueseTextNormalizer:
    """Normalizes Portuguese text for comparison and matching.
    
    Handles:
    - Accent removal (é -> e, ã -> a, etc.)
    - Case normalization
    - Whitespace normalization
    - Special character handling
    """
    
    # Common Portuguese accent mappings
    ACCENT_MAP = {
        'á': 'a', 'à': 'a', 'ã': 'a', 'â': 'a', 'ä': 'a',
        'é': 'e', 'è': 'e', 'ê': 'e', 'ë': 'e',
        'í': 'i', 'ì': 'i', 'î': 'i', 'ï': 'i',
        'ó': 'o', 'ò': 'o', 'õ': 'o', 'ô': 'o', 'ö': 'o',
        'ú': 'u', 'ù': 'u', 'û': 'u', 'ü': 'u',
        'ç': 'c',
        'ñ': 'n',
        'ý': 'y', 'ÿ': 'y',
    }
    
    @staticmethod
    def normalize(text: str) -> str:
        """Normalize Portuguese text for comparison.
        
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
            >>> PortugueseTextNormalizer.normalize("Título do Livro")
            'titulo do livro'
        """
        if not text:
            return ""
            
        # Convert to lowercase
        text = text.lower().strip()
        
        # Remove accents using NFKD decomposition
        text = unicodedata.normalize('NFKD', text)
        text = ''.join(c for c in text if not unicodedata.combining(c))
        
        # Remove special characters, keep only alphanumeric and spaces
        text = ''.join(c for c in text if c.isalnum() or c.isspace())
        
        # Normalize whitespace (multiple spaces -> single space)
        text = ' '.join(text.split())
        
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
        text = ''.join(c for c in text if c.isalnum() or c.isspace() or unicodedata.category(c).startswith('M'))
        text = ' '.join(text.split())
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
            >>> PortugueseTextNormalizer.similarity("Título", "titulo")
            1.0
            >>> PortugueseTextNormalizer.similarity("Autor", "Escritor")
            0.0
        """
        norm_a = PortugueseTextNormalizer.normalize(a)
        norm_b = PortugueseTextNormalizer.normalize(b)
        
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
        norm_a = PortugueseTextNormalizer.normalize(a)
        norm_b = PortugueseTextNormalizer.normalize(b)
        
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
        normalized = PortugueseTextNormalizer.normalize(text)
        return normalized.split()
    
    @staticmethod
    def acronym_match(a: str, b: str) -> float:
        """Check if strings match by acronym.
        
        Example:
            >>> PortugueseTextNormalizer.acronym_match("NCM", "Número Código Mercadoria")
            1.0
        """
        norm_a = PortugueseTextNormalizer.normalize(a)
        norm_b = PortugueseTextNormalizer.normalize(b)
        
        # Get first letters of each word in b
        words_b = norm_b.split()
        acronym_b = ''.join(word[0] for word in words_b if word)
        
        if norm_a == acronym_b:
            return 1.0
        
        # Check if a is contained in acronym
        if norm_a in acronym_b or acronym_b in norm_a:
            return 0.8
        
        return 0.0


def normalize_text(text: str) -> str:
    """Convenience function for quick normalization.
    
    Args:
        text: Text to normalize
        
    Returns:
        Normalized text
    """
    return PortugueseTextNormalizer.normalize(text)


def text_similarity(a: str, b: str) -> float:
    """Convenience function for quick similarity calculation.
    
    Args:
        a: First string
        b: Second string
        
    Returns:
        Similarity ratio
    """
    return PortugueseTextNormalizer.similarity(a, b)
