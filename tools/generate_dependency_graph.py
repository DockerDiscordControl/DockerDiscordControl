#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Dependency Graph Generator                     #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""
Generate visual dependency graphs for DDC codebase.

This tool creates visualizations of module dependencies using Graphviz.

Requirements:
    - graphviz (Python package): pip install graphviz
    - Graphviz binary: apt-get install graphviz (Linux) or brew install graphviz (Mac)

Usage:
    python tools/generate_dependency_graph.py
    python tools/generate_dependency_graph.py --output docs/dependency_graph.png
    python tools/generate_dependency_graph.py --format svg
    python tools/generate_dependency_graph.py --level service
"""

import ast
import sys
import argparse
from pathlib import Path
from typing import Dict, List, Set, Tuple
from collections import defaultdict

try:
    import graphviz
except ImportError:
    print("Error: graphviz package not installed", file=sys.stderr)
    print("Install with: pip install graphviz", file=sys.stderr)
    sys.exit(1)


class ImportAnalyzer(ast.NodeVisitor):
    """AST visitor to extract imports."""

    def __init__(self):
        self.imports: List[str] = []

    def visit_Import(self, node: ast.Import):
        for alias in node.names:
            self.imports.append(alias.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        if node.module:
            self.imports.append(node.module)
        self.generic_visit(node)


def get_module_imports(file_path: Path, base_path: Path) -> Tuple[str, List[str]]:
    """Extract imports from a Python file."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            tree = ast.parse(f.read(), filename=str(file_path))

        # Convert file path to module name
        relative = file_path.relative_to(base_path)
        module_parts = list(relative.parts)[:-1]
        if relative.stem != '__init__':
            module_parts.append(relative.stem)
        module_name = '.'.join(module_parts)

        # Extract imports
        analyzer = ImportAnalyzer()
        analyzer.visit(tree)

        # Filter to internal imports
        internal_imports = []
        for imp in analyzer.imports:
            if any(imp.startswith(pkg) for pkg in ['services', 'app', 'utils']):
                internal_imports.append(imp)

        return module_name, internal_imports

    except (AttributeError, KeyError, RuntimeError, TypeError) as e:
        return "", []


def build_dependency_graph(paths: List[str]) -> Dict[str, List[str]]:
    """Build dependency graph from Python files."""
    base_path = Path.cwd()
    dependency_graph: Dict[str, List[str]] = defaultdict(list)

    for path_str in paths:
        path = Path(path_str)
        if not path.exists():
            continue

        python_files = list(path.rglob('*.py'))
        for py_file in python_files:
            module_name, imports = get_module_imports(py_file, base_path)
            if module_name:
                dependency_graph[module_name] = imports

    return dependency_graph


def aggregate_to_level(
    graph: Dict[str, List[str]],
    level: str
) -> Dict[str, Set[str]]:
    """
    Aggregate dependencies to a higher level.

    Args:
        graph: Full dependency graph
        level: 'package' or 'service'

    Returns:
        Aggregated dependency graph
    """
    aggregated: Dict[str, Set[str]] = defaultdict(set)

    def get_aggregate_name(module: str) -> str:
        if level == 'service':
            # services.config.config_service -> services.config
            parts = module.split('.')
            if len(parts) >= 2:
                return '.'.join(parts[:2])
            return module
        elif level == 'package':
            # services.config.config_service -> services
            return module.split('.')[0]
        return module

    for module, deps in graph.items():
        agg_module = get_aggregate_name(module)
        for dep in deps:
            agg_dep = get_aggregate_name(dep)
            if agg_module != agg_dep:  # No self-loops
                aggregated[agg_module].add(agg_dep)

    return {k: list(v) for k, v in aggregated.items()}


def create_graph(
    dependencies: Dict[str, List[str]],
    title: str = "DDC Dependency Graph"
) -> graphviz.Digraph:
    """Create a Graphviz graph from dependencies."""
    dot = graphviz.Digraph(comment=title)
    dot.attr(rankdir='LR')  # Left to right
    dot.attr('node', shape='box', style='rounded,filled', fillcolor='lightblue')

    # Color scheme for different packages
    colors = {
        'services': 'lightblue',
        'app': 'lightgreen',
        'utils': 'lightyellow',
    }

    # Add nodes
    for module in dependencies.keys():
        color = colors.get(module.split('.')[0], 'lightgray')
        dot.node(module, module, fillcolor=color)

    # Add edges
    added_edges = set()
    for module, deps in dependencies.items():
        for dep in deps:
            edge = (module, dep)
            if edge not in added_edges:
                dot.edge(module, dep)
                added_edges.add(edge)

    return dot


def create_hierarchical_graph(
    dependencies: Dict[str, List[str]],
    title: str = "DDC Service Hierarchy"
) -> graphviz.Digraph:
    """Create a hierarchical graph with subgraphs for packages."""
    dot = graphviz.Digraph(comment=title)
    dot.attr(rankdir='TB')  # Top to bottom
    dot.attr('node', shape='box', style='rounded,filled')

    # Group modules by top-level package
    packages: Dict[str, List[str]] = defaultdict(list)
    for module in dependencies.keys():
        pkg = module.split('.')[0]
        packages[pkg].append(module)

    # Create subgraphs for each package
    colors = {
        'services': 'lightblue',
        'app': 'lightgreen',
        'utils': 'lightyellow',
    }

    for pkg, modules in packages.items():
        with dot.subgraph(name=f'cluster_{pkg}') as sub:
            sub.attr(label=pkg.upper(), style='filled', color='lightgray')
            for module in modules:
                color = colors.get(pkg, 'white')
                sub.node(module, module.split('.')[-1], fillcolor=color)

    # Add edges
    for module, deps in dependencies.items():
        for dep in deps:
            if dep in dependencies:  # Only if target exists
                dot.edge(module, dep)

    return dot


