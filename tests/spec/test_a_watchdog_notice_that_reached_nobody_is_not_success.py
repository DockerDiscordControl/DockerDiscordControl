# -*- coding: utf-8 -*-
"""A watchdog notice that reached nobody is not a success, and tries the control channel.

THE FINDING (audit 2026-09-26, F13). _send_feedback skipped a channel the bot
could not see (deleted, or no permission) without a word, and a NOTIFY rule
was recorded SUCCESS anyway - spending its cooldown, 24 hours by default, on
a message nobody got. A rule's own channel that had gone away did not fall
back to the control channel either.

THE CONTRACT: the notice goes to the rule's channel, else the control
channel; if neither takes it, the log says so and the NOTIFY is FAILED (its
cooldown released, so the next event tries again).

COUNTER-CHECK (2026-09-26): red before the fix - nothing reached the control
channel, and the history said SUCCESS.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.automation.auto_action_config_service import AutoActionRule
from services.automation.container_watch import WatchEvent

GONE = "222222222222222222"
CONTROL = "111111111111111111"
STOPPED = WatchEvent("web", "stopped", "Container 'web' stopped (it was running).")


class _Bot:
    """Knows only the channels it is given."""

    def __init__(self, *known):
        self.sent = []
        self._known = {int(c) for c in known}

    def get_channel(self, channel_id):
        if channel_id not in self._known:
            return None
        bot = self

        class _Channel:
            async def send(self, message):
                bot.sent.append((channel_id, message))

        return _Channel()


@pytest.fixture
def engine():
    from services.automation import automation_service as mod

    service = mod.AutomationService.__new__(mod.AutomationService)
    service.config_service = MagicMock()
    service.config_service.get_global_settings.return_value = {"enabled": True, "protected_containers": []}
    service.config_service.get_rules.return_value = [AutoActionRule.from_dict({
        "id": "r1", "name": "Tell me", "enabled": True, "priority": 1,
        "trigger": {"type": "container_state", "states": ["stopped"], "containers": ["web"]},
        "action": {"type": "NOTIFY", "containers": [], "notification_channel_id": GONE},
        "safety": {"cooldown_minutes": 1}})]
    service.state_service = MagicMock()
    service.state_service.acquire_execution_locks.return_value = (True, "", None)
    return service


@pytest.mark.asyncio
async def test_a_gone_channel_falls_back_to_the_control_channel(engine):
    bot = _Bot(CONTROL)

    await engine.process_container_events([STOPPED], bot=bot, control_channel_id=CONTROL)

    assert [channel for channel, _ in bot.sent] == [int(CONTROL)]


@pytest.mark.asyncio
async def test_a_notice_nobody_got_is_recorded_as_failed(engine):
    bot = _Bot()   # knows no channel at all

    await engine.process_container_events([STOPPED], bot=bot, control_channel_id=CONTROL)

    results = [call.args[4] for call in engine.state_service.record_trigger.call_args_list]
    assert results == ["FAILED"], results


@pytest.mark.asyncio
async def test_a_notice_that_arrived_is_success(engine):
    """Counter-case."""
    bot = _Bot(GONE)

    await engine.process_container_events([STOPPED], bot=bot, control_channel_id=CONTROL)

    results = [call.args[4] for call in engine.state_service.record_trigger.call_args_list]
    assert results == ["SUCCESS"] and [c for c, _ in bot.sent] == [int(GONE)]
