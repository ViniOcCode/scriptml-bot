#!/usr/bin/env python3
"""Check for duplicate imports within same file."""

import ast
import os
from collections import defaultdict

def check_file_for_duplicates(filepath):
    """Check a single file for duplicate imports."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        tree = ast.parse(content, filename=filepath)
        
        imports = defaultdict(list)
        
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    key = f"import {alias.name}"
                    imports[key].append(node.lineno)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ''
                level = '.' * node.level
                for alias in node.names:
                    key = f"from {level}{module} import {alias.name}"
                    imports[key].append(node.lineno)
        
        # Find duplicates
        duplicates = {k: v for k, v in imports.items() if len(v) > 1}
        if duplicates:
            print(f"\n{filepath}:")
            for imp, lines in duplicates.items():
                print(f"  {imp}")
                print(f"    Lines: {lines}")
                
    except Exception as e:
        pass

# Find all Python files
base_dir = '/home/vini/scriptml'
for root, dirs, files in os.walk(base_dir):
    dirs[:] = [d for d in dirs if d not in ['.venv', '__pycache__', '.pytest_cache', '.mypy_cache', '.ruff_cache', 'htmlcov', 'mercado_livre_bulk_upload.egg-info']]
    
    for file in files:
        if file.endswith('.py'):
            check_file_for_duplicates(os.path.join(root, file))
