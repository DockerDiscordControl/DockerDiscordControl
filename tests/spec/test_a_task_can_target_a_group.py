# -*- coding: utf-8 -*-
"""A scheduled task can act on a group, not only on one container.

WHAT THE OPERATOR ASKED FOR (2026-09-23): groups must work everywhere a single
container works. This is the scheduler's half - "every Sunday at 4: restart the
group Gameserver".

What it has to get right, and what each rule costs if it is missing:

* every member gets the action, one after the other, with the half second
  between them that the bulk buttons use - counted by ATTEMPTS, so a daemon
  where every call fails is not hammered (the same bug was fixed twice in the
  buttons);
* a member DDC no longer has is REPORTED and the run is not called a success.
  A group of three that quietly became two would restart two containers and
  write "success" into the task list;
* a group that is gone, or empty, is an error with that reason - not a
  cheerful "done" about nothing;
* one container failing does not stop the others, and the failure is named.

COUNTER-CHECK (2026-09-23): red before - ScheduledTask had no notion of a
group at all.
"""

import asyncio
import json
from types import SimpleNamespace

import pytest

from services.scheduling import scheduler


@pytest.fixture
def world(tmp_path, monkeypatch):
    """Three containers, a group of them, and a record of what was asked of Docker."""
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    containers = tmp_path / "containers"
    containers.mkdir()
    for name in ("Valheim", "Icarus 1", "Enshrouded"):
        (containers / f"{name}.json").write_text(
            json.dumps({"container_name": name, "allowed_actions": ["status", "restart"]}),
            encoding="utf-8")

    from services.config import group_service

    group_service.reset_group_service()
    group_service.get_group_service().save_group(
        "Gameserver", ["Valheim", "Icarus 1", "Enshrouded"])

    asked = []
    sleeps = []

    async def docker_action(name, action):
        asked.append((name, action))
        return world.result_for(name)

    async def sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr("services.docker_service.docker_action_service.docker_action_service_first",
                        docker_action)
    monkeypatch.setattr(scheduler.asyncio, "sleep", sleep)
    monkeypatch.setattr(scheduler, "_persist_executed_task", lambda task: None)
    monkeypatch.setattr(scheduler, "log_user_action", lambda **kwargs: None)

    world = SimpleNamespace(asked=asked, sleeps=sleeps, result_for=lambda name: True,
                            tmp_path=tmp_path)
    return world


def _group_task(group="Gameserver", action="restart"):
    task = scheduler.ScheduledTask(container_name=group, action=action, cycle="daily",
                                   hour=4, minute=0, timezone_str="UTC")
    task.target_is_group = True
    return task


def test_every_member_gets_the_action(world):
    task = _group_task()

    assert asyncio.run(scheduler.execute_task(task)) is True
    assert world.asked == [("Valheim", "restart"), ("Icarus 1", "restart"),
                           ("Enshrouded", "restart")]
    assert task.last_run_success is True


def test_the_members_are_paced_like_a_bulk_button(world):
    asyncio.run(scheduler.execute_task(_group_task()))

    assert [s for s in world.sleeps if s == 0.5] == [0.5, 0.5], (
        f"three containers were asked with {world.sleeps} between them")


def test_a_failing_member_does_not_stop_the_others(world):
    world.result_for = lambda name: name != "Icarus 1"
    task = _group_task()

    assert asyncio.run(scheduler.execute_task(task)) is False
    assert [name for name, _ in world.asked] == ["Valheim", "Icarus 1", "Enshrouded"]
    assert "Icarus 1" in (task.last_run_error or ""), task.last_run_error


def test_a_failing_run_is_paced_too(world):
    """Counter-check: the pause counts attempts, not successes."""
    world.result_for = lambda name: False

    asyncio.run(scheduler.execute_task(_group_task()))

    assert [s for s in world.sleeps if s == 0.5] == [0.5, 0.5]


def test_a_member_that_is_gone_is_not_a_success(world):
    from services.config import group_service

    group_service.get_group_service().save_group(
        "Gameserver", ["Valheim", "Gone"])
    task = _group_task()

    assert asyncio.run(scheduler.execute_task(task)) is False
    assert [name for name, _ in world.asked] == ["Valheim"]
    assert "Gone" in (task.last_run_error or ""), task.last_run_error


def test_a_group_that_no_longer_exists_says_so(world):
    task = _group_task(group="Deleted")

    assert asyncio.run(scheduler.execute_task(task)) is False
    assert world.asked == []
    assert "Deleted" in (task.last_run_error or "")


def test_an_empty_group_is_not_a_success(world):
    from services.config import group_service

    group_service.get_group_service().save_group("Gameserver", [])

    task = _group_task()

    assert asyncio.run(scheduler.execute_task(task)) is False
    assert world.asked == []


def test_a_task_on_one_container_is_untouched(world, monkeypatch):
    """Counter-check: the ordinary task must not go through the group path."""
    task = scheduler.ScheduledTask(container_name="Valheim", action="restart", cycle="daily",
                                   hour=4, minute=0, timezone_str="UTC")

    assert task.target_is_group is False
