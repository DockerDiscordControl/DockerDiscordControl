#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Exception Handler Analyzer                     #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""
Analyze generic Exception handlers in the codebase.

This tool identifies generic 'except Exception:' blocks and suggests
specific custom exceptions to use instead.

Usage:
    python tools/analyze_exception_handlers.py
    python tools/analyze_exception_handlers.py --detailed
    python tools/analyze_exception_handlers.py --suggest-replacements
"""

import ast
import sys
from pathlib import Path
from typing import List, Dict, Tuple
from collections import defaultdict
import argparse


class ExceptionHandlerVisitor(ast.NodeVisitor):
    """AST visitor to find exception handlers."""

    def __init__(self, filename: str):
        self.filename = filename
        self.handlers: List[Dict] = []
        self.current_function = None

    def visit_FunctionDef(self, node: ast.FunctionDef):
        """Track current function context."""
        old_function = self.current_function
        self.current_function = node.name
        self.generic_visit(node)
        self.current_function = old_function

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        """Track current async function context."""
        old_function = self.current_function
        self.current_function = node.name
        self.generic_visit(node)
        self.current_function = old_function

    def visit_ExceptHandler(self, node: ast.ExceptHandler):
        """Visit exception handlers."""
        # Check if it's a generic Exception handler
        is_generic = False
        exception_type = "bare except"

        if node.type is None:
            # Bare except:
            is_generic = True
        elif isinstance(node.type, ast.Name) and node.type.id == "Exception":
            # except Exception:
            is_generic = True
            exception_type = "Exception"

        if is_generic:
            # Try to extract context from the handler body
            context = self._extract_context(node)

            self.handlers.append({
                'line': node.lineno,
                'function': self.current_function or '<module>',
                'exception_type': exception_type,
                'context': context
            })

        self.generic_visit(node)

    def _extract_context(self, node: ast.ExceptHandler) -> str:
        """Extract context from exception handler body."""
        # Look for logger calls, error messages, etc.
        context_parts = []

        for stmt in node.body:
            # Look for logger calls
            if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
                if isinstance(stmt.value.func, ast.Attribute):
                    if stmt.value.func.attr in ['error', 'warning', 'critical']:
                        # Extract message
                        if stmt.value.args:
                            if isinstance(stmt.value.args[0], ast.Constant):
                                context_parts.append(stmt.value.args[0].value)

        return ' | '.join(context_parts[:2]) if context_parts else "No context"


def analyze_file(file_path: Path) -> List[Dict]:
    """Analyze a Python file for generic exception handlers."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            tree = ast.parse(f.read(), filename=str(file_path))

        visitor = ExceptionHandlerVisitor(str(file_path))
        visitor.visit(tree)

        return visitor.handlers

    except (SyntaxError, OSError, IOError, PermissionError, UnicodeDecodeError) as e:
        print(f"Warning: Could not parse {file_path}: {e}", file=sys.stderr)
        return []


def suggest_replacement(context: str, filename: str) -> str:
    """Suggest a specific exception based on context."""
    context_lower = context.lower()
    filename_lower = str(filename).lower()

    # Config-related
    if 'config' in filename_lower or 'config' in context_lower:
        if 'load' in context_lower or 'read' in context_lower:
            return "ConfigLoadError"
        elif 'save' in context_lower or 'write' in context_lower:
            return "ConfigSaveError"
        elif 'validate' in context_lower or 'invalid' in context_lower:
            return "ConfigValidationError"
        return "ConfigServiceError"

    # Docker-related
    if 'docker' in filename_lower or 'container' in context_lower:
        if 'connect' in context_lower or 'connection' in context_lower:
            return "DockerConnectionError"
        elif 'timeout' in context_lower:
            return "DockerTimeoutError"
        elif 'not found' in context_lower:
            return "DockerContainerNotFoundError"
        return "DockerServiceError"

    # Donation-related
    if 'donation' in filename_lower:
        if 'validate' in context_lower or 'invalid' in context_lower:
            return "DonationValidationError"
        elif 'process' in context_lower:
            return "DonationProcessingError"
        return "DonationServiceError"

    # Mech-related
    if 'mech' in filename_lower:
        if 'animation' in context_lower:
            return "MechAnimationError"
        elif 'state' in context_lower:
            return "MechStateError"
        return "MechServiceError"

    # Scheduler-related
    if 'schedul' in filename_lower:
        return "SchedulerServiceError"

    # Generic fallback
    return "ServiceError"


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Analyze generic Exception handlers"
    )
    parser.add_argument(
        '--detailed',
        action='store_true',
        help='Show detailed analysis with context'
    )
    parser.add_argument(
        '--suggest-replacements',
        action='store_true',
        help='Suggest specific exception replacements'
    )
    parser.add_argument(
        '--top',
        type=int,
        default=20,
        help='Show top N files with most generic handlers'
    )

    args = parser.parse_args()

    print("🔍 Analyzing generic Exception handlers...\n")

    # Find all Python files
    base_path = Path.cwd()
    paths = ['services', 'app', 'utils']

    all_handlers: Dict[str, List[Dict]] = {}
    total_count = 0

    for path_str in paths:
        path = base_path / path_str
        if not path.exists():
            continue

        for py_file in path.rglob('*.py'):
            handlers = analyze_file(py_file)
            if handlers:
                relative_path = str(py_file.relative_to(base_path))
                all_handlers[relative_path] = handlers
                total_count += len(handlers)

    # Summary
    total_files = sum(
        len(list((base_path / path_str).rglob('*.py')))
        for path_str in paths
        if (base_path / path_str).exists()
    )
    print(f"📊 Summary:")
    print(f"  Total files analyzed: {total_files}")
    print(f"  Files with generic handlers: {len(all_handlers)}")
    print(f"  Total generic handlers: {total_count}\n")

    # Top files
    sorted_files = sorted(
        all_handlers.items(),
        key=lambda x: len(x[1]),
        reverse=True
    )[:args.top]

    print(f"📁 Top {args.top} files with most generic Exception handlers:\n")
    for i, (filename, handlers) in enumerate(sorted_files, 1):
        print(f"{i:3}. {filename}: {len(handlers)} handlers")

    print()

    # Detailed analysis
    if args.detailed or args.suggest_replacements:
        print("📝 Detailed Analysis:\n")

        for filename, handlers in sorted_files[:10]:  # Show top 10 in detail
            print(f"{'='*80}")
            print(f"File: {filename}")
            print(f"Generic handlers: {len(handlers)}")
            print(f"{'='*80}")

            for handler in handlers[:5]:  # Show first 5 per file
                print(f"\n  Line {handler['line']} in {handler['function']}():")
                print(f"    Type: {handler['exception_type']}")
                if args.detailed:
                    print(f"    Context: {handler['context']}")

                if args.suggest_replacements:
                    suggestion = suggest_replacement(handler['context'], filename)
                    print(f"    💡 Suggested: {suggestion}")

            if len(handlers) > 5:
                print(f"\n  ... and {len(handlers) - 5} more")

            print()

    # Recommendations
    print("\n💡 Recommendations:\n")
    print("1. Replace generic 'except Exception:' with specific custom exceptions")
    print("2. Use exceptions from services/exceptions.py")
    print("3. Add context and helpful error messages")
    print("4. Log errors with appropriate severity")
    print("5. Consider error recovery strategies")
    print("\nSee docs/ERROR_HANDLING.md for migration guide.")
    print(f"\nTotal handlers to refactor: {total_count}")


if __name__ == '__main__':
    main()
