# -*- coding: utf-8 -*-
"""No dropdown, view or button is defined that nothing ever builds.

No ``@covers`` marker: a finding, not a guarantee.

THE FINDING (stage 4 review, stage B, section 10 F2, re-checked 2026-09-20):
the reported defect was that the yearly task flow stores the date as one
"DD.MM" string while ``CreateTaskButton`` reads it with ``int(...)``, which
would raise on every yearly task. It cannot happen: the classes that store it
that way - ``YeardayDropdown``, ``ManualDateView``, ``DaySelectDropdown``,
``MonthSelectDropdown``, ``ConfirmDateButton`` - are never built. Nor are
``MonthdayDropdown`` (which cuts 1-31 down to the first 25 with
``options[:25]``, quietly dropping the 26th to the 31st) and ``DateDropdown``.
The flow that really runs asks for day and month separately
(``SimpleMonthdayDropdown`` + ``MonthDropdown``, review B21).

So it is not a crash but a trap: 250 lines of plausible, broken UI that a
reader takes for the live path.
"""

import ast
import re
from functools import lru_cache
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
SOURCE_DIRECTORIES = ("cogs", "services", "app", "utils")
CALL_IN_TEXT = re.compile(r"\b([A-Za-z_]\w*)\s*\(")


UI_BASES = {"View", "Select", "Button", "Modal", "Item", "InputText"}


def _is_ui_base(base):
    """``discord.ui.View`` and a directly imported ``View`` are the same thing."""
    written = ast.unparse(base)
    return written.startswith("discord.ui.") or written in UI_BASES


def _ui_classes():
    """Classes under cogs/ that are a discord.ui element."""
    found = {}
    for path in sorted((PROJECT / "cogs").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and any(_is_ui_base(base) for base in node.bases):
                found[node.name] = f"{path.name}:{node.lineno}"
    return found


@lru_cache(maxsize=1)
def _called_names():
    """Every name that is called anywhere - in the application and in the tests.

    The application code is parsed, which is exact. The test tree is only read
    as text: parsing all of it costs about a minute, and here a rough answer is
    enough - a class the tests build is one that cannot simply be deleted,
    whether the name stands in code or in a string. Class definitions are
    skipped, or every class would look like its own caller.
    """
    called = set()
    for directory in SOURCE_DIRECTORIES:
        for path in (PROJECT / directory).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                function = node.func
                if isinstance(function, ast.Name):
                    called.add(function.id)
                elif isinstance(function, ast.Attribute):
                    called.add(function.attr)
    for path in (PROJECT / "tests").rglob("*.py"):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.lstrip().startswith("class "):
                continue
            called.update(CALL_IN_TEXT.findall(line))
    return called


def test_the_scan_sees_the_live_ones():
    """Guard against a blunt tool: the classes the bot really builds must pass."""
    classes = _ui_classes()
    assert len(classes) > 20, f"only {len(classes)} UI classes found - the scan is blind"
    called = _called_names()
    for name in ("ControlView", "SimpleMonthdayDropdown", "CreateTaskButton"):
        assert name in classes and name in called, f"{name} should be seen as built"


def test_every_ui_class_is_ever_built():
    classes = _ui_classes()
    never_built = sorted(f"{name} ({where})" for name, where in classes.items()
                         if name not in _called_names())

    assert not never_built, f"nothing ever builds these, so they are dead: {never_built}"
