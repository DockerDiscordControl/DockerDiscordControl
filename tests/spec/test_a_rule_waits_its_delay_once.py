# -*- coding: utf-8 -*-
"""A rule with a delay waits it once, not once per container.

THE FINDING (stage 4 review before v3.1.0, section 11 pass 4 F8): the delay
was slept inside the loop over the targets, so a rule with a delay of N on
three containers acted on the last one 3 x N seconds after the message,
while its announcement said "(Ns delay)" and the panel's tooltip "wait time
before the action runs".

THE CONTRACT: one wait, before the first container.

HOW THIS TEST CAN FAIL: the delay is slept per container again.

COUNTER-CHECK (2026-09-29): red before the change.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.spec.test_rule_cooldown_survives_one_failed_container import RULE, state  # noqa: F401


@pytest.mark.asyncio
async def test_three_containers_one_wait(state, monkeypatch):  # noqa: F811
    from services.automation import automation_service as auto_mod

    service = auto_mod.AutomationService.__new__(auto_mod.AutomationService)
    service.config_service = MagicMock()
    service.state_service = state
    monkeypatch.setattr(auto_mod, "is_container_exists", AsyncMock(return_value=True))
    monkeypatch.setattr(auto_mod, "docker_action", AsyncMock(return_value=True))
    monkeypatch.setattr(service, "_trigger_status_refresh", AsyncMock())
    slept = AsyncMock()
    monkeypatch.setattr(auto_mod.asyncio, "sleep", slept)
    rule = SimpleNamespace(
        id=RULE, name="Rule", priority=1, only_if_running=False,
        action=SimpleNamespace(type="RESTART", containers=["a", "b", "c"], delay_seconds=60,
                               silent=True, notification_channel_id=None, player_options=None),
        safety=SimpleNamespace(cooldown_minutes=60, cooldown_scope="container"),
        cooldown_minutes=60, cooldown_scope="container")
    context = auto_mod.TriggerContext(message_id="1", channel_id="9", guild_id="2", user_id="3",
                                      username="w", is_webhook=False, content="crash", embeds_text="")

    await service._execute_rule(rule, context, {"protected_containers": [], "global_cooldown_seconds": 0}, None)

    delays = [c.args[0] for c in slept.await_args_list if c.args and c.args[0] == 60]
    assert delays == [60], f"the delay was slept {len(delays)} times for three containers"
