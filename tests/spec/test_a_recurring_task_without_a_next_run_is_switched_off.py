# -*- coding: utf-8 -*-
"""A recurring task that has no next run is switched off, not left hanging.

THE FINDING (review D22, pass 2, section 31 F4): `_calculate_frontend_status`
deactivates a ONE-TIME task that has lost its `next_run_ts` and marks it for
saving. Every other cycle falls into the catch-all branch, which only writes
a warning to the log and answers `"deactivated" if not task.is_active else
"expired"`.

So a weekly, monthly or cron task whose `next_run_ts` became None - a
schedule that could not be resolved - stays `is_active = True` with nothing
to run. It never fires, the panel calls it "expired" on every refresh
forever, and nothing is ever written back. The operator sees a task that
looks alive, is not, and cannot be told apart from one that simply ran out.

Switching it off is not a loss: re-enabling it goes through
`_prepare_task_activation`, which computes a fresh next run first. What
changes is that the state on disk matches what the panel shows.
"""

import time

import pytest

from services.scheduling.scheduler import CYCLE_ONCE
from services.web.task_management_service import TaskManagementService


class _Task:
    def __init__(self, cycle="weekly", next_run_ts=None, is_active=True):
        self.task_id = "t1"
        self.cycle = cycle
        self.next_run_ts = next_run_ts
        self.status = "pending"
        self.is_active = is_active


@pytest.fixture
def service():
    return TaskManagementService()


@pytest.mark.parametrize("cycle", ["weekly", "monthly", "cron"])
def test_it_is_switched_off(service, cycle):
    task = _Task(cycle=cycle)

    _status, needs_update = service._calculate_frontend_status(task, time.time())

    assert task.is_active is False, (
        f"a {cycle} task with no next run stays active and never runs"
    )
    assert needs_update is True, "the change is never written back"


def test_the_one_time_case_is_unchanged(service):
    """Counter-check: the branch that already worked must keep working."""
    task = _Task(cycle=CYCLE_ONCE)

    status, needs_update = service._calculate_frontend_status(task, time.time())

    assert status == "expired"
    assert task.is_active is False
    assert needs_update is True


def test_a_healthy_recurring_task_is_untouched(service):
    """Counter-check: switching off everything would pass the test above."""
    task = _Task(next_run_ts=time.time() + 3600)

    status, needs_update = service._calculate_frontend_status(task, time.time())

    assert task.is_active is True
    assert needs_update is False
    assert status == "active"


def test_an_already_inactive_one_is_not_rewritten(service):
    """Counter-check: nothing to change means nothing to save."""
    task = _Task(is_active=False)

    status, needs_update = service._calculate_frontend_status(task, time.time())

    assert needs_update is False
    assert status == "deactivated"
