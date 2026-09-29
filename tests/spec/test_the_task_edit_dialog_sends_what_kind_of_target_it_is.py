# -*- coding: utf-8 -*-
"""The task edit dialog sends whether the chosen target is a group.

THE FINDING (second review before v3.1.0, 2026-09-29). 82fea523 (2026-09-23)
let the edit dialog offer groups and computed `targetIsGroup` from the
chosen option - with a comment that without it "an edited group task kept
target_is_group while pointing at a container". The value was never put
into the payload. task_management_service.edit_task only changes
target_is_group when the key is sent, so switching a task from a group to a
container (or back) kept the old flag: the scheduler then looked for a group
named like the container ("the group does not exist any more"), and since
v3.1.0 the player gate checked the wrong target too. A comment stronger than
its code.

THE CONTRACT: the payload the dialog sends carries target_is_group, taken
from the chosen option.

HOW THIS TEST CAN FAIL: the key drops out of the payload again.

The dialog is DOM-bound and does not run in node, so the test reads the
payload literal of collectFormData(); the server side is covered by
tests that send target_is_group to edit_task.

COUNTER-CHECK (2026-09-29): written before the fix and red then.
"""

import re
from pathlib import Path

TASKS_JS = Path(__file__).resolve().parents[2] / "app" / "static" / "js" / "tasks.js"


def test_the_payload_carries_the_target_kind():
    source = TASKS_JS.read_text(encoding="utf-8")
    method = source[source.index("collectFormData() {"):]
    method = method[:method.index("validateTaskData(")]
    payload = re.search(r"data:\s*\{(.*?)\}\s*\};", method, re.S)

    assert "const targetIsGroup" in method, "the dialog no longer reads the target kind"
    assert payload, "payload literal not found"
    assert re.search(r"target_is_group:\s*targetIsGroup", payload.group(1)), (
        "the dialog computes targetIsGroup and does not send it")
