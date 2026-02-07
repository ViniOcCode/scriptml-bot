#!/usr/bin/env python3
"""Comprehensive Python import analyzer for detecting critical issues."""

import ast
import os
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Set, Tuple, Optional
import sys

@dataclass
class ImportInfo:
    """Information about a single import statement."""
    file_path: str
    line_number: int
    module: str
    names: List[str]
    is_from_import: bool
    level: int  # For relative imports
    used_names: Set[str] = None
    
    def __post_init__(self):
        if self.used_names is None:
            self.used_names = set()

class ImportAnalyzer:
    """Analyzes Python imports for various issues."""
    
    def __init__(self, root_dir: str):
        self.root_dir = Path(root_dir)
        self.imports: Dict[str, List[ImportInfo]] = defaultdict(list)
        self.file_contents: Dict[str, str] = {}
        self.file_asts: Dict[str, ast.AST] = {}
        self.import_graph: Dict[str, Set[str]] = defaultdict(set)
        
    def analyze_project(self):
        """Main analysis entry point."""
        print("🔍 Scanning Python files...")
        python_files = self._find_python_files()
        print(f"📁 Found {len(python_files)} Python files")
        
        for file_path in python_files:
            self._analyze_file(file_path)
        
        return self
    
    def _find_python_files(self) -> List[Path]:
        """Find all Python files in the project."""
        python_files = []
        for root, dirs, files in os.walk(self.root_dir):
            # Skip common directories
            dirs[:] = [d for d in dirs if d not in {'.venv', '__pycache__', '.git', 
                                                     'node_modules', '.pytest_cache', 
                                                     '.mypy_cache', 'htmlcov'}]
            for file in files:
                if file.endswith('.py'):
                    python_files.append(Path(root) / file)
        return sorted(python_files)
    
    def _analyze_file(self, file_path: Path):
        """Analyze a single Python file."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            rel_path = str(file_path.relative_to(self.root_dir))
            self.file_contents[rel_path] = content
            
            try:
                tree = ast.parse(content, filename=str(file_path))
                self.file_asts[rel_path] = tree
                self._extract_imports(tree, rel_path)
            except SyntaxError as e:
                print(f"⚠️  Syntax error in {rel_path}: {e}")
                
        except Exception as e:
            print(f"⚠️  Error reading {file_path}: {e}")
    
    def _extract_imports(self, tree: ast.AST, file_path: str):
        """Extract all imports from an AST."""
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    import_info = ImportInfo(
                        file_path=file_path,
                        line_number=node.lineno,
                        module=alias.name,
                        names=[alias.asname or alias.name],
                        is_from_import=False,
                        level=0
                    )
                    self.imports[file_path].append(import_info)
                    
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ''
                names = [alias.name for alias in node.names]
                import_info = ImportInfo(
                    file_path=file_path,
                    line_number=node.lineno,
                    module=module,
                    names=names,
                    is_from_import=True,
                    level=node.level
                )
                self.imports[file_path].append(import_info)
    
    def _resolve_module_path(self, import_info: ImportInfo) -> Optional[str]:
        """Resolve relative imports to absolute module paths."""
        if import_info.level == 0:
            return import_info.module
        
        # Handle relative imports
        file_parts = Path(import_info.file_path).parent.parts
        if import_info.level > len(file_parts):
            return None
        
        base_parts = file_parts[:-import_info.level] if import_info.level else file_parts
        if import_info.module:
            return '.'.join(base_parts + (import_info.module,))
        return '.'.join(base_parts)
    
    def check_unused_imports(self) -> List[Dict]:
        """Find imports that are not used in the code."""
        issues = []
        
        for file_path, imports in self.imports.items():
            content = self.file_contents.get(file_path, '')
            tree = self.file_asts.get(file_path)
            
            if not tree:
                continue
            
            # Get all names used in the file
            used_names = self._get_used_names(tree)
            
            for import_info in imports:
                # Skip star imports
                if '*' in import_info.names:
                    continue
                
                # Check each imported name
                for name in import_info.names:
                    # Get the actual name that would be used in code
                    if import_info.is_from_import:
                        use_name = name
                    else:
                        # For 'import x.y.z', we use 'x'
                        use_name = import_info.module.split('.')[0]
                    
                    # Check if used in code
                    if use_name not in used_names:
                        # Additional check: is it in __all__?
                        if not self._is_in_all_export(tree, use_name):
                            import_str = self._format_import(import_info, name)
                            issues.append({
                                'file': file_path,
                                'line': import_info.line_number,
                                'import': import_str,
                                'name': name,
                                'problem': 'unused'
                            })
        
        return issues
    
    def _get_used_names(self, tree: ast.AST) -> Set[str]:
        """Get all names used in the AST (excluding imports)."""
        used_names = set()
        
        for node in ast.walk(tree):
            # Skip import statements
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            
            if isinstance(node, ast.Name):
                used_names.add(node.id)
            elif isinstance(node, ast.Attribute):
                # For a.b.c, we want to capture 'a'
                current = node
                while isinstance(current, ast.Attribute):
                    current = current.value
                if isinstance(current, ast.Name):
                    used_names.add(current.id)
        
        return used_names
    
    def _is_in_all_export(self, tree: ast.AST, name: str) -> bool:
        """Check if a name is in __all__ export list."""
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == '__all__':
                        if isinstance(node.value, (ast.List, ast.Tuple)):
                            for elt in node.value.elts:
                                if isinstance(elt, ast.Constant) and elt.value == name:
                                    return True
        return False
    
    def _format_import(self, import_info: ImportInfo, name: str = None) -> str:
        """Format an import statement as a string."""
        if import_info.is_from_import:
            if import_info.level > 0:
                dots = '.' * import_info.level
                module = f"{dots}{import_info.module}" if import_info.module else dots
            else:
                module = import_info.module
            
            if name:
                return f"from {module} import {name}"
            return f"from {module} import {', '.join(import_info.names)}"
        else:
            if name:
                return f"import {name}"
            return f"import {import_info.module}"
    
    def check_duplicate_imports(self) -> List[Dict]:
        """Find duplicate imports in the same file."""
        issues = []
        
        for file_path, imports in self.imports.items():
            seen = {}  # (module, name) -> line_number
            
            for import_info in imports:
                for name in import_info.names:
                    key = (import_info.module, name, import_info.level)
                    
                    if key in seen:
                        import_str = self._format_import(import_info, name)
                        issues.append({
                            'file': file_path,
                            'line': import_info.line_number,
                            'import': import_str,
                            'problem': f'duplicate (already imported on line {seen[key]})',
                            'first_line': seen[key]
                        })
                    else:
                        seen[key] = import_info.line_number
        
        return issues
    
    def check_circular_imports(self) -> List[Dict]:
        """Detect circular import dependencies."""
        issues = []
        
        # Build import graph
        graph = defaultdict(set)
        for file_path, imports in self.imports.items():
            file_module = self._file_to_module(file_path)
            for import_info in imports:
                resolved = self._resolve_module_path(import_info)
                if resolved and self._is_internal_module(resolved):
                    graph[file_module].add(resolved)
        
        # Find cycles using DFS
        visited = set()
        rec_stack = []
        
        def dfs(node):
            if node in rec_stack:
                # Found a cycle
                cycle_start = rec_stack.index(node)
                cycle = rec_stack[cycle_start:] + [node]
                return [cycle]
            
            if node in visited:
                return []
            
            visited.add(node)
            rec_stack.append(node)
            
            cycles = []
            for neighbor in graph.get(node, []):
                cycles.extend(dfs(neighbor))
            
            rec_stack.pop()
            return cycles
        
        all_cycles = []
        for node in graph:
            if node not in visited:
                cycles = dfs(node)
                for cycle in cycles:
                    if cycle not in all_cycles:
                        all_cycles.append(cycle)
        
        # Format cycles as issues
        for cycle in all_cycles:
            cycle_str = '→'.join(cycle)
            # Find the file that starts this cycle
            first_module = cycle[0]
            file_path = self._module_to_file(first_module)
            if file_path:
                issues.append({
                    'file': file_path,
                    'import': f"circular dependency",
                    'problem': f'circular: {cycle_str}',
                    'cycle': cycle
                })
        
        return issues
    
    def check_auth_package_duplicate(self) -> List[Dict]:
        """Check for duplicate auth package usage."""
        issues = []
        
        top_level_auth = set()
        nested_auth = set()
        
        for file_path, imports in self.imports.items():
            for import_info in imports:
                module = import_info.module
                
                # Check for top-level auth imports
                if module == 'auth' or module.startswith('auth.'):
                    top_level_auth.add(file_path)
                    for name in import_info.names:
                        import_str = self._format_import(import_info, name)
                        issues.append({
                            'file': file_path,
                            'line': import_info.line_number,
                            'import': import_str,
                            'problem': 'imports from TOP-LEVEL auth package',
                            'severity': 'CRITICAL'
                        })
                
                # Check for nested auth imports
                if module == 'mercadolivre_upload.auth' or module.startswith('mercadolivre_upload.auth.'):
                    nested_auth.add(file_path)
                    for name in import_info.names:
                        import_str = self._format_import(import_info, name)
                        issues.append({
                            'file': file_path,
                            'line': import_info.line_number,
                            'import': import_str,
                            'problem': 'imports from NESTED auth package',
                            'severity': 'CRITICAL'
                        })
        
        return issues
    
    def check_clean_architecture_violations(self) -> List[Dict]:
        """Check for Clean Architecture boundary violations."""
        issues = []
        
        for file_path, imports in self.imports.items():
            layer = self._get_layer(file_path)
            
            for import_info in imports:
                resolved = self._resolve_module_path(import_info)
                if not resolved:
                    continue
                
                # Check if it's an internal import
                if not self._is_internal_module(resolved):
                    continue
                
                target_layer = self._get_layer_from_module(resolved)
                
                # Domain layer violations
                if layer == 'domain':
                    forbidden_layers = {'infrastructure', 'api', 'adapters', 'cli', 'application'}
                    if target_layer in forbidden_layers:
                        for name in import_info.names:
                            import_str = self._format_import(import_info, name)
                            issues.append({
                                'file': file_path,
                                'line': import_info.line_number,
                                'import': import_str,
                                'problem': f'Domain layer importing from {target_layer} layer',
                                'severity': 'HIGH',
                                'violation_type': 'domain_boundary'
                            })
                
                # Application layer violations (should only depend on domain)
                elif layer == 'application':
                    forbidden_layers = {'infrastructure', 'api', 'adapters', 'cli'}
                    if target_layer in forbidden_layers:
                        for name in import_info.names:
                            import_str = self._format_import(import_info, name)
                            issues.append({
                                'file': file_path,
                                'line': import_info.line_number,
                                'import': import_str,
                                'problem': f'Application layer importing from {target_layer} layer',
                                'severity': 'MEDIUM',
                                'violation_type': 'application_boundary'
                            })
        
        return issues
    
    def _get_layer(self, file_path: str) -> Optional[str]:
        """Determine which architectural layer a file belongs to."""
        parts = Path(file_path).parts
        
        if 'domain' in parts:
            return 'domain'
        elif 'application' in parts:
            return 'application'
        elif 'infrastructure' in parts:
            return 'infrastructure'
        elif 'api' in parts:
            return 'api'
        elif 'adapters' in parts:
            return 'adapters'
        elif 'cli' in parts:
            return 'cli'
        
        return None
    
    def _get_layer_from_module(self, module: str) -> Optional[str]:
        """Determine which layer a module belongs to."""
        parts = module.split('.')
        
        for part in parts:
            if part in {'domain', 'application', 'infrastructure', 'api', 'adapters', 'cli'}:
                return part
        
        return None
    
    def _is_internal_module(self, module: str) -> bool:
        """Check if a module is internal to this project."""
        return (module.startswith('mercadolivre_upload.') or 
                module == 'mercadolivre_upload' or
                module.startswith('auth.') or
                module == 'auth')
    
    def _file_to_module(self, file_path: str) -> str:
        """Convert file path to Python module name."""
        path = Path(file_path)
        parts = list(path.parts)
        
        # Remove .py extension
        if parts[-1].endswith('.py'):
            parts[-1] = parts[-1][:-3]
        
        # Remove __init__
        if parts[-1] == '__init__':
            parts = parts[:-1]
        
        return '.'.join(parts)
    
    def _module_to_file(self, module: str) -> Optional[str]:
        """Convert module name to file path."""
        parts = module.split('.')
        
        # Try as __init__.py
        init_path = os.path.join(*parts, '__init__.py')
        if init_path in self.file_contents:
            return init_path
        
        # Try as .py file
        file_path = os.path.join(*parts) + '.py'
        if file_path in self.file_contents:
            return file_path
        
        return None

def main():
    root_dir = '/home/vini/scriptml'
    analyzer = ImportAnalyzer(root_dir)
    analyzer.analyze_project()
    
    print("\n" + "="*80)
    print("🔍 COMPREHENSIVE IMPORT ANALYSIS RESULTS")
    print("="*80)
    
    # 1. Auth package duplicate
    print("\n## CRITICAL: Duplicate Auth Package\n")
    auth_issues = analyzer.check_auth_package_duplicate()
    if auth_issues:
        top_level = [i for i in auth_issues if 'TOP-LEVEL' in i['problem']]
        nested = [i for i in auth_issues if 'NESTED' in i['problem']]
        
        print(f"📊 Found {len(top_level)} imports from TOP-LEVEL auth/")
        print(f"📊 Found {len(nested)} imports from NESTED mercadolivre_upload/auth/\n")
        
        print("| File | Line | Import | Problem | Impact | Minimal Suggestion |")
        print("|------|------|--------|---------|--------|-------------------|")
        for issue in sorted(auth_issues, key=lambda x: (x['file'], x['line'])):
            print(f"| {issue['file']} | {issue['line']} | {issue['import']} | {issue['problem']} | {issue['severity']} | Consolidate into single auth package |")
    else:
        print("✅ No duplicate auth package issues found")
    
    # 2. Circular imports
    print("\n## Circular Import Dependencies\n")
    circular = analyzer.check_circular_imports()
    if circular:
        print(f"📊 Found {len(circular)} circular dependency chains\n")
        print("| File | Import | Problem | Impact | Minimal Suggestion |")
        print("|------|--------|---------|--------|--------------------|")
        for issue in circular:
            cycle_str = issue['problem']
            print(f"| {issue['file']} | {issue['import']} | {cycle_str} | HIGH | Break dependency chain by extracting interface |")
    else:
        print("✅ No circular import dependencies found")
    
    # 3. Clean Architecture violations
    print("\n## Clean Architecture Boundary Violations\n")
    arch_violations = analyzer.check_clean_architecture_violations()
    if arch_violations:
        print(f"📊 Found {len(arch_violations)} boundary violations\n")
        print("| File | Line | Import | Problem | Impact | Minimal Suggestion |")
        print("|------|------|--------|---------|--------|-------------------|")
        for issue in sorted(arch_violations, key=lambda x: (x.get('severity', 'LOW'), x['file'])):
            suggestion = "Pass as constructor/method parameter (dependency injection)"
            print(f"| {issue['file']} | {issue['line']} | {issue['import']} | {issue['problem']} | {issue['severity']} | {suggestion} |")
    else:
        print("✅ No Clean Architecture violations found")
    
    # 4. Unused imports
    print("\n## Unused Imports\n")
    unused = analyzer.check_unused_imports()
    if unused:
        print(f"📊 Found {len(unused)} unused imports\n")
        print("| File | Line | Import | Problem | Impact | Minimal Suggestion |")
        print("|------|------|--------|---------|--------|-------------------|")
        for issue in sorted(unused, key=lambda x: (x['file'], x['line'])):
            print(f"| {issue['file']} | {issue['line']} | {issue['import']} | {issue['problem']} | LOW | Remove this line |")
    else:
        print("✅ No unused imports found")
    
    # 5. Duplicate imports
    print("\n## Duplicate Imports in Same File\n")
    duplicates = analyzer.check_duplicate_imports()
    if duplicates:
        print(f"📊 Found {len(duplicates)} duplicate imports\n")
        print("| File | Line | Import | Problem | Impact | Minimal Suggestion |")
        print("|------|------|--------|---------|--------|-------------------|")
        for issue in sorted(duplicates, key=lambda x: (x['file'], x['line'])):
            print(f"| {issue['file']} | {issue['line']} | {issue['import']} | {issue['problem']} | LOW | Remove duplicate import |")
    else:
        print("✅ No duplicate imports found")
    
    print("\n" + "="*80)
    print("✨ Analysis complete!")
    print("="*80)

if __name__ == '__main__':
    main()
