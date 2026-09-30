# -*- coding: utf-8 -*-
"""A tasks.json holding only whitespace is an empty task list, not a failed read.

THE FINDING (stage 4 review before v3.1.0, section 26 pass 4 F2): load_tasks
parsed `read_text() or "[]"`; a file holding "\\n" is truthy, json.loads
raised, and the read counted as failed - every save was refused with "the
last read failed" until the operator edited the file, so the panel could
not add a task. A 0-byte file and the other reader
(_load_raw_tasks_from_file, which strips first) take the same content as an
empty list. Trigger: `echo > tasks.json`, or an editor leaving a blank line.

THE CONTRACT: whitespace alone reads as an empty list; the next add saves.

HOW THIS TEST CAN FAIL: the add is refused again.

COUNTER-CHECK (2026-09-30): red before the change (add_task False).
"""

import json

import pytest

import services.scheduling.scheduler as scheduler_mod
from tests.spec.test_an_unreadable_task_file_is_not_an_empty_one import _new_task, tasks_file  # noqa: F401


@pytest.mark.parametrize("blank", ["\n", "  \n\n", "\t"])
def test_a_task_can_be_added_to_a_blank_file(tasks_file, blank):  # noqa: F811
    tasks_file.write_text(blank, encoding="utf-8")

    assert scheduler_mod.add_task(_new_task()) is True
    saved = json.loads(tasks_file.read_text(encoding="utf-8"))
    assert [entry.get("container") for entry in saved] == ["nginx"]
