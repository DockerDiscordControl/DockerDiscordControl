# -*- coding: utf-8 -*-
"""The JavaScript cases are run together, or their silence is at least one skip.

THE FINDING (2026-09-24). Eight files under tests/js hold the rules the panel's
JavaScript has to get right, and each is started by one test in tests/spec that
begins:

    if not shutil.which("node"):
        pytest.skip("node is not installed here - run it by hand")

node is not in the test image, so all eight skip on every run of the suite.
They are only ever run by hand. I ran them by hand:

    auto_actions_rule_form.test.js   5 of 5 cases FAILED

It had been red since 2026-09-23 (commit 2652aafd, "A rule that loses sight of
its group does not start watching everything"). That commit gave the rule
editor group targets: the save started reading one combined selector for
containers and groups, the widening guard moved into rule_targets.js, and the
memory watchdog had added a second threshold field the day before. The little
stand-in DOM in the case file knew none of it, so every case died on a null
element or sent an empty target list - and the suite said nothing, eight times
over, for a day.

WHAT THIS FILE ADDS: one place that runs ALL of them. Where node exists it runs
every case file and fails by name; in the test image it still skips - but it is
ONE skip whose reason is the whole set, and the wiring it checks around that
skip does run: every case file is started by exactly one spec test, and no spec
test names a file that is not there. A ninth case file cannot be added and
quietly never run, and a file cannot be orphaned by deleting the test that
started it.

WHAT IT DOES NOT CLAIM: it cannot make the container run node. The honest
answer to "why is this skipped" is now one line instead of eight, and the
project's rule - run the JS cases on a machine that has node before committing
JavaScript - is written down where the skip is.

COUNTER-CHECK (2026-09-24): run against the red file before the repair, it
named auto_actions_rule_form.test.js and the five cases. The repair was itself
counter-checked with two sabotage variants on a green baseline (dropping the
kept-but-invisible target, and blinding the combined selector), which took 1
and 3 cases red.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
JS = ROOT / "tests" / "js"
SPEC = ROOT / "tests" / "spec"


def _case_files():
    return sorted(JS.glob("*.test.js"))


def _spec_text():
    return {path: path.read_text(encoding="utf-8") for path in sorted(SPEC.glob("*.py"))
            if path.name != Path(__file__).name}


def test_there_are_cases_to_run():
    """Safeguard against a blunt tool: a scan finding nothing is green."""
    assert len(_case_files()) >= 8, f"only {len(_case_files())} case files found"


def test_every_case_file_is_started_by_exactly_one_test():
    """A file nobody starts is a file nobody runs, by hand or otherwise."""
    texts = _spec_text()
    unstarted, duplicated = [], []
    for case in _case_files():
        starters = [path.name for path, text in texts.items() if case.name in text]
        if not starters:
            unstarted.append(case.name)
        elif len(starters) > 1:
            duplicated.append((case.name, starters))

    assert unstarted == [], f"no test starts these: {unstarted}"
    assert duplicated == [], f"started from more than one place: {duplicated}"


def test_no_test_starts_a_case_file_that_is_gone():
    """The other direction: a renamed file leaves a test that skips for a
    reason that is no longer true."""
    names = {case.name for case in _case_files()}
    missing = []
    for path, text in _spec_text().items():
        for named in re.findall(r"[\w.]+\.test\.js", text):
            if named not in names:
                missing.append(f"{path.name} -> {named}")

    assert missing == [], f"these tests start a file that does not exist: {missing}"


def test_all_of_them_pass():
    """THE FINDING ITSELF. One run, every file, named when it fails."""
    node = shutil.which("node")
    if not node:
        pytest.skip(
            "node is not installed here, so none of the JavaScript cases ran. "
            "Run them on a machine that has node before committing JavaScript: "
            "for f in tests/js/*.test.js; do node \"$f\"; done")

    broken = []
    for case in _case_files():
        result = subprocess.run([node, str(case)], capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            failures = [line for line in result.stdout.splitlines()
                        if line.startswith("FAIL")]
            broken.append(f"{case.name}: {len(failures)} case(s) failed - "
                          f"{failures[0][:80] if failures else result.stderr[:80]}")

    assert broken == [], "\n  ".join(["JavaScript cases are failing:"] + broken)
