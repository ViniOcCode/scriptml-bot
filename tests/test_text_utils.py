"""
Tests for text_utils.py - 100% coverage.
"""

from mercadolivre_upload.shared.utils.text_utils import (
    capitalize_words,
    clean_html,
    count_words,
    extract_keywords,
    format_price,
    is_valid_title,
    normalize_text,
    remove_extra_whitespace,
    sanitize_filename,
    slugify,
    truncate_text,
)


class TestNormalizeText:
    """Test cases for normalize_text function."""

    def test_normalize_with_accents(self):
        """Test removing accents from text."""
        assert normalize_text("café") == "cafe"
        assert normalize_text("naïve") == "naive"
        assert normalize_text("São Paulo") == "Sao Paulo"

    def test_normalize_without_accents(self):
        """Test text without accents remains unchanged."""
        assert normalize_text("hello") == "hello"
        assert normalize_text("world") == "world"

    def test_normalize_non_string_input(self):
        """Test with non-string input."""
        assert normalize_text(123) == "123"
        assert normalize_text(None) == "None"


class TestSlugify:
    """Test cases for slugify function."""

    def test_slugify_basic(self):
        """Test basic slugify."""
        assert slugify("Hello World") == "hello-world"

    def test_slugify_with_accents(self):
        """Test slugify removes accents."""
        assert slugify("São Paulo") == "sao-paulo"

    def test_slugify_with_special_chars(self):
        """Test slugify removes special characters."""
        assert slugify("Hello @#$ World!!!") == "hello-world"

    def test_slugify_multiple_spaces(self):
        """Test slugify with multiple spaces."""
        assert slugify("Hello    World") == "hello-world"

    def test_slugify_leading_trailing_dashes(self):
        """Test slugify strips leading/trailing dashes."""
        assert slugify("!Hello World!") == "hello-world"

    def test_slugify_underscores(self):
        """Test slugify converts underscores."""
        assert slugify("hello_world") == "hello-world"

    def test_slugify_multiple_hyphens(self):
        """Test slugify collapses multiple hyphens."""
        assert slugify("hello---world") == "hello-world"

    def test_slugify_empty(self):
        """Test slugify with empty string."""
        assert slugify("") == ""

    def test_slugify_only_special_chars(self):
        """Test slugify with only special characters."""
        assert slugify("@#$%") == ""


class TestTruncateText:
    """Test cases for truncate_text function."""

    def test_truncate_no_need(self):
        """Test text that doesn't need truncation."""
        assert truncate_text("hello", 10) == "hello"

    def test_truncate_needed(self):
        """Test text that needs truncation."""
        assert truncate_text("hello world", 8) == "hello..."

    def test_truncate_custom_suffix(self):
        """Test with custom suffix."""
        assert truncate_text("hello world", 8, suffix="..") == "hello .."

    def test_truncate_exact_length(self):
        """Test text at exact length."""
        assert truncate_text("hello", 5) == "hello"

    def test_truncate_suffix_longer_than_max(self):
        """Test when suffix is longer than max_length."""
        assert truncate_text("hi", 2, suffix="...") == "hi"

    def test_truncate_zero_truncate_at(self):
        """Test when truncate_at becomes 0."""
        assert truncate_text("hello", 2, suffix="...") == "..."

    def test_truncate_non_string(self):
        """Test with non-string input."""
        assert truncate_text(12345, 3) == "..."


