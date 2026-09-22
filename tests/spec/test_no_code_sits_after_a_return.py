# -*- coding: utf-8 -*-
"""No statement sits after a return in the same block.

THE FINDING (review 2026-09-22): _validate_yearly ended with `return True`
and was followed by eleven more lines - a copy of the monthly day check,
left behind when the two validators were split. Unreachable code is not
harmless here: a reader trying to understand what a yearly task validates
reads rules that never run, and the next repair may well be made in the copy.

Checked for the whole tree, so the next one cannot settle in either.

COUNTER-CHECK (2026-09-22): a `return True` followed by one line, added to a
scratch file under services/, turns this red.
"""

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DIRECTORIES = ("cogs", "services", "app", "utils")


def _unreachable(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(body, list):
            continue
        for index, statement in enumerate(body[:-1]):
            if isinstance(statement, (ast.Return, ast.Raise, ast.Continue, ast.Break)):
                following = body[index + 1]
                yield f"{path.relative_to(ROOT)}:{following.lineno} after line {statement.lineno}"


def test_nothing_is_written_that_cannot_run():
    found = []
    for directory in DIRECTORIES:
        for path in sorted((ROOT / directory).rglob("*.py")):
            found.extend(_unreachable(path))
    assert not found, "unreachable code:\n" + "\n".join(found)
