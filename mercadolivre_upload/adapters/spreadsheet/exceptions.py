"""Parser exceptions."""


class ParserError(Exception):
    """Base exception for parser errors."""

    pass


class ValidationError(ParserError):
    """Raised when data validation fails."""

    def __init__(self, message, errors=None):  # type: ignore[no-untyped-def]
        """Initialize with message and optional error list."""
        super().__init__(message)
        self.errors = errors or []


class MissingColumnError(ParserError):
    """Raised when required columns are missing from the Excel file."""

    def __init__(self, missing_columns):  # type: ignore[no-untyped-def]
        """Initialize with list of missing column names."""
        message = f"Missing required columns: {', '.join(missing_columns)}"
        super().__init__(message)
        self.missing_columns = missing_columns
