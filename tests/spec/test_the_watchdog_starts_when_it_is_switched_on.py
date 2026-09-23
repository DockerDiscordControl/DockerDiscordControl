# -*- coding: utf-8 -*-
"""Switching the Status Watchdog on in the panel takes effect without a restart.

THE FINDING (independent review of the cog modules, 2026-09-23):
_setup_background_loops starts heartbeat_send_loop only if the watchdog was
already enabled when DDC started:

    if heartbeat_enabled:
        heartbeat_task = self.bot.loop.create_task(...)

and that function runs exactly once, from setup() or from on_ready() behind a
guard. Saving the panel writes the file and emits channel_config_changed;
nothing starts the loop.

So: the operator ticks "Status Watchdog", pastes the Healthchecks.io URL and
saves. The panel answers "Configuration saved successfully." and renders the
switch as on, because it reads it back from the file. No ping is ever sent, and
after its grace period the monitoring service alerts "DDC is down" about a bot
that is running perfectly.

This is the one feature whose entire job is to tell the operator when DDC has
stopped, and it was silently off for the whole window between enabling it and
the next restart - with no hint anywhere that a restart was needed.

THE FIX IS THE SMALL ONE: the loop body already reads the configuration on
every cycle and returns immediately when the watchdog is off (background_loops
.py, "if not heartbeat_config.get('enabled')"). It guards itself. So it is
simply always started, and the switch takes effect within one interval - on
AND off, which the old arrangement could not do either.

The cost is one config read every five minutes when the feature is unused.

HOW THIS TEST CAN FAIL: it starts the loops with the watchdog switched OFF and
asks whether the loop is running. If it is not, the panel switch cannot take
effect and the test is red.

COUNTER-CHECK (2026-09-23): red before - the loop was never started. The other
tests keep the point: a running loop with the watchdog off pings nothing, and
with it on it pings.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

import cogs.docker_control as dc
from cogs.background_loops import BackgroundLoopsMixin


def _cog_with_loops(monkeypatch, heartbeat_enabled):
    """A cog whose loop-starting is recorded instead of done."""
    started = []

    cog = dc.DockerControlCog.__new__(dc.DockerControlCog)
    cog.bot = MagicMock()
    cog.bot.loop = MagicMock()
    cog.bot.loop.create_task = lambda coro: (coro.close(), MagicMock())[1]
    cog.config = {}
    cog._tracked_tasks = set()

    async def start_loop_safely(loop, name):
        started.append(name)

    cog._start_loop_safely = start_loop_safely
    cog._track_task = AsyncMock()

    monkeypatch.setattr(dc, "load_config", lambda: {
        "heartbeat": {"enabled": heartbeat_enabled, "ping_url": "https://hc-ping.com/abc"}})
    return cog, started


def _source_of_setup():
    import inspect

    return inspect.getsource(dc.DockerControlCog._setup_background_loops)


def test_the_watchdog_loop_is_started_even_when_it_is_off():
    """THE FINDING: it was started only if it was on at boot.

    Read from the source, because that is where the fault is - a start that
    never happens cannot be observed by calling the thing that does not run.
    """
    source = _source_of_setup()

    assert "if heartbeat_enabled:" not in source, (
        "the watchdog loop is still started only when it was already on at "
        "boot, so switching it on in the panel does nothing until a restart")
    assert "heartbeat_send_loop" in source, (
        "the watchdog loop is not started at all any more")


def test_the_loop_guards_itself_when_the_watchdog_is_off(monkeypatch):
    """Always starting it is only safe because the body checks every cycle."""
    cog = MagicMock()
    cog.config = {}
    pinged = []

    import cogs.background_loops as bl

    monkeypatch.setattr(bl, "load_config", lambda: {"heartbeat": {"enabled": False}})
    monkeypatch.setattr(
        "aiohttp.ClientSession",
        lambda *a, **k: pinged.append("ping") or MagicMock())

    asyncio.run(BackgroundLoopsMixin.heartbeat_send_loop.coro(cog))

    assert pinged == [], "the watchdog pinged although it is switched off"


def test_the_loop_pings_when_the_watchdog_is_on(monkeypatch):
    """Counter-check: with it on, it really does ping."""
    cog = MagicMock()
    cog.config = {}
    cog.heartbeat_send_loop = MagicMock()
    cog.heartbeat_send_loop.minutes = 5
    asked = []

    import cogs.background_loops as bl

    monkeypatch.setattr(bl, "load_config", lambda: {"heartbeat": {
        "enabled": True, "ping_url": "https://hc-ping.com/abc", "interval": 5}})

    class _Response:
        status = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def get(self, url, **kwargs):
            asked.append(url)
            return _Response()

    monkeypatch.setattr("aiohttp.ClientSession", lambda *a, **k: _Session())

    asyncio.run(BackgroundLoopsMixin.heartbeat_send_loop.coro(cog))

    assert asked == ["https://hc-ping.com/abc"]


def test_a_url_that_is_not_https_is_still_refused(monkeypatch):
    """Counter-check: the outbound rule is untouched."""
    cog = MagicMock()
    cog.config = {}
    asked = []

    import cogs.background_loops as bl

    monkeypatch.setattr(bl, "load_config", lambda: {"heartbeat": {
        "enabled": True, "ping_url": "http://hc-ping.com/abc"}})
    monkeypatch.setattr("aiohttp.ClientSession",
                        lambda *a, **k: asked.append("ping") or MagicMock())

    asyncio.run(BackgroundLoopsMixin.heartbeat_send_loop.coro(cog))

    assert asked == [], "a plain-HTTP monitoring URL was pinged"
