# -*- coding: utf-8 -*-
"""A scheduled restart waits until nobody plays - at the latest until its deadline.

THE OPERATOR'S IDEA (2026-09-28, v3.0.2): "Restart daily at 4, but only once 0
players are online (at the latest at 6)", and optionally a warning in Discord,
"Valheim restarts in 10 minutes". Decided with the operator: at the deadline
the restart happens anyway (warned before), the warning goes to status and
control channels, and an unreadable player count counts as empty (checked and
reported when the task is saved - see the save test).

HOW THIS TEST CAN FAIL (services/scheduling/player_gate.py and its call sites
in scheduler_service._check_and_execute_tasks):
* a restart runs while players are online, before its deadline;
* it does not run the moment the server is empty, or not at the deadline;
* the missed-run grace writes a waiting occurrence off as "missed";
* an unknown count holds the task back (it must count as empty);
* the warning is not posted, posted twice, posted to a waiting task on an
  empty server, or posted before a task that does not wait at the wrong time;
* the options do not survive a save of the task;
* the option rules accept nonsense (a warning on "start", 0 or 13 h waits).

COUNTER-CHECK (2026-09-28): with the gate call in the loop removed, the
"players online" case went red; with the window left out of the missed-run
check, the "not written off" case did; with occupied() counting unknown as
playing, the unknown case did.
"""

import time as _time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from services.scheduling import player_gate
from services.scheduling import runtime as scheduler_runtime
from services.scheduling import scheduler as scheduler_mod
from services.scheduling import scheduler_service as ss
from services.scheduling.scheduler import CYCLE_DAILY, ScheduledTask, load_tasks, save_tasks

WAIT = {"wait_for_empty": True, "max_wait_minutes": 120, "warn_minutes": 10}


@pytest.fixture(autouse=True)
def _isolated_config(monkeypatch, tmp_path):
    monkeypatch.setenv("DDC_SCHEDULER_CONFIG_DIR", str(tmp_path))
    scheduler_runtime.reset_scheduler_runtime()
    fresh = scheduler_runtime.get_scheduler_runtime()
    monkeypatch.setattr(scheduler_mod, "_runtime", fresh)
    monkeypatch.setattr(scheduler_mod, "TASKS_FILE_PATH", fresh.tasks_file_path)
    monkeypatch.setattr(scheduler_mod, "_get_system_tasks", lambda: [])
    yield tmp_path
    scheduler_runtime.reset_scheduler_runtime()


@pytest.fixture
def world(monkeypatch):
    """The clock, the players on Valheim, what ran and what was posted."""
    state = {"now": _time.time(), "players": 3, "ran": [], "posted": [], "rescheduled": []}
    monkeypatch.setattr(ss, "time", SimpleNamespace(time=lambda: state["now"]))
    monkeypatch.setattr(ss, "MISSED_RUN_GRACE_SECONDS", 300)
    monkeypatch.setattr(ss, "BATCH_PAUSE_SECONDS", 0)
    monkeypatch.setattr(player_gate, "players_online", lambda name: state["players"])

    async def _execute(task):
        state["ran"].append(task.task_id)
        task.update_after_execution()
    monkeypatch.setattr(ss, "execute_task", _execute)

    async def _post(bot, text):
        state["posted"].append(text)
        return 1
    monkeypatch.setattr(player_gate, "post_warning", _post)
    monkeypatch.setattr(ss, "reschedule_missed_task", lambda task: state["rescheduled"].append(task.task_id))
    return state


def _store(state, options, due_in=0.0, action="restart"):
    task = ScheduledTask(task_id="t1", container_name="Valheim", action=action, cycle=CYCLE_DAILY,
                         hour=4, minute=0, timezone_str="UTC")
    task.options = dict(options)
    task.next_run_ts = state["now"] + due_in
    assert save_tasks([task]) is True
    return task


async def _cycle(service, state, advance=0):
    state["now"] += advance
    await service._check_and_execute_tasks()


# ----------------------------------------------------------------- waiting

