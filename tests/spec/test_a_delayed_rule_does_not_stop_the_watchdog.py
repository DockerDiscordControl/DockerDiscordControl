# -*- coding: utf-8 -*-
"""A watchdog rule with a delay does not hold up the status loop, and looks again.

THE FINDING (audit 2026-09-26, F5). A container-state rule may wait up to an
hour (delay_seconds) before it acts. The wait was awaited inside
_execute_container_rule, which the STATUS LOOP calls: for the whole delay no
status update, no watchdog, and the notes of DDC's own stops (a few minutes)
ran out meanwhile. And after the wait nothing looked again - a container that
had come back by itself was restarted anyway.

THE CONTRACT: a delayed action runs beside the loop; processing the events
returns at once. After the delay the container is looked at again, and a
stopped container that runs again (or an unhealthy one that is healthy) is
left alone, with a SKIPPED record saying so.

COUNTER-CHECK (2026-09-26): red before the fix - the call took the whole delay
(asyncio.sleep was awaited inline), and the recovered container was restarted.
"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.automation.auto_action_config_service import AutoActionRule
from services.automation.container_watch import WatchEvent

STOPPED = WatchEvent("web", "stopped", "Container 'web' stopped (it was running).")


@pytest.fixture
def engine(monkeypatch):
    from services.automation import automation_service as mod

    service = mod.AutomationService.__new__(mod.AutomationService)
    service.config_service = MagicMock()
    service.config_service.get_global_settings.return_value = {"enabled": True, "protected_containers": []}
    service.config_service.get_rules.return_value = [AutoActionRule.from_dict({
        "id": "r1", "name": "Bring it back", "enabled": True, "priority": 1,
        "trigger": {"type": "container_state", "states": ["stopped"], "containers": ["web"]},
        "action": {"type": "RESTART", "containers": [], "delay_seconds": 5},
        "safety": {"cooldown_minutes": 1}})]
    service.state_service = MagicMock()
    service.state_service.acquire_execution_locks.return_value = (True, "", None)
    service._send_feedback = AsyncMock()
    service._trigger_status_refresh = AsyncMock()
    action = AsyncMock(return_value=True)
    monkeypatch.setattr(mod, "docker_action", action)
    return service, action, mod


async def _settle(service):
    await asyncio.gather(*list(getattr(service, "_delayed_actions", set())))


@pytest.mark.asyncio
async def test_the_events_are_processed_without_waiting_for_the_delay(engine):
    service, _action, _mod = engine
    start = time.monotonic()

    await service.process_container_events([STOPPED], bot=object(), control_channel_id=7)

    assert time.monotonic() - start < 2, "the status loop waited for the rule's delay"
    for task in list(getattr(service, "_delayed_actions", set())):
        task.cancel()


@pytest.mark.asyncio
async def test_a_container_that_came_back_is_left_alone(engine, monkeypatch):
    service, action, mod = engine
    monkeypatch.setattr(mod.asyncio, "sleep", AsyncMock())
    monkeypatch.setattr(mod, "get_docker_info", AsyncMock(return_value={"State": {"Running": True}}))

    await service.process_container_events([STOPPED], bot=object(), control_channel_id=7)
    await _settle(service)

    action.assert_not_awaited()
    results = [call.args[4] for call in service.state_service.record_trigger.call_args_list]
    assert results == ["SKIPPED"], results


@pytest.mark.asyncio
async def test_a_container_still_down_is_restarted(engine, monkeypatch):
    """Counter-case: the look after the delay must not stop the rule working."""
    service, action, mod = engine
    monkeypatch.setattr(mod.asyncio, "sleep", AsyncMock())
    monkeypatch.setattr(mod, "get_docker_info", AsyncMock(return_value={"State": {"Running": False}}))

    await service.process_container_events([STOPPED], bot=object(), control_channel_id=7)
    await _settle(service)

    action.assert_awaited_once_with("web", "restart")
