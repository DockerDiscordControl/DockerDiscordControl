# -*- coding: utf-8 -*-
"""A broken decision service must not override the operator's refresh interval.

THE FINDING (review E18, cogs/docker_control.py): the periodic edit loop asks
``StatusOverviewService.make_update_decision`` whether an overview message is
due, and wraps that call in a handler for when the service itself is
unavailable. It does this TWICE, for two messages that take the same decision -
and the two fallbacks are different:

    # overview
    except (ImportError, AttributeError, RuntimeError):
        tasks_to_run.append(self._update_overview_message(..., "overview"))

    # admin_overview
    except (ImportError, AttributeError, RuntimeError):
        if last_update_time is None or (now_utc - last_update_time) >= update_interval_delta:
            tasks_to_run.append(self._update_overview_message(..., "admin_overview"))

The loop runs ``@tasks.loop(minutes=1)``. So with the decision service broken,
the admin overview kept to the channel's ``update_interval_minutes`` and the
plain overview was edited **every single minute** - five times the default, and
up to sixty times what an operator who set an hour asked for. Their setting was
quietly discarded at the one moment nothing was going to tell them.

Nobody decided that the two should differ; one was written and the other was
written later. The admin one is the right one, so both do that now.
"""

from datetime import datetime, timedelta, timezone

import pytest


@pytest.fixture
def cog_with_a_broken_decision_service(monkeypatch):
    """A cog with one status channel, and the decision service unavailable."""
    import cogs.docker_control as docker_control
    from cogs.docker_control import DockerControlCog

    monkeypatch.setattr(docker_control, "load_config", lambda: {
        "channel_permissions": {
            "111": {"enable_auto_refresh": True, "update_interval_minutes": 60},
        }
    })

    import services.discord.status_overview_service as overview_service

    def unavailable():
        raise RuntimeError("the decision service is not there")

    monkeypatch.setattr(overview_service, "get_status_overview_service", unavailable)

    cog = DockerControlCog.__new__(DockerControlCog)
    cog.initial_messages_sent = True
    cog.channel_server_message_ids = {111: {"overview": 9001, "admin_overview": 9002}}
    # Both were updated one minute ago; the channel asks for one hour.
    a_minute_ago = datetime.now(timezone.utc) - timedelta(minutes=1)
    cog.last_message_update_time = {111: {"overview": a_minute_ago,
                                          "admin_overview": a_minute_ago}}
    cog.last_channel_activity = {}

    queued = []

    async def _update(channel_id, message_id, kind):
        queued.append(kind)

    cog._update_overview_message = _update
    return cog, queued


@pytest.mark.asyncio
async def test_the_overview_waits_like_the_admin_overview_does(
        cog_with_a_broken_decision_service):
    cog, queued = cog_with_a_broken_decision_service

    from cogs.docker_control import DockerControlCog
    await DockerControlCog.periodic_message_edit_loop.coro(cog)

    assert "overview" not in queued, (
        "the channel asks for one hour between refreshes and the overview was "
        "edited one minute after the last one, because the decision service was "
        "unavailable - the operator's setting was discarded in silence"
    )


@pytest.mark.asyncio
async def test_the_admin_overview_still_waits_too(cog_with_a_broken_decision_service):
    """The counter-check: the branch that was already right stays right."""
    cog, queued = cog_with_a_broken_decision_service

    from cogs.docker_control import DockerControlCog
    await DockerControlCog.periodic_message_edit_loop.coro(cog)

    assert "admin_overview" not in queued


@pytest.mark.asyncio
async def test_an_overdue_overview_is_still_refreshed(
        cog_with_a_broken_decision_service):
    """A fallback that never refreshes would be worse than one that always does."""
    cog, queued = cog_with_a_broken_decision_service
    long_ago = datetime.now(timezone.utc) - timedelta(hours=3)
    cog.last_message_update_time = {111: {"overview": long_ago,
                                          "admin_overview": long_ago}}

    from cogs.docker_control import DockerControlCog
    await DockerControlCog.periodic_message_edit_loop.coro(cog)

    assert "overview" in queued, (
        "three hours past a one-hour interval and the overview was not refreshed"
    )
