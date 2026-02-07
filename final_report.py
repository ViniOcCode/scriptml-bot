#!/usr/bin/env python3
"""Generate final comprehensive import analysis report."""

import ast
import os
from collections import defaultdict
from pathlib import Path

class Issue:
    def __init__(self, file, line, import_stmt, problem, impact, suggestion):
        self.file = file
        self.line = line
        self.import_stmt = import_stmt
        self.problem = problem
        self.impact = impact
        self.suggestion = suggestion

issues = []

def get_import_context(filepath, lineno):
    """Check if import is at module level or inside a function."""
    try:
        with open(filepath, 'r') as f:
            content = f.read()
        tree = ast.parse(content)
        
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                if node.lineno == lineno:
                    # Check if parent is module
                    for parent_node in ast.walk(tree):
                        if isinstance(parent_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            if any(child for child in ast.walk(parent_node) if hasattr(child, 'lineno') and child.lineno == lineno):
                                return 'function'
                    return 'module'
    except:
        pass
    return 'module'

def analyze_file(filepath):
    """Analyze a single file."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
            
        tree = ast.parse(content, filename=filepath)
        
        # Track imports at module level only
        module_imports = defaultdict(list)
        import_details = {}
        used_names = set()
        
        # Check if file has __all__ (re-exports)
        has_all = '__all__' in content
        
        # First pass: collect imports
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                # Check if at module level
                is_module_level = True
                for parent in ast.walk(tree):
                    if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        if any(child for child in ast.walk(parent) if child is node):
                            is_module_level = False
                            break
                
                for alias in node.names:
                    name = alias.asname if alias.asname else alias.name
                    key = f"import {alias.name}"
                    full_import = f"import {alias.name}" + (f" as {alias.asname}" if alias.asname else "")
                    
                    if is_module_level:
                        module_imports[key].append(node.lineno)
                    
                    import_details[node.lineno] = {
                        'type': 'import',
                        'name': name,
                        'module': alias.name,
                        'full': full_import,
                        'is_module_level': is_module_level
                    }
                    
            elif isinstance(node, ast.ImportFrom):
                # Check if at module level
                is_module_level = True
                for parent in ast.walk(tree):
                    if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        if any(child for child in ast.walk(parent) if child is node):
                            is_module_level = False
                            break
                
                module = node.module or ''
                level = '.' * node.level
                full_module = f"{level}{module}" if module else level
                
                for alias in node.names:
                    name = alias.asname if alias.asname else alias.name
                    key = f"from {level}{module} import {alias.name}"
                    full_import = f"from {full_module} import {alias.name}" + (f" as {alias.asname}" if alias.asname else "")
                    
                    if is_module_level:
                        module_imports[key].append(node.lineno)
                    
                    import_details[node.lineno] = {
                        'type': 'from',
                        'name': name,
                        'module': module,
                        'full': full_import,
                        'imported_name': alias.name,
                        'is_module_level': is_module_level
                    }
                    
            elif isinstance(node, ast.Name):
                used_names.add(node.id)
            elif isinstance(node, ast.Attribute):
                current = node
                while isinstance(current, ast.Attribute):
                    current = current.value
                if isinstance(current, ast.Name):
                    used_names.add(current.id)
        
        rel_path = os.path.relpath(filepath, '/home/vini/scriptml')
        
        # Check for duplicates (only at module level)
        for key, linenos in module_imports.items():
            if len(linenos) > 1:
                for i, lineno in enumerate(linenos):
                    if i > 0:  # First occurrence is ok
                        detail = import_details[lineno]
                        issues.append(Issue(
                            file=rel_path,
                            line=lineno,
                            import_stmt=detail['full'],
                            problem="duplicate",
                            impact=f"Already imported on line {linenos[0]}",
                            suggestion=f"Remove line {lineno}"
                        ))
        
        # Check for unused imports (only module level, not in __all__ files)
        if not has_all:
            for lineno, detail in import_details.items():
                if not detail.get('is_module_level', True):
                    continue
                    
                name = detail['name']
                
                # Skip star imports
                if name == '*':
                    continue
                
                # Skip __future__ imports (they affect behavior even if not "used")
                if detail.get('module') == '__future__':
                    continue
                
                # Skip imports with # noqa comments
                try:
                    with open(filepath, 'r') as f:
                        lines = f.readlines()
                        if lineno <= len(lines):
                            line_content = lines[lineno - 1]
                            if '# noqa' in line_content or '# type: ignore' in line_content:
                                continue
                except:
                    pass
                
                # Check if used
                if name not in used_names:
                    issues.append(Issue(
                        file=rel_path,
                        line=lineno,
                        import_stmt=detail['full'],
                        problem="unused",
                        impact="Code bloat, confusion",
                        suggestion=f"Remove line {lineno}"
                    ))
        
        # Check for auth package confusion
        for lineno, detail in import_details.items():
            module = detail.get('module', '')
            if module and (module.startswith('auth.') or module == 'auth'):
                # Check if this is in mercadolivre_upload but using top-level auth
                if 'mercadolivre_upload' in filepath and 'tests' not in filepath:
                    imported_name = detail.get('imported_name', '')
                    new_import = module.replace('auth', 'mercadolivre_upload.auth', 1)
                    issues.append(Issue(
                        file=rel_path,
                        line=lineno,
                        import_stmt=detail['full'],
                        problem="package confusion",
                        impact="Using root auth/ instead of mercadolivre_upload/auth/",
                        suggestion=f"Change to: from {new_import} import {imported_name}"
                    ))
        
        # Check for architecture violations
        if 'mercadolivre_upload/domain' in filepath:
            for lineno, detail in import_details.items():
                module = detail.get('module', '')
                if any(x in module for x in ['infrastructure', 'api', 'adapters', 'application', 'cli']):
                    issues.append(Issue(
                        file=rel_path,
                        line=lineno,
                        import_stmt=detail['full'],
                        problem="boundary violation",
                        impact="Domain importing from outer layers",
                        suggestion="Inject as dependency parameter"
                    ))
        
        if 'mercadolivre_upload/application' in filepath and 'ports' not in filepath:
            for lineno, detail in import_details.items():
                module = detail.get('module', '')
                # Check for direct infrastructure imports
                if ('mercadolivre_upload.adapters' in module or 
                    ('mercadolivre_upload.api' in module and 'cbt_extractor' in module)):
                    issues.append(Issue(
                        file=rel_path,
                        line=lineno,
                        import_stmt=detail['full'],
                        problem="boundary violation",
                        impact="Application importing infrastructure directly",
                        suggestion="Define port interface and inject via DI"
                    ))
                    
    except Exception as e:
        pass

# Scan all files
base_dir = '/home/vini/scriptml'
for root, dirs, files in os.walk(base_dir):
    dirs[:] = [d for d in dirs if d not in ['.venv', '__pycache__', '.pytest_cache', '.mypy_cache', '.ruff_cache', 'htmlcov', 'mercado_livre_bulk_upload.egg-info']]
    
    for file in files:
        if file.endswith('.py'):
            analyze_file(os.path.join(root, file))

# Sort issues by file and line
issues.sort(key=lambda x: (x.file, x.line))

# Print table
print("| File | Line | Import | Problem | Impact | Minimal Suggestion |")
print("|------|------|--------|---------|--------|--------------------|")

for issue in issues:
    file_short = issue.file
    if len(file_short) > 45:
        file_short = "..." + file_short[-42:]
    
    import_short = issue.import_stmt
    if len(import_short) > 50:
        import_short = import_short[:47] + "..."
    
    impact_short = issue.impact
    if len(impact_short) > 45:
        impact_short = impact_short[:42] + "..."
        
    suggestion_short = issue.suggestion
    if len(suggestion_short) > 50:
        suggestion_short = suggestion_short[:47] + "..."
    
    print(f"| {file_short} | {issue.line} | {import_short} | {issue.problem} | {impact_short} | {suggestion_short} |")

print(f"\n**Total issues found: {len(issues)}**")

# Summary by type
by_type = defaultdict(int)
for issue in issues:
    by_type[issue.problem] += 1

print("\n**Summary by type:**")
for problem_type, count in sorted(by_type.items(), key=lambda x: -x[1]):
    print(f"- {problem_type}: {count}")

# Check for the duplicate auth packages
auth_root = Path('/home/vini/scriptml/auth')
auth_nested = Path('/home/vini/scriptml/mercadolivre_upload/auth')

if auth_root.exists() and auth_nested.exists():
    print("\n**CRITICAL: Duplicate auth packages detected!**")
    print(f"- {auth_root} (2 files)")
    print(f"- {auth_nested} (5 files)")
    print("Recommendation: Consolidate into mercadolivre_upload/auth/ and update imports")
