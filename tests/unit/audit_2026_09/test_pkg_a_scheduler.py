# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Audit 2026-09 package A regression tests       #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Regression tests for audit 2026-09 package A (scheduler & tasks).

Covers A1-A7, A10 (execution-time check) and A12. Every test runs against a
private tasks.json (same isolation as the scheduler unit suites).
"""

from __future__ import annotations

import dataclasses
import json
import threading
import time as _time
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytz

from services.scheduling import runtime as scheduler_runtime
from services.scheduling import scheduler as scheduler_mod
from services.scheduling import scheduler_service as ss
from services.scheduling.scheduler import (
    CYCLE_DAILY,
    CYCLE_ONCE,
    CYCLE_WEEKLY,
    DAYS_OF_WEEK,
    DONATION_TASK_ID,
    ScheduledTask,
    add_task,
    create_donation_system_task,
    delete_task,
    load_tasks,
    normalize_weekday,
    parse_weekday_string,
    save_tasks,
    update_task,
)

BERLIN = pytz.timezone("Europe/Berlin")
_REAL_DISALLOWED_REASON = scheduler_mod._get_disallowed_action_reason


@pytest.fixture(autouse=True)
def _isolated_tasks_file(monkeypatch, tmp_path):
    monkeypatch.setenv("DDC_SCHEDULER_CONFIG_DIR", str(tmp_path))
    scheduler_runtime.reset_scheduler_runtime()
    fresh = scheduler_runtime.get_scheduler_runtime()
    monkeypatch.setattr(scheduler_mod, "_runtime", fresh)
    monkeypatch.setattr(scheduler_mod, "TASKS_FILE_PATH", fresh.tasks_file_path)
    monkeypatch.setattr(scheduler_mod, "_get_system_tasks", lambda: [])
    # Container config lookups must not depend on the host's config/ directory
    monkeypatch.setattr(scheduler_mod, "_get_disallowed_action_reason", lambda c, a: None)
    yield tmp_path
    scheduler_runtime.reset_scheduler_runtime()


def _stored(tmp_path):
    return json.loads((tmp_path / "tasks.json").read_text(encoding="utf-8"))


def _daily(task_id=None, container="c1", action="restart", hour=4, minute=0, created_by=""):
    return ScheduledTask(task_id=task_id, container_name=container, action=action,
                         cycle=CYCLE_DAILY, hour=hour, minute=minute, timezone_str="UTC",
                         created_by=created_by)


def _weekday_of(ts):
    return datetime.fromtimestamp(ts, pytz.UTC).weekday()


# --------------------------------------------------------------------------- #
# A1 - weekday is persisted                                                   #
# --------------------------------------------------------------------------- #
class TestA1WeekdayPersisted:
    def test_discord_button_weekly_task_survives_reload(self, tmp_path):
        # CreateTaskButton passes weekday=<0-6> and day=None
        task = ScheduledTask(container_name="c1", action="restart", cycle=CYCLE_WEEKLY,
                             hour=4, minute=0, day=None, weekday=1, timezone_str="UTC")
        assert task.to_dict()["schedule_details"] == {"time": "04:00", "day": "tuesday"}
        assert add_task(task) is True

        reloaded = load_tasks()
        assert [t.task_id for t in reloaded] == [task.task_id]
        assert reloaded[0].day_val == "tuesday"
        assert reloaded[0].weekday_val == 1
        # load_tasks() must not drop the task from the file
        assert _stored(tmp_path)[0]["schedule_details"]["day"] == "tuesday"
        assert _weekday_of(reloaded[0].next_run_ts) == 1

    def test_weekday_only_in_weekday_val_is_saved(self):
        task = ScheduledTask(container_name="c1", action="restart", cycle=CYCLE_WEEKLY,
                             schedule_details={"time": "04:00"}, timezone_str="UTC")
        task.weekday_val = 4
        assert task.to_dict()["schedule_details"]["day"] == "friday"

    def test_top_level_weekday_used_next_to_schedule_details(self):
        task = ScheduledTask.from_dict({
            "id": "t1", "container": "c1", "action": "stop", "cycle": "weekly",
            "schedule_details": {"time": "04:00"}, "weekday": 3, "_timezone_str": "UTC",
        })
        assert task.is_valid() is True
        assert task.day_val == "thursday"

    def test_web_ui_edit_to_weekly_keeps_weekday(self, tmp_path, monkeypatch):
        from services.web.task_management_service import EditTaskRequest, TaskManagementService
        monkeypatch.setattr(TaskManagementService, "_log_task_update", lambda self, task, orig: None)
        task = _daily()
        assert add_task(task) is True

        result = TaskManagementService().edit_task(EditTaskRequest(
            task_id=task.task_id, operation="update",
            data={"cycle": "weekly", "schedule_details": {"time": "05:00", "day": "Fri"}},
        ))
        assert result.success is True, result.error
        assert _stored(tmp_path)[0]["schedule_details"] == {"time": "05:00", "day": "friday"}
        reloaded = load_tasks()
        assert len(reloaded) == 1
        assert _weekday_of(reloaded[0].next_run_ts) == 4


# --------------------------------------------------------------------------- #
# A2 - Web UI weekday abbreviations                                           #
# --------------------------------------------------------------------------- #
class TestA2WeekdayAbbreviations:
    @pytest.mark.parametrize("day, expected", [
        ("Mon", 0), ("tue", 1), ("WED", 2), ("Thu", 3), ("fri", 4), ("Sat", 5), ("Sun", 6), ("sunday", 6),
    ])
    def test_abbreviations_are_accepted(self, day, expected):
        task = ScheduledTask(container_name="c1", action="restart", cycle=CYCLE_WEEKLY,
                             schedule_details={"time": "04:00", "day": day}, timezone_str="UTC")
        assert task.is_valid() is True
        assert task.day_val == DAYS_OF_WEEK[expected]
        assert _weekday_of(task.next_run_ts) == expected

    def test_web_ui_add_weekly_task(self, tmp_path, monkeypatch):
        from services.web.task_management_service import AddTaskRequest, TaskManagementService
        monkeypatch.setattr(TaskManagementService, "_log_task_creation", lambda self, task: None)
        result = TaskManagementService().add_task(AddTaskRequest(
            container="c1", action="restart", cycle="weekly",
            schedule_details={"time": "04:00", "day": "Mon"}, timezone_str="UTC",
        ))
        assert result.success is True, result.error
        assert _stored(tmp_path)[0]["schedule_details"]["day"] == "monday"

    def test_normalize_weekday_rejects_invalid_values(self):
        for value in (None, "", "mo", "xyz", 7, -1, True, "8", 2.0):
            assert normalize_weekday(value) is None
        assert normalize_weekday("7") == "sunday"  # tolerated for old data
        assert normalize_weekday(0) == "monday"


# --------------------------------------------------------------------------- #
# A3 - /schedule_weekly weekday handling                                      #
# --------------------------------------------------------------------------- #
class TestA3WeekdayParsing:
    def test_numeric_input_is_one_based(self):
        assert parse_weekday_string("1") == 0
        assert parse_weekday_string("2") == 1
        assert parse_weekday_string("7") == 6
        assert parse_weekday_string("0") is None
        assert parse_weekday_string("Tuesday") == 1

    # test_schedule_weekly_command_keeps_selected_day stood here. It drove
    # ScheduleCommandsMixin._impl_schedule_weekly_command, the /schedule weekly
    # slash command - a command the bot never registered: no cog inherited that
    # mixin and the startup never loaded the module, so the test was the only
    # thing keeping cogs/scheduler_commands.py alive (review B17). What it
    # really guarded - a weekly task keeping the day that was picked - is
    # checked above against the weekday parsing and below against the web
    # panel's own add/edit path, which are the two ways a weekly task is
    # created today.


# --------------------------------------------------------------------------- #
# A4 - missed runs                                                            #
# --------------------------------------------------------------------------- #
class TestA4MissedRuns:
    @pytest.fixture(autouse=True)
    def _grace(self, monkeypatch):
        monkeypatch.setattr(ss, "MISSED_RUN_GRACE_SECONDS", 300)

    async def test_long_missed_recurring_task_is_rescheduled_not_run(self, monkeypatch):
        task = _daily()
        assert add_task(task) is True
        task.next_run_ts = _time.time() - 3600  # e.g. host was down
        assert save_tasks([task]) is True
        executed = AsyncMock()
        monkeypatch.setattr(ss, "execute_task", executed)

        await ss.SchedulerService()._check_and_execute_tasks()

        executed.assert_not_called()
        stored = load_tasks()[0]
        assert stored.is_active is True
        assert stored.next_run_ts > _time.time()

    async def test_slightly_late_task_runs_exactly_once(self, monkeypatch):
        task = _daily()
        assert add_task(task) is True
        task.next_run_ts = _time.time() - 150  # outside the old 90 s window
        assert save_tasks([task]) is True
        calls = []

        async def _fake_execute(t):
            calls.append(t.task_id)

        monkeypatch.setattr(ss, "execute_task", _fake_execute)
        # The reschedule cannot be saved -> next_run stays in the past
        monkeypatch.setattr(ss, "update_task", lambda t, **kw: False)
        service = ss.SchedulerService()

        await service._check_and_execute_tasks()
        await service._check_and_execute_tasks()

        assert calls == [task.task_id]

    async def test_missed_one_time_task_is_deactivated(self, monkeypatch):
        task = ScheduledTask(container_name="c1", action="stop", cycle=CYCLE_ONCE,
                             year=2099, month=1, day=1, hour=4, minute=0, timezone_str="UTC")
        assert add_task(task) is True
        task.next_run_ts = _time.time() - 7200
        assert save_tasks([task]) is True
        executed = AsyncMock()
        monkeypatch.setattr(ss, "execute_task", executed)

        await ss.SchedulerService()._check_and_execute_tasks()

        executed.assert_not_called()
        stored = load_tasks()[0]
        assert stored.is_active is False
        assert stored.last_run_success is False
        assert "Missed" in stored.last_run_error


# --------------------------------------------------------------------------- #
# A5 - post-execution reschedule skips the collision check                    #
# --------------------------------------------------------------------------- #
class TestA5RescheduleWithoutCollisionCheck:
    async def test_reschedule_saved_despite_neighbouring_task(self, monkeypatch):
        a = _daily(task_id="a")
        upcoming = a.next_run_ts  # next 04:00 UTC
        b = _daily(task_id="b", action="stop", hour=4, minute=5)
        b.next_run_ts = upcoming + 300  # within the 10-minute window of a's next run
        a.next_run_ts = upcoming - 86400  # the occurrence being executed now
        assert save_tasks([a, b]) is True
        monkeypatch.setattr(scheduler_mod, "docker_action_service_first", AsyncMock(return_value=True))
        monkeypatch.setattr(scheduler_mod, "log_user_action", lambda **kw: None)

        assert await scheduler_mod.execute_task(a, timeout=2) is True

        stored = {t.task_id: t for t in load_tasks()}
        assert stored["a"].next_run_ts == upcoming
        assert stored["a"].last_run_success is True

    def test_user_update_still_checks_collisions(self):
        a = _daily(task_id="a")
        b = _daily(task_id="b", action="stop", hour=8)
        assert save_tasks([a, b]) is True
        b.next_run_ts = a.next_run_ts + 60
        assert update_task(b) is False
        assert update_task(b, check_collision=False) is True


# --------------------------------------------------------------------------- #
# A6 - DST-correct daily/weekly next run                                      #
# --------------------------------------------------------------------------- #
class TestA6DaylightSaving:
    def _task(self, cycle, **kwargs):
        return ScheduledTask(container_name="c1", action="restart", cycle=cycle,
                             timezone_str="Europe/Berlin", **kwargs)

    def test_daily_after_spring_forward(self):
        task = self._task(CYCLE_DAILY, hour=3, minute=0)
        now = BERLIN.localize(datetime(2026, 3, 28, 12, 0))  # CET, day before the switch
        next_run = task._calculate_daily_next_run(now, 3, 0, BERLIN)
        assert next_run.astimezone(pytz.UTC) == pytz.UTC.localize(datetime(2026, 3, 29, 1, 0))
        assert (next_run.hour, next_run.minute) == (3, 0)

    def test_daily_after_fall_back(self):
        task = self._task(CYCLE_DAILY, hour=3, minute=0)
        now = BERLIN.localize(datetime(2026, 10, 24, 12, 0))  # CEST, day before the switch
        next_run = task._calculate_daily_next_run(now, 3, 0, BERLIN)
        assert next_run.astimezone(pytz.UTC) == pytz.UTC.localize(datetime(2026, 10, 25, 2, 0))

    def test_weekly_across_spring_forward(self):
        task = self._task(CYCLE_WEEKLY, schedule_details={"time": "03:00", "day": "sunday"})
        now = BERLIN.localize(datetime(2026, 3, 25, 12, 0))  # Wednesday, CET
        next_run = task._calculate_weekly_next_run(BERLIN, now, 3, 0)
        assert next_run.astimezone(pytz.UTC) == pytz.UTC.localize(datetime(2026, 3, 29, 1, 0))

    def test_weekly_ignores_stale_last_run_after_edit(self):
        # A12: weekly next run used last_run + 7 days, keeping the old weekday
        task = self._task(CYCLE_WEEKLY, schedule_details={"time": "04:00", "day": "monday"})
        task.last_run_ts = _time.time() - 20 * 86400
        task.day_val, task.weekday_val = "friday", 4
        task.calculate_next_run()
        assert task.next_run_ts > _time.time()
        assert datetime.fromtimestamp(task.next_run_ts, BERLIN).weekday() == 4


# --------------------------------------------------------------------------- #
# A7 - donation system task                                                   #
# --------------------------------------------------------------------------- #
class TestA7DonationSystemTask:
    @pytest.fixture(autouse=True)
    def _donations_enabled(self, monkeypatch):
        monkeypatch.setattr("services.donation.donation_utils.is_donations_disabled", lambda: False)
        monkeypatch.setattr(scheduler_mod, "load_config", lambda: {"timezone": "UTC"})

    def test_next_run_stable_across_reloads(self):
        first = create_donation_system_task()
        assert first.next_run_ts is not None
        # At the due moment the remembered next run is slightly in the past ...
        due = _time.time() - 30
        scheduler_mod._runtime.store_system_task_state(DONATION_TASK_ID, {"next_run_ts": due})
        # ... and a reload must not push it to the next month
        assert create_donation_system_task().next_run_ts == due

    async def test_run_state_kept_after_execution(self, monkeypatch):
        monkeypatch.setattr("services.scheduling.donation_message_service.execute_donation_message_task",
                            AsyncMock(return_value=True))
        monkeypatch.setattr("services.scheduling.donation_message_service.get_bot_instance", lambda: None)
        monkeypatch.setattr(scheduler_mod, "log_user_action", lambda **kw: None)
        task = create_donation_system_task()
        task.next_run_ts = _time.time() - 30

        assert await scheduler_mod.execute_task(task) is True

        reloaded = create_donation_system_task()
        assert reloaded.last_run_success is True
        assert reloaded.last_run_ts is not None
        assert reloaded.next_run_ts > _time.time()
        now = datetime.now(pytz.UTC)
        next_dt = datetime.fromtimestamp(reloaded.next_run_ts, pytz.UTC)
        assert (next_dt.year, next_dt.month) > (now.year, now.month)

    async def test_donation_message_uses_progress_state_fields(self):
        from services.mech.progress_service import ProgressState
        from services.scheduling import donation_message_service as dms

        state = ProgressState(level=3, power_current=0.0, power_max=10.0, power_percent=0,
                              evo_current=1.0, evo_max=20.0, evo_percent=5, total_donated=1.0,
                              can_level_up=False, is_offline=True, difficulty_bin=1,
                              difficulty_tier="easy", member_count=1)
        boosted = dataclasses.replace(state, power_current=1.0, is_offline=False)
        progress = MagicMock()
        progress.get_state.return_value = state
        progress.add_system_donation.return_value = boosted
        channel = MagicMock(send=AsyncMock())
        bot = MagicMock()
        bot.get_channel.return_value = channel

        with patch("services.mech.progress_service.get_progress_service", return_value=progress), \
             patch("services.config.config_service.load_config",
                   return_value={"channel_permissions":
                                 {"123": {"commands": {"serverstatus": True}}}}), \
             patch("services.mech.mech_evolutions.get_evolution_level_info",
                   return_value=SimpleNamespace(name="Rusty Mech")):
            assert await dms.execute_donation_message_task(bot=bot) is True

        progress.add_system_donation.assert_called_once()
        stats = channel.send.await_args.kwargs["embed"].fields[0].value
        assert "$1.00" in stats
        assert "3 - Rusty Mech" in stats
        assert "5%" in stats


# --------------------------------------------------------------------------- #
# A10 - allowed_actions re-checked at execution time                          #
# --------------------------------------------------------------------------- #
class TestA10AllowedActionsAtExecution:
    def _servers(self, monkeypatch, servers):
        monkeypatch.setattr(scheduler_mod, "_get_disallowed_action_reason", _REAL_DISALLOWED_REASON)
        service = MagicMock()
        service.get_all_servers.return_value = servers
        monkeypatch.setattr("services.config.server_config_service.get_server_config_service", lambda: service)
        action = AsyncMock(return_value=True)
        monkeypatch.setattr(scheduler_mod, "docker_action_service_first", action)
        monkeypatch.setattr(scheduler_mod, "log_user_action", lambda **kw: None)
        return action

    async def test_disallowed_action_is_skipped_and_marked_failed(self, monkeypatch):
        action = self._servers(monkeypatch, [{"docker_name": "c1", "allowed_actions": ["status", "start"]}])
        task = _daily(action="stop", created_by="someone#1234")
        assert add_task(task) is True

        assert await scheduler_mod.execute_task(task, timeout=2) is False

        action.assert_not_called()
        stored = load_tasks()[0]
        assert stored.last_run_success is False
        assert "no longer allowed" in stored.last_run_error
        assert stored.next_run_ts > _time.time()

    async def test_allowed_action_runs(self, monkeypatch):
        action = self._servers(monkeypatch, [{"docker_name": "c1", "allowed_actions": ["stop"]}])
        task = _daily(action="stop")
        assert add_task(task) is True
        assert await scheduler_mod.execute_task(task, timeout=2) is True
        action.assert_awaited_once()

    async def test_unconfigured_container_still_runs(self, monkeypatch):
        action = self._servers(monkeypatch, [{"docker_name": "other", "allowed_actions": []}])
        task = _daily(action="stop", created_by="someone#1234")
        assert add_task(task) is True
        assert await scheduler_mod.execute_task(task, timeout=2) is True
        action.assert_awaited_once()

    async def test_task_without_creator_marker_still_runs(self, monkeypatch):
        """V2 review B4: tasks from older installs have no created_by. Together with the
        ['status'] default for container configs lacking allowed_actions they would be skipped
        on every run, forever - so a missing marker must NOT count as Discord-created."""
        action = self._servers(monkeypatch, [{"docker_name": "c1", "allowed_actions": ["status"]}])
        task = _daily(action="stop", created_by="")
        assert add_task(task) is True

        assert await scheduler_mod.execute_task(task, timeout=2) is True
        action.assert_awaited_once()


# --------------------------------------------------------------------------- #
# A12 - tasks.json lock                                                       #
# --------------------------------------------------------------------------- #
class TestA12TasksFileLock:
    def test_writes_happen_under_the_lock(self, monkeypatch):
        owned = []
        real_save = scheduler_mod._save_raw_tasks_to_file

        def _spy(data):
            owned.append(scheduler_mod._TASKS_LOCK._is_owned())
            return real_save(data)

        monkeypatch.setattr(scheduler_mod, "_save_raw_tasks_to_file", _spy)
        task = _daily(task_id="locked")
        assert add_task(task) is True
        task.time_str = "05:00"
        task.calculate_next_run()
        assert update_task(task) is True
        assert delete_task("locked") is True
        assert owned and all(owned)

    def test_concurrent_adds_keep_all_tasks(self, tmp_path):
        results = []

        def _add(index):
            results.append(add_task(_daily(task_id=f"t{index}", container=f"c{index}")))

        threads = [threading.Thread(target=_add, args=(i,)) for i in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert results == [True] * 8
        assert sorted(t["id"] for t in _stored(tmp_path)) == sorted(f"t{i}" for i in range(8))
