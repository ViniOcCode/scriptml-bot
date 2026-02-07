#!/usr/bin/env python3
"""Check for circular dependencies."""

import ast
import os
from collections import defaultdict

def get_module_name(filepath, base_dir):
    """Convert filepath to module name."""
    rel_path = os.path.relpath(filepath, base_dir)
    if rel_path.endswith('.py'):
        rel_path = rel_path[:-3]
    module = rel_path.replace('/', '.')
    if module.endswith('.__init__'):
        module = module[:-9]
    return module

def get_imports(filepath):
    """Extract all imports from a file."""
    imports = []
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        tree = ast.parse(content)
        
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.append(node.module)
    except:
        pass
    
    return imports

base_dir = '/home/vini/scriptml'

# Build dependency graph
graph = defaultdict(set)
files = []

for root, dirs, files_list in os.walk(base_dir):
    dirs[:] = [d for d in dirs if d not in ['.venv', '__pycache__', '.pytest_cache', '.mypy_cache', '.ruff_cache', 'htmlcov', 'mercado_livre_bulk_upload.egg-info']]
    
    for file in files_list:
        if file.endswith('.py'):
            filepath = os.path.join(root, file)
            module = get_module_name(filepath, base_dir)
            imports = get_imports(filepath)
            
            for imp in imports:
                # Filter for project imports only
                if imp.startswith('mercadolivre_upload') or imp.startswith('auth') or imp.startswith('config') or imp.startswith('cache'):
                    graph[module].add(imp)

# Find cycles using DFS
def find_cycles(graph):
    """Find all cycles in the graph."""
    cycles = []
    visited = set()
    rec_stack = []
    
    def dfs(node):
        if node in rec_stack:
            # Found a cycle
            idx = rec_stack.index(node)
            cycle = rec_stack[idx:] + [node]
            # Only report if it's a meaningful cycle (length > 1)
            if len(set(cycle)) > 1:
                cycles.append(cycle)
            return
        
        if node in visited:
            return
        
        visited.add(node)
        rec_stack.append(node)
        
        for neighbor in graph.get(node, []):
            dfs(neighbor)
        
        rec_stack.pop()
    
    for node in graph:
        dfs(node)
    
    return cycles

cycles = find_cycles(graph)

if cycles:
    print("CIRCULAR DEPENDENCIES FOUND:")
    print("=" * 80)
    for i, cycle in enumerate(cycles[:10], 1):  # Show first 10
        print(f"\nCycle {i}:")
        print("  " + " -> ".join(cycle))
else:
    print("No circular dependencies found!")
    print()
    print("The import structure is clean - no modules depend on each other cyclically.")
