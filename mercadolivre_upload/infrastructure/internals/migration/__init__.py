"""Forward-compatible shims for migration internals."""

from mercadolivre_upload.infrastructure.internals.migration.schema_primitives import (
    Field,
    FieldType,
    SchemaVersion,
    Version,
)

from .helpers import (
    calculate_schema_match_score,
    clean_data_fields,
    ensure_dataframe,
    parse_version_parts,
    resolve_sheet_name,
)

__all__ = [
    "Field",
    "FieldType",
    "SchemaVersion",
    "Version",
    "calculate_schema_match_score",
    "clean_data_fields",
    "ensure_dataframe",
    "parse_version_parts",
    "resolve_sheet_name",
]
