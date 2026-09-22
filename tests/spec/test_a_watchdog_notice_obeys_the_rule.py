# -*- coding: utf-8 -*-
"""A watchdog notice obeys its rule: silent stays silent, and it is rate-limited.

Two in the container-state path that every other path already handles:

* NOTIFY sent the message without looking at `silent`, while the acting
  branches all check it. A rule saved as silent still posted;
* the notice for a PROTECTED container was sent before the cooldowns were
  taken, so it was the one message in the whole engine with no rate limit at
  all: a protected container flapping healthy -> unhealthy -> healthy posted
  once per transition, every poll.

COUNTER-CHECK (2026-09-22): red before - the silent rule posted, and the
protected container posted twice inside its cooldown.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.automation.auto_action_config_service import AutoActionRule
from services.automation.container_watch import WatchEvent

CONTROL = 55


def _rule(**action):
    data = {"id": "r", "name": "Watch", "trigger": {"type": "container_state", "states": ["stopped"]},
            "action": {"type": "NOTIFY", **action}}
    return AutoActionRule.from_dict(data)


@pytest.fixture
def engine():
    from services.automation import automation_service as mod

    service = mod.AutomationService.__new__(mod.AutomationService)
    service.config_service = MagicMock()
    service.config_service.get_global_settings.return_value = {
        "enabled": True, "global_cooldown_seconds": 0, "protected_containers": ["ddc"]}
    service.state_service = MagicMock()
    service.state_service.acquire_execution_locks.return_value = (True, "", None)
    sent = []

    async def _feedback(bot, channel_id, message):
        sent.append(message)

    service._send_feedback = AsyncMock(side_effect=_feedback)
    return service, sent


async def _fire(service, rule, container="web"):
    service.config_service.get_rules.return_value = [rule]
    return await service.process_container_events(
        [WatchEvent(container, "stopped", f"Container '{container}' stopped (it was running).")],
        bot=object(), control_channel_id=CONTROL)


@pytest.mark.asyncio
async def test_a_silent_rule_does_not_post(engine):
    service, sent = engine
    await _fire(service, _rule(silent=True))
    assert sent == []


@pytest.mark.asyncio
async def test_a_rule_that_is_not_silent_still_posts(engine):
    """Counter-check: silence must not become the default."""
    service, sent = engine
    await _fire(service, _rule())
    assert len(sent) == 1 and "web" in sent[0]


@pytest.mark.asyncio
async def test_the_protected_notice_takes_the_cooldown(engine):
    service, sent = engine
    service.state_service.acquire_execution_locks.side_effect = [(True, "", None),
                                                                 (False, "cooldown", "ddc")]

    await _fire(service, _rule(type="RESTART"), container="ddc")
    await _fire(service, _rule(type="RESTART"), container="ddc")

    assert len(sent) == 1, f"{len(sent)} notices for a protected container inside its cooldown"
    assert "protected" in sent[0].lower()
