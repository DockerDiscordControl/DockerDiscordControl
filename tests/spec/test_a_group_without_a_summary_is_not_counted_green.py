# -*- coding: utf-8 -*-
"""A test group whose output ends without a pytest summary counts as failed, not green.

THE FINDING (while running the fixes of the stage 4 review before v3.1.0,
2026-09-29). `ddc_test.sh --all` took the LAST line of each group's output
as its result. Twice the spec group's output ended with a logging error
written at interpreter exit ("... Arguments: ()"), after pytest's summary.
The line held no "passed" and no "failed", so the group counted as 0 and 0
- the run reported "43 groups: 4298 passed, 0 failed", green, with the
3,600 spec tests not counted at all.

THE CONTRACT: the runner reads the pytest summary line, wherever it is in
the output; a group with no such line is counted as failed and named.

HOW THIS TEST CAN FAIL: the runner trusts the last line again.

The container that runs the suite has no bash, so this reads the runner the
way test_the_runner_can_run_the_whole_suite.py does.

COUNTER-CHECK (2026-09-29): written before the fix and red then.
"""

import re
from pathlib import Path

RUNNER = (Path(__file__).resolve().parents[2] / "scripts" / "ddc_test.sh").read_text(encoding="utf-8")
LOOP = RUNNER[RUNNER.index('while IFS= read -r group'):RUNNER.index('done < "$LIST"')]


def test_the_result_line_is_the_pytest_summary_not_the_last_line():
    taking = re.search(r'line=\$\(.*\)', LOOP).group(0)
    assert "tail -1" not in taking or "passed" in taking, taking


def test_a_missing_summary_is_a_failed_group():
    branch = re.search(r'if \[ -z "\$line" \]; then(.*?)fi', LOOP, re.S)
    assert branch and "NO PYTEST SUMMARY" in branch.group(1) and "summary_missing=1" in branch.group(1)
    assert '[ -n "$summary_missing" ] && bad=1' in LOOP, "a group that did not report still counts as green"
