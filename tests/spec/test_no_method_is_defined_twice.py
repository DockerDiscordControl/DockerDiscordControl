# -*- coding: utf-8 -*-
"""No class defines the same method twice.

No ``@covers`` marker: a finding, not a guarantee.

THE FINDING (stage 4 review, stage B, section 05 F2, re-checked 2026-09-20):
``DockerControlCog._handle_donate_interaction`` existed twice in the same
class. Python keeps the LAST definition, so the first one - the one that
asks ``is_donations_disabled()`` - never ran, while the live one treats any
value in ``donation_disable_key`` as "donations off", valid or not. Two
versions of the same button handler, one of them silently dead.

This is a scan, not a test of one place: a method defined twice is always
one dead version, and the file that held it is 5,000 lines long.
"""

import ast
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[2]
DIRECTORIES = ("cogs", "services", "app", "utils")
DEFS = (ast.FunctionDef, ast.AsyncFunctionDef)


def _duplicates():
    found = []
    for directory in DIRECTORIES:
        for path in sorted((PROJECT / directory).rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                lines = {}
                for member in node.body:
                    if isinstance(member, DEFS):
                        lines.setdefault(member.name, []).append(member.lineno)
                found += [f"{path.relative_to(PROJECT)}: {node.name}.{name} at {at}"
                          for name, at in lines.items() if len(at) > 1]
    return found


def test_the_scan_sees_the_classes():
    """Guard against a blunt tool: an empty scan would pass trivially."""
    classes = sum(1 for directory in DIRECTORIES
                  for path in (PROJECT / directory).rglob("*.py")
                  for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
                  if isinstance(node, ast.ClassDef))
    assert classes > 100, f"only {classes} classes found - the scan is blind"


def test_no_method_is_defined_twice():
    duplicates = _duplicates()
    assert not duplicates, f"the earlier definition is dead code: {duplicates}"
