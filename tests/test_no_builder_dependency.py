"""Boundary test: publisher package must not import builder package."""

from __future__ import annotations

import ast
from pathlib import Path


def test_publisher_has_no_builder_imports() -> None:
    root = Path(__file__).resolve().parents[1] / "mercadolivre_upload"
    violations: list[str] = []
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("ml_listing_builder"):
                        violations.append(f"{path.relative_to(root)} -> {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module.startswith("ml_listing_builder"):
                    violations.append(f"{path.relative_to(root)} -> {module}")
    assert not violations, "Publisher imports builder package:\n" + "\n".join(sorted(violations))

