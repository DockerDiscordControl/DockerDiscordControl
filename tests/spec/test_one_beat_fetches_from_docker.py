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
