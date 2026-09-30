# -*- coding: utf-8 -*-
"""A player warning that no check cycle could post is said in the log.

THE FINDING (stage 4 review before v3.1.0, section 49 pass 4): the player
warning is posted only if a check cycle lands inside [acting_at - warn,
acting_at). With warn_minutes 1 or 2 (the panel allows 1-60), or a raised
DDC_SCHEDULER_CHECK_INTERVAL, a cycle of 60-180 s can jump over that
window; the next cycle finds the occurrence due and the restart runs
with no warning - and nothing anywhere says the warning was skipped.

THE CONTRACT: an occurrence with a warning that was not posted is logged
at WARNING before it runs. (Whether it should also post a late notice, or
refuse short warnings at save time, is the operator's question.)

HOW THIS TEST CAN FAIL: the skipped warning is silent again, or a warning
that was posted is reported as missed.

COUNTER-CHECK (2026-09-30): red before the change (no log line).
"""

import pytest

from services.scheduling import scheduler_service as ss
from tests.spec.test_a_task_waits_until_nobody_plays import (  # noqa: F401 - fixtures
    _cycle, _isolated_config, _store, world)


@pytest.fixture
def warnings(monkeypatch):
    said = []
    real = ss.logger.warning

    def record(message, *args, **kwargs):
        said.append(str(message))
        return real(message, *args, **kwargs)
    monkeypatch.setattr(ss.logger, "warning", record)
    return said


@pytest.mark.asyncio
async def test_a_jumped_window_is_logged(world, warnings):  # noqa: F811
    _store(world, {"warn_minutes": 1}, due_in=61)
    service = ss.SchedulerService()
    await _cycle(service, world)                    # 61 s before: outside the 60 s window
    await _cycle(service, world, 121)               # a 121 s cycle: 60 s late, due
    assert world["ran"] == ["t1"] and world["posted"] == []
    assert any("t1" in text and "warning" in text.lower() for text in warnings), warnings


@pytest.mark.asyncio
async def test_a_posted_warning_is_not_reported_missed(world, warnings):  # noqa: F811
    _store(world, {"warn_minutes": 10}, due_in=5 * 60)
    service = ss.SchedulerService()
    await _cycle(service, world)                    # inside the window: warned
    await _cycle(service, world, 6 * 60)
    assert world["ran"] == ["t1"] and len(world["posted"]) == 1
    assert not any("t1" in text and "warning" in text.lower() for text in warnings), warnings
