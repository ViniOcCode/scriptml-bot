#!/usr/bin/env python3
"""Ultra-comprehensive import analysis - finds EVERY issue."""

import ast
import os
import re
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

class UltraImportAnalyzer:
    """Ultra-comprehensive import analyzer."""
    
    def __init__(self, root_path: str):
        self.root_path = Path(root_path)
        self.issues: List[ImportIssue] = []
        self.all_files_content: Dict[str, str] = {}
        
    def analyze_all(self):
        """Run ultra-comprehensive analysis."""
        print("Phase 1: Reading all files...")
        self._read_all_files()
        
        print("Phase 2: Detecting duplicate auth imports...")
        self._detect_duplicate_auth_comprehensive()
        
        print("Phase 3: Detecting duplicate imports...")
        self._detect_duplicate_imports_comprehensive()
        
        print("Phase 4: Detecting unused imports...")
        self._detect_unused_imports_comprehensive()
        
        print("Phase 5: Detecting architecture violations...")
        self._detect_architecture_violations_comprehensive()
        
        print("Phase 6: Detecting import style inconsistencies...")
        self._detect_import_style_comprehensive()
        
    def _find_python_files(self) -> List[Path]:
        """Find all Python files in the project."""
        files = []
        for root, dirs, filenames in os.walk(self.root_path):
            dirs[:] = [d for d in dirs if d not in {'.venv', '__pycache__', '.git', '.mypy_cache', 
                                                      '.pytest_cache', 'site-packages', '.ruff_cache',
                                                      'htmlcov', '.benchmarks', 'mercado_livre_bulk_upload.egg-info'}]
            
            for filename in filenames:
                if filename.endswith('.py'):
                    files.append(Path(root) / filename)
        return sorted(files)
    
    def _read_all_files(self):
        """Read all Python files."""
        for filepath in self._find_python_files():
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    rel_path = str(filepath.relative_to(self.root_path))
                    self.all_files_content[rel_path] = f.read()
            except Exception as e:
                print(f"Error reading {filepath}: {e}")
    
    def _detect_duplicate_auth_comprehensive(self):
        """Detect ALL duplicate auth package imports."""
        # Pattern 1: Files importing from root auth/
        root_auth_pattern = re.compile(r'^from auth\.|^import auth\b', re.MULTILINE)
        
        # Pattern 2: Files importing from mercadolivre_upload.auth
        package_auth_pattern = re.compile(r'from mercadolivre_upload\.auth|from \.+auth\b', re.MULTILINE)
        
        for file, content in self.all_files_content.items():
            lines = content.split('\n')
            
            root_auth_lines = []
            package_auth_lines = []
            
            for i, line in enumerate(lines, 1):
                line_stripped = line.strip()
                
                # Skip comments and empty lines
                if not line_stripped or line_stripped.startswith('#'):
                    continue
                
                # Check for root auth imports
                if re.match(r'^from auth\.|^import auth\b', line_stripped):
                    root_auth_lines.append((i, line_stripped))
                
                # Check for package auth imports
                if re.search(r'from mercadolivre_upload\.auth|from \.+auth\b', line_stripped):
                    package_auth_lines.append((i, line_stripped))
            
            # Report if both exist
            if root_auth_lines and package_auth_lines:
                for line_no, stmt in root_auth_lines:
                    self.issues.append(ImportIssue(
                        file=file,
                        line=line_no,
                        import_stmt=stmt,
                        problem=f"Imports from root auth/ (also has mercadolivre_upload.auth on lines {[l for l, _ in package_auth_lines]})",
                        impact="CRITICAL",
                        suggestion="Remove ALL root auth/ imports. Use mercadolivre_upload.auth exclusively",
                        category="duplicate_auth"
                    ))
    
    def _detect_duplicate_imports_comprehensive(self):
        """Detect ALL duplicate imports within files."""
        for file, content in self.all_files_content.items():
            lines = content.split('\n')
            seen_imports = {}
            
            for i, line in enumerate(lines, 1):
                line_stripped = line.strip()
                
                # Skip comments and empty lines
                if not line_stripped or line_stripped.startswith('#'):
                    continue
                
                # Match import statements
                if line_stripped.startswith('from ') or line_stripped.startswith('import '):
                    # Normalize the import
                    normalized = re.sub(r'\s+', ' ', line_stripped)
                    
                    if normalized in seen_imports:
                        self.issues.append(ImportIssue(
                            file=file,
                            line=i,
                            import_stmt=line_stripped,
                            problem=f"Duplicate import (already on line {seen_imports[normalized]})",
                            impact="LOW",
                            suggestion=f"Delete line {i}",
                            category="duplicate"
                        ))
                    else:
                        seen_imports[normalized] = i
    
    def _detect_unused_imports_comprehensive(self):
        """Detect ALL unused imports using AST analysis."""
        for file, content in self.all_files_content.items():
            try:
                tree = ast.parse(content, filename=file)
                
                # Collect all imported names and their lines
                imported_items = {}  # name -> (line, full_statement)
                
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            name = alias.asname if alias.asname else alias.name.split('.')[0]
                            imported_items[name] = (node.lineno, f"import {alias.name}")
                    
                    elif isinstance(node, ast.ImportFrom):
                        if node.module:
                            for alias in node.names:
                                if alias.name == '*':
                                    continue
                                name = alias.asname if alias.asname else alias.name
                                module_part = node.module or ''
                                imported_items[name] = (node.lineno, f"from {module_part} import {alias.name}")
                
                # Check for __all__ exports
                all_exports = set()
                for node in ast.walk(tree):
                    if isinstance(node, ast.Assign):
                        for target in node.targets:
                            if isinstance(target, ast.Name) and target.id == '__all__':
                                if isinstance(node.value, (ast.List, ast.Tuple)):
                                    for elt in node.value.elts:
                                        if isinstance(elt, ast.Constant):
                                            all_exports.add(elt.value)
                
                # Collect all name references
                used_names = set()
                for node in ast.walk(tree):
                    if isinstance(node, ast.Name):
                        used_names.add(node.id)
                    elif isinstance(node, ast.Attribute):
                        base = node
                        while isinstance(base, ast.Attribute):
                            base = base.value
                        if isinstance(base, ast.Name):
                            used_names.add(base.id)
                
                # Also check for string references (type hints in quotes)
                string_refs = set(re.findall(r'["\'](\w+)["\']', content))
                used_names.update(string_refs)
                
                # Find unused
                for name, (line, stmt) in imported_items.items():
                    # Skip __init__.py files (often re-export)
                    if file.endswith('__init__.py'):
                        continue
                    
                    # Skip if used or exported
                    if name in used_names or name in all_exports:
                        continue
                    
                    # Skip __future__ imports if they might be needed
                    if 'from __future__' in stmt:
                        # Check if annotations are actually needed
                        if 'annotations' in stmt and '|' not in content and 'Self' not in content:
                            self.issues.append(ImportIssue(
                                file=file,
                                line=line,
                                import_stmt=stmt,
                                problem="Unused __future__ import",
                                impact="LOW",
                                suggestion="Remove this line (no forward refs or union types found)",
                                category="unused"
                            ))
                        continue
                    
                    self.issues.append(ImportIssue(
                        file=file,
                        line=line,
                        import_stmt=stmt,
                        problem="Unused import",
                        impact="LOW",
                        suggestion="Remove this line",
                        category="unused"
                    ))
                    
            except Exception as e:
                print(f"Error analyzing {file}: {e}")
    
    def _detect_architecture_violations_comprehensive(self):
        """Detect ALL architecture boundary violations."""
        for file, content in self.all_files_content.items():
            lines = content.split('\n')
            
            # Determine layer
            file_layer = None
            if '/domain/' in file:
                file_layer = 'domain'
            elif '/application/' in file:
                file_layer = 'application'
            elif '/infrastructure/' in file:
                file_layer = 'infrastructure'
            elif '/adapters/' in file:
                file_layer = 'adapters'
            elif '/api/' in file:
                file_layer = 'api'
            
            if not file_layer:
                continue
            
            for i, line in enumerate(lines, 1):
                line_stripped = line.strip()
                
                # Skip comments
                if not line_stripped or line_stripped.startswith('#'):
                    continue
                
                # Domain layer violations
                if file_layer == 'domain':
                    # Domain should not import infrastructure, adapters, or api
                    if re.search(r'from\s+.*\.(infrastructure|adapters|api|cli)\b', line_stripped):
                        violated_layer = re.search(r'from\s+.*\.(infrastructure|adapters|api|cli)\b', line_stripped).group(1)
                        self.issues.append(ImportIssue(
                            file=file,
                            line=i,
                            import_stmt=line_stripped,
                            problem=f"Domain layer importing from {violated_layer} layer (violates Clean Architecture)",
                            impact="HIGH",
                            suggestion=f"Use dependency injection via ports/interfaces instead",
                            category="architecture"
                        ))
                
                # Application layer violations
                elif file_layer == 'application':
                    # Application can use domain but not infrastructure details
                    if re.search(r'from\s+.*\.infrastructure\.(?!config)', line_stripped):
                        self.issues.append(ImportIssue(
                            file=file,
                            line=i,
                            import_stmt=line_stripped,
                            problem=f"Application layer importing from infrastructure layer (violates Clean Architecture)",
                            impact="HIGH",
                            suggestion=f"Use ports/interfaces or inject via dependency injection",
                            category="architecture"
                        ))
    
    def _detect_import_style_comprehensive(self):
        """Detect ALL import style inconsistencies."""
        for file, content in self.all_files_content.items():
            lines = content.split('\n')
            
            relative_imports = []
            absolute_imports = []
            
            for i, line in enumerate(lines, 1):
                line_stripped = line.strip()
                
                if not line_stripped or line_stripped.startswith('#'):
                    continue
                
                # Relative imports
                if re.match(r'^from \.(\.)*', line_stripped):
                    relative_imports.append((i, line_stripped))
                
                # Absolute imports of mercadolivre_upload
                elif 'mercadolivre_upload' in line_stripped:
                    absolute_imports.append((i, line_stripped))
            
            # Report mixed styles
            if relative_imports and absolute_imports:
                self.issues.append(ImportIssue(
                    file=file,
                    line=relative_imports[0][0],
                    import_stmt="Mixed import styles in file",
                    problem=f"File uses both relative (lines {[l for l, _ in relative_imports[:3]]}) and absolute imports",
                    impact="MEDIUM",
                    suggestion="Standardize on absolute imports (from mercadolivre_upload.module import ...)",
                    category="style"
                ))
    
    def generate_report(self) -> str:
        """Generate the complete detailed report."""
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
        
        # Add header
        report.append("# COMPLETE DETAILED IMPORT ANALYSIS\n")
        report.append(f"Total issues found: **{len(self.issues)}**\n")
        
        # Summary
        report.append("## Summary by Category\n")
        for cat_name, (title, issues) in categories.items():
            if issues:
                report.append(f"- {title.replace('##', '').strip()}: **{len(issues)} issues**")
        report.append("\n---\n")
        
        # Generate tables for each category
        for cat_name, (title, issues) in categories.items():
            if not issues:
                continue
            
            report.append(f"\n{title}\n")
            report.append(f"**Count:** {len(issues)} issues\n")
            report.append("| File | Line | Import | Problem | Impact | Minimal Suggestion |")
            report.append("|------|------|--------|---------|--------|--------------------|")
            
            for issue in sorted(issues, key=lambda x: (x.file, x.line)):
                line_str = str(issue.line) if issue.line > 0 else "N/A"
                # Escape pipes in content
                import_stmt = issue.import_stmt.replace('|', '\\|')
                problem = issue.problem.replace('|', '\\|')
                suggestion = issue.suggestion.replace('|', '\\|')
                
                report.append(
                    f"| {issue.file} | {line_str} | {import_stmt} | {problem} | {issue.impact} | {suggestion} |"
                )
            
            report.append("\n")
        
        return '\n'.join(report)


if __name__ == '__main__':
    analyzer = UltraImportAnalyzer('/home/vini/scriptml')
    print("=" * 80)
    print("ULTRA-COMPREHENSIVE IMPORT ANALYSIS")
    print("=" * 80)
    analyzer.analyze_all()
    
    print(f"\n{'=' * 80}")
    print(f"TOTAL ISSUES FOUND: {len(analyzer.issues)}")
    print(f"{'=' * 80}\n")
    
    report = analyzer.generate_report()
    print(report)
    
    # Save to file
    output_file = '/home/vini/scriptml/COMPLETE_IMPORT_ANALYSIS.md'
    with open(output_file, 'w') as f:
        f.write(report)
    print(f"\n{'=' * 80}")
    print(f"Full report saved to: {output_file}")
    print(f"{'=' * 80}")
