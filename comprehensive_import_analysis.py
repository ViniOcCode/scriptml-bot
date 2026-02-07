#!/usr/bin/env python3
"""Comprehensive Python import analyzer for the entire repository."""

import ast
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Set, Tuple, Optional
import re

class ImportAnalyzer(ast.NodeVisitor):
    """AST visitor to extract import information."""
    
    def __init__(self, filepath: str):
        self.filepath = filepath
        self.imports = []  # List of (lineno, module, names, is_relative)
        self.used_names = set()  # Names used in the code
        
    def visit_Import(self, node):
        for alias in node.names:
            name = alias.asname if alias.asname else alias.name
            self.imports.append({
                'line': node.lineno,
                'type': 'import',
                'module': alias.name,
                'name': name,
                'asname': alias.asname,
                'is_relative': False,
                'full_import': f"import {alias.name}" + (f" as {alias.asname}" if alias.asname else "")
            })
        self.generic_visit(node)
        
    def visit_ImportFrom(self, node):
        module = node.module or ''
        level = node.level
        is_relative = level > 0
        
        for alias in node.names:
            name = alias.asname if alias.asname else alias.name
            rel_prefix = '.' * level
            full_module = f"{rel_prefix}{module}" if module else rel_prefix
            
            self.imports.append({
                'line': node.lineno,
                'type': 'from',
                'module': module,
                'name': name,
                'asname': alias.asname,
                'is_relative': is_relative,
                'level': level,
                'imported_name': alias.name,
                'full_import': f"from {full_module} import {alias.name}" + (f" as {alias.asname}" if alias.asname else "")
            })
        self.generic_visit(node)
        
    def visit_Name(self, node):
        """Track all name references in the code."""
        self.used_names.add(node.id)
        self.generic_visit(node)
        
    def visit_Attribute(self, node):
        """Track attribute access like module.function."""
        # Get the root name
        current = node
        while isinstance(current, ast.Attribute):
            current = current.value
        if isinstance(current, ast.Name):
            self.used_names.add(current.id)
        self.generic_visit(node)

