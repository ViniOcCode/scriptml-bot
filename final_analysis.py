#!/usr/bin/env python3
"""Generate comprehensive import analysis report in table format."""

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
        
        # Track imports
        imports = defaultdict(list)
        import_details = {}
        used_names = set()
        
        # First pass: collect imports
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.asname if alias.asname else alias.name
                    key = f"import {alias.name}"
                    full_import = f"import {alias.name}" + (f" as {alias.asname}" if alias.asname else "")
                    imports[key].append(node.lineno)
                    import_details[node.lineno] = {
                        'type': 'import',
                        'name': name,
                        'module': alias.name,
                        'full': full_import
                    }
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ''
                level = '.' * node.level
                full_module = f"{level}{module}" if module else level
                for alias in node.names:
                    name = alias.asname if alias.asname else alias.name
                    key = f"from {level}{module} import {alias.name}"
                    full_import = f"from {full_module} import {alias.name}" + (f" as {alias.asname}" if alias.asname else "")
                    imports[key].append(node.lineno)
                    import_details[node.lineno] = {
                        'type': 'from',
                        'name': name,
                        'module': module,
                        'full': full_import,
                        'imported_name': alias.name
                    }
            elif isinstance(node, ast.Name):
                used_names.add(node.id)
            elif isinstance(node, ast.Attribute):
                # Track attribute access
                current = node
                while isinstance(current, ast.Attribute):
                    current = current.value
                if isinstance(current, ast.Name):
                    used_names.add(current.id)
        
        rel_path = os.path.relpath(filepath, '/home/vini/scriptml')
        
        # Check for duplicates
        for key, linenos in imports.items():
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
        
        # Check for unused imports
        for lineno, detail in import_details.items():
            name = detail['name']
            
            # Skip star imports
            if name == '*':
                continue
            
            # Skip if in __all__ (re-exports)
            if '__all__' in content:
                continue
            
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
            if module and module.startswith('auth.') or module == 'auth':
                # Check if this is using top-level auth instead of mercadolivre_upload.auth
                if 'mercadolivre_upload' not in filepath:
                    continue
                issues.append(Issue(
                    file=rel_path,
                    line=lineno,
                    import_stmt=detail['full'],
                    problem="package confusion",
                    impact="Importing from wrong auth package (should use mercadolivre_upload.auth)",
                    suggestion=f"Change to: from mercadolivre_upload.auth{module[4:]} import {detail.get('imported_name', '...')}"
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
                        impact="Domain layer importing from outer layers - violates Clean Architecture",
                        suggestion="Inject dependencies via constructor parameters instead"
                    ))
        
        if 'mercadolivre_upload/application' in filepath:
            for lineno, detail in import_details.items():
                module = detail.get('module', '')
                # Check for direct infrastructure imports (should use ports)
                if 'adapters' in module or 'api' in module and 'mercadolivre_upload.api' in module:
                    issues.append(Issue(
                        file=rel_path,
                        line=lineno,
                        import_stmt=detail['full'],
                        problem="boundary violation",
                        impact="Application layer directly importing infrastructure - should use ports/interfaces",
                        suggestion="Define port interface and inject via dependency injection"
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
    if len(file_short) > 50:
        file_short = "..." + file_short[-47:]
    
    import_short = issue.import_stmt
    if len(import_short) > 60:
        import_short = import_short[:57] + "..."
    
    impact_short = issue.impact
    if len(impact_short) > 50:
        impact_short = impact_short[:47] + "..."
        
    suggestion_short = issue.suggestion
    if len(suggestion_short) > 60:
        suggestion_short = suggestion_short[:57] + "..."
    
    print(f"| {file_short} | {issue.line} | {import_short} | {issue.problem} | {impact_short} | {suggestion_short} |")

print(f"\n**Total issues found: {len(issues)}**")

# Summary by type
by_type = defaultdict(int)
for issue in issues:
    by_type[issue.problem] += 1

print("\n**Summary by type:**")
for problem_type, count in sorted(by_type.items(), key=lambda x: -x[1]):
    print(f"- {problem_type}: {count}")
