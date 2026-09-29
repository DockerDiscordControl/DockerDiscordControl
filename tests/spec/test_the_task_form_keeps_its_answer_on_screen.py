# -*- coding: utf-8 -*-
"""What the server answers to a new task stays on screen.

THE FINDING (second review before v3.1.0, 2026-09-29). After a 201 the task
form wrote the answer into #responseMessage - "Task added", the warning
that a waiting task's player count cannot be read, or "switched off: the
time is in the past" - and called resetTaskForm() on the next line, which
empties #responseMessage. The operator saw nothing at all: the v3.1.0
warning meant to tell him at saving time, not at 4 a.m., never showed, and
neither did the older "switched off" notice.

tests/js/task_added_notice.test.js proves the TEXT is right; the fault was
the call site, so this test reads the call site (the form is DOM-bound and
does not run in node).

THE CONTRACT: in the 201 branch the form is reset BEFORE the answer is
written - and the reset does empty the message box (otherwise the order
would not matter and this test would prove nothing).

HOW THIS TEST CAN FAIL: the reset moves back after the answer.

COUNTER-CHECK (2026-09-29): written before the fix and red then.
"""

import re
from pathlib import Path

FORM = Path(__file__).resolve().parents[2] / "app" / "static" / "js" / "task_form.js"


def _source():
    return FORM.read_text(encoding="utf-8")


def test_the_reset_empties_the_message_box():
    reset = re.search(r"function resetTaskForm\(\)\s*\{(.*?)\n\}", _source(), re.S)
    assert reset, "resetTaskForm not found"
    assert "getElementById('responseMessage').textContent = ''" in reset.group(1)


def test_the_answer_is_written_after_the_reset():
    source = _source()
    branch = source[source.index("if (data.status === 201)"):]
    branch = branch[:branch.index("} else {")]

    reset_at = branch.index("resetTaskForm()")
    answer_at = branch.index("textContent = notice.text")

    assert reset_at < answer_at, "the form is reset after the answer and wipes it"