def generate_service_hierarchy() -> str:
    """Generate textual service hierarchy documentation."""
    hierarchy = """# DDC Service Hierarchy

## Architecture Overview

DDC follows a layered service-oriented architecture:

```
┌─────────────────────────────────────┐
│          App Layer (Bot/Web)        │
│  - Discord Bot (app.bot)            │
│  - Web UI (app.web_ui)              │
└─────────────────────────────────────┘
               ↓
┌─────────────────────────────────────┐
│       Business Logic Services       │
│  - ConfigService                    │
│  - DockerService                    │
│  - MechService                      │
│  - DonationService                  │
└─────────────────────────────────────┘
               ↓
┌─────────────────────────────────────┐
│         Utility Layer               │
│  - Logging (utils.logging_utils)    │
│  - Performance (utils.performance)   │
│  - Exceptions (services.exceptions) │
└─────────────────────────────────────┘
```

## Service Dependencies

### Top-Level Services

**ConfigService** (services.config):
- No dependencies (foundation service)
- Used by: All other services
- Purpose: Configuration management

**DockerService** (services.docker_service):
- Depends on: ConfigService
- Used by: App layer, MechService
- Purpose: Docker container management

**MechService** (services.mech):
- Depends on: ConfigService, DonationService
- Used by: App layer
- Purpose: Mech evolution and state management

**DonationService** (services.donation):
- Depends on: ConfigService
- Used by: MechService, App layer
- Purpose: Ko-fi integration and power management

### App Layer

**Bot** (app.bot):
- Depends on: All services
- Purpose: Discord bot interface

**Web UI** (app.web_ui):
- Depends on: All services
- Purpose: Web configuration interface

## Dependency Rules

1. **No Circular Dependencies**: Services must not create circular import chains
2. **Layered Architecture**: Lower layers cannot depend on higher layers
3. **Service Isolation**: Services should minimize cross-dependencies
4. **Utility Independence**: Utils should not depend on services

## Import Guidelines

✅ **Allowed**:
```python
# App layer importing services
from services.config.config_service import get_config_service

# Service importing utils
from utils.logging_utils import get_logger

# Service importing another service (same level or lower)
from services.config.config_service import get_config_service
```

❌ **Not Allowed**:
```python
# Service importing app layer
from app.bot import bot_instance  # WRONG

# Circular imports
# services.mech -> services.donation -> services.mech  # WRONG
```

## Service Communication

Services communicate through:
1. **Direct method calls**: For synchronous operations
2. **Async patterns**: For concurrent operations
3. **Singleton pattern**: Services are singletons (get_*_service())
4. **Request/Result pattern**: Typed input/output with dataclasses
"""
    return hierarchy


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Generate DDC dependency graphs"
    )
    parser.add_argument(
        '--output',
        default='docs/dependency_graph',
        help='Output file path (without extension)'
    )
    parser.add_argument(
        '--format',
        choices=['png', 'svg', 'pdf'],
        default='png',
        help='Output format (default: png)'
    )
    parser.add_argument(
        '--level',
        choices=['module', 'service', 'package'],
        default='service',
        help='Aggregation level (default: service)'
    )
    parser.add_argument(
        '--hierarchical',
        action='store_true',
        help='Create hierarchical graph with subgraphs'
    )
    parser.add_argument(
        '--generate-text',
        action='store_true',
        help='Generate textual service hierarchy'
    )

    args = parser.parse_args()

    print("🔍 Analyzing dependencies...")

    # Build dependency graph
    paths = ['services', 'app', 'utils']
    graph = build_dependency_graph(paths)

    if not graph:
        print("Error: No dependencies found", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(graph)} modules")

    # Aggregate if needed
    if args.level != 'module':
        print(f"Aggregating to {args.level} level...")
        graph = aggregate_to_level(graph, args.level)
        print(f"Aggregated to {len(graph)} {args.level}s")

    # Generate graph
    print(f"Generating {'hierarchical ' if args.hierarchical else ''}graph...")

    if args.hierarchical:
        dot = create_hierarchical_graph(graph, "DDC Service Hierarchy")
    else:
        dot = create_graph(graph, "DDC Dependency Graph")

    # Save graph
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        dot.render(str(output_path), format=args.format, cleanup=True)
        print(f"✅ Graph saved to: {output_path}.{args.format}")
    except (RuntimeError) as e:
        print(f"Error: Could not save graph: {e}", file=sys.stderr)
        print("Make sure Graphviz is installed: apt-get install graphviz", file=sys.stderr)
        sys.exit(1)

    # Generate textual hierarchy
    if args.generate_text:
        hierarchy_path = output_path.parent / "SERVICE_HIERARCHY.md"
        with open(hierarchy_path, 'w') as f:
            f.write(generate_service_hierarchy())
        print(f"✅ Service hierarchy saved to: {hierarchy_path}")

    print("\nDone!")


if __name__ == '__main__':
    main()
