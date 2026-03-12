"""Architecture contract tests for phase-1 boundary hardening."""

from __future__ import annotations

import ast
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "mercadolivre_upload"
PORTS_FILE = PACKAGE_ROOT / "application" / "ports.py"
FLOW_FILE = PACKAGE_ROOT / "application" / "publish" / "internals" / "flow.py"
PAYLOAD_FILE = PACKAGE_ROOT / "application" / "publish" / "internals" / "payload.py"


def _class_method_names(path: Path, class_name: str) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return {method.name for method in node.body if isinstance(method, ast.FunctionDef)}
    raise AssertionError(f"Class {class_name} not found in {path}")


def _application_api_imports() -> list[str]:
    application_root = PACKAGE_ROOT / "application"
    imports: set[str] = set()
    for path in application_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module.startswith("mercadolivre_upload.api"):
                    imports.add(str(path.relative_to(PACKAGE_ROOT)))
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("mercadolivre_upload.api"):
                        imports.add(str(path.relative_to(PACKAGE_ROOT)))
    return sorted(imports)


def test_item_publisher_port_covers_publish_flow_surface() -> None:
    methods = _class_method_names(PORTS_FILE, "ItemPublisherPort")
    required = {
        "get_users_me",
        "validate_item",
        "validate_user_product_item",
        "create_item",
        "create_user_product_item",
        "get_available_listing_types",
        "get_site_listing_types",
        "get_category_sale_terms",
        "create_item_description",
    }
    missing = sorted(required - methods)
    assert not missing, f"ItemPublisherPort is missing methods: {missing}"


def test_publish_flow_avoids_dynamic_publisher_getattr_calls() -> None:
    flow_source = FLOW_FILE.read_text(encoding="utf-8")
    payload_source = PAYLOAD_FILE.read_text(encoding="utf-8")
    assert 'getattr(use_case.publisher, "validate_user_product_item"' not in flow_source
    assert 'getattr(use_case.publisher, "create_user_product_item"' not in flow_source
    assert 'getattr(use_case.publisher, "get_site_listing_types"' not in payload_source


def test_application_api_import_boundary_has_single_documented_exception() -> None:
    assert _application_api_imports() == ["application/publish_product.py"]
