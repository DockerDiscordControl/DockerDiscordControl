# -*- coding: utf-8 -*-
"""The warning before a scheduled restart or stop is posted.

THE FINDING (final check before v3.1.0, 2026-09-29). The task "Icarus2
restart 01:51, warning 5 min before" ran on the operator's host - and at
01:46 the log said "No bot to post the warning". The scheduler asked its
own scheduler_service.get_bot_instance(), which nothing ever filled: bot.py
registers the bot in donation_message_service only. No task warning was
ever posted; the auto-actions were not hit, they are handed the bot by
their trigger. The warning had no test that went through the real lookup.

THE CONTRACT: with the bot registered the way bot.py registers it, a task
inside its warning window posts the warning, once per occurrence.

HOW THIS TEST CAN FAIL: the scheduler hands post_warning None again.

COUNTER-CHECK (2026-09-29): with get_bot_instance back to returning only
its own (never set) global, the first two go red - nothing is sent.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


class _Channel:
    def __init__(self):
        self.send = AsyncMock()


@pytest.fixture
def setup(monkeypatch):
    from services.scheduling import donation_message_service, player_gate, scheduler_service

    channel = _Channel()
    bot = SimpleNamespace(get_channel=lambda _cid: channel)
    monkeypatch.setattr(scheduler_service, "_bot_instance", None)
    monkeypatch.setattr(donation_message_service, "_bot_instance", None)
    donation_message_service.set_bot_instance(bot)      # what bot.py does
    monkeypatch.setattr(player_gate, "warning_channel_ids", lambda _config: [42])
    monkeypatch.setattr(player_gate, "counts_for", lambda _containers: {"Icarus2": 2})
    monkeypatch.setattr("services.config.config_service.load_config", lambda: {})

    service = scheduler_service.SchedulerService()
    service._warned = {}
    run_at = 10_000.0
    task = SimpleNamespace(task_id="t1", container_name="Icarus2", action="restart",
                           target_is_group=False, next_run_ts=run_at,
                           options={"warn_minutes": 5})
    yield service, task, run_at, channel
    donation_message_service.set_bot_instance(None)


@pytest.mark.asyncio
async def test_the_warning_is_posted_through_the_registered_bot(setup):
    service, task, run_at, channel = setup

    await service._warn_players_if_due(task, run_at - 5 * 60)

    channel.send.assert_awaited_once()
    assert "Icarus2" in channel.send.await_args.args[0]


@pytest.mark.asyncio
async def test_one_occurrence_is_warned_once(setup):
    """Counter-check: the next check cycle does not post it again."""
    service, task, run_at, channel = setup

    await service._warn_players_if_due(task, run_at - 5 * 60)
    await service._warn_players_if_due(task, run_at - 4 * 60)

    assert channel.send.await_count == 1


@pytest.mark.asyncio
async def test_outside_the_window_nothing_is_posted(setup):
    """Counter-check: an hour before, there is nothing to say yet."""
    service, task, run_at, channel = setup

    await service._warn_players_if_due(task, run_at - 3600)

    channel.send.assert_not_awaited()
