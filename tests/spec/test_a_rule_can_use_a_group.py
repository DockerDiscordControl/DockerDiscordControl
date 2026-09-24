# -*- coding: utf-8 -*-
"""An auto-action rule can name a group, as a filter and as a target.

WHAT THE OPERATOR ASKED FOR (2026-09-23): groups must work everywhere. In the
auto-action system that means two different things, and both are needed:

* as a FILTER - "for every container of the group Gameserver: if it stops,
  restart IT". The rule listens to the members; what it acts on is the one
  container the event was about;
* as a TARGET - "if the database dies, restart the group Gameserver". The
  action hits every member.

A group is written as "group:<name>" wherever a container name may stand. A
Docker container name cannot contain a colon, so nothing existing is ambiguous.

The dangerous case, and the reason this file exists at all: an empty trigger
list means EVERY container. A group that was deleted must therefore never
resolve to "nothing", or a rule written for five containers would quietly
start firing on all thirty-seven.

COUNTER-CHECK (2026-09-23): red before - "group:Gameserver" was compared with
the event's container name and never matched, so a group rule did nothing.
"""

import json
from types import SimpleNamespace

import pytest

from services.automation.auto_action_config_service import AutoActionRule


@pytest.fixture
def groups(tmp_path, monkeypatch):
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    containers = tmp_path / "containers"
    containers.mkdir()
    for name in ("Valheim", "alpha", "AdGuard-Home"):
        (containers / f"{name}.json").write_text(
            json.dumps({"container_name": name, "allowed_actions": ["status", "restart"]}),
            encoding="utf-8")

    from services.config import group_service

    group_service.reset_group_service()
    service = group_service.get_group_service()
    service.save_group("Gameserver", ["Valheim", "alpha"])
    return service


def _rule(trigger_containers=(), action_containers=()):
    return AutoActionRule.from_dict({
        "id": "r1", "name": "watch", "enabled": True,
        "trigger": {"type": "container_state", "states": ["stopped"],
                    "containers": list(trigger_containers), "channel_ids": [], "keywords": []},
        "action": {"type": "RESTART", "containers": list(action_containers)},
    })


def test_a_group_as_a_filter_matches_its_members(groups):
    from services.automation.automation_service import rule_listens_to

    rule = _rule(trigger_containers=["group:Gameserver"])

    assert rule_listens_to(rule, "Valheim") is True
    assert rule_listens_to(rule, "alpha") is True
    assert rule_listens_to(rule, "AdGuard-Home") is False


def test_a_rule_without_a_filter_still_listens_to_everything(groups):
    """Counter-check: the existing meaning of an empty list is untouched."""
    from services.automation.automation_service import rule_listens_to

    assert rule_listens_to(_rule(), "anything at all") is True


def test_a_deleted_group_does_not_become_everything(groups):
    """THE dangerous case: a rule for five containers must not become a rule for all."""
    from services.automation.automation_service import rule_listens_to

    rule = _rule(trigger_containers=["group:Gone"])

    assert rule_listens_to(rule, "Valheim") is False, (
        "a rule whose group disappeared now fires on every container")
    assert rule_listens_to(rule, "AdGuard-Home") is False


def test_a_group_as_a_target_resolves_to_its_members(groups):
    from services.automation.automation_service import containers_of_action

    assert containers_of_action(_rule(action_containers=["group:Gameserver"])) == [
        "Valheim", "alpha"]


def test_a_target_group_that_is_gone_is_empty_not_everything(groups):
    from services.automation.automation_service import containers_of_action

    assert containers_of_action(_rule(action_containers=["group:Gone"])) == []


def test_containers_and_groups_can_be_mixed(groups):
    from services.automation.automation_service import containers_of_action, rule_listens_to

    rule = _rule(trigger_containers=["group:Gameserver", "AdGuard-Home"],
                 action_containers=["group:Gameserver", "AdGuard-Home"])

    assert rule_listens_to(rule, "AdGuard-Home") is True
    assert rule_listens_to(rule, "Valheim") is True
    assert containers_of_action(rule) == ["Valheim", "alpha", "AdGuard-Home"]


def test_a_member_named_twice_is_acted_on_once(groups):
    """Counter-check: a container in the group AND named directly."""
    from services.automation.automation_service import containers_of_action

    rule = _rule(action_containers=["group:Gameserver", "Valheim"])

    assert containers_of_action(rule) == ["Valheim", "alpha"]


async def _true():
    return True


async def _false():
    return False


@pytest.mark.asyncio
async def test_the_action_really_acts_on_the_whole_group(groups, monkeypatch):
    """Resolving is worth nothing if the execution still reads the raw list.

    COUNTER-CHECK (2026-09-23): red before - _execute_rule read
    rule.action.containers, so a rule targeting "group:Gameserver" asked Docker
    to restart a container of that name, which does not exist.
    """
    from services.automation import automation_service as module

    asked = []

    async def docker_action(name, action):
        asked.append((name, action))
        return True, ""

    monkeypatch.setattr(module, "is_container_exists", lambda name: _true())
    monkeypatch.setattr(module, "docker_action", docker_action)

    service = module.AutomationService()
    service._honours_only_if_running = lambda *a, **k: _false()
    service.state_service = SimpleNamespace(
        record_trigger=lambda *a, **k: None,
        acquire_execution_locks=lambda *a, **k: (True, "", None),
        release_execution_lock=lambda *a, **k: None,
        release_execution_locks=lambda *a, **k: None,
        release_rule_cooldown=lambda *a, **k: None)

    await service._execute_rule(_rule(action_containers=["group:Gameserver"]),
                                SimpleNamespace(message=None, channel_id=None),
                                {"protected_containers": []}, bot=None)

    assert [name for name, _action in asked] == ["Valheim", "alpha"], (
        f"the action did not reach the group's containers: {asked}")


@pytest.mark.asyncio
async def test_a_protected_member_still_stops_the_action(groups, monkeypatch):
    """Counter-check: resolving a group must not step around the protection."""
    from services.automation import automation_service as module

    asked = []

    async def docker_action(name, action):
        asked.append((name, action))
        return True, ""

    monkeypatch.setattr(module, "is_container_exists", lambda name: _true())
    monkeypatch.setattr(module, "docker_action", docker_action)

    service = module.AutomationService()
    service._honours_only_if_running = lambda *a, **k: _false()
    service.state_service = SimpleNamespace(
        record_trigger=lambda *a, **k: None,
        acquire_execution_locks=lambda *a, **k: (True, "", None),
        release_execution_lock=lambda *a, **k: None,
        release_execution_locks=lambda *a, **k: None,
        release_rule_cooldown=lambda *a, **k: None)

    done = await service._execute_rule(_rule(action_containers=["group:Gameserver"]),
                                       SimpleNamespace(message=None, channel_id=None),
                                       {"protected_containers": ["valheim"]}, bot=None)

    assert done is False
    assert asked == [], "a protected container inside a group was acted on"
