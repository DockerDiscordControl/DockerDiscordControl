# -*- coding: utf-8 -*-
"""A rule cancelled mid-batch (DDC shutting down) leaves no lock on disk for an untouched container.

THE FINDING (stage 4 review before v3.1.0, section 11 pass 4 F4 + F6): a
message rule on [A, B] with a delay locks both up front. A is acted on and
recorded - and the record saves the whole state, B's up-front lock with it.
If DDC is stopped during B's delay (an update, a restart), the cancellation
handler released B in memory only. After the restart B was refused with
"cooldown active" for up to the rule cooldown (24 h by default), although
nothing had been done to it.

THE CONTRACT: the handler releases the containers not yet recorded in this
run - not the ones already acted on - and writes the state down.

HOW THIS TEST CAN FAIL: B is still locked after a restart, or A's lock is
released as well.

COUNTER-CHECK (2026-09-29): red before the change.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.automation import automation_service as auto_mod
from services.automation.auto_action_config_service import AutoActionRule
from services.automation.auto_action_state_service import AutoActionStateService

RULE = AutoActionRule.from_dict({
    "id": "r1", "name": "delayed", "enabled": True,
    "trigger": {"channel_ids": ["123456789012345678"], "keywords": ["update"]},
    "action": {"type": "RESTART", "containers": ["alpha", "beta"], "delay_seconds": 5,
               "silent": True},
    "safety": {"cooldown_minutes": 60, "cooldown_scope": "container", "only_if_running": False}})


async def test_the_untouched_container_is_free_after_a_restart(monkeypatch, tmp_path):
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    service = auto_mod.AutomationService.__new__(auto_mod.AutomationService)
    service.config_service = MagicMock()
    service.config_service.get_global_settings.return_value = {
        "enabled": True, "protected_containers": [], "global_cooldown_seconds": 0}
    service.config_service.get_rules.return_value = [RULE]
    service.state_service = AutoActionStateService()
    monkeypatch.setattr(auto_mod, "is_container_exists", AsyncMock(return_value=True))
    monkeypatch.setattr(auto_mod, "docker_action", AsyncMock(return_value=True))
    monkeypatch.setattr(service, "_trigger_status_refresh", AsyncMock())
    naps = {"n": 0}

    async def _sleep(seconds):
        naps["n"] += 1
        if naps["n"] == 2:                      # during beta's delay: DDC stops
            raise asyncio.CancelledError()
    monkeypatch.setattr(auto_mod.asyncio, "sleep", _sleep)
    context = auto_mod.TriggerContext(message_id="1", channel_id="123456789012345678",
                                      guild_id="2", user_id="3", username="w",
                                      is_webhook=False, content="update now", embeds_text="")

    with pytest.raises(asyncio.CancelledError):
        await service.process_message(context)

    after_restart = AutoActionStateService()     # reads the file, as the next start does
    assert after_restart.acquire_execution_locks("r1", ["beta"], 0, 60)[0], (
        "beta was never touched, and is locked on disk for the whole cooldown")
    assert not after_restart.acquire_execution_locks("r1", ["alpha"], 0, 60)[0], (
        "alpha was restarted - its cooldown must stand")
