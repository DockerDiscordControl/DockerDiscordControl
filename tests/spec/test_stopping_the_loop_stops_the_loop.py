# -*- coding: utf-8 -*-
"""Stopping the background loop stops it, rather than asking it to notice.

THE FINDING (review C70, section 23 F7): ``stop_background_loop()`` sets
``_loop_running = False`` and then cancels ``self._loop_task`` - a field
initialised to None at construction and never written to, by this file or any
other. So the cancel branch never ran, and stopping the loop meant flipping a
flag that the loop only looks at after its ``await asyncio.sleep(...)``
returns: up to a full refresh interval, 30 s by default.

The existing unit test put a Mock into ``_loop_task`` by hand and checked
that cancel() was called on it. That pins the route, not the promise - it
passes just as happily while nothing ever puts a task there.
"""

import asyncio

import pytest

from services.mech.mech_status_cache_service import MechStatusCacheService


@pytest.fixture
def service(monkeypatch):
    service = MechStatusCacheService()
    service._refresh_interval = 30.0
    # The refresh itself is not the subject here.
    async def _noop():
        return None
    monkeypatch.setattr(service, "_background_refresh", _noop)
    return service


@pytest.mark.asyncio
async def test_a_running_loop_is_reachable(service):
    """Without this, nothing could cancel the loop even in principle."""
    task = asyncio.ensure_future(service.start_background_loop())
    await asyncio.sleep(0)          # let it get going
    try:
        assert service._loop_task is not None, (
            "the loop is running and the service does not know which task it is"
        )
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_stopping_does_not_wait_out_the_sleep(service):
    task = asyncio.ensure_future(service.start_background_loop())
    await asyncio.sleep(0)          # the loop reaches its 30 s sleep

    service.stop_background_loop()

    try:
        await asyncio.wait_for(asyncio.shield(task), timeout=1.0)
    except asyncio.TimeoutError:
        pytest.fail("stop_background_loop() returned and the loop is still sleeping")
    except asyncio.CancelledError:
        pass                        # cancelled, which is the point
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    assert service._loop_running is False


@pytest.mark.asyncio
async def test_stopping_a_loop_that_never_ran_is_harmless(service):
    """Counter-check: the usual shutdown calls this whether or not it ran."""
    service.stop_background_loop()

    assert service._loop_running is False
    assert service._loop_task is None


@pytest.mark.asyncio
async def test_a_finished_loop_leaves_nothing_behind(service):
    """Counter-check: the field must not keep a dead task alive."""
    task = asyncio.ensure_future(service.start_background_loop())
    await asyncio.sleep(0)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    assert service._loop_task is None
