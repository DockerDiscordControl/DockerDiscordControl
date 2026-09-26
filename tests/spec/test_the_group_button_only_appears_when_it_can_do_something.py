# -*- coding: utf-8 -*-
"""The group button: narrow, and only there when there is a group.

WHAT THE OPERATOR SAW (screenshot, 2026-09-23): five buttons in the admin
overview's row, and only one of them carrying a text label ("Stack"), which
made the whole row too wide. On top of that the button could do nothing at
all on that server: DDC read a "stack" from com.docker.compose.project, and
0 of the 37 containers there have it.

So the button is an icon now, like restart and stop, and it is only added
when there is something to offer - a group the operator defined, or a Compose
stack DDC found. Installations that DO use Compose keep their stacks; the
button just has two sources instead of one.

COUNTER-CHECK (2026-09-23): red before - the button was always in the row, and
it carried a label.
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import cogs.admin_overview as ao
from cogs import stack_restart
from services.docker_status.models import ContainerStatusResult


@pytest.fixture
def world(tmp_path, monkeypatch):
    """Two containers, no Compose project, and no groups yet."""
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    containers = tmp_path / "containers"
    containers.mkdir()
    for name in ("Valheim", "alpha"):
        (containers / f"{name}.json").write_text(
            json.dumps({"container_name": name, "allowed_actions": ["status", "restart"]}),
            encoding="utf-8")

    from services.config import group_service

    group_service.reset_group_service()
    servers = [{"docker_name": name, "active": True, "allowed_actions": ["restart"]}
               for name in ("Valheim", "alpha")]

    def _entry(name):
        result = ContainerStatusResult.success_result(
            docker_name=name, display_name=name, is_running=True, cpu="1%", ram="1MB",
            uptime="1h", details_allowed=True)
        result.compose_project = None
        return {"data": result}

    monkeypatch.setattr(ao, "get_server_config_service",
                        lambda: SimpleNamespace(get_all_servers=lambda: servers))
    monkeypatch.setattr(ao, "get_status_cache_service",
                        lambda: SimpleNamespace(get=_entry))
    return SimpleNamespace(groups=group_service.get_group_service(), entry=_entry,
                           servers=servers)


def _buttons(view):
    return [item for item in view.children if hasattr(item, "custom_id")]


def _group_button(view):
    return next((b for b in _buttons(view)
                 if "restart_stack" in (b.custom_id or "")), None)


@pytest.mark.asyncio
async def test_without_a_group_or_a_stack_the_button_is_not_there(world):
    view = ao.AdminOverviewView(SimpleNamespace(), 42, has_running_containers=True)

    assert _group_button(view) is None, "a button that can do nothing takes up the row"
    assert len(_buttons(view)) == 4


@pytest.mark.asyncio
async def test_a_group_does_not_bring_it_back(world):
    """REVERSED BY THE OPERATOR (2026-09-24), and rewritten rather than
    deleted so the reversal is readable.

    The button was made conditional because it could do nothing on a server
    with no groups and no Compose stacks. Then a group became a thing that
    behaves like a container: it stands in the overview by name, and it is
    picked and pressed in the admin list beside the containers
    (test_a_group_is_controlled_where_a_container_is.py). A second door to the
    same room, labelled with a filing box, was the clutter he asked to remove.
    """
    world.groups.save_group("Gameserver", ["Valheim", "alpha"])

    view = ao.AdminOverviewView(SimpleNamespace(), 42, has_running_containers=True)

    assert _group_button(view) is None, "the stack button is drawn again"
    assert len(_buttons(view)) == 4


@pytest.mark.asyncio
async def test_a_click_on_an_old_message_is_still_answered(world):
    """What `every_button` is for: a message posted before today still carries
    that button, and py-cord answers a click only for the custom_ids it was
    registered with."""
    view = ao.AdminOverviewView(SimpleNamespace(), 42, has_running_containers=True,
                                every_button=True)

    button = _group_button(view)

    assert button is not None, "a click on yesterday's overview answers nothing"
    assert not button.label, f"the button widens the row with the text {button.label!r}"
    assert button.emoji is not None


@pytest.mark.asyncio
async def test_a_compose_stack_does_not_bring_it_either(world, monkeypatch):
    """Compose stacks were the other half of what the button offered. They are
    still found - the panel sorts the container table by them - but they are
    not worth a button of their own: measured on the operator's server, 0 of
    26 containers carry the label."""
    def _with_project(name):
        entry = world.entry(name)
        entry["data"].compose_project = "blog"
        return entry

    monkeypatch.setattr(ao, "get_status_cache_service",
                        lambda: SimpleNamespace(get=_with_project))

    view = ao.AdminOverviewView(SimpleNamespace(), 42, has_running_containers=True)

    assert _group_button(view) is None


def test_the_menu_offers_groups_and_stacks(world, monkeypatch):
    world.groups.save_group("Gameserver", ["Valheim", "alpha"])

    def _with_project(name):
        entry = world.entry(name)
        entry["data"].compose_project = "blog" if name == "alpha" else None
        return entry

    monkeypatch.setattr(ao, "get_status_cache_service",
                        lambda: SimpleNamespace(get=_with_project))

    targets = stack_restart.current_targets()

    assert "Gameserver" in targets, "the operator's own group is not offered"
    assert "blog" in targets, "a Compose stack is not offered any more"
    assert [name for name in targets["Gameserver"]] == ["Valheim", "alpha"]


def test_a_group_member_that_is_gone_is_not_offered_as_present(world):
    """A group can name containers DDC no longer has; the menu must not lie."""
    world.groups.save_group("Gameserver", ["Valheim", "Deleted"])

    assert stack_restart.current_targets()["Gameserver"] == ["Valheim"]


@pytest.mark.asyncio
async def test_confirming_a_group_restarts_its_containers(world, monkeypatch):
    """The confirm button looked up Compose stacks only.

    COUNTER-CHECK (2026-09-23): red before - a chosen GROUP was not in
    current_stacks(), so the admin was told "the stack has no active containers
    any more" and nothing was restarted. The menu offered something the confirm
    could not carry out.
    """
    world.groups.save_group("Gameserver", ["Valheim", "alpha"])
    restarted = []

    async def docker_action(name, action):
        restarted.append((name, action))
        return True

    monkeypatch.setattr("services.docker_service.docker_action_service.docker_action_service_first",
                        docker_action)
    monkeypatch.setattr(ao.asyncio, "sleep", AsyncMock())

    cog = SimpleNamespace(_bulk_operation_in_progress=False,
                          bot=SimpleNamespace(get_channel=lambda cid: None))
    monkeypatch.setattr(ao, "get_admin_service",
                        lambda: SimpleNamespace(is_user_admin_async=AsyncMock(return_value=True)))

    interaction = SimpleNamespace(
        response=SimpleNamespace(defer=AsyncMock()),
        followup=SimpleNamespace(send=AsyncMock()),
        user=SimpleNamespace(id=7),
        channel=SimpleNamespace(id=42))

    button = stack_restart.ConfirmRestartStackButton(cog, 42, "Gameserver")
    await button.callback(interaction)

    assert [name for name, _action in restarted] == ["Valheim", "alpha"], (
        f"the group was not restarted: {restarted}")
    assert cog._bulk_operation_in_progress is False, "the bulk lock stayed held"
