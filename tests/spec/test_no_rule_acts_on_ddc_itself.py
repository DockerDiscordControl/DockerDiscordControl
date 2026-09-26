# -*- coding: utf-8 -*-
"""No auto-action rule acts on DDC's own container, whatever it is called.

THE FINDING (audit 2026-09-26, F10). protected_containers defaults to
["ddc", "portainer"], and self_restart.py says that this list guards DDC
against the rules. DDC's container is called "dockerdiscordcontrol" on the
operator's server and in every template, so it was not protected at all. A
watchdog rule with no container list and RESTART on high_memory or unhealthy
would restart DDC - and the process dies before the cooldown is written, so it
would do so again every time the condition came back.

THE CONTRACT: DDC's own container, looked up through Docker, is protected in
both rule paths (watchdog and message rules), in addition to the list.

COUNTER-CHECK (2026-09-26): red before the fix - the watchdog rule restarted
"dockerdiscordcontrol".
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from services.automation.auto_action_config_service import AutoActionRule
from services.automation.container_watch import WatchEvent


@pytest.fixture
def engine(monkeypatch):
    from services.automation import automation_service as mod

    monkeypatch.setattr(mod, "_own_container_name", lambda: "dockerdiscordcontrol", raising=False)
    service = mod.AutomationService.__new__(mod.AutomationService)
    service.config_service = MagicMock()
    service.config_service.get_global_settings.return_value = {
        "enabled": True, "protected_containers": ["ddc", "portainer"]}
    service.config_service.get_rules.return_value = [AutoActionRule.from_dict({
        "id": "r1", "name": "Restart the unhealthy", "enabled": True, "priority": 1,
        "trigger": {"type": "container_state", "states": ["unhealthy"]},
        "action": {"type": "RESTART", "containers": []}, "safety": {"cooldown_minutes": 1}})]
    service.state_service = MagicMock()
    service.state_service.acquire_execution_locks.return_value = (True, "", None)
    service._send_feedback = AsyncMock()
    service._trigger_status_refresh = AsyncMock()
    action = AsyncMock(return_value=True)
    monkeypatch.setattr(mod, "docker_action", action)
    return service, action


def _unhealthy(name):
    return WatchEvent(name, "unhealthy", f"Container '{name}' is unhealthy.")


@pytest.mark.asyncio
async def test_ddc_is_not_restarted_by_its_own_watchdog(engine):
    service, action = engine

    await service.process_container_events([_unhealthy("dockerdiscordcontrol")], bot=object(),
                                           control_channel_id=7)

    action.assert_not_awaited()


@pytest.mark.asyncio
async def test_any_other_container_still_is(engine):
    """Counter-case: protecting DDC must not protect everything."""
    service, action = engine

    await service.process_container_events([_unhealthy("Valheim")], bot=object(), control_channel_id=7)

    action.assert_awaited_once_with("Valheim", "restart")


@pytest.mark.asyncio
async def test_the_list_still_counts(engine):
    service, action = engine

    await service.process_container_events([_unhealthy("portainer")], bot=object(), control_channel_id=7)

    action.assert_not_awaited()