class TestCleanHtml:
    """Test cases for clean_html function."""

    def test_clean_simple_tags(self):
        """Test removing simple HTML tags."""
        assert clean_html("<p>Hello</p>") == "Hello"

    def test_clean_multiple_tags(self):
        """Test removing multiple tags."""
        assert clean_html("<p><b>Hello</b> <i>World</i></p>") == "Hello World"

    def test_clean_script_content(self):
        """Test removing script content."""
        assert clean_html("<script>alert('test')</script>Hello") == "Hello"

    def test_clean_style_content(self):
        """Test removing style content."""
        assert clean_html("<style>body{color:red}</style>Hello") == "Hello"

    def test_clean_html_entities(self):
        """Test decoding HTML entities."""
        assert clean_html("&lt;div&gt;&amp;&quot;text&quot;&nbsp;&#39;&#39;") == "<div>&\"text\" ''"

    def test_clean_no_html(self):
        """Test text without HTML."""
        assert clean_html("Hello World") == "Hello World"

    def test_clean_non_string(self):
        """Test with non-string input."""
        assert clean_html(123) == "123"

    def test_clean_empty(self):
        """Test with empty string."""
        assert clean_html("") == ""


class TestCapitalizeWords:
    """Test cases for capitalize_words function."""

    def test_capitalize_words_basic(self):
        """Test basic capitalization."""
        assert capitalize_words("hello world") == "Hello World"

    def test_capitalize_words_already_capitalized(self):
        """Test with already capitalized words."""
        assert capitalize_words("Hello World") == "Hello World"

    def test_capitalize_words_mixed_case(self):
        """Test with mixed case."""
        assert capitalize_words("hELLO wORLD") == "Hello World"

    def test_capitalize_words_non_string(self):
        """Test with non-string input."""
        assert capitalize_words(123) == "123"


class TestRemoveExtraWhitespace:
    """Test cases for remove_extra_whitespace function."""

    def test_remove_multiple_spaces(self):
        """Test removing multiple spaces."""
        assert remove_extra_whitespace("hello    world") == "hello world"

    def test_remove_newlines(self):
        """Test removing newlines."""
        assert remove_extra_whitespace("hello\n\n\nworld") == "hello world"

    def test_remove_tabs(self):
        """Test removing tabs."""
        assert remove_extra_whitespace("hello\t\tworld") == "hello world"

    def test_strip_edges(self):
        """Test stripping whitespace from edges."""
        assert remove_extra_whitespace("  hello world  ") == "hello world"

    def test_non_string(self):
        """Test with non-string input."""
        assert remove_extra_whitespace(123) == "123"


class TestExtractKeywords:
    """Test cases for extract_keywords function."""

    def test_extract_basic(self):
        """Test basic keyword extraction."""
        result = extract_keywords("the quick brown fox")
        assert "quick" in result
        assert "brown" in result
        assert "fox" in result
        assert "the" not in result  # stop word

    def test_extract_no_duplicates(self):
        """Test that duplicates are removed."""
        result = extract_keywords("quick quick brown brown")
        assert result == ["quick", "brown"]

    def test_extract_min_length(self):
        """Test with custom min_length."""
        result = extract_keywords("a bb ccc dddd", min_length=3)
        assert "ccc" in result
        assert "dddd" in result
        assert "a" not in result
        assert "bb" not in result

    def test_extract_removes_accents(self):
        """Test that accents are removed."""
        result = extract_keywords("café especial")
        assert "cafe" in result

    def test_extract_non_string(self):
        """Test with non-string input."""
        result = extract_keywords(12345)
        assert "12345" in result

    def test_extract_portuguese_stop_words(self):
        """Test Portuguese stop words are removed."""
        result = extract_keywords("livro de suspense e aventura do autor")
        assert "de" not in result
        assert "e" not in result
        assert "o" not in result
        assert "do" not in result
        assert "da" not in result


class TestFormatPrice:
    """Test cases for format_price function."""

    def test_format_price_basic(self):
        """Test basic price formatting."""
        assert format_price(123.45) == "R$ 123,45"

    def test_format_price_thousands(self):
        """Test price with thousands."""
        assert format_price(1234.56) == "R$ 1.234,56"

    def test_format_price_zero(self):
        """Test zero price."""
        assert format_price(0) == "R$ 0,00"

    def test_format_price_none(self):
        """Test None price."""
        assert format_price(None) == "R$ 0,00"

    def test_format_price_invalid(self):
        """Test invalid price."""
        assert format_price("invalid") == "R$ 0,00"

    def test_format_price_custom_currency(self):
        """Test with custom currency."""
        assert format_price(99.99, currency="$") == "$ 99,99"

    def test_format_price_integer(self):
        """Test with integer."""
        assert format_price(100) == "R$ 100,00"


