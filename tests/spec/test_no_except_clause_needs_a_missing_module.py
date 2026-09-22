# -*- coding: utf-8 -*-
"""
THE FINDING (review C17, section 30 F1 and F2): three modules import an
optional library defensively -

    try:
        import docker
    except ImportError:
        docker = None  # Handle missing docker library gracefully

- and then name that very module inside an except clause:

    except (AttributeError, ..., docker.errors.APIError,
            docker.errors.DockerException) as e:

Python builds the except tuple only when an exception is actually being
matched. If the library is missing, `docker` is None, and building the tuple
raises `AttributeError: 'NoneType' object has no attribute 'errors'` - at the
exact moment the handler was supposed to rescue the situation. The original
error is replaced by a new one that nothing catches, so the "graceful" path is
the one that brings the request down.

`_get_config_cache_stats` does not even touch Docker; the clause was carried
along. The same shape sits in `mech_status_details_service` (discord) and in
`member_count/service.py` (discord).

The scan below holds the whole class shut. Its blindness guard
(test_the_scan_finds_a_planted_one) checks the scan on a constructed example,
so a scan that finds nothing because it looks for nothing cannot pass.
"""

import ast
import re
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[2]
SOURCE_DIRS = ("services", "app", "cogs", "utils")


def _optional_modules(tree: ast.AST) -> set:
    """Names a module sets to None when an import fails."""
    optional = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        for handler in node.handlers:
            for statement in handler.body:
                if not isinstance(statement, ast.Assign):
                    continue
                if not (isinstance(statement.value, ast.Constant)
                        and statement.value.value is None):
                    continue
                for target in statement.targets:
                    if isinstance(target, ast.Name):
                        optional.add(target.id)
    return optional


def _root_name(node: ast.AST):
    while isinstance(node, ast.Attribute):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def _handlers_needing(tree: ast.AST, names: set) -> list:
    """except clauses whose type expression reads an attribute of such a name."""
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler) or node.type is None:
            continue
        parts = node.type.elts if isinstance(node.type, ast.Tuple) else [node.type]
        for part in parts:
            if isinstance(part, ast.Attribute) and _root_name(part) in names:
                found.append((node.lineno, ast.unparse(part)))
    return found


def _scan(source: str) -> list:
    tree = ast.parse(source)
    optional = _optional_modules(tree)
    return _handlers_needing(tree, optional) if optional else []


def _python_files():
    for directory in SOURCE_DIRS:
        yield from (PROJECT / directory).rglob("*.py")


def test_no_except_clause_depends_on_an_optional_module():
    """THE FINDING: an except clause must be buildable when the library it
    names is not installed."""
    offenders = []
    for path in _python_files():
        for lineno, expression in _scan(path.read_text(encoding="utf-8")):
            offenders.append(f"{path.relative_to(PROJECT)}:{lineno} {expression}")

    assert offenders == [], "\n".join(offenders)


def test_the_scan_finds_a_planted_one():
    """BLINDNESS GUARD: the scan must fail on a constructed example, so an
    empty result means "none left", not "looked for nothing"."""
    planted = (
        "try:\n"
        "    import docker\n"
        "except ImportError:\n"
        "    docker = None\n"
        "\n"
        "def f():\n"
        "    try:\n"
        "        pass\n"
        "    except (RuntimeError, docker.errors.APIError):\n"
        "        pass\n"
    )

    assert _scan(planted) == [(9, "docker.errors.APIError")]


def test_the_scan_leaves_a_normal_import_alone():
    """BLINDNESS GUARD, other side: a library imported normally may of course
    be named in an except clause."""
    normal = (
        "import docker\n"
        "\n"
        "def f():\n"
        "    try:\n"
        "        pass\n"
        "    except (RuntimeError, docker.errors.APIError):\n"
        "        pass\n"
    )

    assert _scan(normal) == []


def test_the_handler_survives_a_missing_library(monkeypatch):
    """The finding in the concrete: with docker missing, the handler in
    _get_config_cache_stats must still work."""
    from services.web import performance_stats_service as module

    monkeypatch.setattr(module, "docker", None)
    service = module.PerformanceStatsService()

    def _boom():
        raise KeyError("cache gone")

    monkeypatch.setattr("utils.config_cache.get_cache_memory_stats", _boom)

    stats = service._get_config_cache_stats()

    assert 'error' in stats
