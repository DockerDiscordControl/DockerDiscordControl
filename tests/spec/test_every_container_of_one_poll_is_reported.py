# -*- coding: utf-8 -*-
"""When several containers change at once, every one of them is reported.

THE FINDING: process_container_events asks acquire_execution_locks for each
event, and the GLOBAL cooldown (30 seconds by default) rejects everything
that follows the first. One poll that sees four containers stopped - a host
reboot, "Stop All", a Docker restart, exactly when the operator wants to
know - therefore reported ONE of them. And because ContainerWatcher has
already written the new state, the other three never produce an event again:
they are not delayed, they are lost.

The global cooldown exists so that a chatty Discord channel cannot fire a
rule every second. The events of ONE poll are not that: each is a different
container's state change, and the per-container and per-rule cooldowns still
apply. So it is checked once for the batch - if it passes, every event of
that poll is handled; if it does not, the poll is skipped as a whole.

COUNTER-CHECK (2026-09-22): red before - only the first container was
reported; and a batch that arrives INSIDE the global cooldown is still
skipped entirely (second test), which goes red if the cooldown is simply
dropped for watchdog events.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.automation.auto_action_config_service import AutoActionRule
from services.automation.auto_action_state_service import AutoActionStateService
from services.automation.container_watch import WatchEvent

RULE = {"id": "watch", "name": "Watch all", "priority": 1,
        "trigger": {"type": "container_state", "states": ["stopped"]},
        "action": {"type": "NOTIFY"}, "cooldown_minutes": 0}


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    from services.automation import automation_service as mod

    engine = mod.AutomationService.__new__(mod.AutomationService)
    engine.config_service = MagicMock()
    engine.config_service.get_global_settings.return_value = {"enabled": True,
                                                              "global_cooldown_seconds": 30}
    engine.config_service.get_rules.return_value = [AutoActionRule.from_dict(RULE)]
    engine.state_service = AutoActionStateService()
    engine._send_feedback = AsyncMock()
    return engine


def _events(*names):
    return [WatchEvent(name, "stopped", f"Container '{name}' stopped (it was running).")
            for name in names]


@pytest.mark.asyncio
async def test_all_four_containers_of_one_poll_are_reported(service):
    executed = await service.process_container_events(_events("web", "db", "cache", "proxy"),
                                                      bot=object(), control_channel_id=7)

    assert len(executed) == 4, f"{len(executed)} of 4 containers reported"
    said_about = " ".join(str(call.args[2]) for call in service._send_feedback.await_args_list)
    for name in ("web", "db", "cache", "proxy"):
        assert name in said_about, f"nothing was said about {name}"


@pytest.mark.asyncio
async def test_a_second_poll_inside_the_global_cooldown_is_skipped(service):
    await service.process_container_events(_events("web"), bot=object(), control_channel_id=7)
    service._send_feedback.reset_mock()

    executed = await service.process_container_events(_events("db", "cache"),
                                                      bot=object(), control_channel_id=7)

    assert executed == [], "the global cooldown no longer holds between polls"
    service._send_feedback.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_container_keeps_its_own_cooldown(service):
    """Counter-check: the per-container cooldown must still bite inside a batch."""
    service.config_service.get_rules.return_value = [
        AutoActionRule.from_dict({**RULE, "cooldown_minutes": 60})]

    first = await service.process_container_events(_events("web", "db"), bot=object(),
                                                   control_channel_id=7)
    second = await service.process_container_events(_events("web"), bot=object(),
                                                    control_channel_id=7)

    assert len(first) == 2 and second == []
