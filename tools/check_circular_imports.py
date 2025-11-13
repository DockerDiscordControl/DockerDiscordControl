#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Circular Import Detector                       #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""
Detect circular imports in the DDC codebase.

This tool analyzes Python imports and identifies circular dependencies that
could cause import errors at runtime.

Usage:
    python tools/check_circular_imports.py
    python tools/check_circular_imports.py --paths services app utils
    python tools/check_circular_imports.py --verbose
"""

import ast
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple
from collections import defaultdict
import argparse


class ImportAnalyzer(ast.NodeVisitor):
    """AST visitor to extract imports from Python files."""

    def __init__(self, module_path: str):
        self.module_path = module_path
        self.imports: List[str] = []

    def visit_Import(self, node: ast.Import):
        """Visit import statements."""
        for alias in node.names:
            self.imports.append(alias.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        """Visit from...import statements."""
        if node.module:
            self.imports.append(node.module)
        self.generic_visit(node)


def get_module_imports(file_path: Path, base_path: Path) -> Tuple[str, List[str]]:
    """
    Extract imports from a Python file.

    Args:
        file_path: Path to Python file
        base_path: Base path for relative module names

    Returns:
        Tuple of (module_name, list_of_imports)
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            tree = ast.parse(f.read(), filename=str(file_path))

        # Convert file path to module name
        relative = file_path.relative_to(base_path)
        module_parts = list(relative.parts)[:-1]  # Remove .py file
        if relative.stem != '__init__':
            module_parts.append(relative.stem)
        module_name = '.'.join(module_parts)

        # Extract imports
        analyzer = ImportAnalyzer(module_name)
        analyzer.visit(tree)

        # Filter to only internal imports
        internal_imports = []
        for imp in analyzer.imports:
            # Only consider imports from our packages
            if any(imp.startswith(pkg) for pkg in ['services', 'app', 'utils']):
                internal_imports.append(imp)

        return module_name, internal_imports

    except (AttributeError, KeyError, RuntimeError, TypeError) as e:
        print(f"Warning: Could not parse {file_path}: {e}", file=sys.stderr)
        return "", []


def build_dependency_graph(paths: List[str]) -> Dict[str, List[str]]:
    """
    Build a dependency graph from Python files.

    Args:
        paths: List of directory paths to analyze

    Returns:
        Dictionary mapping module names to their dependencies
    """
    base_path = Path.cwd()
    dependency_graph: Dict[str, List[str]] = defaultdict(list)

    for path_str in paths:
        path = Path(path_str)
        if not path.exists():
            print(f"Warning: Path {path} does not exist", file=sys.stderr)
            continue

        # Find all Python files
        python_files = list(path.rglob('*.py'))

        for py_file in python_files:
            module_name, imports = get_module_imports(py_file, base_path)
            if module_name:
                dependency_graph[module_name] = imports

    return dependency_graph


def find_circular_dependencies(
    graph: Dict[str, List[str]]
) -> List[List[str]]:
    """
    Find circular dependencies using DFS.

    Args:
        graph: Dependency graph

    Returns:
        List of circular dependency chains
    """
    visited: Set[str] = set()
    rec_stack: Set[str] = set()
    circles: List[List[str]] = []
    path: List[str] = []

    def dfs(node: str) -> bool:
        """DFS to detect cycles."""
        visited.add(node)
        rec_stack.add(node)
        path.append(node)

        # Check all dependencies
        for neighbor in graph.get(node, []):
            if neighbor not in visited:
                if dfs(neighbor):
                    return True
            elif neighbor in rec_stack:
                # Found a cycle
                cycle_start = path.index(neighbor)
                cycle = path[cycle_start:] + [neighbor]
                circles.append(cycle)
                return True

        path.pop()
        rec_stack.remove(node)
        return False

    # Check all nodes
    for node in graph:
        if node not in visited:
            dfs(node)

    return circles


def format_cycle(cycle: List[str]) -> str:
    """Format a circular dependency for display."""
    return " → ".join(cycle)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Detect circular imports in DDC codebase"
    )
    parser.add_argument(
        '--paths',
        nargs='+',
        default=['services', 'app', 'utils'],
        help='Paths to analyze (default: services app utils)'
    )
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Verbose output'
    )
    parser.add_argument(
        '--fail-on-circular',
        action='store_true',
        help='Exit with error code if circular imports found'
    )

    args = parser.parse_args()

    print("🔍 Analyzing Python imports for circular dependencies...")
    print(f"Paths: {', '.join(args.paths)}\n")

    # Build dependency graph
    if args.verbose:
        print("Building dependency graph...")
    graph = build_dependency_graph(args.paths)

    if args.verbose:
        print(f"Found {len(graph)} modules")
        print(f"Total dependencies: {sum(len(deps) for deps in graph.values())}\n")

    # Find circular dependencies
    if args.verbose:
        print("Checking for circular dependencies...")
    circles = find_circular_dependencies(graph)

    # Remove duplicates (same cycle in different order)
    unique_circles = []
    seen = set()
    for circle in circles:
        # Normalize cycle (rotate to start with smallest element)
        min_idx = circle.index(min(circle[:-1]))  # Exclude last (duplicate of first)
        normalized = tuple(circle[min_idx:-1] + circle[:min_idx])
        if normalized not in seen:
            seen.add(normalized)
            unique_circles.append(circle)

    # Report results
    if unique_circles:
        print(f"❌ Found {len(unique_circles)} circular dependencies:\n")
        for i, cycle in enumerate(unique_circles, 1):
            print(f"{i}. {format_cycle(cycle)}")
        print()

        if args.fail_on_circular:
            sys.exit(1)
    else:
        print("✅ No circular dependencies found!")
        print()

    # Show most imported modules
    if args.verbose:
        import_counts = defaultdict(int)
        for deps in graph.values():
            for dep in deps:
                import_counts[dep] += 1

        if import_counts:
            print("Top 10 most imported modules:")
            sorted_imports = sorted(
                import_counts.items(),
                key=lambda x: x[1],
                reverse=True
            )[:10]
            for module, count in sorted_imports:
                print(f"  {module}: {count} imports")
            print()

    print("Analysis complete.")


if __name__ == '__main__':
    main()
