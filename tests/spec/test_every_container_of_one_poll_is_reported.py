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
that poll is handled. (Until 2026-09-26: "if it does not, the poll is skipped
as a whole" - which lost events for good; see the revised case below.)

COUNTER-CHECK (2026-09-22): red before - only the first container was
reported.
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
async def test_a_second_poll_inside_the_global_cooldown_is_still_reported(service):
    """REVISED 2026-09-26 (audit F3, the operator asked for all of it fixed). This case used
    to pin the opposite - a poll inside the 30 s global cooldown skipped as a
    whole. With a poll every 30 s and the cooldown written after each action,
    that was EVERY poll after one that acted, and the watcher has already
    stored the new state: the database dies, the app that depends on it dies
    on the next poll, and the app's alarm is gone for good. The global
    cooldown is for chatty Discord channels; a watchdog event happens once per
    state change and has its per-rule-and-container cooldown.

    COUNTER-CHECK (2026-09-26): red before the fix - executed == [].
    """
    await service.process_container_events(_events("web"), bot=object(), control_channel_id=7)
    service._send_feedback.reset_mock()

    executed = await service.process_container_events(_events("db", "cache"),
                                                      bot=object(), control_channel_id=7)

    assert len(executed) == 2, "an event inside the global cooldown was lost"


@pytest.mark.asyncio
async def test_a_refused_first_event_does_not_hold_back_the_rest(service):
    """Audit F4: the first event of a poll hits a protected container, so its
    action is refused - and the global cooldown it had already taken kept
    every later event of the same poll out.

    COUNTER-CHECK (2026-09-26): red before the fix - only the refusal."""
    service.config_service.get_global_settings.return_value = {
        "enabled": True, "global_cooldown_seconds": 30, "protected_containers": ["web"]}
    service.config_service.get_rules.return_value = [
        AutoActionRule.from_dict({**RULE, "action": {"type": "RESTART"}})]
    from services.automation import automation_service as mod

    acted = []

    async def _act(name, verb):
        acted.append(name)
        return True

    import pytest as _pytest
    with _pytest.MonkeyPatch.context() as patch:
        patch.setattr(mod, "docker_action", _act)
        patch.setattr(service, "_trigger_status_refresh", AsyncMock())
        await service.process_container_events(_events("web", "db"), bot=object(),
                                               control_channel_id=7)

    assert acted == ["db"], acted


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
