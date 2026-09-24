# -*- coding: utf-8 -*-
"""Acting on a group is one call, and there is one place that knows how.

THE OPERATOR, 2026-09-24: a group behaves like ONE container, only with
several behind it. Everything that acts on a container in DDC calls
docker_action_service_first(name, action) - the buttons under a status
message, the admin overview, a rule, a task. So that is where a group has to
be a name like any other: `group:Icaruse`, the same spelling the auto-action
rules already use for their targets.

WHY IT IS ONE PLACE AND NOT TWO. services/scheduling/group_tasks.py already
held this loop: resolve the group, act on each member half a second apart,
report a partial run as a failure. Writing a second copy in the action service
would be the defect I spent the night finding elsewhere - two code paths
answering the same question, drifting apart until a group restarted from a
button behaves differently from the same group restarted by a task. The loop
moved into services/docker_service/group_actions.py, and both callers ask it.

WHAT THE GROUP DECIDES, unchanged and now in one place: a group that is
switched off does nothing, and neither does one the operator did not allow
that action. A member DDC has no configuration for is reported, not silently
dropped, because acting on four of seven and calling it done is what this
whole feature forbids.

THE PER-MEMBER TIMEOUT stays with the caller that needs it. A scheduled stop
gives each container StopTimeout + margin (a database with StopTimeout=120 was
logged as failed every night while the stop was still running); a button press
uses the plain timeout. The hook is an argument, so neither behaviour is lost
in the move.

HOW THIS TEST CAN FAIL: a group target that acts on nobody, one that ignores
the group's permissions, a partial run reported as success, or a second copy
of the loop appearing somewhere.

COUNTER-CHECK (2026-09-24): red before - `group:` was just a container name
nobody has, and docker_action_service_first returned False for it.
"""

import ast
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def world(tmp_path, monkeypatch):
    """Two configured containers and a group that holds both."""
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    containers = tmp_path / "containers"
    containers.mkdir()
    for name in ("Icarus", "Icarus2"):
        (containers / f"{name}.json").write_text(json.dumps(
            {"container_name": name, "docker_name": name, "active": True,
             "allowed_actions": ["status"]}), encoding="utf-8")

    from services.config import group_service

    group_service.reset_group_service()
    groups = group_service.get_group_service()
    groups.save_group("Icaruse", ["Icarus", "Icarus2"],
                      active=True, allowed_actions=["status", "start", "stop", "restart"])
    return SimpleNamespace(groups=groups)


@pytest.fixture
def acted(monkeypatch):
    """Records what the action service was asked to do, and answers True."""
    done = []

    async def _act(container, action):
        done.append((container, action))
        return True

    import services.docker_service.group_actions as group_actions

    monkeypatch.setattr(group_actions, "_act_on_one", _act)
    # The pacing, not asyncio.sleep: group_actions.asyncio IS the asyncio
    # module, and replacing its sleep with something that calls asyncio.sleep
    # replaced that function with itself - the first run of this fixture hit
    # the recursion limit.
    monkeypatch.setattr(group_actions, "PACE_SECONDS", 0)
    return done


def _run(coroutine):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coroutine)


def test_a_group_name_acts_on_every_member(world, acted):
    """THE POINT: one name, one call, every member."""
    from services.docker_service.docker_action_service import docker_action_service_first

    assert _run(docker_action_service_first("group:Icaruse", "restart")) is True
    assert acted == [("Icarus", "restart"), ("Icarus2", "restart")]


def test_a_container_is_still_a_container(world, acted):
    """Counter-check: the prefix is the only thing that makes a group."""
    from services.docker_service import docker_action_service as service

    calls = []

    class _Service:
        async def execute_docker_action(self, request):
            calls.append((request.container_name, request.action))
            return SimpleNamespace(success=True)

    import services.docker_service.docker_action_service as module
    original = module.get_docker_action_service
    module.get_docker_action_service = lambda: _Service()
    try:
        assert _run(service.docker_action_service_first("Icarus", "restart")) is True
    finally:
        module.get_docker_action_service = original

    assert calls == [("Icarus", "restart")]
    assert acted == [], "a plain container name went through the group path"


def test_a_group_that_may_not_do_it_does_nothing(world, acted):
    from services.docker_service.docker_action_service import docker_action_service_first

    world.groups.save_group("Icaruse", ["Icarus", "Icarus2"], allowed_actions=["status"])

    assert _run(docker_action_service_first("group:Icaruse", "restart")) is False
    assert acted == [], "it acted on a group that may not"


def test_a_switched_off_group_does_nothing(world, acted):
    from services.docker_service.docker_action_service import docker_action_service_first

    world.groups.save_group("Icaruse", ["Icarus", "Icarus2"], active=False)

    assert _run(docker_action_service_first("group:Icaruse", "restart")) is False
    assert acted == []


def test_a_group_that_does_not_exist_is_not_a_success(world, acted):
    from services.docker_service.docker_action_service import docker_action_service_first

    assert _run(docker_action_service_first("group:Nothing", "restart")) is False
    assert acted == []


def test_a_member_that_fails_makes_the_whole_run_a_failure(world, monkeypatch):
    """Acting on one of two and reporting success is what this feature
    forbids."""
    import services.docker_service.group_actions as group_actions

    async def _act(container, action):
        return container != "Icarus2"

    monkeypatch.setattr(group_actions, "_act_on_one", _act)
    monkeypatch.setattr(group_actions, "PACE_SECONDS", 0)
    from services.docker_service.docker_action_service import docker_action_service_first

    assert _run(docker_action_service_first("group:Icaruse", "restart")) is False


def test_a_missing_member_is_reported_not_dropped(world, acted):
    """The outcome names what it could not reach, so a caller can say so."""
    from services.docker_service.group_actions import act_on_group

    world.groups.save_group("Icaruse", ["Icarus", "Icarus2", "Gone"])
    outcome = _run(act_on_group("Icaruse", "restart"))

    assert outcome.missing == ["Gone"]
    assert outcome.success is False, "a group acting on two of three is not a success"


def test_there_is_only_one_loop(world):
    """THE REASON IT MOVED: a second copy drifts, and then a group restarted
    from a button behaves differently from the same group in a task."""
    tasks = (ROOT / "services" / "scheduling" / "group_tasks.py").read_text(encoding="utf-8")
    tree = ast.parse(tasks)
    calls = [ast.unparse(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)]

    assert any("act_on_group" in call for call in calls), (
        "the scheduled task still walks the members itself")
    assert "docker_action_service_first(container" not in tasks, (
        "the scheduled task still acts on the members one by one")
