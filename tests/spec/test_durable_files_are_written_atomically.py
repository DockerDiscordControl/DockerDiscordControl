# -*- coding: utf-8 -*-
"""
THE FINDING (review C25, section 23 F3 and F4, plus what the scan turned up):
`utils/atomic_io.py` exists precisely so that a crash mid-write can never leave
a config or state file truncated - it says so in its own docstring: "either the
old content or the new one, never neither". Several files that hold durable
state were written straight past it with `Path.write_text()` or
`open(..., 'w')`:

* `services/mech/progress/runtime.py` - the progress config, at FOUR sites. Two
  of them are the recovery path: `load_config` catches a JSONDecodeError on a
  truncated file, logs, resets to the defaults and writes them back with the
  same unprotected call - so the recovery from a torn write can itself be torn,
  and the user's configuration (a non-default timezone, for instance) is
  replaced by the defaults with nothing louder than one ERROR line.
* `services/mech/mech_reset_service.py` - `evolution_mode.json`.
* `services/scheduling/scheduler.py` - the upgrade-state file and the initial
  `tasks.json`.
* `services/mech/progress_paths.py` and `services/donation/unified/reset.py` -
  the sequence counter.

The scan below holds the class shut. Three kinds of plain write stay allowed,
each for a stated reason, because atomicity buys nothing there:

* a temp file that is itself part of an atomic write,
* a marker file whose EXISTENCE is the signal, not its content,
* a cache entry or an export, where a torn file costs a repeat, not data.

The blindness guard (test_the_scan_finds_a_planted_one) checks the scan against
a constructed example, so "no offenders" cannot mean "looked for nothing".

That the atomic helper really is atomic is not re-proved here - it has its own
tests. A first version of this file added one that monkeypatched
atomic_write_text and then called it, which proves nothing about the modules
under test; it was removed rather than kept as a decoration.
"""

import ast
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[2]
SOURCE_DIRS = ("services", "app", "utils", "cogs")

# Plain writes that are allowed, by the name of what they write to, with the
# reason. Anything else must go through utils/atomic_io.
ALLOWED = {
    "marker": "a marker file - its existence is the signal, not its content",
    "unlocked_path": "a cache entry - a torn file costs a regeneration, not data",
    "output_file": "an export the operator asked for - repeatable and visible",
    "event_log": "truncated to empty ON PURPOSE - the reset IS the emptying, so "
                 "there is no previous content an atomic swap could protect",
}


def _is_temp_target(expression: str) -> bool:
    lowered = expression.lower()
    return "tmp" in lowered or "temp" in lowered


def _plain_writes(source: str):
    """(line, target expression) for every write that truncates its target."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "write_text":
            found.append((node.lineno, ast.unparse(func.value)))
        elif isinstance(func, ast.Name) and func.id == "open" and node.args:
            mode = None
            if len(node.args) > 1 and isinstance(node.args[1], ast.Constant):
                mode = node.args[1].value
            for keyword in node.keywords:
                if keyword.arg == "mode" and isinstance(keyword.value, ast.Constant):
                    mode = keyword.value.value
            if isinstance(mode, str) and "w" in mode:
                found.append((node.lineno, ast.unparse(node.args[0])))
    return found


def _offenders(source: str):
    out = []
    for lineno, target in _plain_writes(source):
        if _is_temp_target(target):
            continue
        if target.split(".")[-1] in ALLOWED:
            continue
        out.append((lineno, target))
    return out


def test_no_durable_file_is_written_by_a_plain_write():
    """THE FINDING: a config or state file must survive a crash mid-write."""
    offenders = []
    for directory in SOURCE_DIRS:
        for path in (PROJECT / directory).rglob("*.py"):
            for lineno, target in _offenders(path.read_text(encoding="utf-8")):
                offenders.append(f"{path.relative_to(PROJECT)}:{lineno} -> {target}")

    assert offenders == [], "\n".join(offenders)


def test_the_scan_finds_a_planted_one():
    """BLINDNESS GUARD: the scan must fail on a constructed example."""
    planted = (
        "def f(paths):\n"
        "    paths.config_file.write_text('{}')\n"
        "    with open(paths.state_file, 'w') as fh:\n"
        "        fh.write('x')\n"
    )

    assert _offenders(planted) == [(2, "paths.config_file"), (3, "paths.state_file")]


def test_the_scan_leaves_the_allowed_kinds_alone():
    """BLINDNESS GUARD, other side: the three named exceptions and the temp
    files of an atomic write itself must not be flagged."""
    allowed = (
        "def f(self, marker, output_file, tmp_path):\n"
        "    marker.write_text('x')\n"
        "    with open(output_file, 'w') as fh:\n"
        "        fh.write('x')\n"
        "    with open(tmp_path, 'w') as fh:\n"
        "        fh.write('x')\n"
    )

    assert _offenders(allowed) == []
