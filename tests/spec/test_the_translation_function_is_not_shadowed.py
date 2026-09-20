# -*- coding: utf-8 -*-
"""``_`` stays the translation function wherever it is called.

No ``@covers`` marker: a finding, not a guarantee.

THE FINDING (found while fixing B27, 2026-09-20): in this code base ``_`` is
the translation function, imported at module level. It is also Python's
customary name for a value one does not need - and
``AdminContainerDropdown.callback`` uses it that way: ``embed, view, _ =
await ...``. That single assignment makes ``_`` a LOCAL name for the whole
function, so any ``_("...")`` in it raises UnboundLocalError - before the
assignment as much as after it. I walked into exactly that while adding the
permission check to that callback: the refusal message crashed instead of
being sent, and it took a test run to see it.

Nothing in the tree does this today - the callback uses an alias. This scan
keeps it that way, because the failure is invisible until the line runs, and
the lines in question are the ones that tell a user something went wrong.
"""

import ast
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
DIRECTORIES = ("cogs", "services", "app", "utils")
FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)


def _own_nodes(function):
    """The function's own nodes - what is inside a nested function is its own scope."""
    nested = [node for node in ast.walk(function)
              if isinstance(node, FUNCTIONS) and node is not function]
    skip = {id(node) for parent in nested for node in ast.walk(parent)}
    return [node for node in ast.walk(function) if id(node) not in skip]


def _assigned_and_called(function):
    """Lines where ``_`` is bound and lines where ``_`` is called, same scope."""
    assigned, called = [], []
    for node in _own_nodes(function):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                for name in ast.walk(target):
                    if isinstance(name, ast.Name) and name.id == "_":
                        assigned.append(node.lineno)
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            for name in ast.walk(node.target):
                if isinstance(name, ast.Name) and name.id == "_":
                    assigned.append(node.lineno)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id == "_":
            called.append(node.lineno)
    return sorted(set(assigned)), sorted(set(called))


def _scan():
    shadowed = []
    for directory in DIRECTORIES:
        for path in sorted((PROJECT / directory).rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for function in ast.walk(tree):
                if not isinstance(function, FUNCTIONS):
                    continue
                assigned, called = _assigned_and_called(function)
                if assigned and called:
                    shadowed.append(
                        f"{path.relative_to(PROJECT)}:{function.lineno} {function.name}: "
                        f"_ is bound at {assigned} and called at {called}"
                    )
    return shadowed


SAMPLE = """
from x import _

def careful():
    a, b, translate = 1, 2, 3
    print(_("hello"))

def shadowing():
    a, _ = 1, 2
    print(_("hello"))

def only_discarding():
    a, _ = 1, 2
    print(a)

def nested_is_its_own_scope():
    def inner():
        a, _ = 1, 2
    print(_("hello"))
"""


def test_the_scan_can_tell_these_apart():
    """Guard against a blunt tool: only the shadowing function may be flagged."""
    tree = ast.parse(SAMPLE)
    flagged = [function.name for function in ast.walk(tree) if isinstance(function, FUNCTIONS)
               and all(_assigned_and_called(function))]

    assert flagged == ["shadowing"], f"expected only 'shadowing', got {flagged}"


def test_the_translation_function_is_not_shadowed():
    shadowed = _scan()

    assert not shadowed, (
        "_ is the translation function here; bound as a throwaway it turns every "
        f"_() in the same scope into an UnboundLocalError: {shadowed}"
    )
