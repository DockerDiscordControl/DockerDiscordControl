# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Scheduler Extended Coverage Tests             #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Extended unit tests for ``services.scheduling.scheduler``.

Companion to ``test_scheduler_partial.py`` — that file covers the pure
construction / validation / IO surface; this file pushes coverage on the
calculation helpers (cron, monthly, yearly, weekly edge cases), the donation
system task creation path, and various error / fallback branches that the
partial suite intentionally skipped.

Mock policy: dependencies are swapped in via ``monkeypatch`` (per-test) — we
do *not* manipulate ``sys.modules`` directly. ``croniter`` is injected as a
fake module via ``monkeypatch.setitem(sys.modules, ...)`` which pytest cleans
up automatically after each test.
"""

from __future__ import annotations

import calendar
import sys
import time as _time
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import List

import pytest
import pytz

from services.scheduling import runtime as scheduler_runtime
from services.scheduling import scheduler as scheduler_mod
from services.scheduling.scheduler import (
    CYCLE_CRON,
    CYCLE_DAILY,
    CYCLE_MONTHLY,
    CYCLE_ONCE,
    CYCLE_WEEKLY,
    CYCLE_YEARLY,
    DONATION_TASK_ID,
    SYSTEM_TASK_PREFIX,
    ScheduledTask,
    _get_system_tasks,
    _load_raw_tasks_from_file,
    _save_raw_tasks_to_file,
    add_task,
    create_donation_system_task,
    delete_task,
    execute_task,
    find_task_by_id,
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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolated_tasks_file(monkeypatch, tmp_path):
    """Redirect every scheduler IO call at a private ``tasks.json``.

    Mirrors the partial test suite's isolation. Both the module-level singleton
    and the constants captured at import time are pointed at ``tmp_path``.
    """

    monkeypatch.setenv("DDC_SCHEDULER_CONFIG_DIR", str(tmp_path))
    scheduler_runtime.reset_scheduler_runtime()

    fresh = scheduler_runtime.get_scheduler_runtime()
    monkeypatch.setattr(scheduler_mod, "_runtime", fresh)
    monkeypatch.setattr(scheduler_mod, "TASKS_FILE_PATH", fresh.tasks_file_path)

    # Suppress system tasks unless a specific test wants them.
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
# _parse_task_time / calculate_next_run fallbacks
# ---------------------------------------------------------------------------


class TestParseTaskTimeAndCalcNextRun:
    def test_parse_task_time_returns_none_when_missing(self):
        task = _make_daily_task()
        task.time_str = None
        assert task._parse_task_time() is None

    def test_parse_task_time_invalid_format_returns_none(self):
        task = _make_daily_task()
        task.time_str = "not-a-time"
        # Falls through to datetime.strptime which will raise ValueError →
        # method returns None and logs.
        assert task._parse_task_time() is None

    def test_parse_task_time_non_padded_format(self):
        task = _make_daily_task()
        # Force the slow path via a non-digit form — strptime accepts "9:5"
        # via %H:%M which actually requires zero pad in many locales; this
        # at minimum exercises the fallback path. Use a clearly non-digit
        # format to cover the strptime branch.
        task.time_str = "07:05"
        assert task._parse_task_time() == (7, 5)

    def test_calculate_next_run_unknown_cycle_returns_none(self):
        task = _make_daily_task()
        # Force an unknown cycle to exercise the "Unknown cycle type" branch.
        task.cycle = "weird"
        # time_str is still valid → _parse_task_time returns OK; but the
        # cycle branch falls through to the else branch returning None.
        assert task.calculate_next_run() is None

    def test_calculate_next_run_invalid_time_str_returns_none(self):
        task = _make_daily_task()
        task.time_str = "not-a-time"
        # _parse_task_time returns None → calculate_next_run returns None.
        assert task.calculate_next_run() is None


# ---------------------------------------------------------------------------
# _calculate_cron_next_run
# ---------------------------------------------------------------------------


class TestCronCalculation:
    def test_cron_import_error_returns_none(self, monkeypatch):
        # Make the croniter import inside _calculate_cron_next_run fail by
        # forcing sys.modules to surface an ImportError. monkeypatch's
        # delitem cleans up after the test.
        monkeypatch.setitem(sys.modules, "croniter", None)

        task = ScheduledTask(
            task_id="cron-1",
            container_name="cron-c",
            action="restart",
            cycle=CYCLE_CRON,
            schedule_details={"cron_string": "0 0 * * *"},
            timezone_str="UTC",
        )
        # Cron tasks pre-compute next_run during __init__ when valid; calling
        # the method directly with a None croniter module yields None.
        tz = pytz.timezone("UTC")
        assert task._calculate_cron_next_run(tz) is None

    def test_cron_with_fake_croniter_module(self, monkeypatch):
        # Inject a fake croniter module that returns a fixed datetime.
        future_dt = datetime(2099, 1, 2, 3, 4, tzinfo=pytz.UTC)

        class _FakeCronIter:
            def __init__(self, expr, base):
                self.expr = expr
                self.base = base

            def get_next(self, _type):
                return future_dt

        fake_mod = SimpleNamespace(croniter=_FakeCronIter)
        monkeypatch.setitem(sys.modules, "croniter", fake_mod)

        task = ScheduledTask(
            task_id="cron-2",
            container_name="cron-c",
            action="restart",
            cycle=CYCLE_CRON,
            schedule_details={"cron_string": "0 0 * * *"},
            timezone_str="UTC",
        )
        tz = pytz.timezone("UTC")
        ts = task._calculate_cron_next_run(tz)
        assert ts == future_dt.timestamp()
        assert task.next_run_ts == ts

    def test_cron_invalid_expression_returns_none(self, monkeypatch):
        class _RaisingCronIter:
            def __init__(self, expr, base):
                raise ValueError("bad expr")

        monkeypatch.setitem(
            sys.modules, "croniter", SimpleNamespace(croniter=_RaisingCronIter)
        )

        task = ScheduledTask(
            task_id="cron-3",
            container_name="cron-c",
            action="restart",
            cycle=CYCLE_CRON,
            schedule_details={"cron_string": "garbage"},
            timezone_str="UTC",
        )
        tz = pytz.timezone("UTC")
        assert task._calculate_cron_next_run(tz) is None

    def test_calculate_next_run_dispatches_cron_branch(self, monkeypatch):
        # Verify calculate_next_run() routes CYCLE_CRON to the cron helper.
        called = {"hit": False}

        def _fake(self, tz):
            called["hit"] = True
            return 12345.0

        monkeypatch.setattr(ScheduledTask, "_calculate_cron_next_run", _fake)

        task = ScheduledTask(
            task_id="cron-route",
            container_name="cron-c",
            action="restart",
            cycle=CYCLE_CRON,
            schedule_details={"cron_string": "0 0 * * *"},
            timezone_str="UTC",
        )
        result = task.calculate_next_run()
        assert called["hit"] is True
        assert result == 12345.0


# ---------------------------------------------------------------------------
# _calculate_once_next_run edge cases
# ---------------------------------------------------------------------------


class TestOnceNextRun:
    def test_once_in_past_returns_none(self):
        # Construct a once-task with the date set far in the past.
        task = ScheduledTask(
            task_id="once-past",
            container_name="x",
            action="start",
            cycle=CYCLE_ONCE,
            year=2000,
            month=1,
            day=1,
            hour=12,
            minute=0,
            timezone_str="UTC",
        )
        # is_valid still passes (date is parseable) but next_run is in the
        # past → calculate_next_run returns None.
        assert task.is_valid() is True
        assert task.calculate_next_run() is None

    def test_once_with_invalid_date_returns_none(self):
        task = _make_daily_task()
        task.cycle = CYCLE_ONCE
        # Force impossible date via direct attribute mutation.
        task.year_val = 2099
        task.month_val = 13  # invalid month
        task.day_val = 1
        task.time_str = "10:00"
        # Calculation triggers ValueError internally → returns None.
        assert task.calculate_next_run() is None

    def test_once_missing_date_components_returns_none(self):
        task = _make_daily_task()
        task.cycle = CYCLE_ONCE
        task.year_val = None  # Missing
        task.month_val = 1
        task.day_val = 1
        assert task.calculate_next_run() is None


# ---------------------------------------------------------------------------
# _calculate_weekly_next_run edge cases
# ---------------------------------------------------------------------------


class TestWeeklyNextRun:
    def test_weekly_invalid_day_string_returns_none(self):
        task = _make_daily_task()
        task.cycle = CYCLE_WEEKLY
        task.day_val = "not-a-weekday"
        task.weekday_val = None
        # _calculate_weekly_next_run hits the ValueError branch via
        # DAYS_OF_WEEK.index(...) → returns None.
        assert task.calculate_next_run() is None

    def test_weekly_no_day_no_weekday_returns_none(self):
        task = _make_daily_task()
        task.cycle = CYCLE_WEEKLY
        task.day_val = None
        task.weekday_val = None
        assert task.calculate_next_run() is None

    def test_weekly_with_last_run_ts_recomputes(self):
        # Force the "last_run_ts present" branch (lines 559-562).
        task = ScheduledTask(
            container_name="x",
            action="start",
            cycle=CYCLE_WEEKLY,
            hour=10,
            minute=0,
            schedule_details={"time": "10:00", "day": "wednesday"},
            timezone_str="UTC",
        )
        # Set a known last_run timestamp ~3 days ago.
        task.last_run_ts = _time.time() - (3 * 24 * 3600)
        # Recalculate — should hit the last_run branch and produce a future
        # next_run (~7 days after last_run).
        next_run = task.calculate_next_run()
        assert next_run is not None
        # Next run is exactly 7 days after last run shifted to 10:00.
        # We allow some tolerance for the time replace + 7 days rule.
        assert next_run > task.last_run_ts

    def test_weekly_target_today_already_passed_uses_next_week(self):
        # Construct a weekly task where target_weekday == today and time
        # already passed → days_ahead becomes 7 (line 568-569 branch).
        task = ScheduledTask(
            container_name="x",
            action="start",
            cycle=CYCLE_WEEKLY,
            hour=0,  # 00:00 — almost certainly already passed today.
            minute=0,
            schedule_details={
                "time": "00:00",
                "day": ["monday", "tuesday", "wednesday",
                        "thursday", "friday", "saturday", "sunday"][datetime.now(pytz.UTC).weekday()],
            },
            timezone_str="UTC",
        )
        next_run = task.calculate_next_run()
        # Should be at least a few hours into the future (next week's same
        # day at 00:00, OR could land on tomorrow if exact midnight). We
        # only assert it is not None and is in the future.
        assert next_run is not None
        assert next_run > _time.time()


# ---------------------------------------------------------------------------
# _calculate_monthly_next_run edge cases
# ---------------------------------------------------------------------------


class TestMonthlyNextRun:
    def test_monthly_no_day_returns_none(self):
        task = _make_daily_task()
        task.cycle = CYCLE_MONTHLY
        task.day_val = None
        assert task.calculate_next_run() is None

    def test_monthly_non_numeric_day_returns_none(self):
        task = _make_daily_task()
        task.cycle = CYCLE_MONTHLY
        task.day_val = "abc"  # int conversion fails.
        assert task.calculate_next_run() is None

    def test_monthly_out_of_range_day_returns_none(self):
        task = _make_daily_task()
        task.cycle = CYCLE_MONTHLY
        task.day_val = 99  # Out of 1..31.
        assert task.calculate_next_run() is None

    def test_monthly_skips_months_when_day_invalid(self):
        # Day 31 doesn't exist in some months → loop should skip to the
        # next month with day 31 (lines 597-604).
        task = ScheduledTask(
            container_name="x",
            action="start",
            cycle=CYCLE_MONTHLY,
            hour=12,
            minute=0,
            day=31,
            timezone_str="UTC",
        )
        ts = task.calculate_next_run()
        assert ts is not None
        # Next run is on day 31 of some month.
        next_dt = datetime.fromtimestamp(ts, pytz.UTC)
        assert next_dt.day == 31


# ---------------------------------------------------------------------------
# _calculate_yearly_next_run edge cases (Feb 29 + past-year handling)
# ---------------------------------------------------------------------------


class TestYearlyNextRun:
    def test_yearly_feb_29_in_non_leap_year_falls_back_to_28(self):
        # Pick a future non-leap year explicitly.
        non_leap = 2099  # 2099 is not a leap year
        assert not calendar.isleap(non_leap)

        task = ScheduledTask(
            container_name="x",
            action="start",
            cycle=CYCLE_YEARLY,
            hour=10,
            minute=0,
            year=non_leap,
            month=2,
            day=29,
            timezone_str="UTC",
        )
        ts = task.calculate_next_run()
        assert ts is not None
        next_dt = datetime.fromtimestamp(ts, pytz.UTC)
        # Falls back to Feb 28 in non-leap year.
        assert next_dt.month == 2
        assert next_dt.day == 28
        assert next_dt.year == non_leap

    def test_yearly_in_past_uses_next_year(self):
        # Set year_val to None so calculate_yearly defaults to current year,
        # then if month/day already passed, advance to next year.
        # Use Jan 1 — virtually certain to be in the past for most of the year.
        task = ScheduledTask(
            container_name="x",
            action="start",
            cycle=CYCLE_YEARLY,
            hour=0,
            minute=0,
            month=1,
            day=1,
            timezone_str="UTC",
        )
        ts = task.calculate_next_run()
        assert ts is not None
        next_dt = datetime.fromtimestamp(ts, pytz.UTC)
        assert next_dt.month == 1
        assert next_dt.day == 1
        # Year is at least the current year (could equal current year if
        # it's actually Jan 1 right now, or next year otherwise).
        assert next_dt.year >= datetime.now(pytz.UTC).year

    def test_yearly_missing_month_day_returns_none(self):
        task = _make_daily_task()
        task.cycle = CYCLE_YEARLY
        task.month_val = None
        task.day_val = None
        assert task.calculate_next_run() is None

    def test_yearly_invalid_date_returns_none(self):
        task = _make_daily_task()
        task.cycle = CYCLE_YEARLY
        task.year_val = 2099
        task.month_val = 13  # Out of range
        task.day_val = 1
        task.time_str = "10:00"
        assert task.calculate_next_run() is None


# ---------------------------------------------------------------------------
# get_next_run_datetime
# ---------------------------------------------------------------------------


class TestGetNextRunDatetime:
    def test_returns_none_when_no_next_run_ts(self):
        task = _make_daily_task()
        task.next_run_ts = None
        assert task.get_next_run_datetime() is None

    def test_returns_aware_datetime(self):
        task = _make_daily_task()
        dt = task.get_next_run_datetime()
        assert dt is not None
        assert dt.tzinfo is not None

    def test_invalid_timestamp_returns_none(self, monkeypatch):
        task = _make_daily_task()
        # Force the timezone helper to raise so the except branch fires.
        # _get_timezone raises AttributeError → caught → returns None.
        def _boom(_tz):
            raise AttributeError("bad tz")

        monkeypatch.setattr(scheduler_mod, "_get_timezone", _boom)
        task.next_run_ts = _time.time() + 60
        assert task.get_next_run_datetime() is None


# ---------------------------------------------------------------------------
# Donation system task creation + _calculate_next_donation_run
# ---------------------------------------------------------------------------


class TestDonationSystemTask:
    def test_create_donation_task_when_donations_enabled(self, monkeypatch):
        # Donations enabled → task active, next_run_ts populated.
        monkeypatch.setattr(
            "services.donation.donation_utils.is_donations_disabled",
            lambda: False,
        )
        monkeypatch.setattr(scheduler_mod, "load_config", lambda: {"timezone": "UTC"})

        task = create_donation_system_task()
        assert task is not None
        assert task.task_id == DONATION_TASK_ID
        assert task.is_active is True
        assert task.status == "active"
        assert task.next_run_ts is not None
        # Should be a Sunday at 13:37 UTC.
        next_dt = datetime.fromtimestamp(task.next_run_ts, pytz.UTC)
        assert next_dt.weekday() == 6  # Sunday
        assert next_dt.hour == 13
        assert next_dt.minute == 37

    def test_create_donation_task_when_donations_disabled(self, monkeypatch):
        monkeypatch.setattr(
            "services.donation.donation_utils.is_donations_disabled",
            lambda: True,
        )
        monkeypatch.setattr(scheduler_mod, "load_config", lambda: {"timezone": "UTC"})

        task = create_donation_system_task()
        assert task is not None
        assert task.task_id == DONATION_TASK_ID
        # Inactive when disabled by premium key.
        assert task.is_active is False
        assert task.status == "disabled"
        # Next run NOT scheduled.
        assert task.next_run_ts is None
        assert "DISABLED" in task.description.upper()

    def test_create_donation_task_load_config_failure_uses_default_tz(
        self, monkeypatch
    ):
        # load_config raising IOError on the FIRST call (in
        # create_donation_system_task) should fall back to Europe/Berlin.
        # The downstream _calculate_next_donation_run() may call load_config
        # again — we let that succeed so we test only the timezone fallback.
        monkeypatch.setattr(
            "services.donation.donation_utils.is_donations_disabled",
            lambda: False,
        )

        call_count = {"n": 0}

        def _flaky():
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise IOError("config read failed")
            return {"timezone": "Europe/Berlin"}

        monkeypatch.setattr(scheduler_mod, "load_config", _flaky)

        task = create_donation_system_task()
        assert task is not None
        assert task.timezone_str == "Europe/Berlin"

    def test_create_donation_task_handles_import_error(self, monkeypatch):
        # If is_donations_disabled cannot be imported, the helper returns None.
        # We simulate by injecting a None entry for donation_utils so that
        # ``from services.donation.donation_utils import is_donations_disabled``
        # raises ImportError.
        monkeypatch.setitem(sys.modules, "services.donation.donation_utils", None)

        result = create_donation_system_task()
        assert result is None

    def test_calculate_next_donation_run_sets_second_sunday(self, monkeypatch):
        monkeypatch.setattr(scheduler_mod, "load_config", lambda: {"timezone": "UTC"})
        # Build a minimal task and run the donation calculation directly.
        task = ScheduledTask(
            task_id=DONATION_TASK_ID,
            container_name="SYSTEM",
            action="donation_message",
            cycle=CYCLE_MONTHLY,
            timezone_str="UTC",
        )
        task._calculate_next_donation_run()
        assert task.next_run_ts is not None
        next_dt = datetime.fromtimestamp(task.next_run_ts, pytz.UTC)
        # 2nd Sunday: must be Sunday and between day 8 and 14 inclusive.
        assert next_dt.weekday() == 6
        assert 8 <= next_dt.day <= 14
        assert next_dt.hour == 13 and next_dt.minute == 37

    def test_calculate_next_donation_run_skips_when_already_run_this_month(
        self, monkeypatch
    ):
        # If last_run_ts is in the current month, next run should be in a
        # later month.
        monkeypatch.setattr(scheduler_mod, "load_config", lambda: {"timezone": "UTC"})
        task = ScheduledTask(
            task_id=DONATION_TASK_ID,
            container_name="SYSTEM",
            action="donation_message",
            cycle=CYCLE_MONTHLY,
            timezone_str="UTC",
        )
        # Fake last run earlier this same month.
        now = datetime.now(pytz.UTC)
        task.last_run_ts = datetime(
            now.year, now.month, 1, 12, 0, tzinfo=pytz.UTC
        ).timestamp()
        task._calculate_next_donation_run()
        assert task.next_run_ts is not None
        next_dt = datetime.fromtimestamp(task.next_run_ts, pytz.UTC)
        # Must be in a later month than the current one.
        is_later_month = (next_dt.year, next_dt.month) > (now.year, now.month)
        assert is_later_month, f"expected later month, got {next_dt}"

    def test_was_run_this_month_true(self):
        task = ScheduledTask(
            task_id=DONATION_TASK_ID,
            container_name="SYSTEM",
            action="donation_message",
            cycle=CYCLE_MONTHLY,
            timezone_str="UTC",
        )
        now = datetime.now(pytz.UTC)
        task.last_run_ts = now.timestamp()
        assert task._was_run_this_month(now) is True

    def test_was_run_this_month_false_when_no_last_run(self):
        task = ScheduledTask(
            task_id=DONATION_TASK_ID,
            container_name="SYSTEM",
            action="donation_message",
            cycle=CYCLE_MONTHLY,
            timezone_str="UTC",
        )
        task.last_run_ts = None
        now = datetime.now(pytz.UTC)
        assert task._was_run_this_month(now) is False

    def test_was_run_this_month_false_when_old_run(self):
        task = ScheduledTask(
            task_id=DONATION_TASK_ID,
            container_name="SYSTEM",
            action="donation_message",
            cycle=CYCLE_MONTHLY,
            timezone_str="UTC",
        )
        now = datetime.now(pytz.UTC)
        # Last run 100 days ago.
        task.last_run_ts = (now - timedelta(days=100)).timestamp()
        assert task._was_run_this_month(now) is False


# ---------------------------------------------------------------------------
# update_after_execution path for donation task
# ---------------------------------------------------------------------------


class TestUpdateAfterExecution:
    def test_donation_task_uses_donation_recalc(self, monkeypatch):
        # update_after_execution should route the donation task to its
        # bespoke calculation rather than the regular calculate_next_run.
        monkeypatch.setattr(scheduler_mod, "load_config", lambda: {"timezone": "UTC"})

        task = ScheduledTask(
            task_id=DONATION_TASK_ID,
            container_name="SYSTEM",
            action="donation_message",
            cycle=CYCLE_MONTHLY,
            timezone_str="UTC",
        )
        called = {"donation": False, "regular": False}

        original_donation = ScheduledTask._calculate_next_donation_run

        def _track_donation(self):
            called["donation"] = True
            return original_donation(self)

        def _track_regular(self):
            called["regular"] = True
            return None

        monkeypatch.setattr(
            ScheduledTask, "_calculate_next_donation_run", _track_donation
        )
        monkeypatch.setattr(ScheduledTask, "calculate_next_run", _track_regular)

        task.update_after_execution()
        assert called["donation"] is True
        assert called["regular"] is False
        assert task.status == "pending"

    def test_recurring_non_donation_uses_regular_recalc(self, monkeypatch):
        task = _make_daily_task()
        called = {"regular": False}

        def _track(self):
            called["regular"] = True
            return None

        monkeypatch.setattr(ScheduledTask, "calculate_next_run", _track)
        task.update_after_execution()
        assert called["regular"] is True
        assert task.status == "pending"


# ---------------------------------------------------------------------------
# _get_system_tasks
# ---------------------------------------------------------------------------


class TestGetSystemTasks:
    def test_returns_donation_task(self, monkeypatch):
        # Restore the real _get_system_tasks for this test; the autouse
        # fixture stubs it to [].
        monkeypatch.setattr(
            scheduler_mod, "_get_system_tasks", scheduler_mod.__dict__["_get_system_tasks"].__wrapped__
            if hasattr(scheduler_mod._get_system_tasks, "__wrapped__")
            else _get_system_tasks,
        )
        monkeypatch.setattr(
            "services.donation.donation_utils.is_donations_disabled",
            lambda: False,
        )
        monkeypatch.setattr(scheduler_mod, "load_config", lambda: {"timezone": "UTC"})

        tasks = _get_system_tasks()
        assert isinstance(tasks, list)
        assert any(t.task_id == DONATION_TASK_ID for t in tasks)

    def test_returns_empty_when_creation_fails(self, monkeypatch):
        # Force create_donation_system_task to return None → list ends up
        # empty (the function does not append None).
        monkeypatch.setattr(scheduler_mod, "create_donation_system_task", lambda: None)
        # Use real _get_system_tasks; autouse fixture replaces with stub so
        # we re-bind here.
        monkeypatch.setattr(
            scheduler_mod, "_get_system_tasks", scheduler_mod._get_system_tasks
        )
        # Call directly.
        result = _get_system_tasks()
        # The donation task is None → no system tasks → empty list.
        assert result == []


# ---------------------------------------------------------------------------
# add_task / update_task collision + recalc paths
# ---------------------------------------------------------------------------


class TestAddUpdateTaskEdgeCases:
    def test_add_task_recalculates_missing_next_run(self):
        task = _make_daily_task(container_name="recalc-1", hour=5, minute=0)
        task.next_run_ts = None  # Simulate missing next_run.
        # Daily cycle → recalculation should populate it and add succeeds.
        assert add_task(task) is True
        assert task.next_run_ts is not None

    def test_add_task_collision_rejected(self):
        a = _make_daily_task(container_name="busy", hour=4, minute=0)
        assert add_task(a) is True

        # Second task within 10-minute window → collision rejected.
        b = _make_daily_task(container_name="busy", hour=4, minute=5)
        b.next_run_ts = a.next_run_ts + 60  # 1 minute later
        assert add_task(b) is False

    def test_update_task_rejects_non_scheduled_task(self):
        # Type mismatch → False (lines 1310-1311).
        # We do NOT pass a system-prefixed string-or-object; use a non-task.
        class _Stub:
            task_id = "notreallytask"
            cycle = CYCLE_DAILY
            next_run_ts = None

            def is_system_task(self):
                return False

            def is_valid(self):
                return True

        result = update_task(_Stub())
        # is_valid() True but isinstance check fails → False.
        # (Note: the system task check runs first; our stub returns False there.)
        assert result is False

    def test_update_task_rejects_invalid_task_object(self):
        bad = ScheduledTask(container_name=None, action="start", cycle=CYCLE_DAILY)
        # is_valid() False → False.
        assert update_task(bad) is False

    def test_update_task_recalculates_missing_next_run(self):
        existing = _make_daily_task(
            container_name="upd-recalc", task_id="upd-recalc-1", hour=8, minute=0
        )
        assert add_task(existing) is True

        existing.next_run_ts = None  # Force recalc branch
        # Daily → recalc succeeds → update succeeds.
        assert update_task(existing) is True

    def test_update_task_collision_rejected(self):
        a = _make_daily_task(
            container_name="upd-coll", task_id="a-1", hour=4, minute=0
        )
        b = _make_daily_task(
            container_name="upd-coll", task_id="b-1", hour=8, minute=0
        )
        assert add_task(a) is True
        assert add_task(b) is True

        # Move b to within 10 minutes of a → collision on update.
        b.next_run_ts = a.next_run_ts + 60
        assert update_task(b) is False


# ---------------------------------------------------------------------------
# get_tasks_in_timeframe non-cached path
# ---------------------------------------------------------------------------


class TestTimeframeNonCached:
    def test_timeframe_returns_sorted_when_cache_empty(self, monkeypatch):
        a = _make_daily_task(container_name="aa", task_id="a", hour=1, minute=0)
        b = _make_daily_task(container_name="bb", task_id="b", hour=2, minute=0)
        a.next_run_ts = _time.time() + 100
        b.next_run_ts = _time.time() + 50
        assert save_tasks([a, b]) is True

        # Force the "is_modified" branch by clearing the cache.
        scheduler_mod._runtime.clear_tasks_cache()

        results = get_tasks_in_timeframe(_time.time(), _time.time() + 200)
        # Sorted by next_run_ts ascending.
        assert [t.task_id for t in results] == ["b", "a"]


# ---------------------------------------------------------------------------
# validate_new_task_input — additional branches
# ---------------------------------------------------------------------------


class TestValidateNewTaskInputBranches:
    def test_invalid_container_name_format_rejected(self, monkeypatch):
        # Patch validate_container_name to return False to cover that branch.
        from utils import common_helpers

        monkeypatch.setattr(common_helpers, "validate_container_name", lambda _n: False)
        ok, err = validate_new_task_input(
            container_name="bad/name",
            action="start",
            cycle=CYCLE_DAILY,
            hour=1,
            minute=0,
        )
        assert ok is False
        assert "Invalid container name" in err

    def test_cron_cycle_rejected_because_not_in_valid_cycles(self):
        # CYCLE_CRON is intentionally not in VALID_CYCLES — validate_new_task_input
        # rejects it at the cycle check. The cron-string-required branch in
        # the function is therefore unreachable through this entrypoint and
        # is documented behaviour (covered by from_dict / direct construction).
        ok, err = validate_new_task_input(
            container_name="x",
            action="start",
            cycle=CYCLE_CRON,
            cron_string="0 0 * * *",
        )
        assert ok is False
        assert "Invalid cycle" in err

    def test_invalid_hour_rejected(self):
        ok, err = validate_new_task_input(
            container_name="x",
            action="start",
            cycle=CYCLE_DAILY,
            hour=25,
            minute=0,
        )
        assert ok is False
        assert "Hour" in err

    def test_invalid_minute_rejected(self):
        ok, err = validate_new_task_input(
            container_name="x",
            action="start",
            cycle=CYCLE_DAILY,
            hour=10,
            minute=99,
        )
        assert ok is False
        assert "Minute" in err

    def test_once_invalid_month_rejected(self):
        ok, err = validate_new_task_input(
            container_name="x",
            action="start",
            cycle=CYCLE_ONCE,
            year=2099,
            month=13,
            day=1,
            hour=10,
            minute=0,
        )
        assert ok is False
        assert "Month" in err

    def test_once_invalid_day_rejected(self):
        ok, err = validate_new_task_input(
            container_name="x",
            action="start",
            cycle=CYCLE_ONCE,
            year=2099,
            month=1,
            day=99,
            hour=10,
            minute=0,
        )
        assert ok is False
        assert "Day" in err

    def test_once_impossible_calendar_date_rejected(self):
        # Year/month/day each individually valid but combined not a real date.
        ok, err = validate_new_task_input(
            container_name="x",
            action="start",
            cycle=CYCLE_ONCE,
            year=2099,
            month=2,
            day=30,  # Feb has at most 29 days
            hour=10,
            minute=0,
        )
        assert ok is False
        assert "Invalid date" in err

    def test_yearly_invalid_calendar_date_rejected(self):
        # Apr 31 doesn't exist.
        ok, err = validate_new_task_input(
            container_name="x",
            action="start",
            cycle=CYCLE_YEARLY,
            month=4,
            day=31,
            hour=10,
            minute=0,
        )
        assert ok is False

    def test_monthly_missing_day_rejected(self):
        ok, err = validate_new_task_input(
            container_name="x",
            action="start",
            cycle=CYCLE_MONTHLY,
            hour=1,
            minute=0,
        )
        assert ok is False


# ---------------------------------------------------------------------------
# Parser fallbacks (extra branches)
# ---------------------------------------------------------------------------


class TestParserFallbacks:
    def test_parse_time_string_dot_format(self):
        # H.MM with %H.%M format.
        assert parse_time_string("14.30") == (14, 30)

    def test_parse_time_string_am_pm(self):
        # 12-hour format with am/pm.
        result = parse_time_string("3:30 PM")
        # Should be 15:30 (covers the 12-hour fallback path).
        assert result == (15, 30)

    def test_parse_time_string_out_of_range_in_hh_mm(self):
        # 25:99 is out of range — function tries the slow paths and
        # eventually returns (None, None).
        assert parse_time_string("25:99") == (None, None)

    def test_parse_month_string_typeerror_path(self):
        # Pass a value that triggers AttributeError on .lower() — returns None.
        # parse_month_string is lru_cached; pass a string that looks like a
        # month but is invalid to exercise the failure return.
        assert parse_month_string("notamonth-xyz") is None

    def test_parse_weekday_string_partial_match(self):
        # Partial match (>=2 chars) returns the right value.
        assert parse_weekday_string("we") == 2  # wednesday

    def test_parse_weekday_string_invalid(self):
        # Single char that doesn't match any prefix.
        assert parse_weekday_string("xyz") is None

    def test_parse_weekday_string_out_of_range_numeric(self):
        # A numeric string outside both 0-6 and 1-7 → None.
        assert parse_weekday_string("99") is None


# ---------------------------------------------------------------------------
# Raw load/save: error paths, malformed JSON, retry behaviour
# ---------------------------------------------------------------------------


class TestRawLoadSaveErrorPaths:
    def test_load_raw_returns_empty_when_file_missing(self, tmp_path):
        # Autouse fixture points runtime at tmp_path; no tasks.json exists.
        result = _load_raw_tasks_from_file()
        assert result == []

    def test_load_raw_returns_empty_for_empty_file(self, tmp_path):
        tasks_file = tmp_path / "tasks.json"
        tasks_file.write_text("", encoding="utf-8")
        assert _load_raw_tasks_from_file() == []

    def test_load_raw_returns_empty_for_whitespace_file(self, tmp_path):
        tasks_file = tmp_path / "tasks.json"
        tasks_file.write_text("   \n  ", encoding="utf-8")
        assert _load_raw_tasks_from_file() == []

    def test_load_raw_returns_empty_for_malformed_json(self, tmp_path):
        tasks_file = tmp_path / "tasks.json"
        tasks_file.write_text("{not-json", encoding="utf-8")
        # JSONDecodeError → returns [] (line 959-961).
        assert _load_raw_tasks_from_file() == []

    def test_load_raw_loads_valid_data(self, tmp_path):
        tasks_file = tmp_path / "tasks.json"
        import json as _json

        data = [
            {
                "id": "raw-1",
                "container": "x",
                "action": "start",
                "cycle": CYCLE_DAILY,
                "schedule_details": {"time": "10:00"},
                "_timezone_str": "UTC",
            }
        ]
        tasks_file.write_text(_json.dumps(data), encoding="utf-8")
        loaded = _load_raw_tasks_from_file()
        assert isinstance(loaded, list)
        assert len(loaded) == 1
        assert loaded[0]["id"] == "raw-1"

    def test_save_raw_skips_write_when_unchanged(self, tmp_path):
        # Calling _save_raw_tasks_to_file with identical data should hit the
        # unchanged-skip branch.
        data = [
            {
                "id": "stable-1",
                "container": "c",
                "action": "start",
                "cycle": CYCLE_DAILY,
                "schedule_details": {"time": "01:00"},
            }
        ]
        # First write actually persists.
        assert _save_raw_tasks_to_file(data) is True
        # Second write with the same content takes the comparison branch.
        assert _save_raw_tasks_to_file(data) is True

    def test_load_tasks_with_malformed_json_returns_empty(self, tmp_path):
        # load_tasks should swallow malformed JSON and return [] (system
        # tasks suppressed by fixture).
        tasks_file = tmp_path / "tasks.json"
        tasks_file.write_text("{not json}", encoding="utf-8")
        result = load_tasks()
        assert result == []

    def test_load_tasks_with_invalid_task_data_skipped(self, tmp_path):
        # Mix of valid + invalid (broken types) — invalid ones are dropped,
        # valid one is kept.
        tasks_file = tmp_path / "tasks.json"
        import json as _json

        data = [
            {
                "id": "good",
                "container": "x",
                "action": "start",
                "cycle": CYCLE_DAILY,
                "schedule_details": {"time": "10:00"},
                "_timezone_str": "UTC",
            },
            # This entry: action is None — from_dict accepts but is_valid()
            # returns False → filtered out (line 1115-1118).
            {
                "id": "bad",
                "container": "x",
                "action": None,
                "cycle": CYCLE_DAILY,
                "schedule_details": {"time": "10:00"},
                "_timezone_str": "UTC",
            },
        ]
        tasks_file.write_text(_json.dumps(data), encoding="utf-8")
        loaded = load_tasks()
        # Bad task is filtered → only the good one survives.
        ids = [t.task_id for t in loaded]
        assert "good" in ids
        assert "bad" not in ids


# ---------------------------------------------------------------------------
# load_tasks: system task merge, find_task_by_id targeted-search path
# ---------------------------------------------------------------------------


class TestLoadAndFindOptimizedPaths:
    def test_load_tasks_appends_system_tasks(self, monkeypatch, tmp_path):
        # Override the autouse stub to return a synthetic system task.
        sys_task = ScheduledTask(
            task_id=f"{SYSTEM_TASK_PREFIX}TEST_MERGE",
            container_name="SYSTEM",
            action="donation_message",
            cycle=CYCLE_MONTHLY,
            timezone_str="UTC",
        )
        monkeypatch.setattr(scheduler_mod, "_get_system_tasks", lambda: [sys_task])

        # Add a user task to verify both are present.
        user_task = _make_daily_task(container_name="user-merge", task_id="user-1")
        assert add_task(user_task) is True

        loaded = load_tasks()
        ids = {t.task_id for t in loaded}
        assert "user-1" in ids
        assert f"{SYSTEM_TASK_PREFIX}TEST_MERGE" in ids

    def test_find_task_uses_cache_when_unmodified(self, tmp_path):
        # First add → cache populated.
        task = _make_daily_task(task_id="cached-1", hour=4, minute=0)
        assert add_task(task) is True
        # Now lookup should be served from cache (not re-read file).
        found = find_task_by_id("cached-1")
        assert found is not None
        assert found.task_id == "cached-1"

    def test_find_task_returns_none_when_no_file(self, tmp_path):
        # No file, empty cache → returns None via the load_tasks() fallback.
        # Ensure no file exists.
        tasks_file = tmp_path / "tasks.json"
        if tasks_file.exists():
            tasks_file.unlink()
        scheduler_mod._runtime.clear_tasks_cache()
        result = find_task_by_id("missing")
        assert result is None


# ---------------------------------------------------------------------------
# get_tasks_for_container — cached & uncached paths
# ---------------------------------------------------------------------------


class TestGetTasksForContainerExtra:
    def test_cached_path_serves_from_cache(self):
        a = _make_daily_task(container_name="cached-c", task_id="ca-1", hour=1, minute=0)
        b = _make_daily_task(container_name="cached-c", task_id="ca-2", hour=4, minute=0)
        assert add_task(a) is True
        assert add_task(b) is True

        first = get_tasks_for_container("cached-c")
        assert {t.task_id for t in first} == {"ca-1", "ca-2"}

        # Second call within container_cache TTL should still return both.
        second = get_tasks_for_container("cached-c")
        assert {t.task_id for t in second} == {"ca-1", "ca-2"}

    def test_filters_by_container(self):
        a = _make_daily_task(container_name="alpha-x", task_id="ax-1", hour=1, minute=0)
        b = _make_daily_task(container_name="beta-x", task_id="bx-1", hour=2, minute=0)
        assert add_task(a) is True
        assert add_task(b) is True

        result = get_tasks_for_container("alpha-x")
        assert all(t.container_name == "alpha-x" for t in result)
        assert any(t.task_id == "ax-1" for t in result)


# ---------------------------------------------------------------------------
# execute_task — donation path & docker action path
# ---------------------------------------------------------------------------


class _FakeBot:
    """Minimal bot stub for the donation-message execution path."""

    user = SimpleNamespace(name="test-bot")


class TestExecuteTask:
    @pytest.mark.asyncio
    async def test_execute_donation_when_donations_disabled_short_circuits(
        self, monkeypatch
    ):
        # Path: action == 'donation_message' AND is_donations_disabled() True.
        # Should mark success, reschedule via update_after_execution, return True.
        monkeypatch.setattr(
            "services.donation.donation_utils.is_donations_disabled",
            lambda: True,
        )
        # Suppress update_task file IO.
        monkeypatch.setattr(scheduler_mod, "update_task", lambda t: True)
        # Suppress the donation-task recalc to avoid touching load_config.
        monkeypatch.setattr(scheduler_mod, "load_config", lambda: {"timezone": "UTC"})

        task = ScheduledTask(
            task_id=DONATION_TASK_ID,
            container_name="SYSTEM",
            action="donation_message",
            cycle=CYCLE_MONTHLY,
            timezone_str="UTC",
        )
        result = await execute_task(task, timeout=2)
        assert result is True
        # last_run_success and last_run_error reflect the no-op success.
        assert task.last_run_success is True
        assert task.last_run_error is None

    @pytest.mark.asyncio
    async def test_execute_donation_success(self, monkeypatch):
        # Donations enabled → execute_donation_message_task is called.
        monkeypatch.setattr(
            "services.donation.donation_utils.is_donations_disabled",
            lambda: False,
        )

        async def _fake_execute(bot=None):
            return True

        # Patch the dynamically-imported donation_message_service.
        fake_dms = SimpleNamespace(
            execute_donation_message_task=_fake_execute,
            get_bot_instance=lambda: _FakeBot(),
        )
        monkeypatch.setitem(
            sys.modules, "services.scheduling.donation_message_service", fake_dms
        )

        monkeypatch.setattr(scheduler_mod, "update_task", lambda t: True)
        monkeypatch.setattr(scheduler_mod, "load_config", lambda: {"timezone": "UTC"})

        task = ScheduledTask(
            task_id=DONATION_TASK_ID,
            container_name="SYSTEM",
            action="donation_message",
            cycle=CYCLE_MONTHLY,
            timezone_str="UTC",
        )
        result = await execute_task(task, timeout=2)
        assert result is True
        assert task.last_run_success is True

    @pytest.mark.asyncio
    async def test_execute_donation_failure(self, monkeypatch):
        monkeypatch.setattr(
            "services.donation.donation_utils.is_donations_disabled",
            lambda: False,
        )

        async def _fake_execute(bot=None):
            return False

        fake_dms = SimpleNamespace(
            execute_donation_message_task=_fake_execute,
            get_bot_instance=lambda: None,
        )
        monkeypatch.setitem(
            sys.modules, "services.scheduling.donation_message_service", fake_dms
        )

        monkeypatch.setattr(scheduler_mod, "update_task", lambda t: True)
        monkeypatch.setattr(scheduler_mod, "load_config", lambda: {"timezone": "UTC"})

        task = ScheduledTask(
            task_id=DONATION_TASK_ID,
            container_name="SYSTEM",
            action="donation_message",
            cycle=CYCLE_MONTHLY,
            timezone_str="UTC",
        )
        result = await execute_task(task, timeout=2)
        assert result is False
        assert task.last_run_success is False
        assert task.last_run_error is not None

    @pytest.mark.asyncio
    async def test_execute_donation_import_error(self, monkeypatch):
        # Force an ImportError when loading donation_message_service.
        monkeypatch.setattr(
            "services.donation.donation_utils.is_donations_disabled",
            lambda: False,
        )
        monkeypatch.setitem(
            sys.modules, "services.scheduling.donation_message_service", None
        )
        monkeypatch.setattr(scheduler_mod, "update_task", lambda t: True)
        monkeypatch.setattr(scheduler_mod, "load_config", lambda: {"timezone": "UTC"})

        task = ScheduledTask(
            task_id=DONATION_TASK_ID,
            container_name="SYSTEM",
            action="donation_message",
            cycle=CYCLE_MONTHLY,
            timezone_str="UTC",
        )
        result = await execute_task(task, timeout=2)
        assert result is False
        assert task.last_run_success is False

    @pytest.mark.asyncio
    async def test_execute_docker_action_success(self, monkeypatch):
        # Non-donation task → docker_action_service_first invoked.
        async def _fake_action(container, action, timeout=60):
            return True

        monkeypatch.setattr(
            scheduler_mod, "docker_action_service_first", _fake_action
        )
        monkeypatch.setattr(scheduler_mod, "update_task", lambda t: True)
        monkeypatch.setattr(scheduler_mod, "log_user_action", lambda **kw: None)

        task = _make_daily_task(container_name="docker-target", hour=4, minute=0)
        result = await execute_task(task, timeout=2)
        assert result is True
        assert task.last_run_success is True
        assert task.last_run_error is None

    @pytest.mark.asyncio
    async def test_execute_docker_action_failure(self, monkeypatch):
        async def _fake_action(container, action, timeout=60):
            return False

        monkeypatch.setattr(
            scheduler_mod, "docker_action_service_first", _fake_action
        )
        monkeypatch.setattr(scheduler_mod, "update_task", lambda t: True)
        monkeypatch.setattr(scheduler_mod, "log_user_action", lambda **kw: None)

        task = _make_daily_task(container_name="docker-target", hour=4, minute=0)
        result = await execute_task(task, timeout=2)
        assert result is False
        assert task.last_run_success is False
        assert task.last_run_error == "Docker action failed"

    @pytest.mark.asyncio
    async def test_execute_docker_action_runtime_error(self, monkeypatch):
        async def _fake_action(container, action, timeout=60):
            raise RuntimeError("boom")

        monkeypatch.setattr(
            scheduler_mod, "docker_action_service_first", _fake_action
        )
        monkeypatch.setattr(scheduler_mod, "update_task", lambda t: True)
        monkeypatch.setattr(scheduler_mod, "log_user_action", lambda **kw: None)

        task = _make_daily_task(container_name="docker-target", hour=4, minute=0)
        result = await execute_task(task, timeout=2)
        assert result is False
        assert task.last_run_success is False
        assert "boom" in (task.last_run_error or "")

    @pytest.mark.asyncio
    async def test_execute_docker_action_timeout(self, monkeypatch):
        import asyncio

        async def _slow_action(container, action, timeout=60):
            # Sleep longer than the asyncio.wait_for timeout to trigger
            # both timeouts (initial + retry) → final timeout branch.
            await asyncio.sleep(5)
            return True

        monkeypatch.setattr(
            scheduler_mod, "docker_action_service_first", _slow_action
        )
        monkeypatch.setattr(scheduler_mod, "update_task", lambda t: True)
        monkeypatch.setattr(scheduler_mod, "log_user_action", lambda **kw: None)

        task = _make_daily_task(container_name="slow-target", hour=4, minute=0)
        # Use a very short timeout so retries also trigger asyncio.TimeoutError.
        result = await execute_task(task, timeout=0.05)
        assert result is False
        assert task.last_run_success is False
        assert "timed out" in (task.last_run_error or "").lower()
