# -*- coding: utf-8 -*-
"""The stage 4 sectioning covers the application code without gaps.

NO ``@covers`` marker: that would be a new guarantee, and those are the
operator's decision.

WHAT THIS IS ABOUT: stage 4 requires a review with verifiable coverage.
For that, the application code is split in ``docs/quality/SECTIONS.txt`` into
sections of at most 2000 lines. The proof is only worth as much as the
guarantee that this list REALLY covers the tree completely - otherwise a
section is overlooked and nobody notices.

THE TRAP AVOIDED HERE: expectation and claim must not come from the same
source. The **claim** is SECTIONS.txt. The **expectation** is the tree
itself - all ``.py`` under cogs/, services/, app/, utils/ with their real line
counts. Deriving both from the section file would be a mirror test; exactly
such a one slipped past me today in the wiring test and stayed green with the
CSRF protection removed.

COUNTER-CHECK (carried out 2026-09-17): this test is green from the start - the
guarantee does hold right now. Its value therefore depends entirely on whether
it can bite at all. Four mutations of SECTIONS.txt, each on its own::

    file removed from the list          -> 1 failed
    gap torn open (range from 5)        -> 1 failed
    coverage ends before end of file    -> 1 failed
    section artificially over 2000 l.   -> 2 failed

The fourth turns two tests red, because an inflated range also falsifies the
coverage. Restored: 3 green, file bit-identical to the backup.

Without this check it would be a test that cannot fail - exactly the kind
that stage 3 weeds out. In the wiring test (test_app_factory_wiring.py) the
first version really was one: it took expectation AND claim from the same file
and stayed green with the CSRF protection removed.

SECTION STATUS: 37 sections, 188 pieces, 60,369 of 60,369 lines in
183 files. Four files exceed 2000 lines and had to be split;
``DockerControlCog`` is a SINGLE class of 4,485 lines and can only be cut
at method boundaries - a structural finding of its own, recorded in the
stage 4 report.
"""

import re
from collections import defaultdict
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[2]
SECTIONS = PROJECT / "docs" / "quality" / "SECTIONS.txt"
DIRECTORIES = ("cogs", "services", "app", "utils")
LIMIT = 2000

LINE = re.compile(r"^(?P<path>[^:#]+\.py):(?P<start>\d+)-(?P<end>\d+)\s*$")


def _claim():
    """What SECTIONS.txt claims: {path: [(start, end), ...]}, plus section sizes."""
    pieces = defaultdict(list)
    sizes, current = [], 0
    for line in SECTIONS.read_text(encoding="utf-8").splitlines():
        if line.startswith("## Section"):
            if current:
                sizes.append(current)
            current = 0
            continue
        hit = LINE.match(line)
        if not hit:
            continue
        start, end = int(hit["start"]), int(hit["end"])
        pieces[hit["path"]].append((start, end))
        current += end - start + 1
    if current:
        sizes.append(current)
    return dict(pieces), sizes


def _expectation():
    """What the tree yields: {path: line_count}. Independent of the section file."""
    tree = {}
    for directory in DIRECTORIES:
        for path in sorted((PROJECT / directory).rglob("*.py")):
            rel = str(path.relative_to(PROJECT))
            tree[rel] = len(path.read_text(encoding="utf-8", errors="replace").splitlines())
    return tree


def test_both_sides_are_filled():
    """Safeguard against a blunt tool.

    If one of the two sides reads into nothing - wrong path, changed format -
    the tests below would be green without proving anything.
    """
    assert SECTIONS.is_file(), f"{SECTIONS} is missing"
    pieces, sizes = _claim()
    tree = _expectation()
    assert len(sizes) > 20, f"Only {len(sizes)} sections read - format changed?"
    assert len(pieces) > 100, f"Only {len(pieces)} files in the list - format changed?"
    assert len(tree) > 100, f"Only {len(tree)} files found in the tree - wrong path?"


def test_no_section_is_too_large():
    """At most 2000 lines - otherwise it cannot be read in one go."""
    _, sizes = _claim()
    too_large = [(i + 1, g) for i, g in enumerate(sizes) if g > LIMIT]
    assert not too_large, f"Sections over {LIMIT} lines: {too_large}"


def test_every_source_file_is_in_exactly_one_section():
    """Without gaps and without overlaps - checked against the TREE."""
    pieces, _ = _claim()
    tree = _expectation()

    missing = sorted(set(tree) - set(pieces))
    assert not missing, (
        f"{len(missing)} source files are in NO section and would be overlooked "
        f"in the review:\n  " + "\n  ".join(missing[:20])
    )

    surplus = sorted(set(pieces) - set(tree))
    assert not surplus, (
        "The section list names files that do not exist - a review would "
        f"run into nothing there:\n  " + "\n  ".join(surplus[:20])
    )

    defects = []
    for path, line_count in sorted(tree.items()):
        ranges = sorted(pieces[path])
        # without gaps from 1 to the end of the file, without overlap
        expected = 1
        for start, end in ranges:
            if start != expected:
                defects.append(
                    f"{path}: {'gap' if start > expected else 'overlap'} "
                    f"at line {expected} (next piece starts at {start})"
                )
                break
            expected = end + 1
        else:
            if expected - 1 != line_count:
                defects.append(
                    f"{path}: coverage ends at {expected - 1}, file has {line_count} lines"
                )
    assert not defects, (
        f"{len(defects)} files are not covered without gaps:\n  "
        + "\n  ".join(defects[:20])
    )
