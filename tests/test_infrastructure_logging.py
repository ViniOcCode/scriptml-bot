"""Tests for infrastructure logging formatters."""

from __future__ import annotations

import logging

from mercadolivre_upload.infrastructure.logging import ColoredFormatter


def _build_record(level: int = logging.WARNING, message: str = "warn") -> logging.LogRecord:
    return logging.LogRecord(
        name="mercadolivre_upload.tests",
        level=level,
        pathname=__file__,
        lineno=1,
        msg=message,
        args=(),
        exc_info=None,
    )


def test_colored_formatter_does_not_mutate_shared_log_record() -> None:
    formatter = ColoredFormatter("%(levelname)s: %(message)s", use_colors=True)
    formatter.use_colors = True
    record = _build_record()

    _ = formatter.format(record)

    assert record.levelname == "WARNING"


def test_colored_formatter_output_does_not_leak_into_plain_formatter() -> None:
    colored = ColoredFormatter("%(levelname)s: %(message)s", use_colors=True)
    colored.use_colors = True
    plain = logging.Formatter("%(levelname)s: %(message)s")
    record = _build_record(logging.ERROR, "failure")

    colored_output = colored.format(record)
    plain_output = plain.format(record)

    assert "\033[" in colored_output
    assert plain_output == "ERROR: failure"
