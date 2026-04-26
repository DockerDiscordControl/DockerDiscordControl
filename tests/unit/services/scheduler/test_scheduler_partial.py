# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Scheduler Partial Coverage Tests              #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Functional unit tests for ``services.scheduling.scheduler`` and
``services.scheduling.schedule_helpers``.

The scheduler module is large and has historically had very low coverage
(~10%).  These tests exercise the pure / file-IO portions of the public
surface to lift coverage without touching the async ``_check_and_execute_tasks``
loop or the Docker action paths in ``execute_task``.

Strategy:
- Each test (or fixture) redirects the scheduler runtime at a per-test
  ``tmp_path`` so reads/writes to ``tasks.json`` are fully isolated.
- The module-level ``TASKS_FILE_PATH`` constant captured at import time is
  monkeypatched alongside the runtime so file-IO functions resolve to tmp.
- System task injection (the donation task) is patched out for tests that
  exercise raw load/save round-trips so we can make exact size assertions.
"""

from __future__ import annotations

import json
import time as _time
from pathlib import Path
from typing import List

import pytest

from services.scheduling import runtime as scheduler_runtime
from services.scheduling import scheduler as scheduler_mod
from services.scheduling.scheduler import (
    CYCLE_CRON,
    CYCLE_DAILY,
    CYCLE_MONTHLY,
    CYCLE_ONCE,
    CYCLE_WEEKLY,
    CYCLE_YEARLY,
    DAYS_OF_WEEK,
    DONATION_TASK_ID,
    MIN_TASK_INTERVAL_SECONDS,
    SYSTEM_TASK_PREFIX,
    VALID_ACTIONS,
    VALID_CYCLES,
    ScheduledTask,
    add_task,
    check_task_time_collision,
    delete_task,
    find_task_by_id,
    get_next_week_tasks,
    get_tasks_for_container,
    get_tasks_in_timeframe,
    load_tasks,
    parse_month_string,
    parse_time_string,
    parse_weekday_string,
    save_tasks,
    update_task,
    validate_new_task_input,
)
from services.scheduling.schedule_helpers import (
    ScheduleValidationError,
    check_schedule_permissions,
    create_task_success_message,
    parse_and_validate_time,
    validate_task_before_creation,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolated_tasks_file(monkeypatch, tmp_path):
    """Redirect every scheduler IO call at a private ``tasks.json``.

    Both the runtime singleton and the import-time captured module constants
    are pointed at ``tmp_path`` so the production config dir is never touched.
    """

    monkeypatch.setenv("DDC_SCHEDULER_CONFIG_DIR", str(tmp_path))
    scheduler_runtime.reset_scheduler_runtime()

    # Recreate the runtime under the new env var and re-bind the module
    # constants that captured the original path at import time.
    fresh = scheduler_runtime.get_scheduler_runtime()
    monkeypatch.setattr(scheduler_mod, "_runtime", fresh)
    monkeypatch.setattr(scheduler_mod, "TASKS_FILE_PATH", fresh.tasks_file_path)

    # Suppress the donation system task so load_tasks returns *exactly* the
    # user tasks we wrote, making counts easy to assert.
    monkeypatch.setattr(scheduler_mod, "_get_system_tasks", lambda: [])

    yield tmp_path

    scheduler_runtime.reset_scheduler_runtime()


def _make_daily_task(
    *,
    container_name: str = "nginx",
    action: str = "restart",
    hour: int = 4,
    minute: int = 30,
    task_id: str | None = None,
) -> ScheduledTask:
    """Helper: produce a valid daily ScheduledTask."""

    return ScheduledTask(
        task_id=task_id,
        container_name=container_name,
        action=action,
        cycle=CYCLE_DAILY,
        hour=hour,
        minute=minute,
        timezone_str="UTC",
    )


# ---------------------------------------------------------------------------
# ScheduledTask: construction & basic invariants
# ---------------------------------------------------------------------------


class TestScheduledTaskConstruction:
    def test_default_task_id_is_uuid_like(self):
        task = _make_daily_task()
        assert isinstance(task.task_id, str)
        # uuid4 default has 36 chars (8-4-4-4-12 + 4 dashes).
        assert len(task.task_id) == 36

    def test_explicit_task_id_preserved(self):
        task = _make_daily_task(task_id="abc-123")
        assert task.task_id == "abc-123"

    def test_time_str_formatted_from_hour_minute(self):
        task = _make_daily_task(hour=7, minute=5)
        assert task.time_str == "07:05"

    def test_next_run_calculated_when_valid(self):
        task = _make_daily_task()
        # Daily tasks are valid by construction → next_run_ts populated.
        assert task.next_run_ts is not None
        assert task.next_run_ts > _time.time()

    def test_is_active_default_true(self):
        task = _make_daily_task()
        assert task.is_active is True
        assert task.status == "pending"

    def test_created_at_from_iso_string(self):
        iso = "2025-01-15T08:30:00+00:00"
        task = ScheduledTask(
            container_name="x",
            action="start",
            cycle=CYCLE_DAILY,
            hour=12,
            minute=0,
            created_at=iso,
            timezone_str="UTC",
        )
        assert task.created_at_ts is not None
        assert task.created_at_dt.year == 2025
        assert task.created_at_dt.month == 1

    def test_created_at_from_timestamp(self):
        ts = 1_700_000_000.0
        task = ScheduledTask(
            container_name="x",
            action="start",
            cycle=CYCLE_DAILY,
            hour=12,
            minute=0,
            created_at=ts,
            timezone_str="UTC",
        )
        assert task.created_at_ts == ts

    def test_created_at_invalid_iso_falls_back(self):
        task = ScheduledTask(
            container_name="x",
            action="start",
            cycle=CYCLE_DAILY,
            hour=12,
            minute=0,
            created_at="not-an-iso",
            timezone_str="UTC",
        )
        # Falls back to current time without raising.
        assert task.created_at_ts is not None


# ---------------------------------------------------------------------------
# ScheduledTask.is_valid
# ---------------------------------------------------------------------------


class TestScheduledTaskValidation:
    def test_daily_task_is_valid(self):
        assert _make_daily_task().is_valid() is True

    def test_missing_container_invalid(self):
        task = ScheduledTask(action="start", cycle=CYCLE_DAILY, hour=1, minute=0)
        assert task.is_valid() is False

    def test_missing_action_invalid(self):
        task = ScheduledTask(container_name="x", cycle=CYCLE_DAILY, hour=1, minute=0)
        assert task.is_valid() is False

    def test_missing_cycle_invalid(self):
        task = ScheduledTask(container_name="x", action="start", hour=1, minute=0)
        assert task.is_valid() is False

    def test_unknown_action_invalid(self):
        task = ScheduledTask(
            container_name="x", action="bounce", cycle=CYCLE_DAILY, hour=1, minute=0
        )
        assert task.is_valid() is False

    def test_unknown_cycle_invalid(self):
        task = ScheduledTask(
            container_name="x",
            action="start",
            cycle="every_full_moon",
            hour=1,
            minute=0,
        )
        assert task.is_valid() is False

    def test_invalid_time_string_invalid(self):
        task = ScheduledTask(
            container_name="x", action="start", cycle=CYCLE_DAILY, hour=25, minute=0
        )
        # Hour out of range → invalid.
        assert task.is_valid() is False

    def test_weekly_with_weekday_val_valid(self):
        task = ScheduledTask(
            container_name="x",
            action="start",
            cycle=CYCLE_WEEKLY,
            hour=10,
            minute=0,
            weekday=2,
        )
        assert task.is_valid() is True

    def test_weekly_with_day_val_string_valid(self):
        task = ScheduledTask(
            container_name="x",
            action="start",
            cycle=CYCLE_WEEKLY,
            hour=10,
            minute=0,
            schedule_details={"time": "10:00", "day": "wednesday"},
        )
        assert task.is_valid() is True

    def test_weekly_without_day_invalid(self):
        task = ScheduledTask(
            container_name="x", action="start", cycle=CYCLE_WEEKLY, hour=10, minute=0
        )
        assert task.is_valid() is False

    def test_monthly_with_day_valid(self):
        task = ScheduledTask(
            container_name="x",
            action="start",
            cycle=CYCLE_MONTHLY,
            hour=3,
            minute=0,
            day=15,
        )
        assert task.is_valid() is True

    def test_monthly_invalid_day(self):
        task = ScheduledTask(
            container_name="x",
            action="start",
            cycle=CYCLE_MONTHLY,
            hour=3,
            minute=0,
            day=42,
        )
        assert task.is_valid() is False

    def test_yearly_valid(self):
        task = ScheduledTask(
            container_name="x",
            action="start",
            cycle=CYCLE_YEARLY,
            hour=0,
            minute=0,
            month=6,
            day=15,
        )
        assert task.is_valid() is True

    def test_yearly_invalid_month(self):
        task = ScheduledTask(
            container_name="x",
            action="start",
            cycle=CYCLE_YEARLY,
            hour=0,
            minute=0,
            month=13,
            day=1,
        )
        assert task.is_valid() is False

    def test_once_valid(self):
        task = ScheduledTask(
            container_name="x",
            action="start",
            cycle=CYCLE_ONCE,
            hour=0,
            minute=0,
            year=2099,
            month=1,
            day=1,
        )
        assert task.is_valid() is True

    def test_once_missing_year_invalid(self):
        task = ScheduledTask(
            container_name="x",
            action="start",
            cycle=CYCLE_ONCE,
            hour=0,
            minute=0,
            month=1,
            day=1,
        )
        assert task.is_valid() is False

    def test_system_task_id_treated_specially(self):
        task = ScheduledTask(
            task_id=DONATION_TASK_ID,
            container_name="SYSTEM",
            action="donation_message",
            cycle=CYCLE_MONTHLY,
        )
        # Donation/system task validates via _validate_system_task — donation
        # is in SYSTEM_ACTIONS so it should be considered valid even without
        # a container_name being a real docker container.
        assert task.is_valid() is True
        assert task.is_system_task() is True
        assert task.is_donation_task() is True


# ---------------------------------------------------------------------------
# ScheduledTask.to_dict / from_dict round-trip
# ---------------------------------------------------------------------------


class TestScheduledTaskSerialization:
    def test_to_dict_contains_expected_keys(self):
        task = _make_daily_task()
        data = task.to_dict()

        assert data["id"] == task.task_id
        assert data["container"] == "nginx"
        assert data["action"] == "restart"
        assert data["cycle"] == CYCLE_DAILY
        assert data["is_active"] is True
        assert data["status"] == "pending"
        assert data["schedule_details"]["time"] == "04:30"
        assert data["_timezone_str"] == "UTC"

    def test_from_dict_round_trip(self):
        original = _make_daily_task(
            container_name="redis", action="stop", hour=22, minute=15
        )
        original_id = original.task_id
        original_next_run = original.next_run_ts

        data = original.to_dict()
        rebuilt = ScheduledTask.from_dict(data)

        assert rebuilt.task_id == original_id
        assert rebuilt.container_name == "redis"
        assert rebuilt.action == "stop"
        assert rebuilt.cycle == CYCLE_DAILY
        assert rebuilt.time_str == "22:15"
        # next_run_ts is carried via _next_run_ts in the dict.
        assert rebuilt.next_run_ts == original_next_run

    def test_from_dict_accepts_alt_id_field(self):
        data = {
            "task_id": "alt-id-1",
            "container_name": "alt-container",
            "action": "start",
            "cycle": CYCLE_DAILY,
            "schedule_details": {"time": "10:00"},
            "_timezone_str": "UTC",
        }
        task = ScheduledTask.from_dict(data)
        assert task.task_id == "alt-id-1"
        assert task.container_name == "alt-container"


# ---------------------------------------------------------------------------
# ScheduledTask: should_run / update_after_execution
# ---------------------------------------------------------------------------


class TestScheduledTaskRuntime:
    def test_should_run_false_when_in_future(self):
        task = _make_daily_task()
        assert task.should_run() is False

    def test_should_run_true_when_past(self):
        task = _make_daily_task()
        task.next_run_ts = _time.time() - 60
        assert task.should_run() is True

    def test_should_run_false_when_no_next_run(self):
        task = _make_daily_task()
        task.next_run_ts = None
        assert task.should_run() is False

    def test_update_after_execution_once_marks_completed(self):
        task = ScheduledTask(
            container_name="x",
            action="start",
            cycle=CYCLE_ONCE,
            hour=0,
            minute=0,
            year=2099,
            month=1,
            day=1,
            timezone_str="UTC",
        )
        task.update_after_execution()
        assert task.status == "completed"
        assert task.is_active is False
        assert task.next_run_ts is None
        assert task.last_run_ts is not None

    def test_update_after_execution_daily_reschedules(self):
        task = _make_daily_task()
        first = task.next_run_ts
        task.update_after_execution()
        # Recurring → still pending and a new (later) next_run computed.
        assert task.status == "pending"
        assert task.next_run_ts is not None
        # Daily reschedule moves to next occurrence (>= today, possibly
        # tomorrow). We just assert it recomputed and last_run_ts is set.
        assert task.last_run_ts is not None
        assert task.next_run_ts >= first - 1

    def test_get_next_run_datetime_returns_aware_dt(self):
        task = _make_daily_task()
        dt = task.get_next_run_datetime()
        assert dt is not None
        assert dt.tzinfo is not None


# ---------------------------------------------------------------------------
# Pure parser helpers
# ---------------------------------------------------------------------------


class TestParsers:
    def test_parse_time_string_hh_mm(self):
        assert parse_time_string("14:30") == (14, 30)

    def test_parse_time_string_padded(self):
        assert parse_time_string("07:05") == (7, 5)

    def test_parse_time_string_single_number(self):
        assert parse_time_string("9") == (9, 0)

    def test_parse_time_string_invalid(self):
        # Out-of-range still returns (None, None) per implementation.
        # Use an unambiguously broken string so all fallbacks fail.
        assert parse_time_string("not-a-time") == (None, None)

    def test_parse_time_string_empty(self):
        assert parse_time_string("") == (None, None)

    def test_parse_month_string_full_name(self):
        assert parse_month_string("January") == 1
        assert parse_month_string("december") == 12

    def test_parse_month_string_short_name(self):
        assert parse_month_string("Feb") == 2

    def test_parse_month_string_german(self):
        assert parse_month_string("Mai") == 5

    def test_parse_month_string_numeric(self):
        assert parse_month_string("7") == 7

    def test_parse_month_string_invalid(self):
        assert parse_month_string("notamonth") is None
        assert parse_month_string("13") is None

    def test_parse_weekday_string_names(self):
        assert parse_weekday_string("monday") == 0
        assert parse_weekday_string("Sun") == 6
        assert parse_weekday_string("WED") == 2

    def test_parse_weekday_string_numeric_zero_based(self):
        assert parse_weekday_string("0") == 0
        assert parse_weekday_string("6") == 6

    def test_parse_weekday_string_numeric_one_based(self):
        # 7 is converted via (n-1) % 7 = 6 (Sunday).
        assert parse_weekday_string("7") == 6


# ---------------------------------------------------------------------------
# validate_new_task_input
# ---------------------------------------------------------------------------


class TestValidateNewTaskInput:
    def test_missing_container(self):
        ok, _ = validate_new_task_input(
            container_name="", action="start", cycle=CYCLE_DAILY, hour=1, minute=0
        )
        assert ok is False

    def test_invalid_action(self):
        ok, _ = validate_new_task_input(
            container_name="x", action="bounce", cycle=CYCLE_DAILY, hour=1, minute=0
        )
        assert ok is False

    def test_invalid_cycle(self):
        ok, _ = validate_new_task_input(
            container_name="x",
            action="start",
            cycle="quarterly",
            hour=1,
            minute=0,
        )
        assert ok is False

    def test_daily_ok(self):
        ok, _ = validate_new_task_input(
            container_name="x", action="start", cycle=CYCLE_DAILY, hour=1, minute=30
        )
        assert ok is True

    def test_weekly_missing_weekday(self):
        ok, _ = validate_new_task_input(
            container_name="x",
            action="start",
            cycle=CYCLE_WEEKLY,
            hour=1,
            minute=0,
        )
        assert ok is False

    def test_weekly_with_weekday_ok(self):
        ok, _ = validate_new_task_input(
            container_name="x",
            action="start",
            cycle=CYCLE_WEEKLY,
            hour=1,
            minute=0,
            weekday=3,
        )
        assert ok is True

    def test_monthly_invalid_day(self):
        ok, _ = validate_new_task_input(
            container_name="x",
            action="start",
            cycle=CYCLE_MONTHLY,
            hour=1,
            minute=0,
            day=99,
        )
        assert ok is False

    def test_once_invalid_year(self):
        ok, _ = validate_new_task_input(
            container_name="x",
            action="start",
            cycle=CYCLE_ONCE,
            hour=1,
            minute=0,
            year=1500,
            month=1,
            day=1,
        )
        assert ok is False

    def test_yearly_feb_29_rejected(self):
        ok, msg = validate_new_task_input(
            container_name="x",
            action="start",
            cycle=CYCLE_YEARLY,
            hour=1,
            minute=0,
            month=2,
            day=29,
        )
        # February 29 is rejected unless the *current* year is a leap year.
        # We assert behaviourally: either it's rejected with an explanatory
        # message, or accepted only when current year is a leap year. The
        # test is robust either way.
        from datetime import datetime as _dt
        import calendar as _cal

        if _cal.isleap(_dt.now().year):
            assert ok is True
        else:
            assert ok is False
            assert "leap" in msg.lower() or "february" in msg.lower() or "29" in msg


# ---------------------------------------------------------------------------
# File IO: load_tasks / save_tasks
# ---------------------------------------------------------------------------


class TestFileIO:
    def test_load_tasks_creates_empty_file_when_missing(self, tmp_path):
        # Initial state: file does not exist.
        tasks_file = tmp_path / "tasks.json"
        assert not tasks_file.exists()

        loaded = load_tasks()
        # Empty list returned, file was created (system tasks suppressed by
        # fixture so result is exactly the empty user tasks list).
        assert loaded == []
        assert tasks_file.exists()
        assert tasks_file.read_text(encoding="utf-8") == "[]"

    def test_save_then_load_round_trip(self, tmp_path):
        tasks_file = tmp_path / "tasks.json"

        task = _make_daily_task(container_name="alpha", hour=2, minute=0)
        assert save_tasks([task]) is True
        assert tasks_file.exists()

        # File content is JSON list of one dict.
        on_disk = json.loads(tasks_file.read_text(encoding="utf-8"))
        assert isinstance(on_disk, list)
        assert len(on_disk) == 1
        assert on_disk[0]["container"] == "alpha"

        # load_tasks reads it back.
        loaded = load_tasks()
        assert len(loaded) == 1
        assert loaded[0].container_name == "alpha"
        assert loaded[0].time_str == "02:00"

    def test_save_tasks_strips_system_tasks(self, tmp_path):
        tasks_file = tmp_path / "tasks.json"

        user_task = _make_daily_task(container_name="user", hour=1, minute=0)

        sys_task = ScheduledTask(
            task_id=f"{SYSTEM_TASK_PREFIX}TEST",
            container_name="SYSTEM",
            action="donation_message",
            cycle=CYCLE_MONTHLY,
        )
        assert save_tasks([user_task, sys_task]) is True

        on_disk = json.loads(tasks_file.read_text(encoding="utf-8"))
        # System task filtered out.
        assert len(on_disk) == 1
        assert on_disk[0]["container"] == "user"

    def test_load_tasks_skips_invalid_entries(self, tmp_path):
        tasks_file = tmp_path / "tasks.json"

        bad_task_data = {
            "id": "bad-1",
            "container": "x",
            "action": "start",
            # Missing cycle → invalid → dropped silently.
        }
        tasks_file.write_text(json.dumps([bad_task_data]), encoding="utf-8")

        loaded = load_tasks()
        # Either: from_dict raises and is caught, OR the task is constructed
        # but is_valid() returns False and it's filtered. In both cases the
        # final list is empty.
        assert loaded == []


# ---------------------------------------------------------------------------
# CRUD: add_task / find_task_by_id / update_task / delete_task
# ---------------------------------------------------------------------------


class TestCRUD:
    def test_add_task_persists(self):
        task = _make_daily_task(container_name="postgres", hour=3, minute=0)
        assert add_task(task) is True

        loaded = load_tasks()
        ids = [t.task_id for t in loaded]
        assert task.task_id in ids

    def test_add_task_rejects_non_scheduled_task(self):
        # Type mismatch path.
        assert add_task("not-a-task") is False  # type: ignore[arg-type]

    def test_add_task_rejects_invalid_task(self):
        bad = ScheduledTask(container_name=None, action="start", cycle=CYCLE_DAILY)
        assert add_task(bad) is False

    def test_add_task_rejects_duplicate_id(self):
        task = _make_daily_task(task_id="fixed-id", hour=5, minute=0)
        assert add_task(task) is True

        # Second add with same ID returns False.
        dup = _make_daily_task(task_id="fixed-id", hour=6, minute=0)
        assert add_task(dup) is False

    def test_find_task_by_id_returns_match(self):
        task = _make_daily_task(task_id="findable", hour=8, minute=0)
        assert add_task(task) is True

        found = find_task_by_id("findable")
        assert found is not None
        assert found.task_id == "findable"

    def test_find_task_by_id_returns_none_when_missing(self):
        assert find_task_by_id("does-not-exist") is None

    def test_update_task_replaces_existing(self):
        task = _make_daily_task(task_id="upd-1", hour=10, minute=0, container_name="c1")
        assert add_task(task) is True

        # Mutate and update.
        task.action = "stop"
        # Recompute since we changed nothing time-wise; explicit call ensures
        # next_run_ts remains valid.
        task.calculate_next_run()
        assert update_task(task) is True

        reloaded = find_task_by_id("upd-1")
        assert reloaded is not None
        assert reloaded.action == "stop"

    def test_update_task_returns_false_for_missing(self):
        ghost = _make_daily_task(task_id="ghost", hour=1, minute=0)
        # Not added → update should fail.
        assert update_task(ghost) is False

    def test_update_task_rejects_system_task(self):
        sys_task = ScheduledTask(
            task_id=DONATION_TASK_ID,
            container_name="SYSTEM",
            action="donation_message",
            cycle=CYCLE_MONTHLY,
        )
        assert update_task(sys_task) is False

    def test_delete_task_removes_existing(self):
        task = _make_daily_task(task_id="del-1", hour=11, minute=0)
        assert add_task(task) is True
        assert find_task_by_id("del-1") is not None

        assert delete_task("del-1") is True
        assert find_task_by_id("del-1") is None

    def test_delete_task_returns_false_for_missing(self):
        assert delete_task("never-existed") is False

    def test_delete_task_rejects_system_prefix(self):
        # No need to add — system tasks are rejected outright.
        assert delete_task(f"{SYSTEM_TASK_PREFIX}ANYTHING") is False


# ---------------------------------------------------------------------------
# Container/timeframe queries + collision check
# ---------------------------------------------------------------------------


class TestContainerQueriesAndCollision:
    def test_get_tasks_for_container_filters(self):
        a = _make_daily_task(container_name="alpha", hour=1, minute=0)
        b = _make_daily_task(container_name="beta", hour=2, minute=0)
        assert add_task(a) is True
        assert add_task(b) is True

        alpha_only = get_tasks_for_container("alpha")
        assert all(t.container_name == "alpha" for t in alpha_only)
        assert any(t.task_id == a.task_id for t in alpha_only)

    def test_check_task_time_collision_detects_overlap(self):
        existing = _make_daily_task(container_name="alpha", hour=4, minute=0)
        # Force a known next_run_ts to control the collision window.
        existing.next_run_ts = _time.time() + 3600

        # New task within 10-minute window → collision.
        collide_ts = existing.next_run_ts + 60  # 1 minute after existing.
        assert (
            check_task_time_collision(
                "alpha", collide_ts, existing_tasks_for_container=[existing]
            )
            is True
        )

    def test_check_task_time_collision_outside_window_clean(self):
        existing = _make_daily_task(container_name="alpha", hour=4, minute=0)
        existing.next_run_ts = _time.time() + 3600

        far_ts = existing.next_run_ts + MIN_TASK_INTERVAL_SECONDS + 60
        assert (
            check_task_time_collision(
                "alpha", far_ts, existing_tasks_for_container=[existing]
            )
            is False
        )

    def test_check_task_time_collision_ignores_specific_id(self):
        existing = _make_daily_task(
            container_name="alpha", hour=4, minute=0, task_id="ignore-me"
        )
        existing.next_run_ts = _time.time() + 3600
        clash_ts = existing.next_run_ts + 60

        # When the ignored ID matches, no collision is reported.
        assert (
            check_task_time_collision(
                "alpha",
                clash_ts,
                existing_tasks_for_container=[existing],
                task_id_to_ignore="ignore-me",
            )
            is False
        )

    def test_get_tasks_in_timeframe_returns_sorted(self):
        a = _make_daily_task(container_name="a", hour=1, minute=0, task_id="a")
        b = _make_daily_task(container_name="b", hour=2, minute=0, task_id="b")
        a.next_run_ts = _time.time() + 100
        b.next_run_ts = _time.time() + 50
        assert save_tasks([a, b]) is True

        results = get_tasks_in_timeframe(_time.time(), _time.time() + 200)
        assert [t.task_id for t in results] == ["b", "a"]

    def test_get_next_week_tasks_returns_list(self):
        # Smoke test: function should at least return a list when tasks exist
        # whose next_run is within the next 7 days.
        a = _make_daily_task(container_name="a", hour=1, minute=0)
        assert add_task(a) is True
        result = get_next_week_tasks()
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# Module-level constants sanity (cheap coverage of constant lines)
# ---------------------------------------------------------------------------


class TestModuleConstants:
    def test_valid_actions_contains_expected(self):
        assert "start" in VALID_ACTIONS
        assert "stop" in VALID_ACTIONS
        assert "restart" in VALID_ACTIONS

    def test_valid_cycles_contains_expected(self):
        assert CYCLE_DAILY in VALID_CYCLES
        assert CYCLE_WEEKLY in VALID_CYCLES
        assert CYCLE_MONTHLY in VALID_CYCLES
        assert CYCLE_YEARLY in VALID_CYCLES
        assert CYCLE_ONCE in VALID_CYCLES

    def test_days_of_week_length_seven(self):
        assert len(DAYS_OF_WEEK) == 7
        assert DAYS_OF_WEEK[0] == "monday"
        assert DAYS_OF_WEEK[6] == "sunday"

    def test_cron_constant_value(self):
        # CYCLE_CRON exists but is intentionally NOT in VALID_CYCLES (handled
        # separately in validate_new_task_input).
        assert CYCLE_CRON == "cron"


# ---------------------------------------------------------------------------
# schedule_helpers — pure helpers
# ---------------------------------------------------------------------------


class TestScheduleHelpers:
    def test_parse_and_validate_time_ok(self):
        assert parse_and_validate_time("14:30") == (14, 30)

    def test_parse_and_validate_time_invalid_returns_none(self):
        # parse_time_string returns (None, None) for unparseable input rather
        # than raising — parse_and_validate_time only re-wraps a ValueError,
        # so the contract here is the (None, None) passthrough.
        assert parse_and_validate_time("not-a-time") == (None, None)

    def test_parse_and_validate_time_wraps_value_error(self, monkeypatch):
        # If the underlying parser ever raises ValueError, the helper should
        # wrap it as ScheduleValidationError. We patch the parser to force
        # the failure path (covers the except branch).
        from services.scheduling import schedule_helpers as _sh

        def _boom(_arg):
            raise ValueError("boom")

        monkeypatch.setattr(_sh, "parse_time_string", _boom)
        with pytest.raises(ScheduleValidationError):
            _sh.parse_and_validate_time("anything")

    def test_create_task_success_message_once(self):
        task = ScheduledTask(
            container_name="myc",
            action="start",
            cycle=CYCLE_ONCE,
            hour=10,
            minute=0,
            year=2099,
            month=1,
            day=1,
            timezone_str="UTC",
        )
        msg = create_task_success_message(task, "2099-01-01 10:00 UTC+0000")
        assert "myc" in msg
        assert "2099-01-01 10:00 UTC+0000" in msg

    def test_create_task_success_message_daily(self):
        task = _make_daily_task(container_name="dailyc", hour=4, minute=15)
        msg = create_task_success_message(task, "irrelevant")
        assert "dailyc" in msg
        assert "04:15" in msg

    def test_create_task_success_message_weekly_with_day_val(self):
        task = ScheduledTask(
            container_name="weekc",
            action="start",
            cycle=CYCLE_WEEKLY,
            hour=3,
            minute=0,
            schedule_details={"time": "03:00", "day": "tuesday"},
            timezone_str="UTC",
        )
        msg = create_task_success_message(task, "ignored")
        assert "weekc" in msg
        assert "tuesday" in msg.lower()

    def test_create_task_success_message_weekly_with_weekday_val(self):
        task = ScheduledTask(
            container_name="weekc",
            action="start",
            cycle=CYCLE_WEEKLY,
            hour=3,
            minute=0,
            weekday=2,  # Wednesday
            timezone_str="UTC",
        )
        msg = create_task_success_message(task, "ignored")
        assert "weekc" in msg
        assert "wednesday" in msg.lower()

    def test_create_task_success_message_monthly(self):
        task = ScheduledTask(
            container_name="monc",
            action="start",
            cycle=CYCLE_MONTHLY,
            hour=2,
            minute=0,
            day=15,
            timezone_str="UTC",
        )
        msg = create_task_success_message(task, "ignored")
        assert "monc" in msg
        assert "15" in msg

    def test_create_task_success_message_yearly(self):
        task = ScheduledTask(
            container_name="yearc",
            action="start",
            cycle=CYCLE_YEARLY,
            hour=0,
            minute=0,
            month=6,
            day=21,
            timezone_str="UTC",
        )
        msg = create_task_success_message(task, "ignored")
        assert "yearc" in msg
        assert "6" in msg
        assert "21" in msg

    def test_create_task_success_message_unknown_cycle(self):
        task = _make_daily_task(container_name="genc")
        # Mutate to an unknown cycle to exercise the fallback branch.
        task.cycle = "magic"
        msg = create_task_success_message(task, "ignored")
        assert "genc" in msg

    def test_create_task_success_message_daily_fallback_when_time_str_broken(self):
        # Force the int(...) parse to fail → exercises the AttributeError /
        # ValueError fallback branch in the daily path.
        task = _make_daily_task(container_name="dailyc", hour=4, minute=15)
        task.time_str = None  # split() raises AttributeError → fallback.
        msg = create_task_success_message(task, "ignored")
        assert "dailyc" in msg

    def test_create_task_success_message_weekly_fallback(self):
        task = ScheduledTask(
            container_name="weekc",
            action="start",
            cycle=CYCLE_WEEKLY,
            hour=3,
            minute=0,
            weekday=2,
            timezone_str="UTC",
        )
        task.time_str = None
        msg = create_task_success_message(task, "ignored")
        assert "weekc" in msg

    def test_create_task_success_message_monthly_fallback(self):
        task = ScheduledTask(
            container_name="monc",
            action="start",
            cycle=CYCLE_MONTHLY,
            hour=2,
            minute=0,
            day=15,
            timezone_str="UTC",
        )
        task.time_str = None
        msg = create_task_success_message(task, "ignored")
        assert "monc" in msg

    def test_create_task_success_message_yearly_fallback(self):
        task = ScheduledTask(
            container_name="yearc",
            action="start",
            cycle=CYCLE_YEARLY,
            hour=0,
            minute=0,
            month=6,
            day=21,
            timezone_str="UTC",
        )
        task.time_str = None
        msg = create_task_success_message(task, "ignored")
        assert "yearc" in msg


class TestValidateTaskBeforeCreation:
    def test_valid_task_passes(self):
        # add_task hasn't been called → no collision possible. Daily task is
        # is_valid() and has a next_run_ts.
        task = _make_daily_task(container_name="precheck", hour=4, minute=0)
        # Should not raise.
        validate_task_before_creation(task)

    def test_invalid_task_raises(self):
        bad = ScheduledTask(container_name=None, action="start", cycle=CYCLE_DAILY)
        with pytest.raises(ScheduleValidationError):
            validate_task_before_creation(bad)

    def test_no_next_run_raises(self):
        task = _make_daily_task(container_name="nonext", hour=4, minute=0)
        task.next_run_ts = None
        with pytest.raises(ScheduleValidationError):
            validate_task_before_creation(task)

    def test_collision_raises(self):
        existing = _make_daily_task(container_name="collide", hour=4, minute=0)
        assert add_task(existing) is True

        # New task targeting same container at the SAME next_run_ts will
        # collide via check_task_time_collision (within 10 min window).
        new_task = _make_daily_task(container_name="collide", hour=4, minute=5)
        # Force the timing so it lands inside the 10-minute window.
        new_task.next_run_ts = existing.next_run_ts + 60

        with pytest.raises(ScheduleValidationError) as ei:
            validate_task_before_creation(new_task)
        assert "collide" in str(ei.value) or "conflict" in str(ei.value).lower()


class TestCheckSchedulePermissions:
    def test_container_not_found(self, monkeypatch):
        # Patch the load_config and server_config_service used by the helper
        # to return a known empty server list. We don't need a real Discord
        # ctx because the helper only uses servers config / container name.
        from services.scheduling import schedule_helpers as _sh

        monkeypatch.setattr(_sh, "load_config", lambda: {})

        class _FakeSCS:
            def get_all_servers(self):
                return []

        monkeypatch.setattr(_sh, "get_server_config_service", lambda: _FakeSCS())

        ctx = object()  # not actually accessed for this branch.
        ok, err, server = check_schedule_permissions(ctx, "missing-container", "start")
        assert ok is False
        assert err is not None
        assert "missing-container" in err
        assert server is None

    def test_action_not_allowed(self, monkeypatch):
        from services.scheduling import schedule_helpers as _sh

        monkeypatch.setattr(_sh, "load_config", lambda: {})

        class _FakeSCS:
            def get_all_servers(self):
                return [{"docker_name": "myc", "allowed_actions": ["start"]}]

        monkeypatch.setattr(_sh, "get_server_config_service", lambda: _FakeSCS())

        ok, err, server = check_schedule_permissions(object(), "myc", "stop")
        assert ok is False
        assert err is not None
        assert server == {"docker_name": "myc", "allowed_actions": ["start"]}

    def test_action_allowed(self, monkeypatch):
        from services.scheduling import schedule_helpers as _sh

        monkeypatch.setattr(_sh, "load_config", lambda: {})

        class _FakeSCS:
            def get_all_servers(self):
                return [
                    {"docker_name": "myc", "allowed_actions": ["start", "stop"]},
                ]

        monkeypatch.setattr(_sh, "get_server_config_service", lambda: _FakeSCS())

        ok, err, server = check_schedule_permissions(object(), "myc", "start")
        assert ok is True
        assert err is None
        assert server is not None