def analyze_file(filepath: str) -> Optional[Dict]:
    """Analyze a single Python file."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
            
        tree = ast.parse(content, filename=filepath)
        analyzer = ImportAnalyzer(filepath)
        analyzer.visit(tree)
        
        return {
            'filepath': filepath,
            'imports': analyzer.imports,
            'used_names': analyzer.used_names,
            'content': content
        }
    except Exception as e:
        print(f"Error analyzing {filepath}: {e}", file=sys.stderr)
        return None

def find_circular_dependencies(all_files: Dict[str, Dict]) -> List[Tuple]:
    """Find circular dependencies between modules."""
    # Build dependency graph
    graph = defaultdict(set)
    
    for filepath, data in all_files.items():
        module_name = filepath_to_module(filepath)
        
        for imp in data['imports']:
            imported_module = resolve_import(filepath, imp)
            if imported_module:
                graph[module_name].add(imported_module)
    
    # Find cycles using DFS
    cycles = []
    visited = set()
    rec_stack = []
    
    def dfs(node, path):
        if node in rec_stack:
            # Found a cycle
            cycle_start = rec_stack.index(node)
            cycle = rec_stack[cycle_start:] + [node]
            cycles.append(cycle)
            return
            
        if node in visited:
            return
            
        visited.add(node)
        rec_stack.append(node)
        
        for neighbor in graph.get(node, []):
            dfs(neighbor, path + [node])
            
        rec_stack.pop()
    
    for node in graph:
        if node not in visited:
            dfs(node, [])
    
    return cycles

def filepath_to_module(filepath: str) -> str:
    """Convert filepath to Python module name."""
    base = '/home/vini/scriptml'
    rel_path = os.path.relpath(filepath, base)
    
    # Remove .py extension
    if rel_path.endswith('.py'):
        rel_path = rel_path[:-3]
    
    # Convert / to .
    module = rel_path.replace('/', '.')
    
    # Handle __init__.py
    if module.endswith('.__init__'):
        module = module[:-9]
    
    return module

def resolve_import(filepath: str, imp: Dict) -> Optional[str]:
    """Resolve an import to a module name."""
    if imp['is_relative']:
        # Resolve relative import
        current_module = filepath_to_module(filepath)
        parts = current_module.split('.')
        
        # Go up 'level' directories
        level = imp.get('level', 1)
        if level >= len(parts):
            return None
            
        base_parts = parts[:-level] if level > 0 else parts[:-1]
        
        if imp['module']:
            return '.'.join(base_parts + [imp['module']])
        else:
            return '.'.join(base_parts)
    else:
        return imp['module']

def check_unused_imports(data: Dict) -> List[Dict]:
    """Check for unused imports in a file."""
    unused = []
    
    for imp in data['imports']:
        name_to_check = imp['name']
        
        # Skip star imports
        if name_to_check == '*':
            continue
            
        # Check if the name is used
        if name_to_check not in data['used_names']:
            # Check if it might be re-exported via __all__
            if '__all__' in data['content']:
                continue
                
            unused.append(imp)
    
    return unused

def check_architecture_violations(all_files: Dict[str, Dict]) -> List[Dict]:
    """Check for Clean Architecture boundary violations."""
    violations = []
    
    # Define layers based on directory structure
    layers = {
        'domain': ['mercadolivre_upload/domain'],
        'application': ['mercadolivre_upload/application'],
        'infrastructure': ['mercadolivre_upload/infrastructure', 'mercadolivre_upload/api', 'mercadolivre_upload/adapters'],
        'interface': ['mercadolivre_upload/cli'],
    }
    
    # Rules: domain shouldn't import from application, infrastructure, or interface
    # application shouldn't import from infrastructure or interface
    
    for filepath, data in all_files.items():
        file_layer = get_layer(filepath, layers)
        
        if not file_layer:
            continue
            
        for imp in data['imports']:
            imported_module = resolve_import(filepath, imp)
            if not imported_module:
                continue
                
            # Convert module to potential filepath
            imported_layer = get_layer_from_module(imported_module, layers)
            
            if not imported_layer:
                continue
                
            # Check violations
            if file_layer == 'domain':
                if imported_layer in ['application', 'infrastructure', 'interface']:
                    violations.append({
                        'filepath': filepath,
                        'import': imp,
                        'file_layer': file_layer,
                        'imported_layer': imported_layer,
                        'message': f"Domain layer importing from {imported_layer} layer"
                    })
            elif file_layer == 'application':
                if imported_layer in ['infrastructure', 'interface']:
                    violations.append({
                        'filepath': filepath,
                        'import': imp,
                        'file_layer': file_layer,
                        'imported_layer': imported_layer,
                        'message': f"Application layer importing from {imported_layer} layer"
                    })
    
    return violations

def get_layer(filepath: str, layers: Dict) -> Optional[str]:
    """Determine which layer a file belongs to."""
    for layer_name, paths in layers.items():
        for path in paths:
            if path in filepath:
                return layer_name
    return None

def get_layer_from_module(module: str, layers: Dict) -> Optional[str]:
    """Determine layer from module name."""
    for layer_name, paths in layers.items():
        for path in paths:
            path_as_module = path.replace('/', '.')
            if module.startswith(path_as_module):
                return layer_name
    return None

def check_import_style_inconsistencies(all_files: Dict[str, Dict]) -> List[Dict]:
    """Find inconsistent import styles (relative vs absolute)."""
    # Track how each module is imported
    module_import_styles = defaultdict(lambda: {'relative': [], 'absolute': []})
    
    for filepath, data in all_files.items():
        for imp in data['imports']:
            module = imp['module']
            if not module:
                continue
                
            if imp['is_relative']:
                module_import_styles[module]['relative'].append({
                    'filepath': filepath,
                    'import': imp
                })
            else:
                module_import_styles[module]['absolute'].append({
                    'filepath': filepath,
                    'import': imp
                })
    
    # Find modules imported both ways
    inconsistencies = []
    for module, styles in module_import_styles.items():
        if styles['relative'] and styles['absolute']:
            inconsistencies.append({
                'module': module,
                'relative_imports': styles['relative'],
                'absolute_imports': styles['absolute']
            })
    
    return inconsistencies

def check_package_confusion() -> List[Dict]:
    """Check for confusion between auth/ and mercadolivre_upload/auth/."""
    confusion = []
    
    # Check if both packages exist
    auth_root = Path('/home/vini/scriptml/auth')
    auth_nested = Path('/home/vini/scriptml/mercadolivre_upload/auth')
    
    if auth_root.exists() and auth_nested.exists():
        # Find all files importing from either
        confusion.append({
            'type': 'duplicate_packages',
            'packages': ['auth/', 'mercadolivre_upload/auth/'],
            'message': 'Two separate auth packages exist - they should be consolidated'
        })
    
    return confusion

def main():
    """Main analysis function."""
    base_dir = '/home/vini/scriptml'
    
    # Find all Python files
    python_files = []
    for root, dirs, files in os.walk(base_dir):
        # Skip virtual environments and cache directories
        dirs[:] = [d for d in dirs if d not in ['.venv', '__pycache__', '.pytest_cache', '.mypy_cache', '.ruff_cache', 'htmlcov', 'mercado_livre_bulk_upload.egg-info']]
        
        for file in files:
            if file.endswith('.py'):
                python_files.append(os.path.join(root, file))
    
    print(f"Analyzing {len(python_files)} Python files...")
    
    # Analyze all files
    all_files = {}
    for filepath in python_files:
        data = analyze_file(filepath)
        if data:
            all_files[filepath] = data
    
    print(f"Successfully analyzed {len(all_files)} files\n")
    
    # 1. Check for unused imports
    print("=" * 80)
    print("1. UNUSED IMPORTS")
    print("=" * 80)
    
    unused_count = 0
    for filepath, data in all_files.items():
        unused = check_unused_imports(data)
        if unused:
            for imp in unused:
                print(f"\nFile: {filepath}")
                print(f"Line: {imp['line']}")
                print(f"Import: {imp['full_import']}")
                print(f"Problem: Unused import")
                unused_count += 1
    
    print(f"\nTotal unused imports: {unused_count}")
    
    # 2. Check for circular dependencies
    print("\n" + "=" * 80)
    print("2. CIRCULAR DEPENDENCIES")
    print("=" * 80)
    
    cycles = find_circular_dependencies(all_files)
    if cycles:
        for i, cycle in enumerate(cycles, 1):
            print(f"\nCycle {i}: {' -> '.join(cycle)}")
    else:
        print("\nNo circular dependencies found!")
    
    # 3. Check architecture violations
    print("\n" + "=" * 80)
    print("3. CLEAN ARCHITECTURE VIOLATIONS")
    print("=" * 80)
    
    violations = check_architecture_violations(all_files)
    if violations:
        for v in violations:
            print(f"\nFile: {v['filepath']}")
            print(f"Line: {v['import']['line']}")
            print(f"Import: {v['import']['full_import']}")
            print(f"Problem: {v['message']}")
    else:
        print("\nNo architecture violations found!")
    
    print(f"\nTotal violations: {len(violations)}")
    
    # 4. Check import style inconsistencies
    print("\n" + "=" * 80)
    print("4. IMPORT STYLE INCONSISTENCIES")
    print("=" * 80)
    
    inconsistencies = check_import_style_inconsistencies(all_files)
    if inconsistencies:
        for inc in inconsistencies:
            print(f"\nModule: {inc['module']}")
            print(f"  Imported as relative in:")
            for imp in inc['relative_imports'][:3]:  # Show first 3
                print(f"    - {imp['filepath']}:{imp['import']['line']}")
            print(f"  Imported as absolute in:")
            for imp in inc['absolute_imports'][:3]:  # Show first 3
                print(f"    - {imp['filepath']}:{imp['import']['line']}")
    else:
        print("\nNo import style inconsistencies found!")
    
    # 5. Check package confusion
    print("\n" + "=" * 80)
    print("5. PACKAGE CONFUSION (auth/ vs mercadolivre_upload/auth/)")
    print("=" * 80)
    
    confusion = check_package_confusion()
    if confusion:
        for c in confusion:
            print(f"\nType: {c['type']}")
            print(f"Packages: {', '.join(c['packages'])}")
            print(f"Message: {c['message']}")
    
    # Now find specific imports
    print("\n\nDetailed auth/ import analysis:")
    for filepath, data in all_files.items():
        for imp in data['imports']:
            module = imp.get('module', '')
            if module and ('auth' in module.split('.')[0] or module.startswith('auth')):
                rel_path = os.path.relpath(filepath, base_dir)
                print(f"\n{rel_path}:{imp['line']}")
                print(f"  Import: {imp['full_import']}")
                print(f"  Module: {module}")
                print(f"  Relative: {imp['is_relative']}")

if __name__ == '__main__':
    main()
