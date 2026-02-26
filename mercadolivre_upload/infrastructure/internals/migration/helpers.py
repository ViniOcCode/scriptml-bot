"""Helper functions for migration internals."""

from __future__ import annotations

import contextlib
import re
from pathlib import Path
from typing import Any


def parse_version_parts(version_str: str) -> tuple[int, ...]:
    """Parse version string into numeric parts for comparison."""
    cleaned_version = version_str.lstrip("vV")
    parts = re.split(r"[.-]", cleaned_version)

    result = []
    for part in parts:
        with contextlib.suppress(ValueError):
            result.append(int(part))

    return tuple(result) if result else (0,)


def clean_data_fields(data: dict[str, Any]) -> set[str]:
    """Remove internal metadata keys from field set."""
    return {field_name for field_name in data if not field_name.startswith("_")}


def calculate_schema_match_score(
    data_fields: set[str],
    schema_fields: set[str],
    required_fields: set[str],
) -> float:
    """Calculate how closely input fields match a schema."""
    common_fields = data_fields & schema_fields
    extra_fields = data_fields - schema_fields
    missing_fields = schema_fields - data_fields

    coverage = len(common_fields) / len(schema_fields) if schema_fields else 0
    required_missing = len(missing_fields & required_fields)

    extra_penalty = min(len(extra_fields) * 0.05, 0.3)
    missing_penalty = required_missing * 0.3

    score = coverage - extra_penalty - missing_penalty

    if data_fields:
        field_match_ratio = len(common_fields) / len(data_fields)
        score += field_match_ratio * 0.1

    return score


def resolve_sheet_name(file_path: Path, pandas_module: Any, sheet_name: str | None) -> str:
    """Return requested sheet name or the workbook first sheet."""
    if sheet_name is not None:
        return sheet_name

    excel_file = pandas_module.ExcelFile(file_path)
    return excel_file.sheet_names[0] if excel_file.sheet_names else "Sheet1"


def ensure_dataframe(sheet_data: Any) -> Any:
    """Normalize read_excel return value to a DataFrame."""
    if isinstance(sheet_data, dict):
        return list(sheet_data.values())[0]
    return sheet_data
