# -*- coding: utf-8 -*-
"""The status loop is the one beat that fetches from Docker.

MEASURED ON THE OPERATOR'S INSTALLATION (2026-09-28): DDC_DOCKER_CACHE_DURATION
= 120, both channels refreshing their messages every minute. Docker was polled
every 60 seconds - by two paths taking turns, as the log showed:

    15:50:28  [STATUS_LOOP] Cache updated: 7 success
    15:51:28  Background cache population completed: 7 success
    15:52:28  [STATUS_LOOP] Cache updated: 7 success

The loop fetched every 120 s. In between, the message edits found entries
older than the age a display accepts (STATUS_CACHE_MAX_RENDER_AGE_SECONDS,
60 s - a container stopped outside DDC must not stay green for minutes) and
fetched on their own. The load was the same either way; but the watchdog,
which only the loop feeds, saw every second fetch, and the setting said 120
while 60 happened.

Now the loop keeps the beat the displays need (status_beat_seconds): while any
channel refreshes on its own, at most that age; with none, the configured
interval. The edits find fresh data; a small grace absorbs the timers' drift,
so an edit landing a fraction of a second past the beat does not fetch again.

COUNTER-CHECK (2026-09-28): with status_beat_seconds ignoring the channels,
the beat case and the loop case went red; with the grace removed, the drift
case did; the old-entry case stayed green in both - it is the safety net that
must keep working.

SECOND STEP, SAME DAY (operator: "let the option in the web panel control it"):
the messages were still edited by a loop of their own, ticking beside the
status loop - two clocks, a 5-second tolerance between them. Now the status
loop edits the due messages right after each fetch, its beat is the shortest
update interval of a refreshing channel in the web panel (or the faster
DDC_DOCKER_CACHE_DURATION), and "due" is counted in beats: reached within half
a beat. COUNTER-CHECK: with the edits no longer called from the status loop,
the one-clock case went red; with is_due back to a plain comparison, the
half-beat case did; with the beat ignoring the channels' minutes, the
five-minute case did.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cogs.background_loops import status_beat_seconds
from cogs.docker_control import STATUS_CACHE_MAX_RENDER_AGE_SECONDS
from tests.unit.audit_2026_09.test_r2_g4_status import FakeStatusCache, _bulk_fetch, _cog, _entry, _servers

REFRESHING = {"channel_permissions": {"1": {"enable_auto_refresh": True, "update_interval_minutes": 1},
                                      "2": {"enable_auto_refresh": False}}}
QUIET = {"channel_permissions": {"1": {"enable_auto_refresh": False}}}


def test_the_beat_follows_the_channels():
    assert status_beat_seconds(REFRESHING, 120) == STATUS_CACHE_MAX_RENDER_AGE_SECONDS
    assert status_beat_seconds(REFRESHING, 30) == 30, "a faster setting must stay faster"
    assert status_beat_seconds(QUIET, 120) == 120, "without refreshing channels the setting governs alone"
    assert status_beat_seconds({}, 120) == 120


@pytest.mark.parametrize("config,beat", [(REFRESHING, 60), (QUIET, 120)])
async def test_the_loop_runs_on_the_beat_and_says_so(monkeypatch, config, beat):
    import cogs.background_loops as loops
    from cogs.docker_control import DockerControlCog

    cog = object.__new__(DockerControlCog)
    cog.cache_ttl_seconds = 300
    cog.status_cache_service = MagicMock()
    cog._mark_status_cache_refreshed = MagicMock()
    cog.pending_actions = {}
    cog.bulk_fetch_container_status = AsyncMock(return_value={})
    cog.edit_due_messages = AsyncMock()
    monkeypatch.setattr(loops, "load_config", lambda: config)
    monkeypatch.setattr(loops, "get_server_config_service",
                        lambda: SimpleNamespace(get_all_servers=lambda: [{"docker_name": "web"}]))
    monkeypatch.setattr("utils.settings.get_setting", lambda key, default=None: 120)
    await cog.status_update_loop.coro(cog)
    # py-cord hands every instance its own copy of the loop: the interval it really has
    assert cog.status_update_loop.seconds == beat
    assert cog.status_refresh_interval_seconds == beat, "the embeds' age hints count from another beat"


async def test_an_edit_just_past_the_beat_does_not_fetch_again():
    """The drift case: the loop fetched 61 s ago - one beat and a timer's hiccup."""
    cog = _cog(FakeStatusCache({"a": _entry(STATUS_CACHE_MAX_RENDER_AGE_SECONDS + 1)}))
    cog.bulk_fetch_container_status = _bulk_fetch()
    with patch("cogs.docker_control.get_server_config_service", return_value=_servers("a")):
        await cog._ensure_status_cache_fresh()
    cog.bulk_fetch_container_status.assert_not_awaited()


