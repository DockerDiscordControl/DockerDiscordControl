# -*- coding: utf-8 -*-
"""R2 - Every guarantee has at least one test.

This test does not cover a single guarantee but programme rule R2 from
SPEC.md: no guarantee may remain without a marker. The prompt names it
explicitly - "another test can check that at least one such marker exists for
every guarantee".

Why this is necessary, with evidence: the state "three guarantees have no
test" was only noticed today because a grep happened to run during a recount.
Exactly this pattern - something is on no list, so nobody looks at it - is the
central warning from stage 4 of the programme, and it occurred three times in
this session (18 forgotten test files, a truncated search list, and this very
gap).

The marker must be a standalone comment line, i.e. ``# @covers Z<number>`` at
the start of the line. Running text in a docstring does NOT count - otherwise
this test would have counted itself as coverage, and that is exactly what
happened to the original grep.

This test is RED when it is created, and that is its purpose: it names the
gap instead of hiding it. It only turns green once Z6, Z9 and Z10 have tests.
"""

import re
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[2]
SPEC = PROJECT / "SPEC.md"
TESTS = PROJECT / "tests"

# Standalone comment line, number mandatory. Without \d+ the running text of
# this docstring would count as a match.
MARKER = re.compile(r"^#\s*@covers\s+Z(\d+)\s*$", re.MULTILINE)
HEADING = re.compile(r"^###\s+Z(\d+)\s+—", re.MULTILINE)


def _guarantees() -> set[str]:
    """All Z numbers from SPEC.md."""
    return {f"Z{n}" for n in HEADING.findall(SPEC.read_text(encoding="utf-8"))}


def _markers() -> dict[str, list[str]]:
    """Z number -> files that mark it."""
    found: dict[str, list[str]] = {}
    for file in sorted(TESTS.rglob("test_*.py")):
        for number in MARKER.findall(file.read_text(encoding="utf-8", errors="replace")):
            found.setdefault(f"Z{number}", []).append(str(file.relative_to(PROJECT)))
    return found


def test_spec_contains_any_guarantees_at_all():
    """Safeguard against a blunt tool.

    If the pattern no longer finds any headings - say because someone changes
    the formatting of the SPEC -, the two tests below would run empty and check
    nothing any more.
    """
    guarantees = _guarantees()
    assert len(guarantees) >= 8, (
        f"Only {len(guarantees)} guarantees found in SPEC.md - the search pattern "
        f"probably no longer matches the headings: {sorted(guarantees)}"
    )


def test_every_guarantee_has_at_least_one_test():
    """No guarantee without a marker."""
    guarantees = _guarantees()
    marked = _markers()
    without = sorted(guarantees - marked.keys(), key=lambda z: int(z[1:]))

    assert not without, (
        f"Without a test: {', '.join(without)}. A guarantee without a test is a "
        f"declaration of intent - it cannot be broken, because nobody "
        f"checks. Covered are: "
        f"{', '.join(sorted(marked, key=lambda z: int(z[1:])))}"
    )


def test_no_marker_points_nowhere():
    """Every marker refers to a guarantee that exists.

    Catches typos: ``@covers Z11`` looks like coverage but covers nothing if
    there is no Z11.
    """
    guarantees = _guarantees()
    marked = _markers()
    orphaned = {z: files for z, files in marked.items() if z not in guarantees}

    assert not orphaned, (
        f"Markers without a matching guarantee in SPEC.md: {orphaned}"
    )
