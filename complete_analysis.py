#!/usr/bin/env python3
"""Complete import analysis including test files."""

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

def analyze_file(filepath):
    """Analyze a single file."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
            lines = content.split('\n')
            
        tree = ast.parse(content, filename=filepath)
        
        # Track all imports
        all_imports = []
        import_by_line = {}
        used_names = set()
        
        # Check if file has __all__
        has_all = '__all__' in content
        
        # Collect imports
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.asname if alias.asname else alias.name
                    full_import = f"import {alias.name}" + (f" as {alias.asname}" if alias.asname else "")
                    
                    all_imports.append({
                        'line': node.lineno,
                        'type': 'import',
                        'name': name,
                        'module': alias.name,
                        'full': full_import,
                        'key': f"import:{alias.name}:{name}"
                    })
                    import_by_line[node.lineno] = all_imports[-1]
                    
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ''
                level = '.' * node.level
                full_module = f"{level}{module}" if module else level
                
                for alias in node.names:
                    name = alias.asname if alias.asname else alias.name
                    full_import = f"from {full_module} import {alias.name}" + (f" as {alias.asname}" if alias.asname else "")
                    
                    all_imports.append({
                        'line': node.lineno,
                        'type': 'from',
                        'name': name,
                        'module': module,
                        'full': full_import,
                        'imported_name': alias.name,
                        'key': f"from:{module}:{alias.name}:{name}"
                    })
                    import_by_line[node.lineno] = all_imports[-1]
                    
            elif isinstance(node, ast.Name):
                used_names.add(node.id)
            elif isinstance(node, ast.Attribute):
                current = node
                while isinstance(current, ast.Attribute):
                    current = current.value
                if isinstance(current, ast.Name):
                    used_names.add(current.id)
        
        rel_path = os.path.relpath(filepath, '/home/vini/scriptml')
        
        # Check for duplicates
        seen_keys = {}
        for imp in all_imports:
            if imp['key'] in seen_keys:
                first_line = seen_keys[imp['key']]
                issues.append(Issue(
                    file=rel_path,
                    line=imp['line'],
                    import_stmt=imp['full'],
                    problem="duplicate",
                    impact=f"Already imported on line {first_line}",
                    suggestion=f"Remove line {imp['line']}"
                ))
            else:
                seen_keys[imp['key']] = imp['line']
        
        # Check for unused imports
        if not has_all:
            for imp in all_imports:
                name = imp['name']
                
                # Skip star imports
                if name == '*':
                    continue
                
                # Skip __future__
                if imp.get('module') == '__future__':
                    continue
                
                # Check for # noqa
                if imp['line'] <= len(lines):
                    line_content = lines[imp['line'] - 1]
                    if '# noqa' in line_content or '# type: ignore' in line_content:
                        continue
                
                # Check if used
                if name not in used_names:
                    issues.append(Issue(
                        file=rel_path,
                        line=imp['line'],
                        import_stmt=imp['full'],
                        problem="unused",
                        impact="Code bloat, confusion",
                        suggestion=f"Remove line {imp['line']}"
                    ))
        
        # Check for auth package confusion (skip tests)
        if 'mercadolivre_upload' in filepath and 'tests' not in filepath:
            for imp in all_imports:
                module = imp.get('module', '')
                if module and (module.startswith('auth.') or module == 'auth'):
                    imported_name = imp.get('imported_name', '')
                    new_import = module.replace('auth', 'mercadolivre_upload.auth', 1)
                    issues.append(Issue(
                        file=rel_path,
                        line=imp['line'],
                        import_stmt=imp['full'],
                        problem="package confusion",
                        impact="Using root auth/ instead of mercadolivre_upload/auth/",
                        suggestion=f"from {new_import} import {imported_name}"
                    ))
        
        # Check architecture violations
        if 'mercadolivre_upload/domain' in filepath:
            for imp in all_imports:
                module = imp.get('module', '')
                if any(x in module for x in ['infrastructure', 'api', 'adapters', 'application', 'cli']):
                    issues.append(Issue(
                        file=rel_path,
                        line=imp['line'],
                        import_stmt=imp['full'],
                        problem="boundary violation",
                        impact="Domain importing from outer layers",
                        suggestion="Inject as dependency parameter"
                    ))
        
        if 'mercadolivre_upload/application' in filepath and 'ports' not in filepath:
            for imp in all_imports:
                module = imp.get('module', '')
                if 'mercadolivre_upload.adapters' in module or ('mercadolivre_upload.api' in module and 'cbt_extractor' in module):
                    issues.append(Issue(
                        file=rel_path,
                        line=imp['line'],
                        import_stmt=imp['full'],
                        problem="boundary violation",
                        impact="Application importing infrastructure directly",
                        suggestion="Define port interface and inject"
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

# Sort issues
issues.sort(key=lambda x: (x.problem, x.file, x.line))

# Group by problem type
by_problem = defaultdict(list)
for issue in issues:
    by_problem[issue.problem].append(issue)

# Print report
print("=" * 100)
print("COMPREHENSIVE PYTHON IMPORT ANALYSIS")
print("=" * 100)
print()

for problem_type in ['unused', 'duplicate', 'package confusion', 'boundary violation', 'circular']:
    if problem_type in by_problem:
        print(f"\n{problem_type.upper()}")
        print("-" * 100)
        print("| File | Line | Import | Problem | Impact | Minimal Suggestion |")
        print("|------|------|--------|---------|--------|--------------------|")
        
        for issue in by_problem[problem_type]:
            file_short = issue.file
            if len(file_short) > 42:
                file_short = "..." + file_short[-39:]
            
            import_short = issue.import_stmt
            if len(import_short) > 45:
                import_short = import_short[:42] + "..."
            
            impact_short = issue.impact
            if len(impact_short) > 40:
                impact_short = impact_short[:37] + "..."
                
            suggestion_short = issue.suggestion
            if len(suggestion_short) > 45:
                suggestion_short = suggestion_short[:42] + "..."
            
            print(f"| {file_short} | {issue.line} | {import_short} | {issue.problem} | {impact_short} | {suggestion_short} |")
        
        print(f"\n**Count: {len(by_problem[problem_type])}**")

print()
print("=" * 100)
print(f"TOTAL ISSUES: {len(issues)}")
print("=" * 100)

# Summary
by_type = defaultdict(int)
for issue in issues:
    by_type[issue.problem] += 1

print("\nSUMMARY BY TYPE:")
for problem_type, count in sorted(by_type.items(), key=lambda x: -x[1]):
    print(f"  - {problem_type}: {count}")

# Package confusion detail
auth_root = Path('/home/vini/scriptml/auth')
auth_nested = Path('/home/vini/scriptml/mercadolivre_upload/auth')

if auth_root.exists() and auth_nested.exists():
    print("\n" + "=" * 100)
    print("CRITICAL: DUPLICATE AUTH PACKAGES")
    print("=" * 100)
    print(f"\nTwo separate auth packages exist:")
    print(f"  1. {auth_root}/ (root level)")
    print(f"  2. {auth_nested}/ (inside mercadolivre_upload)")
    print(f"\nThis causes confusion and should be consolidated.")
    print(f"Recommendation: Remove {auth_root}/ and update all imports to use mercadolivre_upload.auth")
