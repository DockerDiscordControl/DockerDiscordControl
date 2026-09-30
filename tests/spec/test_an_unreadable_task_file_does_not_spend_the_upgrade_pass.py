# -*- coding: utf-8 -*-
"""An unreadable tasks.json at the first start does not use up the long-dead pass.

THE FINDING (stage 4 review before v3.1.0, section 26 pass 4 F6): the
one-time pass that pauses long-dead recurring tasks runs at the first start
after the upgrade. If tasks.json could not be read then, it saw an empty
list, wrote its "done" marker, and never ran again - so once the file was
readable, the long-dead tasks were revived by the missed-run handling,
exactly what the pass exists to prevent.

THE CONTRACT: a failed read skips the pass without the marker, like an
unreadable marker does; the next start runs it.

HOW THIS TEST CAN FAIL: the marker is written after a failed read, and the
long-dead task stays active.

COUNTER-CHECK (2026-09-30): red before the change (the second call returned 0).
"""

import json

import services.scheduling.scheduler as scheduler_mod
from tests.spec.test_an_unreadable_task_file_is_not_an_empty_one import _new_task, tasks_file  # noqa: F401

T = 1_800_000_000.0


def test_the_pass_waits_for_a_readable_file(tasks_file):  # noqa: F811
    tasks_file.write_text("{broken", encoding="utf-8")
    assert scheduler_mod.pause_long_dead_tasks_once(now_ts=T) == 0

    dead = _new_task()
    dead.is_active = True
    dead.next_run_ts = T - 30 * 86400
    tasks_file.write_text(json.dumps([dead.to_dict()]), encoding="utf-8")

    assert scheduler_mod.pause_long_dead_tasks_once(now_ts=T) == 1
    saved = json.loads(tasks_file.read_text(encoding="utf-8"))
    assert [entry.get("is_active", entry.get("active")) for entry in saved] == [False]
