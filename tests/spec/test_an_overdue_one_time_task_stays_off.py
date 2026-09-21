# -*- coding: utf-8 -*-
"""An overdue one-time task cannot be switched back on.

THE FINDING (review D11, pass 2, section 31 F1): `update_task_status` refuses
to activate an expired task and says why:

    "Cannot activate expired task. This task's execution time is in the past
     or its cycle has completed."

`_is_task_expired` tests only `next_run_ts is None` or `cycle == once and
status == "completed"`. It never asks whether the time is in the past, so the
first half of that sentence was a promise the code did not keep.

The listing already knows the rule: `_calculate_frontend_status` marks a
one-time task whose `next_run_ts` has passed as "expired" and deactivates it.
So the operator could switch such a task back on, and the next refresh of the
page would switch it off again - a tug-of-war with an error message claiming
the opposite.

Recurring tasks are a different matter and stay activatable:
`_prepare_task_activation` gives them a fresh future run first.
"""

import time

import pytest

from services.scheduling.scheduler import CYCLE_ONCE
from services.web.task_management_service import (
    TaskManagementService, UpdateTaskStatusRequest)

PAST = time.time() - 3600
FUTURE = time.time() + 3600


class _Task:
    def __init__(self, cycle=CYCLE_ONCE, next_run_ts=PAST, status="pending"):
        self.task_id = "t1"
        self.cycle = cycle
        self.next_run_ts = next_run_ts
        self.status = status
        self.is_active = False
        self.last_run_error = None

    def is_system_task(self):
        return False

    def calculate_next_run(self):
        self.next_run_ts = FUTURE

    def to_dict(self):
        return {"task_id": self.task_id, "is_active": self.is_active}


@pytest.fixture
def service(monkeypatch):
    instance = TaskManagementService()
    monkeypatch.setattr(instance, "_update_task_via_scheduler", lambda task: True)

    def _with(task):
        monkeypatch.setattr(instance, "_find_task_by_id", lambda task_id: task)
        return instance
    return _with


def test_an_overdue_one_time_task_is_refused(service):
    task = _Task(next_run_ts=PAST)
    instance = service(task)

    result = instance.update_task_status(UpdateTaskStatusRequest(task_id="t1", is_active=True))

    assert result.success is False, (
        "a one-time task whose time has passed was switched back on"
    )
    assert task.is_active is False


def test_the_listing_and_the_switch_agree(service):
    """Both sides read the same task. They must not disagree about whether it
    is expired - the listing deactivates it, and the switch let it back on."""
    task = _Task(next_run_ts=PAST)
    instance = service(task)

    frontend_status, _needs_update = instance._calculate_frontend_status(task, time.time())
    refused = not instance.update_task_status(
        UpdateTaskStatusRequest(task_id="t1", is_active=True)).success

    assert (frontend_status == "expired") == refused, (
        f"the listing calls it {frontend_status!r} and the switch "
        f"{'refuses' if refused else 'allows'} it"
    )


def test_a_one_time_task_still_to_come_can_be_switched_on(service):
    """Counter-check: refusing every one-time task would pass the tests above."""
    task = _Task(next_run_ts=FUTURE)
    instance = service(task)

    result = instance.update_task_status(UpdateTaskStatusRequest(task_id="t1", is_active=True))

    assert result.success is True
    assert task.is_active is True


def test_a_recurring_task_with_a_past_run_can_still_be_switched_on(service):
    """Counter-check: for a recurring task a past next_run_ts is ordinary -
    _prepare_task_activation gives it a fresh one."""
    task = _Task(cycle="daily", next_run_ts=PAST)
    instance = service(task)

    result = instance.update_task_status(UpdateTaskStatusRequest(task_id="t1", is_active=True))

    assert result.success is True
    assert task.next_run_ts == FUTURE


def test_a_recurring_task_that_cannot_move_forward_is_still_allowed(service):
    """The guard for recurring tasks has to hold on its own.

    Normally `_prepare_task_activation` hands the expiry check a fresh future
    run, so the guard never decides anything - and the mutation that removed
    it changed nothing (M2 of review D11). It matters when the recalculation
    cannot produce a future time: the listing does not call such a task
    expired either (it has a next_run_ts, so `_calculate_frontend_status`
    falls through to "active"), and the two must keep agreeing.
    """
    task = _Task(cycle="daily", next_run_ts=PAST)
    task.calculate_next_run = lambda: None        # cannot resolve its schedule
    instance = service(task)

    frontend_status, _needs_update = instance._calculate_frontend_status(task, time.time())
    result = instance.update_task_status(UpdateTaskStatusRequest(task_id="t1", is_active=True))

    assert frontend_status != "expired"
    assert result.success is True, (
        "the listing does not call it expired and the switch refuses it"
    )
