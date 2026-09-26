# -*- coding: utf-8 -*-
"""A watchdog rule that reaches a container through a group obeys that group.

THE FINDING (audit 2026-09-26). The operator decided on 2026-09-24 that a
group's own Active and its own actions apply wherever a group acts, and that a
switched-off group acts on nobody (test_a_group_decides_what_it_may_do.py).
Message rules follow that through containers_of_action. A CONTAINER-STATE rule
acts on the container the event is about, not on its action list - and that
path never asked the group: a rule "group:Gameserver stopped -> RESTART" went
on restarting members after the operator had switched the group off or taken
its restart box away.

THE CONTRACT: when a container-state rule would do something to a container
(anything but NOTIFY), and it reaches that container only through groups, at
least one of those groups must be active and allowed that action. A container
the rule names directly, or a rule with no container list, is not gated here -
no group is involved. Watching is never gated: the notice still goes out.

HOW THIS TEST CAN FAIL: a restart through a group that may not restart, or a
rule that stops acting where no group is in the way.

COUNTER-CHECK (2026-09-26): red before the fix - docker_action was called for
Valheim through a group allowed only "status", and through a switched-off one.
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.automation.auto_action_config_service import AutoActionRule
from services.automation.container_watch import WatchEvent

CONTROL = "111111111111111111"
STOPPED = WatchEvent("Valheim", "stopped", "Container 'Valheim' stopped (it was running).")


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    containers = tmp_path / "containers"
    containers.mkdir()
    for name in ("Valheim", "alpha"):
        (containers / f"{name}.json").write_text(json.dumps(
            {"container_name": name, "docker_name": name, "active": True,
             "allowed_actions": ["status", "start", "stop", "restart"]}), encoding="utf-8")

    from services.config import group_service

    group_service.reset_group_service()
    groups = group_service.get_group_service()
    groups.save_group("Gameserver", ["Valheim", "alpha"], active=True,
                      allowed_actions=["status", "start", "stop", "restart"])
    yield SimpleNamespace(groups=groups)
    group_service.reset_group_service()


@pytest.fixture
def engine(monkeypatch):
    from services.automation import automation_service as mod

    service = mod.AutomationService.__new__(mod.AutomationService)
    service.config_service = MagicMock()
    service.config_service.get_global_settings.return_value = {
        "enabled": True, "protected_containers": [], "global_cooldown_seconds": 0}
    service.state_service = MagicMock()
    service.state_service.acquire_execution_locks.return_value = (True, "", None)
    sent = []

    async def _feedback(bot, channel_id, message):
        sent.append(message)

    service._send_feedback = _feedback
    service._trigger_status_refresh = AsyncMock()
    action = AsyncMock(return_value=True)
    monkeypatch.setattr(mod, "docker_action", action)
    return service, sent, action


def _rule(action_type, containers=("group:Gameserver",)):
    return AutoActionRule.from_dict({
        "id": "r1", "name": "Keep the gameservers up", "enabled": True, "priority": 10,
        "trigger": {"type": "container_state", "states": ["stopped"], "containers": list(containers)},
        "action": {"type": action_type, "containers": []},
        "safety": {"cooldown_minutes": 0},
    })


async def _run(service, rule):
    service.config_service.get_rules.return_value = [rule]
    await service.process_container_events([STOPPED], bot=object(), control_channel_id=CONTROL)


@pytest.mark.asyncio
async def test_no_restart_through_a_group_that_may_not(world, engine):
    service, _sent, action = engine
    world.groups.save_group("Gameserver", ["Valheim", "alpha"], allowed_actions=["status"])

    await _run(service, _rule("RESTART"))

    action.assert_not_called()


@pytest.mark.asyncio
async def test_no_restart_through_a_switched_off_group(world, engine):
    service, _sent, action = engine
    world.groups.save_group("Gameserver", ["Valheim", "alpha"], active=False)

    await _run(service, _rule("RESTART"))

    action.assert_not_called()


@pytest.mark.asyncio
async def test_a_group_that_may_restart_still_restarts(world, engine):
    """Counter-case: the gate holds back, it does not switch rules off."""
    service, _sent, action = engine

    await _run(service, _rule("RESTART"))

    action.assert_awaited_once_with("Valheim", "restart")


@pytest.mark.asyncio
async def test_a_container_named_directly_is_not_held_by_its_group(world, engine):
    """No group is involved when the rule names the container itself."""
    service, _sent, action = engine
    world.groups.save_group("Gameserver", ["Valheim", "alpha"], allowed_actions=["status"])

    await _run(service, _rule("RESTART", containers=("group:Gameserver", "Valheim")))

    action.assert_awaited_once_with("Valheim", "restart")


@pytest.mark.asyncio
async def test_watching_is_never_gated(world, engine):
    """A NOTIFY rule reports through a group whatever the group may do."""
    service, sent, action = engine
    world.groups.save_group("Gameserver", ["Valheim", "alpha"], allowed_actions=[])

    await _run(service, _rule("NOTIFY"))

    assert any("Valheim" in message for message in sent), sent
    action.assert_not_called()
