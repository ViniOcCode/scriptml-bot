"""Config boundary tests: publisher must not read builder config."""

from __future__ import annotations

from pathlib import Path

import pytest

from mercadolivre_upload.application.validators.seller_policy import load_seller_config


def test_publisher_code_does_not_reference_builder_config_files() -> None:
    root = Path(__file__).resolve().parents[1] / "mercadolivre_upload"
    forbidden_tokens = ("builder.yaml", "config/builder.yaml")
    violations: list[str] = []
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for token in forbidden_tokens:
            if token in text:
                violations.append(f"{path.relative_to(root)} contains {token!r}")
    assert not violations, "Publisher references builder config:\n" + "\n".join(sorted(violations))


def test_publisher_rejects_builder_owned_fields_in_config(tmp_path: Path) -> None:
    config_file = tmp_path / "publisher.yaml"
    config_file.write_text(
        "seller:\n"
        "  listing:\n"
        "    allowed_types: [gold_special]\n"
        "    default_type: gold_special\n"
        "  pricing:\n"
        "    min_price: 10\n"
        "    max_price: 100\n"
        "builder:\n"
        "  cache: true\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unsupported top-level fields"):
        load_seller_config(config_file)