async def test_players_online_hold_the_restart_back(world):
    _store(world, WAIT)
    service = ss.SchedulerService()
    await _cycle(service, world)
    await _cycle(service, world, 30 * 60)
    assert world["ran"] == [], "the restart ran while 3 players were online"


async def test_it_runs_the_moment_the_server_is_empty(world):
    _store(world, WAIT)
    service = ss.SchedulerService()
    await _cycle(service, world)
    world["players"] = 0
    await _cycle(service, world, 45 * 60)
    assert world["ran"] == ["t1"]


async def test_at_the_deadline_it_runs_anyway(world):
    _store(world, WAIT)
    service = ss.SchedulerService()
    await _cycle(service, world)
    await _cycle(service, world, 120 * 60)
    assert world["ran"] == ["t1"], "the deadline passed with players online and nothing happened"


async def test_waiting_is_not_written_off_as_missed(world):
    _store(world, WAIT)
    service = ss.SchedulerService()
    for _ in range(10):  # 100 minutes of waiting, far past the 300 s grace
        await _cycle(service, world, 10 * 60)
    assert world["rescheduled"] == [], "a task waiting for an empty server was written off as missed"


async def test_an_unknown_count_counts_as_empty(world):
    world["players"] = None
    _store(world, WAIT)
    await _cycle(ss.SchedulerService(), world)
    assert world["ran"] == ["t1"]


async def test_a_task_without_options_is_what_it_was(world):
    _store(world, {})
    await _cycle(ss.SchedulerService(), world)
    assert world["ran"] == ["t1"] and world["posted"] == []


# ----------------------------------------------------------------- warning

async def test_the_warning_comes_before_the_deadline_once(world):
    _store(world, WAIT)
    service = ss.SchedulerService()
    await _cycle(service, world)                 # 04:00, players on: wait, no warning yet
    assert world["posted"] == []
    await _cycle(service, world, 110 * 60)       # 05:50: ten minutes before 06:00
    await _cycle(service, world, 60)             # 05:51
    assert len(world["posted"]) == 1, world["posted"]
    assert "Valheim" in world["posted"][0] and "10" in world["posted"][0]


async def test_no_warning_when_the_server_empties_first(world):
    _store(world, WAIT)
    service = ss.SchedulerService()
    await _cycle(service, world)
    world["players"] = 0
    await _cycle(service, world, 110 * 60)
    assert world["posted"] == [] and world["ran"] == ["t1"]


async def test_a_task_that_does_not_wait_warns_before_its_time(world):
    _store(world, {"warn_minutes": 10}, due_in=15 * 60)
    service = ss.SchedulerService()
    await _cycle(service, world)                 # 15 min before: too early
    assert world["posted"] == []
    await _cycle(service, world, 5 * 60)         # 10 min before
    assert len(world["posted"]) == 1
    await _cycle(service, world, 10 * 60)        # due
    assert world["ran"] == ["t1"] and len(world["posted"]) == 1


# ----------------------------------------------------------------- stored, validated

def test_the_options_survive_a_save():
    task = ScheduledTask(task_id="t9", container_name="Valheim", action="restart", cycle=CYCLE_DAILY,
                         hour=4, minute=0, timezone_str="UTC")
    task.options = dict(WAIT)
    assert save_tasks([task]) is True
    loaded = [t for t in load_tasks() if t.task_id == "t9"][0]
    assert loaded.options == WAIT


@pytest.mark.parametrize("raw, action, ok", [
    ({"wait_for_empty": True}, "restart", True),
    ({"warn_minutes": 5}, "stop", True),
    ({"warn_minutes": 5}, "start", False),
    ({"wait_for_empty": True, "max_wait_minutes": 0}, "restart", False),
    ({"wait_for_empty": True, "max_wait_minutes": 721}, "restart", False),
    ({"warn_minutes": 61}, "restart", False),
    ({"warn_minutes": "ten"}, "restart", False),
    ({}, "start", True),
])
def test_the_option_rules(raw, action, ok):
    options, error = player_gate.normalize_options(raw, action)
    assert (error is None) is ok, (raw, action, error)
    if ok and raw.get("wait_for_empty"):
        assert options["max_wait_minutes"] == raw.get("max_wait_minutes", 120)
