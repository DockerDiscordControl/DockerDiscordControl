# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Task Management Service Tests                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""
Unit tests for :mod:`services.web.task_management_service`.

These tests exercise the public surface of :class:`TaskManagementService`
(``add_task``, ``list_tasks``, ``update_task_status``, ``delete_task``,
``edit_task``, ``get_task_form_data``) plus the dataclass request/result
contracts defined in the same module.

External collaborators (``services.scheduling.scheduler``,
``services.config.config_service``, ``services.infrastructure.action_logger``,
``app.utils.shared_data``) are mocked via ``unittest.mock.patch``; no real
filesystem, Docker or Discord I/O happens here. ``tmp_path`` is used wherever
local-filesystem isolation is helpful even though the service does not write
files itself.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

from services.web.task_management_service import (
    AddTaskRequest,
    AddTaskResult,
    DeleteTaskRequest,
    DeleteTaskResult,
    EditTaskRequest,
    EditTaskResult,
    ListTasksRequest,
    ListTasksResult,
    TaskFormRequest,
    TaskFormResult,
    TaskManagementService,
    UpdateTaskStatusRequest,
    UpdateTaskStatusResult,
    get_task_management_service,
)
import services.web.task_management_service as tms_module


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
class _FakeScheduledTask:
    """Stand-in for ``services.scheduling.scheduler.ScheduledTask``.

    Mimics just enough surface for the production module to function:
    container_name/action/cycle/time_str/etc., is_valid(), is_active flag,
    next_run_ts, calculate_next_run(), to_dict(), is_system_task(),
    is_donation_task().
    """

    def __init__(
        self,
        *,
        container_name: str = "nginx",
        action: str = "restart",
        cycle: str = "once",
        schedule_details: Optional[Dict[str, Any]] = None,
        status: str = "pending",
        description: str = "",
        created_by: str = "Web UI",
        timezone_str: str = "Europe/Berlin",
        is_active: bool = True,
        task_id: str = "task-abc",
        next_run_ts: Optional[float] = None,
        valid: bool = True,
        system: bool = False,
        donation: bool = False,
    ):
        self.container_name = container_name
        self.action = action
        self.cycle = cycle
        self.schedule_details = schedule_details or {}
        self.status = status
        self.description = description
        self.created_by = created_by
        self.timezone_str = timezone_str
        self.is_active = is_active
        self.task_id = task_id
        self.next_run_ts = next_run_ts
        self.created_at_ts = 1_700_000_000.0
        self.time_str = (schedule_details or {}).get("time")
        self.day_val = None
        self.month_val = None
        self.year_val = None
        self.weekday_val = None
        self.cron_string = None
        self._valid = valid
        self._system = system
        self._donation = donation
        self.calculate_next_run_calls = 0

    def is_valid(self) -> bool:
        return self._valid

    def calculate_next_run(self) -> None:
        self.calculate_next_run_calls += 1
        # Default behaviour: leave next_run_ts as-is unless set by test.

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "container_name": self.container_name,
            "action": self.action,
            "cycle": self.cycle,
            "is_active": self.is_active,
            "next_run_ts": self.next_run_ts,
            "status": self.status,
        }

    def is_system_task(self) -> bool:
        return self._system

    def is_donation_task(self) -> bool:
        return self._donation


