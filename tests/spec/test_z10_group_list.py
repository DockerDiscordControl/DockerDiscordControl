# -*- coding: utf-8 -*-
# @covers Z10
"""Z10, second part - the group list must not drift.

The CI gate runs ``tests/GROUPS.txt`` line by line, because several groups in
one shared pytest run break the collection (the reason is given in the file
itself). So the question "is everything tested at all?" hangs on a hand-kept
list.

That is exactly the danger: if a test directory is added and nobody enters it,
it **silently never runs**. Nothing turns red, nothing is visibly missing - CI
keeps reporting success, and the unchecked part quietly grows. That is the same
kind of defect as the finding that triggered this gate in the first place: a
test step that reported success without testing.

So both things are checked:

1. Every test file is in **exactly one** group. None without (would never run),
   none in two (would run twice and lengthen the gate for no reason).
2. Every entry in the list actually exists. A typo like ``tests/unit/cogss``
   makes pytest abort with code 4 - loudly, but the error belongs here, where it
   names the cause, rather than in a CI run.

COUNTER-CHECK (done 2026-09-17): green on the first run - which makes this test
suspicious, because a contract test that holds right away could also be
reading into the void. Against that stands
``test_the_list_and_the_tree_are_not_empty``: it proves that both collections
are filled (>30 groups, >50 files) before the assignment is checked.

One open question was real: ``tests/load/`` has an ``__init__.py`` but is not in
GROUPS.txt. The test stayed green - the directory contains no files pytest
would collect. Had it contained any, that would have been exactly the first
catch.
"""

from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[2]
TESTS = PROJECT / "tests"
LIST_FILE = TESTS / "GROUPS.txt"


def _groups():
    """The entries from GROUPS.txt, without comments and blank lines."""
    lines = LIST_FILE.read_text(encoding="utf-8").splitlines()
    return [z.strip() for z in lines if z.strip() and not z.strip().startswith("#")]


def _test_files():
    """All files that pytest would collect as tests."""
    return sorted(set(TESTS.rglob("test_*.py")) | set(TESTS.rglob("*_test.py")))


def test_the_list_and_the_tree_are_not_empty():
    """Safeguard against a blunt tool.

    If one of the two collections reads into the void - because the file was
    renamed or the search pattern no longer matches - the tests below would be
    green without proving anything.
    """
    assert LIST_FILE.is_file(), f"{LIST_FILE} is missing - the tests below then check nothing"
    groups, files = _groups(), _test_files()
    assert len(groups) > 30, f"Only {len(groups)} groups read - probably a read problem"
    assert len(files) > 50, f"Only {len(files)} test files found - probably a read problem"


def test_every_list_entry_exists():
    """A typo in the list makes a whole group drop out."""
    missing = [g for g in _groups() if not (PROJECT / g).exists()]
    assert not missing, (
        "Entries in tests/GROUPS.txt that do not exist: " + ", ".join(missing)
    )


def test_every_test_file_is_in_exactly_one_group():
    """No file without a group, none in two."""
    groups = [(g, PROJECT / g) for g in _groups()]

    without, duplicate = [], []
    for file in _test_files():
        hits = [
            name for name, path in groups
            if file == path or (path.is_dir() and path in file.parents)
        ]
        rel = file.relative_to(PROJECT)
        if not hits:
            without.append(str(rel))
        elif len(hits) > 1:
            duplicate.append(f"{rel} -> {hits}")

    assert not without, (
        "Test files that are in NO group - they never run in CI, "
        "without anything turning red:\n  " + "\n  ".join(without)
    )
    assert not duplicate, (
        "Test files that are in SEVERAL groups - they run twice and "
        "lengthen the gate for no reason:\n  " + "\n  ".join(duplicate)
    )
