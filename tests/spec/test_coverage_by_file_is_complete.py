# -*- coding: utf-8 -*-
"""The coverage ledger names every source file, and its line counts are current.

NO ``@covers`` marker: this is bookkeeping, not a promise to the user.

WHY IT EXISTS: three times this project stated how much of itself had been
reviewed, and three times the answer was wrong. Every one of them counted
SECTION NUMBERS while the section boundaries were being re-cut by the same
work that was counting - so the numbers referred to different code each time.
`docs/quality/COVERAGE_BY_FILE.txt` is keyed by path instead, and this test
keeps it from drifting the way the section numbers did.

THE TRAP AVOIDED HERE, the same one `test_stage4_sections.py` documents:
expectation and claim must not come from the same source. The **claim** is the
ledger. The **expectation** is the tree - every ``.py`` under cogs/, services/,
app/ and utils/, with its real length. Deriving both from the ledger would be a
mirror that stays green while the tree moves underneath it.

WHAT THIS DOES NOT CHECK: whether the evidence in the ledger is true. It cannot
- the packages it was built from live in a session scratchpad that is gone by
now. What it checks is that no file is missing from the ledger and that no
line count has gone stale, which is what let the section-number bookkeeping rot
unnoticed.
"""

from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[2]
LEDGER = PROJECT / "docs" / "quality" / "COVERAGE_BY_FILE.txt"
DIRECTORIES = ("cogs", "services", "app", "utils")


def _claim():
    """{path: lines} as the ledger states it."""
    claimed = {}
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or not line.strip():
            continue
        parts = line.split("\t")
        assert len(parts) >= 2, f"malformed ledger line: {line!r}"
        claimed[parts[0]] = int(parts[1])
    return claimed


def _expectation():
    """{path: lines} as the tree has it. Independent of the ledger."""
    tree = {}
    for directory in DIRECTORIES:
        for path in sorted((PROJECT / directory).rglob("*.py")):
            rel = str(path.relative_to(PROJECT))
            tree[rel] = len(path.read_text(encoding="utf-8", errors="replace").splitlines())
    return tree


def test_both_sides_are_filled():
    """Safeguard against a blunt tool: a scanner reading nothing is green."""
    assert LEDGER.is_file(), f"{LEDGER} is missing"
    assert len(_claim()) > 100, "the ledger reads almost empty - format changed?"
    assert len(_expectation()) > 100, "the tree reads almost empty - wrong path?"


def test_every_source_file_is_in_the_ledger():
    claimed, tree = _claim(), _expectation()

    missing = sorted(set(tree) - set(claimed))
    assert not missing, (
        f"{len(missing)} source file(s) are in no line of the ledger, so nobody "
        f"can say whether they have been reviewed:\n  " + "\n  ".join(missing[:20])
    )

    surplus = sorted(set(claimed) - set(tree))
    assert not surplus, (
        "the ledger names files that do not exist:\n  " + "\n  ".join(surplus[:20])
    )


def test_the_line_counts_are_current():
    """A stale length makes every leftover count in the ledger a lie."""
    claimed, tree = _claim(), _expectation()

    stale = [(path, claimed[path], tree[path]) for path in sorted(tree)
             if path in claimed and claimed[path] != tree[path]]
    assert not stale, (
        f"{len(stale)} file(s) have changed length since the ledger was written; "
        f"regenerate it, because the 'never in a package' counts are computed "
        f"from these numbers:\n  "
        + "\n  ".join(f"{p}: ledger says {was}, file has {now}" for p, was, now in stale[:20])
    )
