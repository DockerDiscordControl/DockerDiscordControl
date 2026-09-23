# -*- coding: utf-8 -*-
"""A group and a Compose stack of the same name do not swallow each other.

TWO SMALLER FINDINGS from the review (2026-09-23), both in the one menu that
offers groups and stacks together:

* the merge is `setdefault`, so a group called "blog" and a Compose project
  called "blog" collapse into one entry. The group wins and the stack
  disappears - with no hint that the button now restarts something else than
  it did yesterday;
* the menu holds 25 options. Groups are added first, so 25 groups push every
  stack out of it, while the notice speaks of "stacks" and the count is of the
  merged list.

The entry says which kind it is when both exist, and the notice counts what it
actually left out.

COUNTER-CHECK (2026-09-23): red before - one entry for two things, and a
notice that named the wrong thing.
"""

import json
from types import SimpleNamespace

import pytest

import cogs.admin_overview as ao
from cogs import stack_restart
from services.docker_status.models import ContainerStatusResult


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A group called "blog" and a Compose project called "blog"."""
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    containers = tmp_path / "containers"
    containers.mkdir()
    for name in ("web", "db"):
        (containers / f"{name}.json").write_text(
            json.dumps({"container_name": name, "allowed_actions": ["status", "restart"]}),
            encoding="utf-8")

    from services.config import group_service

    group_service.reset_group_service()
    group_service.get_group_service().save_group("blog", ["web"])

    servers = [{"docker_name": "web", "active": True, "allowed_actions": ["restart"]},
               {"docker_name": "db", "active": True, "allowed_actions": ["restart"]}]

    def _entry(name):
        result = ContainerStatusResult.success_result(
            docker_name=name, display_name=name, is_running=True, cpu="1%", ram="1MB",
            uptime="1h", details_allowed=True)
        result.compose_project = "blog"
        return {"data": result}

    monkeypatch.setattr(ao, "get_server_config_service",
                        lambda: SimpleNamespace(get_all_servers=lambda: servers))
    monkeypatch.setattr(ao, "get_status_cache_service", lambda: SimpleNamespace(get=_entry))
    return group_service.get_group_service()


def test_both_are_offered(world):
    targets = stack_restart.current_targets()

    assert len(targets) == 2, (
        f"a group and a stack of the same name became one entry: {targets}")
    names = list(targets)
    assert any("blog" in name for name in names)


def test_the_group_and_the_stack_keep_their_own_members(world):
    targets = stack_restart.current_targets()
    members = sorted(sorted(containers) for containers in targets.values())

    assert members == [["db", "web"], ["web"]], members


def test_a_name_that_exists_only_once_is_not_decorated(world):
    """Counter-check: the extra word appears only where it is needed."""
    world.save_group("Gameserver", ["web"])

    targets = stack_restart.current_targets()

    assert "Gameserver" in targets, f"an unambiguous group was renamed: {list(targets)}"


@pytest.mark.asyncio
async def test_restarting_the_decorated_group_still_finds_it(world, monkeypatch):
    """The menu entry says "(group)"; the group is called what the operator called it.

    COUNTER-CHECK: red before - the confirm button looked up "blog (group)" as
    a group name, found nothing, and the members came from the merged menu -
    which works, but loses the report about members DDC no longer has.
    """
    from unittest.mock import AsyncMock

    world.save_group("blog", ["web", "Gone"])
    monkeypatch.setattr(ao.asyncio, "sleep", AsyncMock())

    servers, missing = stack_restart._servers_of(
        stack_restart._("{name} (group)").format(name="blog"))

    assert [s["docker_name"] for s in servers] == ["web"]
    assert missing == ["Gone"], f"the missing member was not reported: {missing}"
