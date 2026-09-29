# -*- coding: utf-8 -*-
"""A group task interrupted by a DDC restart is not carried out a second time.

THE FINDING (stage 4 review before v3.1.0, section 26 pass 4 F8): a task
writes its occurrence down BEFORE it acts, so a DDC restart in the middle
finds it already begun and does not act again
(test_a_restart_does_not_run_a_task_twice.py). The group branch returned
before that line: a group task wrote its occurrence down only after the
whole group had been acted on. A restart during a group action - an image
update while a long stop runs, or a group that contains DDC itself - ran
the whole group action again after the restart, within the 300 s grace.

THE CONTRACT: the occurrence is written down before the group is touched.

HOW THIS TEST CAN FAIL: the group branch acts before anything was persisted.

COUNTER-CHECK (2026-09-29): red before the change.
"""

import time

from services.scheduling import scheduler as scheduler_mod


async def test_the_occurrence_is_written_down_before_the_group_acts(monkeypatch):
    persisted = []

    async def _persist(task):
        persisted.append(task.last_run_ts)
    monkeypatch.setattr(scheduler_mod, "_persist_async", _persist)
    seen = {}

    async def _group(task, timeout):
        seen["persisted_before"] = list(persisted)
        return True
    monkeypatch.setattr("services.scheduling.group_tasks.execute_group_task", _group)

    task = scheduler_mod.ScheduledTask(container_name="Gameserver", action="restart",
                                       cycle="daily", hour=3, minute=0, timezone_str="UTC",
                                       target_is_group=True)
    due = time.time() - 30
    task.next_run_ts = due

    assert await scheduler_mod.execute_task(task) is True
    assert any(ts and ts >= due for ts in seen["persisted_before"]), (
        "the group was acted on before its occurrence was written down - a restart "
        "in between runs the whole group action again")
