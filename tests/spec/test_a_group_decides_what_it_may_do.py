# -*- coding: utf-8 -*-
"""Wherever a group acts, the GROUP's permissions decide.

THE OPERATOR'S DECISION (2026-09-24), asked because it widens what DDC will
do: a group's own Active and its own four actions apply everywhere a group
acts - the Discord restart menu, a scheduled task, an auto-action rule - and
where they disagree with a member's own settings, the group wins. A container
switched off in DDC, or allowed only to be stopped on its own, is still acted
on through a group that may do more. He was shown that consequence in those
words and chose it.

WHAT WAS MEASURED FIRST (2026-09-24), because the old behaviour was the exact
opposite at every site:

    cogs/stack_restart.py:144   the restart dropped every member that was not
                                active in DDC, and counted it as "missed"
    cogs/stack_restart.py       every group was offered a restart, whatever it
                                was allowed to do - there was nothing to read
    group_tasks.py              a task ran its action on the members without
                                asking the group
    automation_service.py       a rule's "group:<name>" expanded to the members
                                without asking the group

NOTHING AN OPERATOR HAS TODAY BREAKS. A group written before the permissions
existed reads as Active with all four actions
(test_a_group_carries_its_own_permissions.py), so every group that worked
yesterday still works. Only a group whose boxes were cleared on purpose is
held back - and then on purpose.

RECREATE is the one action with no box of its own. A rule may recreate a
container, and the nearest thing the operator ticked is Restart: a recreate is
a restart that comes back on a new image. Requiring two boxes he never
associated with it would block rules that work today. NOTIFY asks for nothing,
because it does nothing to a container.

HOW THIS TEST CAN FAIL: acting on a group the operator switched off, running
an action the group is not allowed, or going back to filtering the members by
their own settings.

COUNTER-CHECK (2026-09-24): red before at all four sites.
"""

import json
from types import SimpleNamespace

import pytest


@pytest.fixture
def world(tmp_path, monkeypatch):
    """Two containers - one active, one switched off in DDC - and a group."""
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    containers = tmp_path / "containers"
    containers.mkdir()
    (containers / "Valheim.json").write_text(json.dumps(
        {"container_name": "Valheim", "docker_name": "Valheim", "active": True,
         "allowed_actions": ["status", "restart"]}), encoding="utf-8")
    # The container the operator's sentence is about: switched off for DDC, and
    # allowed only to be stopped when it is addressed on its own.
    (containers / "alpha.json").write_text(json.dumps(
        {"container_name": "alpha", "docker_name": "alpha", "active": False,
         "allowed_actions": ["stop"]}), encoding="utf-8")

    from services.config import group_service

    group_service.reset_group_service()
    groups = group_service.get_group_service()
    groups.save_group("Gameserver", ["Valheim", "alpha"],
                      active=True, allowed_actions=["status", "start", "stop", "restart"])
    return SimpleNamespace(groups=groups, path=tmp_path)


def _servers(world):
    """What the server configuration says, the way the cogs read it."""
    return [{"docker_name": "Valheim", "active": True, "allowed_actions": ["status", "restart"]},
            {"docker_name": "alpha", "active": False, "allowed_actions": ["stop"]}]


# --- the Discord menu ------------------------------------------------------

def test_a_switched_off_member_is_still_restarted_with_its_group(world, monkeypatch):
    """THE OPERATOR'S CASE. Dropping it was the subordination he rejected."""
    from cogs import admin_overview as ao
    from cogs import stack_restart

    monkeypatch.setattr(ao, "get_server_config_service",
                        lambda: SimpleNamespace(get_all_servers=lambda: _servers(world)))
    monkeypatch.setattr(stack_restart, "current_stacks", dict)
    chosen, missed = stack_restart._servers_of("Gameserver")

    assert [s["docker_name"] for s in chosen] == ["Valheim", "alpha"], (
        "a member that is switched off in DDC was dropped from its group")
    assert missed == []


def test_a_group_that_may_not_restart_is_not_offered(world, monkeypatch):
    from cogs import admin_overview as ao
    from cogs import stack_restart

    world.groups.save_group("Gameserver", ["Valheim", "alpha"],
                            allowed_actions=["status"])
    monkeypatch.setattr(ao, "get_server_config_service",
                        lambda: SimpleNamespace(get_all_servers=lambda: _servers(world)))
    monkeypatch.setattr(stack_restart, "current_stacks", dict)

    assert "Gameserver" not in stack_restart.current_targets(), (
        "a group the operator did not allow to restart is in the restart menu")


def test_a_switched_off_group_is_not_offered(world, monkeypatch):
    from cogs import admin_overview as ao
    from cogs import stack_restart

    world.groups.save_group("Gameserver", ["Valheim", "alpha"], active=False)
    monkeypatch.setattr(ao, "get_server_config_service",
                        lambda: SimpleNamespace(get_all_servers=lambda: _servers(world)))
    monkeypatch.setattr(stack_restart, "current_stacks", dict)

    assert "Gameserver" not in stack_restart.current_targets()


