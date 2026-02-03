"""Parser exceptions."""


class ParserError(Exception):
    """Base exception for parser errors."""
    pass


class ValidationError(ParserError):
    """Raised when data validation fails."""

    def __init__(self, message, errors=None):
        super().__init__(message)
        self.errors = errors or []


class MissingColumnError(ParserError):
    """Raised when required columns are missing from the Excel file."""

    def __init__(self, missing_columns):
        message = f"Missing required columns: {', '.join(missing_columns)}"
        super().__init__(message)
        self.missing_columns = missing_columns
