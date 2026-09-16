# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Audit 2026-09 release review, package G1        #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Regression tests for the scheduler items of the release review.

R1-1 (one-time pause of long-dead tasks), R4-1 (run-time allowed_actions check
only for Discord tasks), R5-1 (no second stop/restart after a timeout), R5-3
(capacity-deferred tasks are never "missed"), R5-7 (yearly next run). Every test
runs against a private config directory.
"""

from __future__ import annotations

import asyncio
import json
import time as _time
from contextlib import asynccontextmanager
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytz

from services.scheduling import runtime as scheduler_runtime
from services.scheduling import scheduler as scheduler_mod
from services.scheduling import scheduler_service as ss
from services.scheduling.scheduler import (
    CYCLE_DAILY,
    CYCLE_MONTHLY,
    CYCLE_ONCE,
    CYCLE_WEEKLY,
    CYCLE_YEARLY,
    UPGRADE_STATE_FILENAME,
    ScheduledTask,
    load_tasks,
    pause_long_dead_tasks_once,
    save_tasks,
)

UTC = pytz.UTC
DAY = 24 * 60 * 60
_REAL_DISALLOWED_REASON = scheduler_mod._get_disallowed_action_reason


@pytest.fixture(autouse=True)
def _isolated_config(monkeypatch, tmp_path):
    monkeypatch.setenv("DDC_SCHEDULER_CONFIG_DIR", str(tmp_path))
    scheduler_runtime.reset_scheduler_runtime()
    fresh = scheduler_runtime.get_scheduler_runtime()
    monkeypatch.setattr(scheduler_mod, "_runtime", fresh)
    monkeypatch.setattr(scheduler_mod, "TASKS_FILE_PATH", fresh.tasks_file_path)
    monkeypatch.setattr(scheduler_mod, "_get_system_tasks", lambda: [])
    monkeypatch.setattr(scheduler_mod, "_get_disallowed_action_reason", lambda c, a: None)
    monkeypatch.setattr(scheduler_mod, "log_user_action", lambda **kw: None)
    # No Docker lookups unless a test provides a StopTimeout
    monkeypatch.setattr(scheduler_mod, "_get_container_stop_timeout", AsyncMock(return_value=None))
    yield tmp_path
    scheduler_runtime.reset_scheduler_runtime()


def _task(cycle=CYCLE_DAILY, container="c1", action="restart", task_id=None, **kwargs):
    params = {"hour": 4, "minute": 0}
    if cycle == CYCLE_WEEKLY:
        params["weekday"] = 0
    elif cycle == CYCLE_MONTHLY:
        params["day"] = 1
    elif cycle == CYCLE_YEARLY:
        params.update(month=1, day=1)
    elif cycle == CYCLE_ONCE:
        params.update(year=2099, month=1, day=1)
    params.update(kwargs)
    return ScheduledTask(task_id=task_id, container_name=container, action=action,
                         cycle=cycle, timezone_str="UTC", **params)


def _far_hour():
    """An hour whose next occurrence is ~12 h away (rescheduled runs stay out of the simulated window)."""
    return (datetime.now(UTC).hour + 12) % 24


def _overdue(task, seconds):
    task.next_run_ts = _time.time() - seconds
    return task


def _by_id():
    return {task.task_id: task for task in load_tasks()}


# --------------------------------------------------------------------------- #
# R1-1 - one-time pause of long-dead tasks                                    #
# --------------------------------------------------------------------------- #
class TestR1LongDeadTasksPausedOnce:
    def test_long_dead_recurring_tasks_are_paused_with_note(self, tmp_path):
        tasks = [
            _overdue(_task(CYCLE_DAILY, task_id="daily-dead"), 3 * DAY),
            _overdue(_task(CYCLE_WEEKLY, task_id="weekly-dead"), 15 * DAY),
            _overdue(_task(CYCLE_MONTHLY, task_id="monthly-dead"), 63 * DAY),
            _overdue(_task(CYCLE_YEARLY, task_id="yearly-dead"), 401 * DAY),
            _overdue(_task(CYCLE_DAILY, task_id="daily-short"), 1 * DAY),
            _overdue(_task(CYCLE_WEEKLY, task_id="weekly-short"), 10 * DAY),
            _overdue(_task(CYCLE_MONTHLY, task_id="monthly-short"), 40 * DAY),
            _task(CYCLE_DAILY, task_id="future"),  # e.g. already rescheduled by A4
            _overdue(_task(CYCLE_ONCE, task_id="once-old"), 30 * DAY),
        ]
        inactive = _overdue(_task(CYCLE_DAILY, task_id="inactive"), 30 * DAY)
        inactive.is_active = False
        assert save_tasks(tasks + [inactive]) is True

        assert pause_long_dead_tasks_once() == 4

        stored = _by_id()
        for task_id in ("daily-dead", "weekly-dead", "monthly-dead", "yearly-dead"):
            assert stored[task_id].is_active is False
            assert stored[task_id].last_run_error.startswith("Paused after upgrade: had not run since ")
            assert stored[task_id].last_run_error.endswith("; re-enable if still wanted")
        for task_id in ("daily-short", "weekly-short", "monthly-short", "future", "once-old"):
            assert stored[task_id].is_active is True
            assert stored[task_id].last_run_error is None
        assert stored["inactive"].last_run_error is None

        state = json.loads((tmp_path / UPGRADE_STATE_FILENAME).read_text(encoding="utf-8"))
        assert sorted(state["paused_long_dead_tasks"]["paused"]) == [
            "daily-dead", "monthly-dead", "weekly-dead", "yearly-dead"]

    def test_note_names_the_last_run(self):
        task = _task(CYCLE_DAILY, task_id="t1")
        task.last_run_ts = datetime(2026, 3, 10, 4, 0, tzinfo=UTC).timestamp()
        task.next_run_ts = task.last_run_ts + DAY
        assert save_tasks([task]) is True

        pause_long_dead_tasks_once()

        assert _by_id()["t1"].last_run_error == (
            "Paused after upgrade: had not run since 2026-03-10 04:00 UTC; re-enable if still wanted")

    def test_pass_runs_only_once_per_install(self, tmp_path):
        assert save_tasks([_task(task_id="future")]) is True
        assert pause_long_dead_tasks_once() == 0
        assert (tmp_path / UPGRADE_STATE_FILENAME).exists()

        # A task that dies later is left to the normal missed-run handling
        assert save_tasks([_overdue(_task(task_id="later"), 5 * DAY)]) is True
        assert pause_long_dead_tasks_once() == 0
        assert _by_id()["later"].is_active is True

    def test_marker_is_written_on_a_fresh_install(self, tmp_path):
        assert pause_long_dead_tasks_once() == 0
        assert "paused_long_dead_tasks" in json.loads(
            (tmp_path / UPGRADE_STATE_FILENAME).read_text(encoding="utf-8"))

    def test_cron_threshold_uses_the_interval(self):
        pytest.importorskip("croniter")
        every_five_minutes = ScheduledTask(container_name="c1", action="restart", cycle="cron",
                                           schedule_details={"cron_string": "*/5 * * * *"},
                                           timezone_str="UTC")
        every_six_hours = ScheduledTask(container_name="c1", action="restart", cycle="cron",
                                        schedule_details={"cron_string": "0 */6 * * *"},
                                        timezone_str="UTC")
        broken = ScheduledTask(container_name="c1", action="restart", cycle="cron",
                               schedule_details={"cron_string": "not a cron"}, timezone_str="UTC")
        broken.next_run_ts = _time.time()
        # Floor of one hour: an update's own downtime must not pause frequent crons
        assert scheduler_mod._dead_task_threshold_seconds(every_five_minutes) == 3600
        assert scheduler_mod._dead_task_threshold_seconds(every_six_hours) == 12 * 3600
        assert scheduler_mod._dead_task_threshold_seconds(broken) == 2 * DAY

    async def test_paused_tasks_stay_off_and_short_misses_are_rescheduled(self, monkeypatch):
        assert save_tasks([
            _overdue(_task(task_id="dead", container="c1"), 30 * DAY),
            _overdue(_task(task_id="short", container="c2"), 3600),
        ]) is True
        executed = AsyncMock()
        monkeypatch.setattr(ss, "execute_task", executed)
        monkeypatch.setattr(ss, "MISSED_RUN_GRACE_SECONDS", 300)
        service = ss.SchedulerService()
        service.running = True

        async def _one_cycle():
            await ss.SchedulerService._check_and_execute_tasks(service)
            service.running = False

        monkeypatch.setattr(service, "_check_and_execute_tasks", _one_cycle)
        monkeypatch.setattr(service, "_calculate_optimal_sleep_interval", lambda t: 0)

        await service._service_loop()

        executed.assert_not_called()
        stored = _by_id()
        assert stored["dead"].is_active is False
        assert stored["dead"].next_run_ts < _time.time()
        assert stored["short"].is_active is True
        assert stored["short"].next_run_ts > _time.time()

    def test_reenable_in_web_ui_computes_a_future_run(self):
        from services.web.task_management_service import TaskManagementService, UpdateTaskStatusRequest

        assert save_tasks([_overdue(_task(task_id="dead"), 30 * DAY)]) is True
        assert pause_long_dead_tasks_once() == 1

        result = TaskManagementService().update_task_status(
            UpdateTaskStatusRequest(task_id="dead", is_active=True))

        assert result.success is True, result.error
        stored = _by_id()["dead"]
        assert stored.is_active is True
        assert stored.next_run_ts > _time.time()
        assert stored.last_run_error is None

    def test_other_errors_are_kept_on_reenable(self):
        from services.web.task_management_service import TaskManagementService, UpdateTaskStatusRequest

        task = _task(task_id="t1")
        task.is_active = False
        task.last_run_success = False
        task.last_run_error = "Docker action failed"
        assert save_tasks([task]) is True

        result = TaskManagementService().update_task_status(UpdateTaskStatusRequest(task_id="t1", is_active=True))

        assert result.success is True, result.error
        assert _by_id()["t1"].last_run_error == "Docker action failed"


# --------------------------------------------------------------------------- #
# R4-1 - execution-time allowed_actions check only for Discord tasks          #
# --------------------------------------------------------------------------- #
class TestR4AllowedActionsOnlyForDiscordTasks:
    def _servers(self, monkeypatch, servers):
        monkeypatch.setattr(scheduler_mod, "_get_disallowed_action_reason", _REAL_DISALLOWED_REASON)
        service = MagicMock()
        service.get_all_servers.return_value = servers
        monkeypatch.setattr("services.config.server_config_service.get_server_config_service", lambda: service)
        action = AsyncMock(return_value=True)
        monkeypatch.setattr(scheduler_mod, "docker_action_service_first", action)
        monkeypatch.setattr(scheduler_mod, "update_task", lambda t, **kw: True)
        return action

    async def test_web_ui_task_runs_although_discord_allows_only_status(self, monkeypatch):
        action = self._servers(monkeypatch, [{"docker_name": "c1", "allowed_actions": ["status"]}])
        task = _task(action="restart", created_by="Web UI")

        assert await scheduler_mod.execute_task(task, timeout=2) is True
        action.assert_awaited_once()

    async def test_discord_task_with_disallowed_action_is_skipped(self, monkeypatch):
        action = self._servers(monkeypatch, [{"docker_name": "c1", "allowed_actions": ["status"]}])
        task = _task(action="restart", created_by="someone#1234")

        assert await scheduler_mod.execute_task(task, timeout=2) is False
        action.assert_not_called()
        assert "no longer allowed" in task.last_run_error

    def test_web_ui_tasks_are_marked_as_such(self):
        from services.web.task_management_service import AddTaskRequest, TaskManagementService

        task = TaskManagementService()._create_scheduled_task(
            AddTaskRequest(container="c1", action="stop", cycle="daily", schedule_details={"time": "04:00"}),
            "UTC")
        assert task.created_by == scheduler_mod.WEB_UI_CREATOR
        # Survives a save/load round trip (stored as _created_by)
        assert ScheduledTask.from_dict(task.to_dict()).created_by == "Web UI"


# --------------------------------------------------------------------------- #
# R5-1 - stop/restart: StopTimeout-aware timeout, never sent twice            #
# --------------------------------------------------------------------------- #
class TestR5StopRestartTimeout:
    def _action(self, monkeypatch, delay=0.0):
        calls = []

        async def _fake_action(container, action, timeout=60):
            calls.append((action, timeout))
            await asyncio.sleep(delay)
            return True

        monkeypatch.setattr(scheduler_mod, "docker_action_service_first", _fake_action)
        monkeypatch.setattr(scheduler_mod, "update_task", lambda t, **kw: True)
        return calls

    async def test_restart_timeout_covers_the_stop_timeout(self, monkeypatch):
        calls = self._action(monkeypatch)
        monkeypatch.setattr(scheduler_mod, "_get_container_stop_timeout", AsyncMock(return_value=300))

        assert await scheduler_mod.execute_task(_task(action="restart"), timeout=60) is True
        assert calls == [("restart", 330)]

    async def test_short_stop_timeout_keeps_the_default(self, monkeypatch):
        calls = self._action(monkeypatch)
        monkeypatch.setattr(scheduler_mod, "_get_container_stop_timeout", AsyncMock(return_value=10))

        assert await scheduler_mod.execute_task(_task(action="stop"), timeout=60) is True
        assert calls == [("stop", 60)]

    @pytest.mark.parametrize("action", ["stop", "restart"])
    async def test_timed_out_stop_or_restart_is_not_sent_again(self, monkeypatch, action):
        calls = self._action(monkeypatch, delay=1)
        task = _task(action=action)

        assert await scheduler_mod.execute_task(task, timeout=0.05) is False

        assert len(calls) == 1
        assert task.last_run_success is False
        assert "timed out" in task.last_run_error
        assert "not sent again" in task.last_run_error

    async def test_timed_out_start_is_retried_once(self, monkeypatch):
        calls = self._action(monkeypatch, delay=1)
        task = _task(action="start")

        assert await scheduler_mod.execute_task(task, timeout=0.05) is False

        assert [timeout for _, timeout in calls] == [0.05, 0.05 * 1.5]
        scheduler_mod._get_container_stop_timeout.assert_not_called()

    async def test_stop_timeout_lookup_reads_the_container_config(self, monkeypatch):
        monkeypatch.setattr(scheduler_mod, "_get_container_stop_timeout",
                            TestR5StopRestartTimeout._real_lookup)
        container = SimpleNamespace(attrs={"Config": {"StopTimeout": 240}})
        client = MagicMock()
        client.containers.get.return_value = container

        @asynccontextmanager
        async def _fake_client(**kwargs):
            yield client

        monkeypatch.setattr("services.docker_service.docker_client_pool.get_docker_client_async", _fake_client)

        assert await scheduler_mod._get_container_stop_timeout("game") == 240
        client.containers.get.assert_called_once_with("game")

    async def test_stop_timeout_lookup_failure_returns_none(self, monkeypatch):
        monkeypatch.setattr(scheduler_mod, "_get_container_stop_timeout",
                            TestR5StopRestartTimeout._real_lookup)

        @asynccontextmanager
        async def _no_docker(**kwargs):
            raise OSError("no docker socket")
            yield  # pragma: no cover

        monkeypatch.setattr("services.docker_service.docker_client_pool.get_docker_client_async", _no_docker)

        assert await scheduler_mod._get_container_stop_timeout("game") is None

    _real_lookup = staticmethod(scheduler_mod._get_container_stop_timeout)


# --------------------------------------------------------------------------- #
# R5-3 - lateness counts only time the scheduler could have run the task      #
# --------------------------------------------------------------------------- #
class TestR5DeferredTasksAreNotMissed:
    @pytest.fixture(autouse=True)
    def _clock(self, monkeypatch):
        self.clock = {"now": _time.time()}
        monkeypatch.setattr(ss, "time", SimpleNamespace(time=lambda: self.clock["now"]))
        monkeypatch.setattr(ss, "MISSED_RUN_GRACE_SECONDS", 300)
        monkeypatch.setattr(ss, "MAX_CONCURRENT_TASKS", 3)
        monkeypatch.setattr(ss, "TASK_BATCH_SIZE", 5)
        monkeypatch.setattr(ss, "CHECK_INTERVAL", 60)
        monkeypatch.setattr(ss, "BATCH_PAUSE_SECONDS", 0)
        self.missed = []
        real_reschedule = ss.reschedule_missed_task

        def _record_missed(task):
            self.missed.append(task.task_id)
            return real_reschedule(task)

        monkeypatch.setattr(ss, "reschedule_missed_task", _record_missed)

    def _store(self, count, due_at):
        tasks = []
        for i in range(count):
            task = _task(task_id=f"t{i}", container=f"c{i}", hour=_far_hour())
            task.next_run_ts = due_at
            tasks.append(task)
        assert save_tasks(tasks) is True

    def _executor(self, monkeypatch, seconds_per_task):
        executed = []

        async def _fake_execute(task):
            executed.append(task.task_id)
            await asyncio.sleep(0)
            self.clock["now"] += seconds_per_task(task)
            task.update_after_execution()

        monkeypatch.setattr(ss, "execute_task", _fake_execute)
        return executed

    async def _run_cycles(self, service, count):
        for _ in range(count):
            start = self.clock["now"]
            await service._check_and_execute_tasks()
            self.clock["now"] += service._calculate_optimal_sleep_interval(self.clock["now"] - start)

    async def test_many_tasks_due_at_once_all_run(self, monkeypatch):
        # Release review simulation: 10 tasks due at the same minute, 45 s per
        # batch of three. Before the fix one task was skipped as "missed".
        self._store(10, due_at=self.clock["now"] - 1)
        executed = self._executor(monkeypatch, lambda task: 15)

        await self._run_cycles(ss.SchedulerService(), 4)

        assert sorted(executed) == sorted(f"t{i}" for i in range(10))
        assert self.missed == []

    async def test_tasks_deferred_for_capacity_are_not_missed(self, monkeypatch):
        self._store(4, due_at=self.clock["now"] - 1)
        executed = self._executor(monkeypatch, lambda task: 1)
        service = ss.SchedulerService()
        service.active_tasks.update({"busy-1", "busy-2", "busy-3"})

        await service._check_and_execute_tasks()  # no free slot -> all deferred
        assert executed == []
        service.active_tasks.clear()
        self.clock["now"] += 600  # longer than the grace period

        await service._check_and_execute_tasks()

        assert sorted(executed) == ["t0", "t1", "t2", "t3"]
        assert self.missed == []

    async def test_task_due_during_a_long_cycle_still_runs(self, monkeypatch):
        slow = _task(task_id="slow", container="c1", hour=_far_hour())
        slow.next_run_ts = self.clock["now"] - 1
        later = _task(task_id="later", container="c2", hour=_far_hour())
        later.next_run_ts = self.clock["now"] + 100  # due while "slow" runs
        assert save_tasks([slow, later]) is True
        executed = self._executor(monkeypatch, lambda task: 400 if task.task_id == "slow" else 1)

        await self._run_cycles(ss.SchedulerService(), 2)

        assert executed == ["slow", "later"]
        assert self.missed == []

    async def test_host_down_between_cycles_is_still_a_missed_run(self, monkeypatch):
        later = _task(task_id="later", hour=_far_hour())
        later.next_run_ts = self.clock["now"] + 100
        assert save_tasks([later]) is True
        executed = self._executor(monkeypatch, lambda task: 1)
        service = ss.SchedulerService()

        await service._check_and_execute_tasks()  # not due yet
        self.clock["now"] += 3600  # e.g. host suspended
        await service._check_and_execute_tasks()

        assert executed == []
        assert self.missed == ["later"]


# --------------------------------------------------------------------------- #
# R5-7 - yearly next run                                                      #
# --------------------------------------------------------------------------- #
class TestR5YearlyNextRun:
    def _next(self, now, month, day, year=None):
        task = _task(CYCLE_YEARLY, month=month, day=day, year=year)
        return task._calculate_yearly_next_run(UTC, now, 4, 0)

    def test_stale_year_does_not_skip_the_current_year(self):
        now = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)
        assert self._next(now, 12, 24, year=2025) == datetime(2026, 12, 24, 4, 0, tzinfo=UTC)

    def test_passed_date_moves_to_next_year(self):
        now = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)
        assert self._next(now, 3, 1, year=2026) == datetime(2027, 3, 1, 4, 0, tzinfo=UTC)

    def test_future_year_is_the_first_run(self):
        now = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)
        assert self._next(now, 3, 1, year=2030) == datetime(2030, 3, 1, 4, 0, tzinfo=UTC)

    def test_feb_29_is_clamped_per_year(self):
        # First computed in a non-leap year -> Feb 28; the next leap year gets Feb 29 again
        assert self._next(datetime(2026, 9, 15, tzinfo=UTC), 2, 29) == datetime(2027, 2, 28, 4, 0, tzinfo=UTC)
        assert self._next(datetime(2027, 3, 1, tzinfo=UTC), 2, 29) == datetime(2028, 2, 29, 4, 0, tzinfo=UTC)
        assert self._next(datetime(2028, 3, 1, tzinfo=UTC), 2, 29) == datetime(2029, 2, 28, 4, 0, tzinfo=UTC)

    def test_stored_day_is_not_changed(self):
        task = _task(CYCLE_YEARLY, month=2, day=29)
        task.calculate_next_run()
        assert task.day_val == 29
        assert task.to_dict()["schedule_details"]["day"] == 29
