# -*- coding: utf-8 -*-
"""The test runner can run the whole suite itself, group by group.

scripts/ddc_test.sh takes ONE group per call on purpose: tests/unit/services
has no __init__.py but is named like the real services package, so several
groups in one pytest run shadow it and nothing is collected (see
tests/GROUPS.txt). A full run - the thing that has to happen before every
push - therefore had to be stitched together by hand in a scratch script,
which is how two groups were missed once.

`ddc_test.sh --all` reads tests/GROUPS.txt, the project's own list, runs each
group in its own container and prints one line per group plus a total. The
group list stays the single source: the workflows read the same file.

COUNTER-CHECK (2026-09-22): red before - the runner had no --all and rejected
it as a pytest path; removing the GROUPS.txt read makes the "no hard-coded
list" case red.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNNER = (ROOT / "scripts" / "ddc_test.sh").read_text(encoding="utf-8")
GROUPS = [line.strip() for line in (ROOT / "tests" / "GROUPS.txt").read_text(encoding="utf-8").splitlines()
          if line.strip() and not line.strip().startswith("#")]


def test_the_runner_knows_all():
    assert "--all" in RUNNER, "the runner has no --all"


def test_it_reads_the_group_list_instead_of_carrying_its_own():
    assert "tests/GROUPS.txt" in RUNNER
    for group in GROUPS:
        assert f'"{group}"' not in RUNNER, f"{group} is hard-coded in the runner"


def test_the_usage_line_mentions_it():
    usage = [line for line in RUNNER.splitlines() if "usage:" in line]
    assert any("--all" in line for line in usage), usage


def test_the_group_list_is_not_empty_and_starts_with_the_specs():
    assert GROUPS and GROUPS[0] == "tests/spec"
