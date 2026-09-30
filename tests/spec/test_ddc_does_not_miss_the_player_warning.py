# -*- coding: utf-8 -*-
"""DDC does not miss the player warning the admin asked for.

THE FINDING (stage 4 review before v3.1.0, section 49 pass 4): the player
warning was posted only if a check cycle happened to land inside
[acting_at - warn, acting_at). With warn_minutes 1 or 2, or a raised
DDC_SCHEDULER_CHECK_INTERVAL, a cycle of 60-180 s jumped over that window
and the restart ran with no warning. The first repair (d39f5438) only
logged it. THE OPERATOR (2026-09-30): the admin sets the warning time -
why should DDC miss it?

THE CONTRACT: the scheduler wakes up when a warning window opens, so the
warning goes out on time. If it still could not (DDC was restarted, a
cycle ran long), the warning is posted as soon as the occurrence is due,
and the action waits the admin's warning time from then on - it is not
written off as missed while it waits.

HOW THIS TEST CAN FAIL: the loop sleeps across a window again, or a late
occurrence runs without its warning or without the time the admin set.

COUNTER-CHECK (2026-09-30): red before the change (the sleep ignored the
window; the late occurrence ran at once, unwarned).
"""

import pytest

from services.scheduling import scheduler_service as ss
from tests.spec.test_a_task_waits_until_nobody_plays import (  # noqa: F401 - fixtures
    _cycle, _isolated_config, _store, world)


@pytest.mark.asyncio
async def test_the_loop_wakes_up_for_the_window(world):  # noqa: F811
    _store(world, {"warn_minutes": 1}, due_in=100)
    service = ss.SchedulerService()
    await _cycle(service, world)                    # 100 s before: the window opens in 40 s
    assert service._sleep_before_next_cycle(0.1) <= 40


@pytest.mark.asyncio
async def test_a_late_occurrence_is_warned_and_waits_the_warning_time(world):  # noqa: F811
    _store(world, {"warn_minutes": 1}, due_in=61)
    service = ss.SchedulerService()
    await _cycle(service, world)                    # outside the window
    await _cycle(service, world, 121)               # jumped over it: due, never warned
    assert world["ran"] == [] and len(world["posted"]) == 1, "ran unwarned"
    await _cycle(service, world, 30)                # 30 of the 60 seconds
    assert world["ran"] == []
    await _cycle(service, world, 31)                # the admin's minute is over
    assert world["ran"] == ["t1"] and world["rescheduled"] == []


@pytest.mark.asyncio
async def test_a_warning_on_time_changes_nothing(world):  # noqa: F811
    _store(world, {"warn_minutes": 10}, due_in=5 * 60)
    service = ss.SchedulerService()
    await _cycle(service, world)                    # inside the window: warned
    await _cycle(service, world, 6 * 60)
    assert world["ran"] == ["t1"] and len(world["posted"]) == 1