class TestSanitizeFilename:
    """Test cases for sanitize_filename function."""

    def test_sanitize_removes_invalid_chars(self):
        """Test removing invalid characters."""
        assert sanitize_filename("file<>:name.txt") == "filename.txt"

    def test_sanitize_removes_control_chars(self):
        """Test removing control characters."""
        assert sanitize_filename("file\x00\x1fname.txt") == "filename.txt"

    def test_sanitize_limits_length(self):
        """Test limiting filename length."""
        long_name = "a" * 300 + ".txt"
        result = sanitize_filename(long_name)
        assert len(result) <= 255

    def test_sanitize_limits_length_no_extension(self):
        """Test limiting filename length without extension."""
        long_name = "a" * 300
        result = sanitize_filename(long_name)
        assert len(result) <= 255

    def test_sanitize_limits_length_dot_at_end(self):
        """Test limiting filename with dot at position 255."""
        long_name = "a" * 254 + "."
        result = sanitize_filename(long_name)
        assert len(result) <= 255

    def test_sanitize_limits_length_only_dots(self):
        """Test limiting filename with only dots."""
        long_name = "." * 300
        result = sanitize_filename(long_name)
        assert result == "unnamed"

    def test_sanitize_empty_result(self):
        """Test when result would be empty - @#$% are not removed, so not empty."""
        # @#$% are not in the invalid chars list, so they remain
        assert sanitize_filename("@#$%") == "@#$%"

    def test_sanitize_only_dots(self):
        """Test with only dots."""
        assert sanitize_filename("...") == "unnamed"

    def test_sanitize_non_string(self):
        """Test with non-string input."""
        assert sanitize_filename(123) == "123"

    def test_sanitize_preserves_valid(self):
        """Test that valid filenames are preserved."""
        assert sanitize_filename("valid_name.txt") == "valid_name.txt"


class TestCountWords:
    """Test cases for count_words function."""

    def test_count_basic(self):
        """Test basic word count."""
        assert count_words("hello world") == 2

    def test_count_multiple_spaces(self):
        """Test with multiple spaces."""
        assert count_words("hello    world") == 2

    def test_count_empty(self):
        """Test empty string."""
        assert count_words("") == 0

    def test_count_non_string(self):
        """Test with non-string input."""
        assert count_words(123) == 1


class TestIsValidTitle:
    """Test cases for is_valid_title function."""

    def test_valid_title(self):
        """Test valid title."""
        assert is_valid_title("Smartphone Samsung Galaxy") is True

    def test_title_too_short(self):
        """Test title below min_length."""
        assert is_valid_title("Short") is False  # Less than 10 chars

    def test_title_too_long(self):
        """Test title above max_length."""
        long_title = "a" * 61
        assert is_valid_title(long_title) is False

    def test_title_excessive_caps(self):
        """Test title with too many caps."""
        assert is_valid_title("SUPER PROMOÇÃO IMPERDÍVEL HOJE") is False

    def test_title_excessive_punctuation(self):
        """Test title with too much punctuation."""
        assert is_valid_title("Super!!! Oferta@#$% Imperdivel!!!!") is False

    def test_valid_title_boundary(self):
        """Test valid title at exact boundaries."""
        assert is_valid_title("a" * 10) is True  # Exactly min_length
        assert is_valid_title("a" * 60) is True  # Exactly max_length

    def test_non_string_title(self):
        """Test with non-string input."""
        assert is_valid_title(123) is False

    def test_custom_lengths(self):
        """Test with custom length parameters."""
        assert is_valid_title("hi", min_length=2, max_length=10) is True
        assert is_valid_title("hello world", min_length=2, max_length=10) is False
