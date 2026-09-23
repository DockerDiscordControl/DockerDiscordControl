# -*- coding: utf-8 -*-
"""A test that freezes a clock freezes the one its code actually reads.

THE BUG CLASS, seen twice on 2026-09-23/24 and both times self-inflicted.

The spam-protection service was moved from `time.time()` to `time.monotonic()`
that morning, so that a wall-clock correction could not brake every button.
Two tests went on doing

    monkeypatch.setattr(time, "time", lambda: NOW)

and then asserting that the refusal states exactly the slider value - "wait
5.0 more". The freeze froze nothing. They stayed green because almost no real
time passes between recording a cooldown and pressing the button, and one of
them went red under the load of a full group run three weeks' worth of tests
later. Green by luck, in a suite whose whole point is to have none of that.

Freezing the wrong clock is invisible: nothing raises, nothing warns, and the
assertion usually still holds. Only the margin disappears.

WHAT THIS CHECKS: every `monkeypatch.setattr(<module>, "time"|"monotonic", …)`
in the suite, resolved to the production module it names, against which clock
that module actually calls. A test freezing a clock its module never reads is
red, by name.

WHAT IT CANNOT CHECK, and says so rather than pretending: a patch on the
stdlib `time` module itself carries no hint of which code it is for, and an
alias this file cannot resolve is skipped. The count of skipped patches is
asserted to stay small, so the check cannot quietly degrade into covering
nothing.

COUNTER-CHECK (2026-09-24): red before the two fixes, naming
test_unbraked_mech_buttons_brake.py and test_mech_details_has_a_slider.py.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TESTS = ROOT / "tests"
SOURCES = ("services", "cogs", "app", "utils")

PATCH = re.compile(r'setattr\(\s*([\w.]+)\s*,\s*"(time|monotonic)"')
CALLS_TIME = re.compile(r"\btime\.time\(\)")
CALLS_MONOTONIC = re.compile(r"\btime\.monotonic\(\)")


def _clocks_each_module_reads():
    """{module stem: {"time", "monotonic"}} for the production code."""
    reads = {}
    for directory in SOURCES:
        for path in (ROOT / directory).rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="replace")
            clocks = set()
            if CALLS_TIME.search(text):
                clocks.add("time")
            if CALLS_MONOTONIC.search(text):
                clocks.add("monotonic")
            if clocks:
                reads[path.stem] = reads.get(path.stem, set()) | clocks
    return reads


def _module_behind(alias, test_source):
    """The production module an alias in a test refers to, or None."""
    stem = alias.split(".")[0]
    for pattern in (rf"import\s+([\w.]+)\s+as\s+{re.escape(stem)}\b",
                    rf"from\s+([\w.]+)\s+import\s+[^\n]*\b{re.escape(stem)}\b"):
        found = re.search(pattern, test_source)
        if found:
            return found.group(1).split(".")[-1]
    return stem


def _survey():
    reads = _clocks_each_module_reads()
    mismatched, checked, skipped = [], 0, 0
    for path in sorted(TESTS.rglob("test_*.py")):
        source = path.read_text(encoding="utf-8", errors="replace")
        for alias, clock in sorted(set(PATCH.findall(source))):
            module = _module_behind(alias, source)
            known = reads.get(module)
            if not known:
                skipped += 1
                continue
            checked += 1
            if clock not in known:
                mismatched.append(
                    f"{path.name}: freezes {clock} on {alias}, but {module}.py "
                    f"reads {sorted(known)}")
    return mismatched, checked, skipped


def test_the_scan_sees_something():
    """Safeguard against a blunt tool: a scan resolving nothing is green."""
    _mismatched, checked, _skipped = _survey()

    assert checked >= 8, (
        f"only {checked} clock patches could be resolved - the import shapes "
        f"changed and this check is no longer looking at anything")


def test_no_test_freezes_a_clock_its_code_does_not_read():
    """THE BUG CLASS: the freeze does nothing and the test stays green on
    timing luck alone."""
    mismatched, _checked, _skipped = _survey()

    assert mismatched == [], (
        f"{len(mismatched)} test(s) freeze a clock the code never reads, so "
        f"the freeze does nothing:\n  " + "\n  ".join(mismatched))


def test_the_unresolvable_ones_stay_a_minority():
    """A patch on the stdlib time module itself names no code, so it cannot be
    checked. That is honest; letting the number grow until the check covers
    nothing is not."""
    _mismatched, checked, skipped = _survey()

    assert skipped <= checked, (
        f"{skipped} clock patches could not be traced to a module against "
        f"{checked} that could - this check is losing its grip")
