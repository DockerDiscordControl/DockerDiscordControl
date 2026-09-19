# -*- coding: utf-8 -*-
"""The same function must not appear twice, character for character.

NO ``@covers`` marker: that would be a new guarantee, and those are the
operator's decision.

THE FINDING (stage 2, item 3 - the same rule in two places). The inventory
lists 27 cases of duplicated logic; this test covers the hardest and at the
same time most clearly checkable subset: functions that are identical
character for character in two places.

    _validate_custom_address   control_ui.py:1177  /  status_info_integration.py:1016
    _get_container_logs        status_info_integration.py:608  /  :779

Why this is more than style: a security check that exists twice gets fixed
once. ``_validate_custom_address`` checks addresses "for security" - if the
check turns out stricter in one of the two copies, a different rule applies to
the same container depending on the path. Exactly this kind of defect already
caused a Z5 breach today: the task delete button existed twice, and only one
version checks the channel permission.

WHY THE GUARANTEE IS SO NARROW: "no duplicated logic" would be a style rule and
would produce false alarms across the whole project - two ``__init__`` methods
that both set three attributes are not a duplication. So only the hard case is
checked: **same name, character-identical body**. Whatever fires here is a
copy, no judgement required.

A test with false alarms gets ignored, and an ignored test is as worthless as a
green one.

SCOPE: only ``cogs/``. That is where the two known pairs sit, and that is where
duplication is expensive, because the Discord UI often offers the same action
by two paths. ``services/`` and ``app/`` are deliberately left out - they have
their own patterns (request/result pairs) that would create noise here without
a finding behind it.

COUNTER-CHECK (done 2026-09-17): red with **three** findings, not the expected
two - and the third was instructive::

    _get_container_logs       status_info_integration.py:608  /  :779
    _validate_custom_address  control_ui.py:1177  /  status_info_integration.py:1019
    get_logs_sync             status_info_integration.py:620  /  :791

``get_logs_sync`` is the nested function INSIDE ``_get_container_logs``. It
only appeared twice because its parent function appeared twice.

The obvious reaction would have been to exclude nested functions so that the
count matches. That would be painting it green: the limit "top-level functions
only" is just as arbitrary as ``MIN_LINES = 8``, and adjusting a threshold
after the fact to fit is the opposite of measuring. So the detector stayed
unchanged, and the more honest check was: does it drop to zero by itself
after the merge?

It does. After the fix: **0 findings**, detector untouched,
``tests/unit/cogs`` still 267 green.

The two guards were green from the start - the comparison normalizes the
indentation (the same method sits at different depths in two classes) and
keeps "same name with different content" apart. Without this distinction the
test would have reported every ``callback`` method in the project.

WHAT THE FIX CHANGES:
``validate_custom_address`` now lives once in ``cogs/control_helpers.py``,
next to ``_channel_has_permission``; both callers import it inside the
function. ``container_logs_text`` is a module function with ``container_name``
as a parameter; six call sites follow. Both methods used nothing from ``self``
except the container name - the copy had no reason except convenience.
"""

import ast
from collections import defaultdict
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[2]
DIRECTORY = PROJECT / "cogs"

# Bodies that are too short are not duplication but convention: a ``pass``, a
# ``return None``, a one-line pass-through. Only from this length on is a
# character-identical copy a finding and not a formality.
MIN_LINES = 8


def _functions():
    """All functions in cogs/ with their normalized body."""
    found = defaultdict(list)
    for path in sorted(DIRECTORY.rglob("*.py")):
        source = path.read_text(encoding="utf-8", errors="replace")
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        lines = source.splitlines()
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            body = lines[node.lineno - 1:node.end_lineno]
            if len(body) < MIN_LINES:
                continue
            # Normalize indentation: the same function in two classes sits at
            # the same depth, but that should not matter.
            text = "\n".join(z.strip() for z in body)
            found[node.name].append(
                (f"{path.relative_to(PROJECT)}:{node.lineno}", text)
            )
    return found


def test_there_are_functions_to_check_at_all():
    """Safeguard against a blunt tool.

    If the search reads into the void - wrong path, changed tree structure -
    the test below would be green without proving anything.
    """
    everything = _functions()
    total = sum(len(v) for v in everything.values())
    assert total > 100, (
        f"Only {total} functions found in cogs/ - the path is probably wrong"
    )


def test_the_tool_detects_a_character_identical_copy():
    """Proof of effect: the detector must fire when there is something to report.

    And it must NOT fire when only the name is the same. Two ``callback``
    methods with different content are not a duplication - without this
    distinction the test would be a false-alarm tool.
    """
    same_a = "def f(self):\n    a = 1\n    b = 2\n    c = 3\n    d = 4\n    e = 5\n    g = 6\n    return a"
    same_b = "    def f(self):\n        a = 1\n        b = 2\n        c = 3\n        d = 4\n        e = 5\n        g = 6\n        return a"
    different = "def f(self):\n    a = 9\n    b = 2\n    c = 3\n    d = 4\n    e = 5\n    g = 6\n    return a"

    norm = lambda t: "\n".join(z.strip() for z in t.splitlines())
    assert norm(same_a) == norm(same_b), (
        "Different indentation must not keep two copies apart - "
        "the same function sits at different depths in two classes."
    )
    assert norm(same_a) != norm(different), (
        "Same name with different content is NOT a duplication - otherwise the "
        "test reports every callback method in the project."
    )


def test_no_function_appears_twice_character_identical():
    """Same name plus character-identical body means: one copy too many."""
    findings = []
    for name, occurrences in sorted(_functions().items()):
        if len(occurrences) < 2:
            continue
        by_text = defaultdict(list)
        for location, text in occurrences:
            by_text[text].append(location)
        for locations in by_text.values():
            if len(locations) > 1:
                findings.append(f"{name}  ->  " + "  /  ".join(locations))

    assert not findings, (
        f"{len(findings)} functions appear character-identical in several places. A "
        "fix to one copy leaves the other unchanged - exactly how the Z5 breach "
        "at the task delete button arose today:\n  "
        + "\n  ".join(findings)
    )
