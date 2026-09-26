# -*- coding: utf-8 -*-
"""A container in maintenance is left alone by the watchdog, and the pause ends by itself.

THE REQUEST (operator, 2026-09-26): the only way to work on a container
without an alarm - or, with a RESTART rule, without DDC starting it again in
the middle of a repair - was to switch the rule off for every container, and
to remember to switch it back on (which is how the stale alarm of audit F6
happened). A pause is per container, has an end, survives a DDC restart, and
can be set from the panel and from Discord.

HOW THIS TEST CAN FAIL: a paused container is restarted or reported, a pause
outlives its end, or ending one raises an alarm about the maintenance.

COUNTER-CHECK (2026-09-26): the filter in process_container_events removed -
the restart case went red; the expiry in pauses() removed - the "ends by
itself" case went red.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.automation import maintenance
from services.automation.auto_action_config_service import AutoActionRule
from services.automation.container_watch import WatchEvent

STOPPED = WatchEvent("web", "stopped", "Container 'web' stopped (it was running).")


@pytest.fixture(autouse=True)
def config(monkeypatch, tmp_path):
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture
def engine(monkeypatch):
    from services.automation import automation_service as mod

    service = mod.AutomationService.__new__(mod.AutomationService)
    service.config_service = MagicMock()
    service.config_service.get_global_settings.return_value = {"enabled": True, "protected_containers": []}
    service.config_service.get_rules.return_value = [AutoActionRule.from_dict({
        "id": "r1", "name": "Bring it back", "enabled": True, "priority": 1,
        "trigger": {"type": "container_state", "states": ["stopped"]},
        "action": {"type": "RESTART", "containers": []}, "safety": {"cooldown_minutes": 1}})]
    service.state_service = MagicMock()
    service.state_service.acquire_execution_locks.return_value = (True, "", None)
    service._send_feedback = AsyncMock(return_value=True)
    service._trigger_status_refresh = AsyncMock()
    monkeypatch.setattr(mod, "_own_container_name", lambda: "", raising=False)
    action = AsyncMock(return_value=True)
    monkeypatch.setattr(mod, "docker_action", action)
    return service, action


@pytest.mark.asyncio
async def test_a_paused_container_is_neither_restarted_nor_reported(engine):
    service, action = engine
    maintenance.pause("web", 60, by="operator")

    await service.process_container_events([STOPPED], bot=object(), control_channel_id=7)

    action.assert_not_awaited()
    service._send_feedback.assert_not_awaited()


@pytest.mark.asyncio
async def test_another_container_is_still_watched(engine):
    """Counter-case: a pause is for one container."""
    service, action = engine
    maintenance.pause("db", 60)

    await service.process_container_events([STOPPED], bot=object(), control_channel_id=7)

    action.assert_awaited_once_with("web", "restart")


def test_the_pause_ends_by_itself_and_survives_a_restart(config):
    maintenance.pause("web", 30, now=1000.0)

    assert (config / maintenance.FILE).exists(), "a restart would forget the pause"
    assert maintenance.is_paused("web", now=1000.0 + 29 * 60)
    assert not maintenance.is_paused("web", now=1000.0 + 31 * 60)


def test_a_pause_can_be_ended_early():
    maintenance.pause("web", 60)

    assert maintenance.resume("web") is True
    assert not maintenance.is_paused("web")


@pytest.mark.parametrize("minutes", [0, -5, maintenance.MAX_MINUTES + 1])
def test_a_pause_has_a_sensible_length(minutes):
    with pytest.raises(ValueError):
        maintenance.pause("web", minutes)


@pytest.mark.asyncio
async def test_ending_a_pause_raises_nothing_about_the_maintenance(monkeypatch):
    """The watchers go on observing during the pause: when it ends they compare
    with the state at that moment."""
    from cogs.docker_control import DockerControlCog

    cog = object.__new__(DockerControlCog)
    cog.bot = object()
    cog.pending_actions = {}
    rule = AutoActionRule.from_dict({"id": "r", "name": "Watch", "enabled": True,
                                     "trigger": {"type": "container_state", "states": ["stopped"]},
                                     "action": {"type": "NOTIFY"}})
    monkeypatch.setattr("services.automation.auto_action_config_service.get_auto_action_config_service",
                        lambda: SimpleNamespace(get_rules=lambda: [rule]))
    seen = []

    async def _process(events, **_):
        seen.extend(e for e in events if not maintenance.is_paused(e.container))
        return []

    monkeypatch.setattr("services.automation.automation_service.get_automation_service",
                        lambda: SimpleNamespace(process_container_events=_process))

    def state(running):
        return {"web": SimpleNamespace(success=True, not_found=False, is_running=running, status=None,
                                       health=None, restart_count=0, cpu_percent=None,
                                       memory_percent=None)}

    await cog._feed_container_watchdog(state(True), {})
    maintenance.pause("web", 60)
    await cog._feed_container_watchdog(state(False), {})     # stopped for the repair
    maintenance.resume("web")
    await cog._feed_container_watchdog(state(False), {})     # still stopped after the pause

    assert seen == []