def test_a_group_that_may_restart_is_still_offered(world, monkeypatch):
    """Counter-check: the permission gates, it does not hide everything."""
    from cogs import admin_overview as ao
    from cogs import stack_restart

    monkeypatch.setattr(ao, "get_server_config_service",
                        lambda: SimpleNamespace(get_all_servers=lambda: _servers(world)))
    monkeypatch.setattr(stack_restart, "current_stacks", dict)

    assert "Gameserver" in stack_restart.current_targets()


# --- a scheduled task ------------------------------------------------------

def _task(action):
    return SimpleNamespace(task_id="t1", container_name="Gameserver", action=action,
                           last_run_success=None, last_run_error=None,
                           update_after_execution=lambda: None)


@pytest.mark.asyncio
async def test_a_task_refuses_an_action_the_group_is_not_allowed(world, monkeypatch):
    from services.scheduling import group_tasks

    world.groups.save_group("Gameserver", ["Valheim", "alpha"], allowed_actions=["status"])
    done = _no_side_effects(monkeypatch, group_tasks)
    task = _task("restart")

    assert await group_tasks.execute_group_task(task, 60) is False
    assert "not allowed" in (task.last_run_error or "").lower(), task.last_run_error
    assert done == [], "the task acted on a container it was not allowed to touch"


@pytest.mark.asyncio
async def test_a_task_on_an_allowed_action_runs(world, monkeypatch):
    """Counter-check: the gate is the permission, not the group."""
    from services.scheduling import group_tasks

    done = _no_side_effects(monkeypatch, group_tasks)

    assert await group_tasks.execute_group_task(_task("restart"), 60) is True
    assert done == ["Valheim", "alpha"]


def _no_side_effects(monkeypatch, group_tasks):
    """Run a group task without a docker daemon, a log or a written file."""
    done = []

    async def _act(container, action):
        done.append(container)
        return True

    import services.docker_service.docker_action_service as das
    import services.scheduling.task_writeback as writeback
    import services.scheduling.scheduler as scheduler

    monkeypatch.setattr(das, "docker_action_service_first", _act)
    monkeypatch.setattr(scheduler, "log_user_action", lambda **kwargs: None)

    async def _persist(task):
        return None

    monkeypatch.setattr(writeback, "persist_executed_task_async", _persist)

    async def _timeout(container, action, timeout):
        return timeout

    monkeypatch.setattr(group_tasks, "_timeout_for", _timeout)
    return done


# --- an auto-action rule ---------------------------------------------------

def _rule(action_type):
    return SimpleNamespace(action=SimpleNamespace(type=action_type,
                                                  containers=["group:Gameserver"]))


def test_a_rule_does_not_act_through_a_group_that_may_not(world):
    from services.automation import automation_service

    world.groups.save_group("Gameserver", ["Valheim", "alpha"], allowed_actions=["status"])

    assert automation_service.containers_of_action(_rule("RESTART")) == []


def test_a_rule_acts_through_a_group_that_may(world):
    from services.automation import automation_service

    assert automation_service.containers_of_action(_rule("RESTART")) == ["Valheim", "alpha"]


def test_a_recreate_asks_for_the_restart_box(world):
    """It is a restart that comes back on a new image, and Restart is the box
    the operator associates with it."""
    from services.automation import automation_service

    world.groups.save_group("Gameserver", ["Valheim", "alpha"],
                            allowed_actions=["start", "stop"])

    assert automation_service.containers_of_action(_rule("RECREATE")) == []

    world.groups.save_group("Gameserver", ["Valheim", "alpha"],
                            allowed_actions=["restart"])

    assert automation_service.containers_of_action(_rule("RECREATE")) == ["Valheim", "alpha"]


def test_a_notification_asks_for_nothing(world):
    """NOTIFY does nothing to a container, so there is nothing to permit - and
    a rule that only reports would otherwise go quiet."""
    from services.automation import automation_service

    world.groups.save_group("Gameserver", ["Valheim", "alpha"], allowed_actions=[])

    assert automation_service.containers_of_action(_rule("NOTIFY")) == ["Valheim", "alpha"]


def test_a_switched_off_group_acts_nowhere(world):
    from services.automation import automation_service

    world.groups.save_group("Gameserver", ["Valheim", "alpha"], active=False)

    assert automation_service.containers_of_action(_rule("RESTART")) == []


def test_the_trigger_side_is_not_gated(world):
    """A permission says what may be DONE, not what may be WATCHED. A rule that
    stopped noticing a container because its group may not restart would be a
    rule that silently watches nothing."""
    from services.automation import automation_service

    world.groups.save_group("Gameserver", ["Valheim", "alpha"], allowed_actions=[])
    rule = SimpleNamespace(trigger=SimpleNamespace(containers=["group:Gameserver"]))

    assert automation_service.rule_listens_to(rule, "Valheim") is True