async def test_an_old_entry_still_fetches():
    """The safety net: the loop missed its beat (a failed cycle) - the edit fetches."""
    cog = _cog(FakeStatusCache({"a": _entry(STATUS_CACHE_MAX_RENDER_AGE_SECONDS + 30)}))
    cog.bulk_fetch_container_status = _bulk_fetch()
    with patch("cogs.docker_control.get_server_config_service", return_value=_servers("a")), \
         patch("cogs.docker_control.load_config", return_value={"language": "en"}), \
         patch("cogs.overview_embeds.load_config", return_value={"language": "en"}):
        await cog._ensure_status_cache_fresh()
    assert cog.bulk_fetch_container_status.await_count == 1


def test_the_beat_is_the_web_panels_update_interval():
    def channels(*minutes):
        return {"channel_permissions": {str(i): {"enable_auto_refresh": True, "update_interval_minutes": m}
                                        for i, m in enumerate(minutes)}}
    assert status_beat_seconds(channels(5), 300) == 300
    assert status_beat_seconds(channels(5, 2), 300) == 120, "the fastest channel sets the pace"
    assert status_beat_seconds(channels(5), 120) == 120, "a faster DDC_DOCKER_CACHE_DURATION stays faster"


def test_due_is_counted_in_beats():
    from datetime import datetime, timedelta, timezone
    from services.discord.status_overview_service import is_due
    ago = lambda seconds: datetime.now(timezone.utc) - timedelta(seconds=seconds)
    minute, five = timedelta(minutes=1), timedelta(minutes=5)
    assert is_due(ago(59.2), minute, beat_seconds=60)
    # Edited in between (after an action, say) 25 s before the beat: waits for the next one
    assert not is_due(ago(25), minute, beat_seconds=60)
    assert is_due(ago(285), five, beat_seconds=60), "the fifth beat was missed by a hair"
    assert not is_due(ago(240), five, beat_seconds=60), "the fourth beat is not the fifth"
    assert is_due(None, five, beat_seconds=60)


async def test_the_status_loop_edits_the_messages_after_it_fetched(monkeypatch):
    import cogs.background_loops as loops
    from cogs.docker_control import DockerControlCog

    order = []
    cog = object.__new__(DockerControlCog)
    cog.cache_ttl_seconds = 300
    cog.status_cache_service = MagicMock()
    cog._mark_status_cache_refreshed = MagicMock()
    cog.pending_actions = {}

    async def _fetch(names):
        order.append("fetch")
        return {}

    async def _edit():
        # Outside the semaphore: an edit that finds something missing refreshes through it
        order.append("edit, semaphore free" if not cog._status_update_semaphore.locked() else "edit, LOCKED")
        raise RuntimeError("Discord said no")
    cog.bulk_fetch_container_status = _fetch
    cog.edit_due_messages = _edit
    monkeypatch.setattr(loops, "load_config", lambda: REFRESHING)
    monkeypatch.setattr(loops, "get_server_config_service",
                        lambda: SimpleNamespace(get_all_servers=lambda: [{"docker_name": "web"}]))
    monkeypatch.setattr("utils.settings.get_setting", lambda key, default=None: 120)
    await cog.status_update_loop.coro(cog)
    assert order == ["fetch", "edit, semaphore free"]


def test_the_messages_have_no_clock_of_their_own():
    import inspect
    from cogs.docker_control import DockerControlCog
    assert not hasattr(DockerControlCog, "periodic_message_edit_loop"), "a second clock is back"
    assert inspect.iscoroutinefunction(DockerControlCog.edit_due_messages)
