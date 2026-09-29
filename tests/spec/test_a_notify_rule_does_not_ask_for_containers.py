# -*- coding: utf-8 -*-
"""A NOTIFY rule whose listed containers are gone does not notify on every message.

THE FINDING (stage 4 review before v3.1.0, section 11 pass 4 F7): a NOTIFY
message rule may name containers. When they no longer existed (removed or
renamed since), each matching message sent the notice AND a "Container not
found" notice - and the "not found" counted as a failure, which freed both
cooldowns, so only the 30 s global cooldown limited it.

THE CONTRACT: a NOTIFY rule does not ask whether its containers exist - the
notice is the action; it was delivered, and the cooldown holds.

HOW THIS TEST CAN FAIL: the second matching message notifies again.

COUNTER-CHECK (2026-09-29): red before the change.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.spec.test_rule_cooldown_survives_one_failed_container import RULE, state  # noqa: F401


@pytest.mark.asyncio
async def test_the_second_message_is_held_by_the_cooldown(state, monkeypatch):  # noqa: F811
    from services.automation import automation_service as auto_mod

    service = auto_mod.AutomationService.__new__(auto_mod.AutomationService)
    service.config_service = MagicMock()
    service.state_service = state
    monkeypatch.setattr(auto_mod, "is_container_exists", AsyncMock(return_value=False))
    sent = []

    async def _feedback(bot, channel_id, text):
        sent.append(text)
    monkeypatch.setattr(service, "_send_feedback", _feedback)
    rule = SimpleNamespace(
        id=RULE, name="Rule", priority=1, only_if_running=False,
        action=SimpleNamespace(type="NOTIFY", containers=["gone"], delay_seconds=0, silent=False,
                               notification_channel_id=None, player_options=None),
        safety=SimpleNamespace(cooldown_minutes=60, cooldown_scope="rule"),
        cooldown_minutes=60, cooldown_scope="rule")
    context = auto_mod.TriggerContext(message_id="1", channel_id="9", guild_id="2", user_id="3",
                                      username="w", is_webhook=False, content="crash", embeds_text="")
    settings = {"protected_containers": [], "global_cooldown_seconds": 0}

    await service._execute_rule(rule, context, settings, object())
    first = len(sent)
    await service._execute_rule(rule, context, settings, object())

    assert not any("not found" in text for text in sent), sent
    assert len(sent) == first, f"the second message notified again: {sent}"
