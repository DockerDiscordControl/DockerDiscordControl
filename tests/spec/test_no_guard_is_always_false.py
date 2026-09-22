# -*- coding: utf-8 -*-
"""No ``if <name>:`` guards a block that can never run.

No ``@covers`` marker: a finding, not a guarantee.

THE FINDING (stage 4 review, stage B, section 04 F2, re-checked 2026-09-20):
``periodic_message_edit_loop`` creates ``all_container_names = set()`` and
later asks ``if all_container_names:`` to pre-load the status cache "before N
message edits". Nothing in between ever puts a name into that set - the code
that once did is the branch that now skips and deletes per-container message
entries. So the guard is always false, the pre-load never happens, and the
log line that announces it can never be written. The cache is kept correct a
few lines further down by ``_ensure_status_cache_fresh()``, so nothing is
rendered stale; what is wrong is that the file describes work it does not do.

This is a scan, not a test of one place: a block behind an always-false
guard is dead whatever it contains, and reading a 5,000-line file top to
bottom is how such a block survives.
"""

import ast
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
DIRECTORIES = ("cogs", "services", "app", "utils")
FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)
EMPTY_CALLS = {"set", "list", "dict", "tuple", "frozenset"}


def _is_empty_container(node):
    """True for ``[]``, ``{}``, ``()``, ``set()``, ``dict()`` and friends."""
    if isinstance(node, (ast.List, ast.Dict, ast.Set, ast.Tuple)):
        return not (getattr(node, "elts", None) or getattr(node, "keys", None))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        return node.func.id in EMPTY_CALLS and not node.args and not node.keywords
    return False


def _bound_once_to_something_empty(function):
    """Local names that get an empty container exactly once and never again."""
    bindings = {}
    for node in ast.walk(function):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    bindings.setdefault(target.id, []).append(node)
        elif isinstance(node, (ast.AugAssign, ast.AnnAssign)) and isinstance(node.target, ast.Name):
            bindings.setdefault(node.target.id, []).append(node)
        elif isinstance(node, ast.For) and isinstance(node.target, ast.Name):
            bindings.setdefault(node.target.id, []).append(node)
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                if isinstance(item.optional_vars, ast.Name):
                    bindings.setdefault(item.optional_vars.id, []).append(node)
    return {name: bound[0] for name, bound in bindings.items()
            if len(bound) == 1 and isinstance(bound[0], ast.Assign)
            and _is_empty_container(bound[0].value)}


def _body_lines(node):
    ends = [child.end_lineno for child in ast.walk(node.body[-1])
            if getattr(child, "end_lineno", None)]
    return range(node.body[0].lineno, max(ends) + 1)


def _dead_guards_in(path, function):
    """``if name:`` where nothing outside that very block can fill ``name``."""
    empty = _bound_once_to_something_empty(function)
    if not empty:
        return []
    dead = []
    for node in ast.walk(function):
        test = getattr(node, "test", None)
        if not isinstance(node, (ast.If, ast.While)) or not isinstance(test, ast.Name):
            continue
        if test.id not in empty:
            continue
        inside = _body_lines(node)
        # Anything that touches the name outside its own block - a call that
        # could fill it, an .add(), a read - makes this too close to call.
        touched = False
        for other in ast.walk(function):
            if isinstance(other, ast.Name) and other.id == test.id:
                if other is test or other is empty[test.id].targets[0]:
                    continue
                touched = touched or other.lineno not in inside
            elif isinstance(other, ast.Attribute) and isinstance(other.value, ast.Name) \
                    and other.value.id == test.id:
                touched = touched or other.lineno not in inside
        if not touched:
            dead.append(
                f"{path}:{node.lineno} {function.name}: 'if {test.id}:' can never be true - "
                f"{test.id} is empty from line {empty[test.id].lineno} on"
            )
    return dead


def _scan():
    found = []
    for directory in DIRECTORIES:
        for path in sorted((PROJECT / directory).rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for function in ast.walk(tree):
                if isinstance(function, FUNCTIONS):
                    found += _dead_guards_in(path.relative_to(PROJECT), function)
    return found


SAMPLE = """
def filled():
    names = set()
    for item in (1, 2):
        names.add(item)
    if names:
        print(names)

def never_filled():
    names = set()
    if names:
        print(names)
"""


def test_the_scan_can_tell_the_two_apart():
    """Guard against a blunt tool: it must see the dead one and only that one."""
    tree = ast.parse(SAMPLE)
    hits = [hit for function in ast.walk(tree) if isinstance(function, FUNCTIONS)
            for hit in _dead_guards_in("sample.py", function)]
    assert len(hits) == 1, f"expected exactly the dead guard, got {hits}"
    assert "never_filled" in hits[0], hits[0]


def test_no_guard_is_always_false():
    dead = _scan()
    assert not dead, f"the code behind these guards can never run: {dead}"
