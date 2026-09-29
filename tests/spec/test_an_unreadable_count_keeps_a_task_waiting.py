# -*- coding: utf-8 -*-
"""A player count that fails at the scheduled moment keeps a waiting task waiting.

THE FINDING (stage 4 review before v3.1.0, section 49 pass 4 F4): a task set
to "only when nobody plays" treated every unreadable count as empty. The rule
was agreed for containers whose count CANNOT be read by their set-up - the save
tells the operator so. But a count that is set up and just fails at 4 o'clock
(the server hangs, the status read failed) let the restart through at once,
with people possibly playing, and nothing was logged.

THE OPERATOR (2026-09-29): then the task keeps waiting until its latest time.

THE CONTRACT (services/scheduling/player_gate.py):
* set up, but no count right now   -> counts as occupied: wait, at the latest
  until the deadline, and log a warning naming the container;
* not set up (Players column off, the query switched off, a game that does not
  answer) -> counts as empty, as before.

HOW THIS TEST CAN FAIL: a momentary failure lets the restart through again; or
the correction overreaches and a container without player counting waits the
full two hours every day.

It runs the scheduler's own check cycle, as test_a_task_waits_until_nobody_plays.

COUNTER-CHECK (2026-09-29): the first case was red before the change; the
second must stay green both before and after.
"""

import logging
import time as _time
from types import SimpleNamespace

import pytest

from services.scheduling import player_gate
from services.scheduling import runtime as scheduler_runtime
from services.scheduling import scheduler as scheduler_mod
from services.scheduling import scheduler_service as ss
from services.scheduling.scheduler import CYCLE_DAILY, ScheduledTask, save_tasks

WAIT = {"wait_for_empty": True, "max_wait_minutes": 120}


@pytest.fixture(autouse=True)
def _isolated_config(monkeypatch, tmp_path):
    monkeypatch.setenv("DDC_SCHEDULER_CONFIG_DIR", str(tmp_path))
    scheduler_runtime.reset_scheduler_runtime()
    fresh = scheduler_runtime.get_scheduler_runtime()
    monkeypatch.setattr(scheduler_mod, "_runtime", fresh)
    monkeypatch.setattr(scheduler_mod, "TASKS_FILE_PATH", fresh.tasks_file_path)
    monkeypatch.setattr(scheduler_mod, "_get_system_tasks", lambda: [])
    yield
    scheduler_runtime.reset_scheduler_runtime()


@pytest.fixture
def world(monkeypatch):
    state = {"now": _time.time(), "ran": []}
    monkeypatch.setattr(ss, "time", SimpleNamespace(time=lambda: state["now"]))
    monkeypatch.setattr(ss, "MISSED_RUN_GRACE_SECONDS", 300)
    monkeypatch.setattr(ss, "BATCH_PAUSE_SECONDS", 0)
    # The status read fails: no count at all.
    monkeypatch.setattr(player_gate, "players_online", lambda name: None)

    async def _execute(task):
        state["ran"].append(task.task_id)
        task.update_after_execution()
    monkeypatch.setattr(ss, "execute_task", _execute)
    monkeypatch.setattr(ss, "reschedule_missed_task", lambda task, *a: None)
    task = ScheduledTask(task_id="t1", container_name="Valheim", action="restart",
                         cycle=CYCLE_DAILY, hour=4, minute=0, timezone_str="UTC")
    task.options = dict(WAIT)
    task.next_run_ts = state["now"]
    assert save_tasks([task]) is True
    return state


async def test_a_count_that_is_set_up_but_fails_keeps_the_task_waiting(world, monkeypatch, caplog):
    monkeypatch.setattr(player_gate, "setup_problem", lambda name: None, raising=False)
    service = ss.SchedulerService()
    with caplog.at_level(logging.WARNING):
        await service._check_and_execute_tasks()
        world["now"] += 30 * 60
        await service._check_and_execute_tasks()
    assert world["ran"] == [], "the count failed for a moment and the restart ran at once"
    assert any("Valheim" in r.getMessage() and r.levelno >= logging.WARNING
               for r in caplog.records), "waiting on an unreadable count left no warning"

    world["now"] += 90 * 60
    await service._check_and_execute_tasks()
    assert world["ran"] == ["t1"], "at the latest time it must run anyway"


async def test_a_container_without_player_counting_still_counts_as_empty(world, monkeypatch):
    monkeypatch.setattr(player_gate, "setup_problem",
                        lambda name: "the player count is not switched on for this container",
                        raising=False)
    await ss.SchedulerService()._check_and_execute_tasks()
    assert world["ran"] == ["t1"], "a container without player counting waited for nobody"