@pytest.fixture
def service() -> TaskManagementService:
    """Fresh service instance for each test."""
    return TaskManagementService()


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Ensure get_task_management_service() singleton is reset per test."""
    tms_module._task_management_service = None
    yield
    tms_module._task_management_service = None


# ---------------------------------------------------------------------------
# Dataclass contracts
# ---------------------------------------------------------------------------
class TestDataclasses:
    def test_add_task_request_defaults(self):
        req = AddTaskRequest(
            container="c1",
            action="start",
            cycle="once",
            schedule_details={"time": "10:00"},
        )
        assert req.container == "c1"
        assert req.timezone_str is None
        assert req.status == "pending"
        assert req.description is None

    def test_add_task_result_default_values(self):
        ok = AddTaskResult(success=True)
        assert ok.success is True
        assert ok.task_data is None
        assert ok.error is None
        assert ok.message is None

    def test_list_tasks_request_optional_timezone(self):
        assert ListTasksRequest().timezone_str is None
        assert ListTasksRequest(timezone_str="UTC").timezone_str == "UTC"

    def test_update_task_status_request_required_fields(self):
        req = UpdateTaskStatusRequest(task_id="t-1", is_active=False)
        assert req.task_id == "t-1"
        assert req.is_active is False

    def test_edit_task_result_error_branch(self):
        res = EditTaskResult(success=False, error="boom")
        assert res.success is False
        assert res.error == "boom"
        assert res.task_data is None

    def test_task_form_request_is_constructible(self):
        # Marker dataclass — no fields, must still construct cleanly.
        TaskFormRequest()


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------
class TestSingleton:
    def test_get_task_management_service_returns_singleton(self):
        first = get_task_management_service()
        second = get_task_management_service()
        assert first is second
        assert isinstance(first, TaskManagementService)


# ---------------------------------------------------------------------------
# _determine_timezone & _get_timezone_abbreviation
# ---------------------------------------------------------------------------
class TestTimezoneHelpers:
    def test_determine_timezone_uses_request_value(self, service):
        assert service._determine_timezone("America/New_York") == "America/New_York"

    def test_determine_timezone_falls_back_to_config(self, service):
        with patch(
            "services.config.config_service.load_config",
            return_value={"timezone": "Asia/Tokyo"},
        ):
            assert service._determine_timezone(None) == "Asia/Tokyo"

    def test_determine_timezone_default_when_config_missing_key(self, service):
        with patch("services.config.config_service.load_config", return_value={}):
            assert service._determine_timezone(None) == "Europe/Berlin"

    def test_get_timezone_abbreviation_valid(self, service):
        # pytz is available in the runtime — this should give a real abbrev.
        result = service._get_timezone_abbreviation("UTC")
        # UTC abbreviation is "UTC" itself.
        assert isinstance(result, str)
        assert result  # non-empty

    def test_get_timezone_abbreviation_falls_back_when_pytz_unavailable(self, service):
        # The production code falls back to the timezone identifier when an
        # ImportError / AttributeError trips inside the helper.  Patch the
        # ``pytz`` module-level attribute lookup to simulate that.
        with patch(
            "services.web.task_management_service.datetime"
        ) as dt_mock:
            dt_mock.now.side_effect = AttributeError("simulated")
            result = service._get_timezone_abbreviation("UTC")
        assert result == "UTC"


# ---------------------------------------------------------------------------
# add_task
# ---------------------------------------------------------------------------
class TestAddTask:
    def test_add_task_success_path(self, service):
        fake_task = _FakeScheduledTask(
            container_name="nginx",
            action="restart",
            cycle="once",
            schedule_details={"time": "12:00"},
            next_run_ts=time.time() + 3600,  # future
            valid=True,
        )

        with patch.object(service, "_create_scheduled_task", return_value=fake_task), \
             patch.object(service, "_validate_and_calculate_next_run", return_value=True), \
             patch.object(service, "_save_task_via_scheduler", return_value={"success": True}), \
             patch.object(service, "_log_task_creation") as log_mock, \
             patch.object(service, "_determine_timezone", return_value="UTC"), \
             patch.object(service, "_debug_time_conversion"):
            req = AddTaskRequest(
                container="nginx",
                action="restart",
                cycle="once",
                schedule_details={"time": "12:00"},
            )
            result = service.add_task(req)

        assert isinstance(result, AddTaskResult)
        assert result.success is True
        assert result.task_data["container_name"] == "nginx"
        assert result.message == "Task added successfully"
        log_mock.assert_called_once_with(fake_task)

    def test_add_task_returns_error_when_create_fails(self, service):
        with patch.object(service, "_determine_timezone", return_value="UTC"), \
             patch.object(service, "_debug_time_conversion"), \
             patch.object(service, "_create_scheduled_task", return_value=None):
            result = service.add_task(
                AddTaskRequest(
                    container="c", action="restart", cycle="once",
                    schedule_details={"time": "10:00"},
                )
            )

        assert result.success is False
        assert "Could not create task object" in (result.error or "")

    def test_add_task_returns_error_when_validation_fails(self, service):
        fake_task = _FakeScheduledTask()
        with patch.object(service, "_determine_timezone", return_value="UTC"), \
             patch.object(service, "_debug_time_conversion"), \
             patch.object(service, "_create_scheduled_task", return_value=fake_task), \
             patch.object(service, "_validate_and_calculate_next_run", return_value=False):
            result = service.add_task(
                AddTaskRequest(
                    container="c", action="restart", cycle="once",
                    schedule_details={"time": "10:00"},
                )
            )
        assert result.success is False
        assert "validation failed" in (result.error or "").lower()

    def test_add_task_returns_error_when_save_fails(self, service):
        fake_task = _FakeScheduledTask()
        with patch.object(service, "_determine_timezone", return_value="UTC"), \
             patch.object(service, "_debug_time_conversion"), \
             patch.object(service, "_create_scheduled_task", return_value=fake_task), \
             patch.object(service, "_validate_and_calculate_next_run", return_value=True), \
             patch.object(
                 service,
                 "_save_task_via_scheduler",
                 return_value={"success": False, "error": "duplicate id"},
             ):
            result = service.add_task(
                AddTaskRequest(
                    container="c", action="restart", cycle="once",
                    schedule_details={"time": "10:00"},
                )
            )
        assert result.success is False
        assert result.error == "duplicate id"

    def test_add_task_handles_service_dependency_error(self, service):
        with patch.object(
            service,
            "_determine_timezone",
            side_effect=ImportError("scheduler missing"),
        ):
            result = service.add_task(
                AddTaskRequest(
                    container="c", action="restart", cycle="once",
                    schedule_details={"time": "10:00"},
                )
            )
        assert result.success is False
        assert "Service error" in (result.error or "")

    def test_add_task_handles_data_error(self, service):
        with patch.object(
            service,
            "_determine_timezone",
            side_effect=ValueError("bad tz"),
        ):
            result = service.add_task(
                AddTaskRequest(
                    container="c", action="restart", cycle="once",
                    schedule_details={"time": "10:00"},
                )
            )
        assert result.success is False
        assert "Data error" in (result.error or "")


# ---------------------------------------------------------------------------
# list_tasks
# ---------------------------------------------------------------------------
class TestListTasks:
    def test_list_tasks_success_returns_dict_per_task(self, service):
        future_ts = time.time() + 3600
        t1 = _FakeScheduledTask(task_id="a", next_run_ts=future_ts)
        t2 = _FakeScheduledTask(task_id="b", next_run_ts=future_ts, is_active=False)

        with patch.object(service, "_load_tasks_from_scheduler", return_value=[t1, t2]), \
             patch.object(service, "_determine_timezone", return_value="UTC"), \
             patch.object(service, "_save_updated_tasks") as save_mock:
            result = service.list_tasks(ListTasksRequest(timezone_str="UTC"))

        assert isinstance(result, ListTasksResult)
        assert result.success is True
        assert len(result.tasks) == 2
        assert {t["task_id"] for t in result.tasks} == {"a", "b"}
        # No expired tasks → no save attempted.
        save_mock.assert_called_once_with([])

    def test_list_tasks_marks_expired_once_task_for_update(self, service):
        past_ts = time.time() - 3600
        expired = _FakeScheduledTask(
            task_id="exp",
            cycle="once",
            next_run_ts=past_ts,
            is_active=True,
        )
        with patch.object(service, "_load_tasks_from_scheduler", return_value=[expired]), \
             patch.object(service, "_determine_timezone", return_value="UTC"), \
             patch.object(service, "_save_updated_tasks") as save_mock:
            result = service.list_tasks(ListTasksRequest())

        assert result.success is True
        # Expired-flag was popped before returning to the caller.
        assert "needs_update" not in result.tasks[0]
        # The expired task was passed to the bulk update helper.
        args, _ = save_mock.call_args
        assert expired in args[0]

    def test_list_tasks_handles_service_error(self, service):
        with patch.object(
            service,
            "_load_tasks_from_scheduler",
            side_effect=RuntimeError("scheduler down"),
        ):
            result = service.list_tasks(ListTasksRequest())
        assert result.success is False
        assert "Service error" in (result.error or "")

    def test_list_tasks_handles_data_error(self, service):
        with patch.object(
            service,
            "_load_tasks_from_scheduler",
            side_effect=KeyError("schema"),
        ):
            result = service.list_tasks(ListTasksRequest())
        assert result.success is False
        assert "Data error" in (result.error or "")


# ---------------------------------------------------------------------------
# update_task_status
# ---------------------------------------------------------------------------
class TestUpdateTaskStatus:
    def test_returns_error_when_task_missing(self, service):
        with patch.object(service, "_find_task_by_id", return_value=None):
            result = service.update_task_status(
                UpdateTaskStatusRequest(task_id="missing", is_active=True)
            )
        assert result.success is False
        assert "not found" in (result.error or "").lower()

    def test_blocks_activation_of_expired_task(self, service):
        expired = _FakeScheduledTask(
            cycle="once", status="completed", next_run_ts=None, is_active=False
        )
        with patch.object(service, "_find_task_by_id", return_value=expired):
            result = service.update_task_status(
                UpdateTaskStatusRequest(task_id="x", is_active=True)
            )
        assert result.success is False
        assert "expired" in (result.error or "").lower()

    def test_allows_deactivation_even_for_expired_task(self, service):
        expired = _FakeScheduledTask(
            cycle="once", status="completed", next_run_ts=None, is_active=True
        )
        with patch.object(service, "_find_task_by_id", return_value=expired), \
             patch.object(service, "_update_task_via_scheduler", return_value=True):
            result = service.update_task_status(
                UpdateTaskStatusRequest(task_id="x", is_active=False)
            )
        assert result.success is True
        assert expired.is_active is False
        assert result.task_data["is_active"] is False

    def test_returns_error_when_update_fails(self, service):
        task = _FakeScheduledTask(cycle="daily", next_run_ts=time.time() + 60)
        with patch.object(service, "_find_task_by_id", return_value=task), \
             patch.object(service, "_update_task_via_scheduler", return_value=False):
            result = service.update_task_status(
                UpdateTaskStatusRequest(task_id="x", is_active=True)
            )
        assert result.success is False
        assert "Failed to update" in (result.error or "")


# ---------------------------------------------------------------------------
# delete_task
# ---------------------------------------------------------------------------
class TestDeleteTask:
    def test_delete_task_success(self, service):
        task = _FakeScheduledTask(task_id="zz", container_name="cN", action="stop", cycle="once")
        with patch.object(service, "_find_task_by_id", return_value=task), \
             patch.object(service, "_delete_task_via_scheduler", return_value=True), \
             patch.object(service, "_log_task_deletion") as log_mock:
            result = service.delete_task(DeleteTaskRequest(task_id="zz"))

        assert result.success is True
        assert "deleted successfully" in (result.message or "")
        log_mock.assert_called_once()

    def test_delete_task_not_found(self, service):
        with patch.object(service, "_find_task_by_id", return_value=None):
            result = service.delete_task(DeleteTaskRequest(task_id="ghost"))
        assert result.success is False
        assert "not found" in (result.error or "").lower()

    def test_delete_task_scheduler_failure(self, service):
        task = _FakeScheduledTask()
        with patch.object(service, "_find_task_by_id", return_value=task), \
             patch.object(service, "_delete_task_via_scheduler", return_value=False):
            result = service.delete_task(DeleteTaskRequest(task_id="x"))
        assert result.success is False
        assert "Failed to delete" in (result.error or "")


# ---------------------------------------------------------------------------
# edit_task
# ---------------------------------------------------------------------------
class TestEditTask:
    def test_edit_task_get_returns_task_data(self, service):
        task = _FakeScheduledTask(next_run_ts=time.time() + 60)
        with patch.object(service, "_find_task_by_id", return_value=task):
            result = service.edit_task(
                EditTaskRequest(task_id="t", operation="get", timezone_str="UTC")
            )
        assert result.success is True
        assert result.task_data["task_id"] == task.task_id
        assert "next_run_local" in result.task_data

    def test_edit_task_unknown_operation(self, service):
        task = _FakeScheduledTask()
        with patch.object(service, "_find_task_by_id", return_value=task):
            result = service.edit_task(
                EditTaskRequest(task_id="t", operation="bogus")
            )
        assert result.success is False
        assert "Invalid operation" in (result.error or "")

    def test_edit_task_not_found(self, service):
        with patch.object(service, "_find_task_by_id", return_value=None):
            result = service.edit_task(
                EditTaskRequest(task_id="missing", operation="get")
            )
        assert result.success is False
        assert "not found" in (result.error or "").lower()

    def test_edit_task_update_no_data(self, service):
        task = _FakeScheduledTask()
        with patch.object(service, "_find_task_by_id", return_value=task):
            result = service.edit_task(
                EditTaskRequest(task_id="t", operation="update", data=None)
            )
        assert result.success is False
        assert "No data provided" in (result.error or "")

    def test_edit_task_update_invalid_data_returns_error(self, service):
        task = _FakeScheduledTask(valid=False)
        with patch.object(service, "_find_task_by_id", return_value=task):
            result = service.edit_task(
                EditTaskRequest(
                    task_id="t",
                    operation="update",
                    data={"container": "newc"},
                )
            )
        assert result.success is False
        assert "invalid" in (result.error or "").lower()

    def test_edit_task_update_success(self, service):
        task = _FakeScheduledTask(cycle="daily", valid=True, next_run_ts=time.time() + 60)
        with patch.object(service, "_find_task_by_id", return_value=task), \
             patch.object(service, "_update_task_via_scheduler", return_value=True), \
             patch.object(service, "_log_task_update") as log_mock:
            result = service.edit_task(
                EditTaskRequest(
                    task_id="t",
                    operation="update",
                    data={
                        "container": "newc",
                        "action": "stop",
                        "cycle": "weekly",
                        "is_active": True,
                        "schedule_details": {"time": "07:30", "day": "Mon"},
                        "timezone_str": "UTC",
                    },
                )
            )
        assert result.success is True
        assert task.container_name == "newc"
        assert task.action == "stop"
        assert task.cycle == "weekly"
        assert task.timezone_str == "UTC"
        assert task.time_str == "07:30"
        assert task.weekday_val == 0  # Mon
        assert task.calculate_next_run_calls == 1
        log_mock.assert_called_once()


# ---------------------------------------------------------------------------
# get_task_form_data
# ---------------------------------------------------------------------------
class TestGetTaskFormData:
    def test_form_data_success(self, service):
        # Patch the source modules for both imports inside the method.
        with patch(
            "app.utils.shared_data.load_active_containers_from_config"
        ) as load_mock, patch(
            "app.utils.shared_data.get_active_containers",
            return_value=["c1", "c2"],
        ), patch(
            "services.config.config_service.load_config",
            return_value={"timezone": "Europe/Berlin"},
        ), patch.object(service, "_get_timezone_abbreviation", return_value="CET"):
            result = service.get_task_form_data(TaskFormRequest())

        assert result.success is True
        assert result.form_data["active_containers"] == ["c1", "c2"]
        assert result.form_data["timezone_str"] == "Europe/Berlin"
        assert result.form_data["timezone_name"] == "CET"
        load_mock.assert_called_once()

    def test_form_data_default_timezone_when_missing(self, service):
        with patch(
            "app.utils.shared_data.load_active_containers_from_config"
        ), patch(
            "app.utils.shared_data.get_active_containers",
            return_value=[],
        ), patch(
            "services.config.config_service.load_config",
            return_value={},  # no timezone key
        ), patch.object(service, "_get_timezone_abbreviation", return_value="CET"):
            result = service.get_task_form_data(TaskFormRequest())

        assert result.success is True
        assert result.form_data["timezone_str"] == "Europe/Berlin"

    def test_form_data_handles_service_error(self, service):
        with patch(
            "app.utils.shared_data.load_active_containers_from_config",
            side_effect=ImportError("missing"),
        ):
            result = service.get_task_form_data(TaskFormRequest())
        assert result.success is False
        assert "Service error" in (result.error or "")


# ---------------------------------------------------------------------------
# Schedule-detail update helpers (cron vs. weekly vs. monthly)
# ---------------------------------------------------------------------------
class TestUpdateScheduleDetails:
    def test_cron_cycle_only_sets_cron_string(self, service):
        task = _FakeScheduledTask(cycle="cron")
        # Pre-populate with leftover values to ensure they are cleared.
        task.time_str = "10:00"
        task.day_val = 5
        service._update_task_schedule_details(task, {"cron_string": "*/5 * * * *"})
        assert task.cron_string == "*/5 * * * *"
        assert task.time_str is None
        assert task.day_val is None

    def test_weekly_cycle_maps_day_to_weekday_int(self, service):
        task = _FakeScheduledTask(cycle="weekly")
        service._update_task_schedule_details(
            task, {"time": "08:00", "day": "Wed"}
        )
        assert task.time_str == "08:00"
        assert task.weekday_val == 2  # Wed
        assert task.day_val is None

    def test_monthly_cycle_parses_day_int(self, service):
        task = _FakeScheduledTask(cycle="monthly")
        service._update_task_schedule_details(
            task, {"time": "23:59", "day": "15", "month": "6", "year": "2026"}
        )
        assert task.day_val == 15
        assert task.month_val == 6
        assert task.year_val == 2026

    def test_invalid_numeric_day_is_silently_ignored(self, service):
        task = _FakeScheduledTask(cycle="monthly")
        service._update_task_schedule_details(
            task, {"day": "not-a-number"}
        )
        assert task.day_val is None  # parse failed → stays cleared


# ---------------------------------------------------------------------------
# _calculate_frontend_status — covers all branches
# ---------------------------------------------------------------------------
class TestCalculateFrontendStatus:
    def test_active_task_with_future_next_run(self, service):
        task = _FakeScheduledTask(cycle="daily", next_run_ts=time.time() + 60)
        status, needs_update = service._calculate_frontend_status(task, time.time())
        assert status == "active"
        assert needs_update is False

    def test_deactivated_task_with_future_next_run(self, service):
        task = _FakeScheduledTask(cycle="daily", next_run_ts=time.time() + 60, is_active=False)
        status, needs_update = service._calculate_frontend_status(task, time.time())
        assert status == "deactivated"
        assert needs_update is False

    def test_once_task_in_past_is_expired_and_marked(self, service):
        past = time.time() - 60
        task = _FakeScheduledTask(cycle="once", next_run_ts=past, is_active=True)
        status, needs_update = service._calculate_frontend_status(task, time.time())
        assert status == "expired"
        assert needs_update is True
        assert task.is_active is False  # auto-deactivated

    def test_once_task_completed_status_is_expired(self, service):
        task = _FakeScheduledTask(
            cycle="once",
            next_run_ts=time.time() + 60,
            status="completed",
            is_active=True,
        )
        status, needs_update = service._calculate_frontend_status(task, time.time())
        assert status == "expired"
        assert needs_update is True
        assert task.is_active is False

    def test_no_next_run_for_recurring_task(self, service):
        task = _FakeScheduledTask(cycle="daily", next_run_ts=None, is_active=False)
        status, needs_update = service._calculate_frontend_status(task, time.time())
        # Inactive + no next run -> "deactivated"
        assert status == "deactivated"
        assert needs_update is False

    def test_once_task_with_no_next_run_marks_expired(self, service):
        task = _FakeScheduledTask(cycle="once", next_run_ts=None, is_active=True)
        status, needs_update = service._calculate_frontend_status(task, time.time())
        assert status == "expired"
        assert needs_update is True
        assert task.is_active is False


# ---------------------------------------------------------------------------
# _is_task_expired
# ---------------------------------------------------------------------------
class TestIsTaskExpired:
    def test_no_next_run_is_expired(self, service):
        assert service._is_task_expired(_FakeScheduledTask(next_run_ts=None)) is True

    def test_once_task_completed_is_expired(self, service):
        task = _FakeScheduledTask(
            cycle="once", status="completed", next_run_ts=time.time() + 60
        )
        assert service._is_task_expired(task) is True

    def test_active_recurring_task_is_not_expired(self, service):
        task = _FakeScheduledTask(cycle="daily", next_run_ts=time.time() + 60)
        assert service._is_task_expired(task) is False


# ---------------------------------------------------------------------------
# _format_timestamp_local — covers fallback path
# ---------------------------------------------------------------------------
class TestFormatTimestampLocal:
    def test_valid_timestamp_renders_with_tz(self, service):
        out = service._format_timestamp_local(1_700_000_000.0, "UTC")
        # Should include the year prefix and the UTC literal.
        assert "2023" in out
        assert "UTC" in out

    def test_invalid_timestamp_falls_back_to_local_strftime(self, service):
        # An OSError raised by ``utcfromtimestamp`` (e.g. out-of-range value)
        # is caught and the helper falls back to ``datetime.fromtimestamp``.
        with patch(
            "services.web.task_management_service.datetime"
        ) as dt_mock:
            dt_mock.utcfromtimestamp.side_effect = OSError("range")
            dt_mock.fromtimestamp.return_value.strftime.return_value = "FALLBACK"
            out = service._format_timestamp_local(1_700_000_000.0, "UTC")
        assert out == "FALLBACK"


# ---------------------------------------------------------------------------
# Debug helpers — drive the inner logger paths but ensure no exceptions leak.
# ---------------------------------------------------------------------------
class TestDebugHelpers:
    def test_debug_time_conversion_skips_when_no_time_key(self, service):
        # No ``time`` key -> early return, no exception.
        service._debug_time_conversion({"day": "10"}, "UTC")

    def test_debug_time_conversion_handles_valid_time(self, service):
        # Valid "HH:MM" exercises the happy debug path.
        service._debug_time_conversion({"time": "08:30"}, "UTC")

    def test_debug_time_conversion_handles_malformed_time(self, service):
        # Malformed input is logged but does NOT raise.
        service._debug_time_conversion({"time": "not-a-time"}, "UTC")

    def test_debug_time_parsing_swallows_format_error(self, service):
        service._debug_time_parsing("bad-time", "UTC")

    def test_debug_time_parsing_handles_valid(self, service):
        service._debug_time_parsing("12:34", "UTC")

    def test_debug_calculated_time_with_mismatched_input(self, service):
        # Builds a task whose time_str doesn't match the calculated next_run.
        # Helper just logs a warning and returns cleanly.
        task = _FakeScheduledTask(next_run_ts=1_700_000_000.0)
        task.time_str = "23:59"  # very unlikely to match calculated 2023-11-14 22:13:20 UTC
        service._debug_calculated_time(task, "UTC")


# ---------------------------------------------------------------------------
# _save_task_via_scheduler
# ---------------------------------------------------------------------------
class TestSaveTaskViaScheduler:
    def test_returns_success_on_scheduler_ok(self, service):
        task = _FakeScheduledTask()
        with patch(
            "services.scheduling.scheduler.add_task",
            return_value=True,
        ):
            out = service._save_task_via_scheduler(task)
        assert out == {"success": True}

    def test_returns_error_when_scheduler_returns_false(self, service):
        task = _FakeScheduledTask()
        with patch(
            "services.scheduling.scheduler.add_task",
            return_value=False,
        ):
            out = service._save_task_via_scheduler(task)
        assert out["success"] is False
        assert "Failed to add task" in out["error"]

    def test_handles_service_error(self, service):
        task = _FakeScheduledTask()
        with patch(
            "services.scheduling.scheduler.add_task",
            side_effect=RuntimeError("boom"),
        ):
            out = service._save_task_via_scheduler(task)
        assert out["success"] is False
        assert "Service error" in out["error"]

    def test_handles_data_error(self, service):
        task = _FakeScheduledTask()
        with patch(
            "services.scheduling.scheduler.add_task",
            side_effect=ValueError("bad"),
        ):
            out = service._save_task_via_scheduler(task)
        assert out["success"] is False
        assert "Data error" in out["error"]


# ---------------------------------------------------------------------------
# _find_task_by_id / _update_task_via_scheduler / _delete_task_via_scheduler
# ---------------------------------------------------------------------------
class TestSchedulerProxies:
    def test_find_task_by_id_success(self, service):
        sentinel = _FakeScheduledTask(task_id="t9")
        with patch(
            "services.scheduling.scheduler.find_task_by_id",
            return_value=sentinel,
        ):
            assert service._find_task_by_id("t9") is sentinel

    def test_find_task_by_id_returns_none_on_service_error(self, service):
        with patch(
            "services.scheduling.scheduler.find_task_by_id",
            side_effect=RuntimeError(),
        ):
            assert service._find_task_by_id("t9") is None

    def test_find_task_by_id_returns_none_on_data_error(self, service):
        with patch(
            "services.scheduling.scheduler.find_task_by_id",
            side_effect=ValueError(),
        ):
            assert service._find_task_by_id("t9") is None

    def test_update_task_via_scheduler_success(self, service):
        with patch(
            "services.scheduling.scheduler.update_task",
            return_value=True,
        ):
            assert service._update_task_via_scheduler(_FakeScheduledTask()) is True

    def test_update_task_via_scheduler_service_error(self, service):
        with patch(
            "services.scheduling.scheduler.update_task",
            side_effect=AttributeError(),
        ):
            assert service._update_task_via_scheduler(_FakeScheduledTask()) is False

    def test_update_task_via_scheduler_data_error(self, service):
        with patch(
            "services.scheduling.scheduler.update_task",
            side_effect=TypeError(),
        ):
            assert service._update_task_via_scheduler(_FakeScheduledTask()) is False

    def test_delete_task_via_scheduler_success(self, service):
        with patch(
            "services.scheduling.scheduler.delete_task",
            return_value=True,
        ):
            assert service._delete_task_via_scheduler("id") is True

    def test_delete_task_via_scheduler_service_error(self, service):
        with patch(
            "services.scheduling.scheduler.delete_task",
            side_effect=RuntimeError(),
        ):
            assert service._delete_task_via_scheduler("id") is False

    def test_delete_task_via_scheduler_data_error(self, service):
        with patch(
            "services.scheduling.scheduler.delete_task",
            side_effect=ValueError(),
        ):
            assert service._delete_task_via_scheduler("id") is False


# ---------------------------------------------------------------------------
# Audit-log helpers (action_logger import path)
# ---------------------------------------------------------------------------
class TestAuditLogging:
    def test_log_task_creation_calls_logger(self, service):
        task = _FakeScheduledTask(task_id="t1")
        with patch(
            "services.infrastructure.action_logger.log_user_action"
        ) as log_mock:
            service._log_task_creation(task)
        log_mock.assert_called_once()
        kwargs = log_mock.call_args.kwargs
        assert kwargs["action"] == "SCHEDULE_CREATE"
        assert "t1" in kwargs["details"]

    def test_log_task_creation_swallows_service_error(self, service):
        task = _FakeScheduledTask()
        with patch(
            "services.infrastructure.action_logger.log_user_action",
            side_effect=ImportError(),
        ):
            # Must not raise.
            service._log_task_creation(task)

    def test_log_task_deletion_calls_logger(self, service):
        details = {"container_name": "c", "action": "stop", "cycle": "once"}
        with patch(
            "services.infrastructure.action_logger.log_user_action"
        ) as log_mock:
            service._log_task_deletion("t1", details)
        log_mock.assert_called_once()

    def test_log_task_deletion_swallows_data_error(self, service):
        # Missing key in details should be caught, not propagated.
        with patch(
            "services.infrastructure.action_logger.log_user_action"
        ):
            service._log_task_deletion("t1", {})  # missing keys -> KeyError

    def test_log_task_update_calls_logger(self, service):
        task = _FakeScheduledTask(task_id="t1")
        original = {"container": "old", "action": "stop", "cycle": "once"}
        with patch(
            "services.infrastructure.action_logger.log_user_action"
        ) as log_mock:
            service._log_task_update(task, original)
        log_mock.assert_called_once()
        assert "old" in log_mock.call_args.kwargs["details"]


# ---------------------------------------------------------------------------
# _create_scheduled_task — exercise both error branches via patched import.
# ---------------------------------------------------------------------------
class TestCreateScheduledTask:
    def test_returns_none_on_import_error(self, service):
        # Make ``ScheduledTask`` constructor raise AttributeError (treated as
        # an import-class error by the helper).
        bad_module = MagicMock()
        bad_module.ScheduledTask.side_effect = AttributeError("missing")
        with patch.dict(
            "sys.modules",
            {"services.scheduling.scheduler": bad_module},
        ):
            req = AddTaskRequest(
                container="c", action="restart", cycle="once",
                schedule_details={"time": "10:00"},
            )
            assert service._create_scheduled_task(req, "UTC") is None

    def test_returns_none_on_data_error(self, service):
        bad_module = MagicMock()
        bad_module.ScheduledTask.side_effect = ValueError("invalid")
        with patch.dict(
            "sys.modules",
            {"services.scheduling.scheduler": bad_module},
        ):
            req = AddTaskRequest(
                container="c", action="restart", cycle="once",
                schedule_details={"time": "10:00"},
            )
            assert service._create_scheduled_task(req, "UTC") is None

    def test_uses_default_description_when_none(self, service):
        captured = {}

        def fake_ctor(**kwargs):
            captured.update(kwargs)
            return _FakeScheduledTask(**{
                k: v for k, v in kwargs.items()
                if k in {
                    "container_name", "action", "cycle", "schedule_details",
                    "status", "description", "created_by", "timezone_str",
                    "is_active",
                }
            })

        fake_module = MagicMock()
        fake_module.ScheduledTask.side_effect = fake_ctor
        with patch.dict(
            "sys.modules",
            {"services.scheduling.scheduler": fake_module},
        ):
            req = AddTaskRequest(
                container="my-cont", action="start", cycle="once",
                schedule_details={"time": "10:00"},
                description=None,
            )
            out = service._create_scheduled_task(req, "UTC")

        assert out is not None
        assert "my-cont" in captured["description"]


# ---------------------------------------------------------------------------
# _validate_and_calculate_next_run — drive its branches directly.
# ---------------------------------------------------------------------------
class TestValidateAndCalculateNextRun:
    def test_returns_false_when_task_invalid(self, service):
        task = _FakeScheduledTask(valid=False)
        assert service._validate_and_calculate_next_run(task, "UTC") is False

    def test_returns_true_for_future_recurring_task(self, service):
        task = _FakeScheduledTask(
            cycle="daily", next_run_ts=time.time() + 60, valid=True
        )
        out = service._validate_and_calculate_next_run(task, "UTC")
        assert out is True
        # Recurring future task -> still active.
        assert task.is_active is True

    def test_deactivates_once_task_when_in_past(self, service):
        task = _FakeScheduledTask(
            cycle="once", next_run_ts=time.time() - 60, valid=True
        )
        out = service._validate_and_calculate_next_run(task, "UTC")
        assert out is True
        assert task.is_active is False

    def test_deactivates_when_no_next_run(self, service):
        task = _FakeScheduledTask(cycle="once", next_run_ts=None, valid=True)
        out = service._validate_and_calculate_next_run(task, "UTC")
        assert out is True
        assert task.is_active is False

    def test_returns_false_on_data_error(self, service):
        task = _FakeScheduledTask(valid=True)
        task.calculate_next_run = MagicMock(side_effect=ValueError())
        out = service._validate_and_calculate_next_run(task, "UTC")
        assert out is False


# ---------------------------------------------------------------------------
# _get_task_for_editing — direct drive
# ---------------------------------------------------------------------------
class TestGetTaskForEditing:
    def test_uses_default_timezone_when_none_given(self, service):
        task = _FakeScheduledTask(next_run_ts=1_700_000_000.0)
        with patch.object(service, "_determine_timezone", return_value="UTC"):
            out = service._get_task_for_editing(task, None)
        assert out.success is True
        assert "next_run_local" in out.task_data

    def test_handles_data_error(self, service):
        task = _FakeScheduledTask()
        task.to_dict = MagicMock(side_effect=KeyError("oops"))
        out = service._get_task_for_editing(task, "UTC")
        assert out.success is False
        assert "Data error" in out.error


# ---------------------------------------------------------------------------
# _save_updated_tasks
# ---------------------------------------------------------------------------
class TestSaveUpdatedTasks:
    def test_noop_for_empty_list(self, service):
        # No exceptions; no scheduler call.
        with patch(
            "services.scheduling.scheduler.update_task"
        ) as upd:
            service._save_updated_tasks([])
        upd.assert_not_called()

    def test_calls_update_task_for_each(self, service):
        tasks = [_FakeScheduledTask(task_id="a"), _FakeScheduledTask(task_id="b")]
        with patch(
            "services.scheduling.scheduler.update_task"
        ) as upd:
            service._save_updated_tasks(tasks)
        assert upd.call_count == 2

    def test_swallows_service_error(self, service):
        tasks = [_FakeScheduledTask()]
        with patch(
            "services.scheduling.scheduler.update_task",
            side_effect=RuntimeError(),
        ):
            # Must not raise.
            service._save_updated_tasks(tasks)


# ---------------------------------------------------------------------------
# _process_task_for_frontend — combines several helpers
# ---------------------------------------------------------------------------
class TestProcessTaskForFrontend:
    def test_active_future_task_marked_active(self, service):
        future = time.time() + 60
        task = _FakeScheduledTask(cycle="daily", next_run_ts=future, is_active=True)
        out = service._process_task_for_frontend(task, "UTC", time.time())
        assert out["frontend_status"] == "active"
        assert out["is_in_past"] in (False, 0)
        assert "next_run_local" in out

    def test_expired_once_task_marks_needs_update(self, service):
        past = time.time() - 60
        task = _FakeScheduledTask(cycle="once", next_run_ts=past, is_active=True)
        out = service._process_task_for_frontend(task, "UTC", time.time())
        assert out["frontend_status"] == "expired"
        assert out["needs_update"] is True
        assert out["is_in_past"] is True

    def test_system_and_donation_flags_propagate(self, service):
        task = _FakeScheduledTask(
            cycle="daily", next_run_ts=time.time() + 60,
            system=True, donation=True,
        )
        out = service._process_task_for_frontend(task, "UTC", time.time())
        assert out["is_system_task"] is True
        assert out["is_donation_task"] is True
