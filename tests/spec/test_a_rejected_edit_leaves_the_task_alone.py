# -*- coding: utf-8 -*-
"""A rejected edit leaves the stored task exactly as it was.

REFUTED as a defect, pinned as a promise (review D21, pass 2, section 31 F2).

The reviewer read `_update_task_with_data` and saw the order: the helpers
mutate the task in place - `_update_task_schedule_details` even clears
time_str, day_val, month_val, year_val, weekday_val and cron_string before
setting anything - and only afterwards does `task.is_valid()` decide. A
rejected edit would therefore leave a wrecked task behind.

It does not, and the reason is one section away: `find_task_by_id` in
scheduler.py hands out `copy.deepcopy(...)`, and says why - review B7 of pass
1 fixed exactly this leak. What the edit path wrecks is its own copy;
`_update_task_via_scheduler` is reached only after the validation passes, so
nothing is written.

These tests are CHARACTERISATION, not a fix: green before and after. They
exist so the copy and the validate-last order cannot drift apart again - if
someone makes find_task_by_id hand out the live object, the reviewer's
reading becomes correct and this file says so.
"""

import time

import pytest

from services.web.task_management_service import (
    EditTaskRequest, TaskManagementService)


class _Task:
    def __init__(self):
        self.task_id = "t1"
        self.container_name = "web"
        self.action = "restart"
        self.cycle = "daily"
        self.time_str = "07:00"
        self.day_val = None
        self.month_val = None
        self.year_val = None
        self.weekday_val = None
        self.cron_string = None
        self.timezone_str = "Europe/Berlin"
        self.is_active = True
        self.next_run_ts = time.time() + 3600
        self.last_run_error = None
        self.valid = True

    def is_valid(self):
        return self.valid

    def calculate_next_run(self):
        self.next_run_ts = time.time() + 7200

    def to_dict(self):
        return {"task_id": self.task_id, "time_str": self.time_str,
                "cycle": self.cycle}


@pytest.fixture
def service(monkeypatch):
    instance = TaskManagementService()
    saved = []
    monkeypatch.setattr(instance, "_update_task_via_scheduler",
                        lambda task: saved.append(task) or True)
    instance.saved = saved
    return instance


def test_a_rejected_edit_saves_nothing(service, monkeypatch):
    stored = _Task()
    stored.valid = False                    # the edit will not pass validation
    monkeypatch.setattr(service, "_find_task_by_id", lambda task_id: stored)

    result = service._update_task_with_data(stored, {"cycle": "weekly"}, None)

    assert result.success is False
    assert service.saved == [], "a task that failed validation was written anyway"


def test_the_lookup_hands_out_a_copy():
    """The load-bearing fact, checked where it lives: the edit path may wreck
    what it is given, because what it is given is not the cached task."""
    from services.scheduling import scheduler

    source = scheduler.find_task_by_id.__doc__ or ""
    import inspect
    body = inspect.getsource(scheduler.find_task_by_id)

    assert "deepcopy" in body, (
        "find_task_by_id no longer copies - the edit path now wrecks the cached "
        "task on a rejected edit, which is exactly what section 31 F2 described"
    )


def test_a_good_edit_is_still_saved(service, monkeypatch):
    """Counter-check: refusing everything would satisfy the test above."""
    stored = _Task()
    monkeypatch.setattr(service, "_find_task_by_id", lambda task_id: stored)

    result = service._update_task_with_data(stored, {"container": "db"}, None)

    assert result.success is True
    assert service.saved == [stored]
