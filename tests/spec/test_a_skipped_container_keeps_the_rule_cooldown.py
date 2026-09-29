# -*- coding: utf-8 -*-
"""A container skipped as "not running" does not wipe the rule's cooldown.

THE FINDING (stage 4 review before v3.1.0, section 11 pass 3 F1 + pass 4
F11): with a rule-wide cooldown and "only if running", a batch [A running,
B stopped] restarted A - which set the rule's cooldown - and then skipped B,
whose lock release deleted the rule's cooldown entirely. The container
cooldown of A still held, but as soon as the targets changed (a group
member, an edited rule), the rule acted again inside the window the
operator had set. Review B10 had already moved single-container FAILURES
off the rule cooldown; the lock release was not brought in line.

THE CONTRACT: releasing one container's lock touches only that container;
the rule's cooldown is freed once per batch, and only when nothing
succeeded - also on the watchdog paths that used to rely on the release.

HOW THIS TEST CAN FAIL: the skip wipes the rule cooldown again.

COUNTER-CHECK (2026-09-29): red before the change; the all-failed batch
still frees it (test_rule_cooldown_survives_one_failed_container.py).
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.spec.test_rule_cooldown_survives_one_failed_container import RULE, _rule, state  # noqa: F401


@pytest.mark.asyncio
async def test_a_skip_after_a_success_keeps_the_rule_cooldown(state, monkeypatch):  # noqa: F811
    from services.automation import automation_service as auto_mod

    service = auto_mod.AutomationService.__new__(auto_mod.AutomationService)
    service.config_service = MagicMock()
    service.state_service = state
    monkeypatch.setattr(auto_mod, "is_container_exists", AsyncMock(return_value=True))
    monkeypatch.setattr(auto_mod, "docker_action", AsyncMock(return_value=True))
    monkeypatch.setattr(service, "_trigger_status_refresh", AsyncMock())
    monkeypatch.setattr(service, "_honours_only_if_running",
                        AsyncMock(side_effect=lambda rule, action, name: name == "beta"))
    rule = _rule(["alpha", "beta"])
    rule.only_if_running = True
    context = auto_mod.TriggerContext(message_id="1", channel_id="9", guild_id="2",
                                      user_id="3", username="w", is_webhook=False,
                                      content="crash", embeds_text="")

    await service._execute_rule(rule, context,
                                {"protected_containers": [], "global_cooldown_seconds": 30}, None)

    assert state.rule_cooldowns.get(RULE, 0) > 0, (
        "alpha was restarted, and skipping beta wiped the rule's cooldown")
