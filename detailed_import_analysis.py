#!/usr/bin/env python3
"""Comprehensive import analysis tool for Python projects."""

import ast
import os
from pathlib import Path
from collections import defaultdict
from dataclasses import dataclass
from typing import List, Set, Dict, Tuple

@dataclass
class ImportIssue:
    """Represents an import issue."""
    file: str
    line: int
    import_stmt: str
    problem: str
    impact: str
    suggestion: str
    category: str

class ImportAnalyzer:
    """Analyzes Python imports for various issues."""
    
    def __init__(self, root_path: str):
        self.root_path = Path(root_path)
        self.issues: List[ImportIssue] = []
        self.import_graph: Dict[str, Set[str]] = defaultdict(set)
        self.file_imports: Dict[str, List[Tuple[int, str, str]]] = defaultdict(list)
        
    def analyze_all(self):
        """Run complete analysis."""
        # First pass: collect all imports
        for py_file in self._find_python_files():
            self._analyze_file(py_file)
        
        # Second pass: detect issues
        self._detect_duplicate_auth_packages()
        self._detect_duplicate_imports()
        self._detect_unused_imports()
        self._detect_architecture_violations()
        self._detect_circular_imports()
        self._detect_import_style_issues()
        
    def _find_python_files(self) -> List[Path]:
        """Find all Python files in the project."""
        files = []
        for root, dirs, filenames in os.walk(self.root_path):
            # Skip virtual environments and cache directories
            dirs[:] = [d for d in dirs if d not in {'.venv', '__pycache__', '.git', '.mypy_cache', '.pytest_cache', 'site-packages'}]
            
            for filename in filenames:
                if filename.endswith('.py'):
                    files.append(Path(root) / filename)
        return sorted(files)
    
    def _analyze_file(self, filepath: Path):
        """Analyze a single Python file."""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
                tree = ast.parse(content, filename=str(filepath))
            
            # Get relative path for display
            rel_path = filepath.relative_to(self.root_path)
            
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        import_stmt = f"import {alias.name}"
                        self.file_imports[str(rel_path)].append((node.lineno, import_stmt, alias.name))
                        self.import_graph[str(rel_path)].add(alias.name.split('.')[0])
                
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        module = node.module
                        names = [alias.name for alias in node.names]
                        import_stmt = f"from {module} import {', '.join(names)}"
                        self.file_imports[str(rel_path)].append((node.lineno, import_stmt, module))
                        self.import_graph[str(rel_path)].add(module.split('.')[0])
                        
        except Exception as e:
            print(f"Error analyzing {filepath}: {e}")
    
    def _detect_duplicate_auth_packages(self):
        """Detect files importing from both auth packages."""
        for file, imports in self.file_imports.items():
            has_root_auth = False
            has_package_auth = False
            root_auth_line = 0
            package_auth_line = 0
            
            for line, stmt, module in imports:
                if module.startswith('auth.') or module == 'auth':
                    has_root_auth = True
                    root_auth_line = line
                elif 'mercadolivre_upload.auth' in module or module.startswith('mercadolivre_upload.auth'):
                    has_package_auth = True
                    package_auth_line = line
            
            if has_root_auth and has_package_auth:
                self.issues.append(ImportIssue(
                    file=file,
                    line=root_auth_line,
                    import_stmt="from auth import ...",
                    problem=f"Imports from BOTH auth/ (line {root_auth_line}) and mercadolivre_upload/auth/ (line {package_auth_line})",
                    impact="CRITICAL",
                    suggestion=f"Remove imports from root auth/ package. Use mercadolivre_upload.auth only",
                    category="duplicate_auth"
                ))
    
    def _detect_duplicate_imports(self):
        """Detect duplicate imports within the same file."""
        for file, imports in self.file_imports.items():
            seen = {}
            for line, stmt, module in imports:
                key = stmt  # Use full statement as key
                if key in seen:
                    self.issues.append(ImportIssue(
                        file=file,
                        line=line,
                        import_stmt=stmt,
                        problem=f"Duplicate import (already on line {seen[key]})",
                        impact="LOW",
                        suggestion=f"Delete line {line}",
                        category="duplicate"
                    ))
                else:
                    seen[key] = line
    
    def _detect_unused_imports(self):
        """Detect potentially unused imports."""
        for py_file in self._find_python_files():
            try:
                with open(py_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                    tree = ast.parse(content, filename=str(py_file))
                
                rel_path = str(py_file.relative_to(self.root_path))
                
                # Collect imported names
                imported_names = set()
                import_lines = {}
                
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            name = alias.asname if alias.asname else alias.name.split('.')[0]
                            imported_names.add(name)
                            import_lines[name] = (node.lineno, f"import {alias.name}")
                    
                    elif isinstance(node, ast.ImportFrom):
                        for alias in node.names:
                            if alias.name == '*':
                                continue  # Skip star imports
                            name = alias.asname if alias.asname else alias.name
                            imported_names.add(name)
                            import_lines[name] = (node.lineno, f"from {node.module} import {alias.name}")
                
                # Check for usage in __all__
                all_exports = set()
                for node in ast.walk(tree):
                    if isinstance(node, ast.Assign):
                        for target in node.targets:
                            if isinstance(target, ast.Name) and target.id == '__all__':
                                if isinstance(node.value, (ast.List, ast.Tuple)):
                                    for elt in node.value.elts:
                                        if isinstance(elt, ast.Constant):
                                            all_exports.add(elt.value)
                
                # Collect used names
                used_names = set()
                for node in ast.walk(tree):
                    if isinstance(node, ast.Name):
                        used_names.add(node.id)
                    elif isinstance(node, ast.Attribute):
                        # Get the base name
                        base = node
                        while isinstance(base, ast.Attribute):
                            base = base.value
                        if isinstance(base, ast.Name):
                            used_names.add(base.id)
                
                # Find unused imports
                for name in imported_names:
                    if name not in used_names and name not in all_exports:
                        line, stmt = import_lines[name]
                        # Skip if it's in __init__.py (likely re-export)
                        if rel_path.endswith('__init__.py'):
                            continue
                        
                        self.issues.append(ImportIssue(
                            file=rel_path,
                            line=line,
                            import_stmt=stmt,
                            problem="Unused import",
                            impact="LOW",
                            suggestion="Remove this line",
                            category="unused"
                        ))
                        
            except Exception as e:
                print(f"Error checking usage in {py_file}: {e}")
    
    def _detect_architecture_violations(self):
        """Detect Clean Architecture boundary violations."""
        for file, imports in self.file_imports.items():
            # Check if file is in domain layer
            if '/domain/' in file:
                for line, stmt, module in imports:
                    # Domain should not import from infrastructure or adapters
                    if 'infrastructure' in module or 'adapters' in module or 'api' in module:
                        self.issues.append(ImportIssue(
                            file=file,
                            line=line,
                            import_stmt=stmt,
                            problem=f"Domain layer importing from {module.split('.')[0]} layer",
                            impact="HIGH",
                            suggestion=f"Inject {module} as a dependency via ports/interfaces",
                            category="architecture"
                        ))
            
            # Check if file is in application layer
            if '/application/' in file:
                for line, stmt, module in imports:
                    # Application should not import from infrastructure
                    if 'infrastructure' in module and 'config' not in module:
                        self.issues.append(ImportIssue(
                            file=file,
                            line=line,
                            import_stmt=stmt,
                            problem=f"Application layer importing from infrastructure layer",
                            impact="HIGH",
                            suggestion=f"Use ports/interfaces instead of direct infrastructure import",
                            category="architecture"
                        ))
    
    def _detect_circular_imports(self):
        """Detect circular import dependencies."""
        # Build module-level graph
        module_graph = defaultdict(set)
        
        for file, imports in self.file_imports.items():
            # Convert file to module name
            file_module = file.replace('/', '.').replace('\\', '.').replace('.py', '')
            if file_module.endswith('.__init__'):
                file_module = file_module[:-9]
            
            for _, stmt, module in imports:
                # Only track internal imports
                if module.startswith('mercadolivre_upload') or module.startswith('auth'):
                    module_graph[file_module].add(module)
        
        # Find cycles using DFS
        def find_cycles(node, path, visited, cycles):
            if node in path:
                cycle_start = path.index(node)
                cycle = path[cycle_start:] + [node]
                cycles.append(cycle)
                return
            
            if node in visited:
                return
            
            visited.add(node)
            path.append(node)
            
            for neighbor in module_graph.get(node, []):
                find_cycles(neighbor, path.copy(), visited, cycles)
        
        cycles = []
        for node in module_graph:
            find_cycles(node, [], set(), cycles)
        
        # Report unique cycles
        seen_cycles = set()
        for cycle in cycles:
            cycle_key = tuple(sorted(cycle))
            if cycle_key not in seen_cycles:
                seen_cycles.add(cycle_key)
                cycle_str = " → ".join(cycle)
                
                # Find a file in the cycle
                first_module = cycle[0].replace('.', '/') + '.py'
                
                self.issues.append(ImportIssue(
                    file=first_module,
                    line=0,
                    import_stmt=f"Circular dependency detected",
                    problem=f"circular: {cycle_str}",
                    impact="HIGH",
                    suggestion=f"Break cycle by extracting shared code or using dependency injection",
                    category="circular"
                ))
    
    def _detect_import_style_issues(self):
        """Detect inconsistent import styles."""
        # Check for mixing absolute and relative imports
        for file, imports in self.file_imports.items():
            has_absolute = False
            has_relative = False
            
            for line, stmt, module in imports:
                if stmt.startswith('from .'):
                    has_relative = True
                elif 'mercadolivre_upload' in module:
                    has_absolute = True
            
            if has_absolute and has_relative:
                self.issues.append(ImportIssue(
                    file=file,
                    line=0,
                    import_stmt="Mixed import styles",
                    problem="File uses both absolute and relative imports",
                    impact="MEDIUM",
                    suggestion="Standardize on absolute imports throughout the file",
                    category="style"
                ))
    
    def generate_report(self) -> str:
        """Generate a detailed report."""
        report = []
        
        # Group by category
        categories = {
            'duplicate_auth': ('## CRITICAL: Duplicate Auth Package', []),
            'circular': ('## Circular Import Dependencies', []),
            'architecture': ('## Clean Architecture Boundary Violations', []),
            'unused': ('## Unused Imports', []),
            'duplicate': ('## Duplicate Imports', []),
            'style': ('## Inconsistent Import Styles', [])
        }
        
        for issue in self.issues:
            categories[issue.category][1].append(issue)
        
        # Generate tables
        for cat_name, (title, issues) in categories.items():
            if not issues:
                continue
            
            report.append(f"\n{title}\n")
            report.append("| File | Line | Import | Problem | Impact | Minimal Suggestion |")
            report.append("|------|------|--------|---------|--------|--------------------|")
            
            for issue in sorted(issues, key=lambda x: (x.file, x.line)):
                line_str = str(issue.line) if issue.line > 0 else "N/A"
                report.append(
                    f"| {issue.file} | {line_str} | {issue.import_stmt} | {issue.problem} | {issue.impact} | {issue.suggestion} |"
                )
        
        # Add summary
        report.insert(0, f"\n# Import Analysis Report\n")
        report.insert(1, f"\nTotal issues found: {len(self.issues)}\n")
        report.insert(2, f"- Duplicate auth package: {len(categories['duplicate_auth'][1])}")
        report.insert(3, f"- Circular imports: {len(categories['circular'][1])}")
        report.insert(4, f"- Architecture violations: {len(categories['architecture'][1])}")
        report.insert(5, f"- Unused imports: {len(categories['unused'][1])}")
        report.insert(6, f"- Duplicate imports: {len(categories['duplicate'][1])}")
        report.insert(7, f"- Style issues: {len(categories['style'][1])}")
        
        return '\n'.join(report)


if __name__ == '__main__':
    analyzer = ImportAnalyzer('/home/vini/scriptml')
    print("Analyzing imports...")
    analyzer.analyze_all()
    print(f"Found {len(analyzer.issues)} issues")
    
    report = analyzer.generate_report()
    print(report)
    
    # Save to file
    with open('/home/vini/scriptml/DETAILED_IMPORT_REPORT.md', 'w') as f:
        f.write(report)
    print("\nReport saved to DETAILED_IMPORT_REPORT.md")
