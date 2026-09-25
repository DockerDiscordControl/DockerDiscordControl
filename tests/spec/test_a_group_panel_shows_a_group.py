# -*- coding: utf-8 -*-
"""Picking a group in the admin list opens a panel about a group.

THE OPERATOR, 2026-09-24, after picking his group there:

    Admin control: Gameserver
    Error: Could not retrieve status. Configuration missing or initial fetch
    failed.                                     [⏹️] [🔄] [ℹ️]

and behind that ℹ️ an empty "Gameserver - Container information" with an edit
button, a lock, an alarm clock and a log button, the last of which answered
"Invalid container name format: group:Gameserver".

Every one of those is the same mistake: the panel was built for a CONTAINER
and handed the name of a group.

    * the embed asks the status cache for "group:Gameserver", which is not a
      container, so it drew the error a missing container draws;
    * the info button opens a container's info text, its protected text and
      its LOGS - a group has none of the three, and docker refuses the name;
    * detailed status has nothing to show.

WHAT A GROUP'S PANEL SAYS instead is what its line in the overview says, with
room: the lamp, how many of its containers are running, and which they are.
And its buttons are the actions the GROUP is allowed - nothing else.

HOW THIS TEST CAN FAIL: a group panel that reports a container's status, or
that offers a button no group can answer.

COUNTER-CHECK (2026-09-24): red before - there was no group panel at all, and
the info button was added to every view.
"""

import json
from types import SimpleNamespace

import pytest


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    containers = tmp_path / "containers"
    containers.mkdir()
    for name in ("alpha", "beta"):
        (containers / f"{name}.json").write_text(json.dumps(
            {"container_name": name, "docker_name": name, "active": True,
             "allowed_actions": ["status"]}), encoding="utf-8")

    from services.config import group_service

    group_service.reset_group_service()
    groups = group_service.get_group_service()
    groups.save_group("Gameserver", ["alpha", "beta"],
                      active=True, allowed_actions=["status", "stop", "restart"])
    return SimpleNamespace(groups=groups)


def _cache(running):
    from services.docker_status.models import ContainerStatusResult

    def get(name):
        if name not in running:
            return None
        return {"data": ContainerStatusResult.success_result(
            docker_name=name, display_name=name, is_running=running[name],
            cpu="1%", ram="1MB", uptime="1h", details_allowed=True)}

    return SimpleNamespace(get=get)


def test_the_panel_reports_the_group_not_a_missing_container(world):
    """THE COMPLAINT: "Error: Could not retrieve status"."""
    from cogs.group_control import group_panel_embed

    embed = group_panel_embed("Gameserver", _cache({"alpha": True, "beta": True}))
    text = f"{embed.title} {embed.description}"

    assert "Gameserver" in text
    assert "Error" not in text and "status" not in text.lower(), text
    assert "2/2" in text, text


def test_it_says_which_containers_are_in_it(world):
    from cogs.group_control import group_panel_embed

    embed = group_panel_embed("Gameserver", _cache({"alpha": True}))

    assert "beta" in embed.description, embed.description
    assert "1/2" in embed.description, embed.description


def test_the_lamp_follows_the_members(world):
    from cogs.group_control import group_panel_embed

    def lamp(running):
        return group_panel_embed("Gameserver", _cache(running)).description

    assert "🟢" in lamp({"alpha": True, "beta": True})
    assert "🟡" in lamp({"alpha": True})
    assert "🔴" in lamp({})


def test_a_group_that_lost_a_container_says_so(world):
    from cogs.group_control import group_panel_embed

    world.groups.save_group("Gameserver", ["alpha", "beta", "Gone"])
    embed = group_panel_embed("Gameserver", _cache({"alpha": True}))

    assert "Gone" in embed.description, embed.description


def test_a_group_that_vanished_is_said_plainly(world):
    """Counter-check: the one case where an error IS the answer."""
    from cogs.group_control import group_panel_embed

    embed = group_panel_embed("Nothing", _cache({}))

    assert embed is not None
    assert "Nothing" in f"{embed.title} {embed.description}"


def _view(cog, config):
    """A discord.ui.View wants a running loop at construction."""
    import asyncio

    from cogs import control_ui

    async def build():
        return control_ui.ControlView(cog, config, is_running=True,
                                      channel_has_control_permission=True, channel_id=42)

    return asyncio.run(build())


def test_the_view_offers_no_container_buttons(world):
    """The info button opens a container's info, its protected text and its
    LOGS - a group has none of the three, and docker refuses its name."""
    from cogs.group_control import group_config_for

    # EXPANDED, or the view adds nothing at all and this case could not fail.
    view = _view(SimpleNamespace(pending_actions={}, expanded_states={"group:Gameserver": True}),
                 group_config_for("group:Gameserver"))
    kinds = [type(item).__name__ for item in view.children]

    assert kinds, "the view is empty - this case would pass on anything"

    assert "InfoButton" not in kinds, kinds


def test_the_view_offers_exactly_what_the_group_may_do(world):
    from cogs.group_control import group_config_for

    view = _view(SimpleNamespace(pending_actions={}, expanded_states={"group:Gameserver": True}),
                 group_config_for("group:Gameserver"))
    actions = sorted(item.action for item in view.children
                     if type(item).__name__ == "ActionButton")

    assert actions == ["restart", "stop"], actions


def test_a_container_keeps_its_buttons(world):
    """Counter-check: nothing was taken from the containers.

    It used to ask for the expand button, which no caller could produce and
    which was removed on 2026-09-25. The info button is the thing a container
    still has and a group does not, so the case asks for that instead."""
    config = {"docker_name": "alpha", "name": "alpha",
              "allowed_actions": ["stop", "restart"], "allow_detailed_status": True}
    view = _view(SimpleNamespace(pending_actions={}, expanded_states={"alpha": True}), config)
    kinds = [type(item).__name__ for item in view.children]

    assert "InfoButton" in kinds, kinds


def test_the_panel_asks_the_right_source(world):
    """THE WEIGHT OF THE BRANCH ITSELF. The embed builder above can be right
    while nothing calls it: removing the group branch from panel_embed_for()
    left every case here green, which is a check that cannot fail."""
    import asyncio

    from cogs.group_control import admin_panel_embed, group_config_for

    asked = []

    class _Cog:
        status_cache_service = _cache({"alpha": True, "beta": True})

        async def _generate_status_embed_and_view(self, *args, **kwargs):
            asked.append(args[1])
            import discord

            return discord.Embed(title="container", description=""), None, True

        async def get_status(self, config):
            return SimpleNamespace(success=True, is_running=True)

    cog = _Cog()
    group = asyncio.run(admin_panel_embed(cog, 42, "group:Gameserver",
                                          group_config_for("group:Gameserver"), {}, "Gameserver"))

    assert asked == [], "a group was looked up as a container"
    assert "Gameserver" in group.title and "2/2" in group.description, group.description

    container = asyncio.run(admin_panel_embed(
        cog, 42, "alpha", {"docker_name": "alpha", "name": "alpha"}, {}, "alpha"))

    assert asked == ["alpha"], "a container stopped going the ordinary way"
    assert "alpha" in container.title


# --- a group is not on or off ------------------------------------------------
# THE OPERATOR, 2026-09-24, looking at "🟡 Gameserver 1/2" with only ⏹ and 🔄
# under it: he still has to be able to start the one that is down.
#
# That was my own rule, and it was a container's rule. A container is either
# up or down, so its panel offers stop-and-restart OR start. A group has a
# COUNT, and at 1/2 every one of the three does something: start the stopped
# one, stop the running one, restart what is up. So a group offers everything
# it is allowed, always, and the lamp says what state it is in.

def test_a_half_running_group_can_still_be_started(world):
    from cogs.group_control import group_config_for

    # His own group may do all four; the fixture above withholds start, which
    # would have made this case pass for the wrong reason.
    world.groups.save_group("Gameserver", ["alpha", "beta"], active=True,
                            allowed_actions=["status", "start", "stop", "restart"])

    view = _view(SimpleNamespace(pending_actions={}, expanded_states={"group:Gameserver": True}),
                 group_config_for("group:Gameserver"))
    actions = sorted(item.action for item in view.children
                     if type(item).__name__ == "ActionButton")

    assert "start" in actions, f"the stopped container cannot be started: {actions}"


def test_a_group_offers_what_it_may_do_whatever_its_lamp(world):
    """Up, down or in between - the buttons are the permissions, not the
    state."""
    from cogs.group_control import group_config_for

    world.groups.save_group("Gameserver", ["alpha", "beta"],
                            active=True, allowed_actions=["status", "start", "stop", "restart"])
    for running in (True, False):
        view = _view(SimpleNamespace(pending_actions={}, expanded_states={"group:Gameserver": True}),
                     group_config_for("group:Gameserver"))
        actions = sorted(item.action for item in view.children
                         if type(item).__name__ == "ActionButton")

        assert actions == ["restart", "start", "stop"], (running, actions)


def test_a_group_still_offers_only_what_it_is_allowed(world):
    """Counter-check: "always" is about the state, not about the permissions."""
    from cogs.group_control import group_config_for

    world.groups.save_group("Gameserver", ["alpha", "beta"],
                            active=True, allowed_actions=["status", "start"])
    view = _view(SimpleNamespace(pending_actions={}, expanded_states={"group:Gameserver": True}),
                 group_config_for("group:Gameserver"))
    actions = sorted(item.action for item in view.children
                     if type(item).__name__ == "ActionButton")

    assert actions == ["start"], actions


def test_a_container_still_offers_one_or_the_other(world):
    """A container IS on or off, and its panel must keep saying so."""
    from cogs import control_ui

    config = {"docker_name": "alpha", "name": "alpha",
              "allowed_actions": ["start", "stop", "restart"], "allow_detailed_status": False}

    async def build(is_running):
        return control_ui.ControlView(
            SimpleNamespace(pending_actions={}, expanded_states={"alpha": True}),
            config, is_running=is_running, channel_has_control_permission=True, channel_id=42)

    import asyncio

    up = sorted(item.action for item in asyncio.run(build(True)).children
                if type(item).__name__ == "ActionButton")
    down = sorted(item.action for item in asyncio.run(build(False)).children
                  if type(item).__name__ == "ActionButton")

    assert "start" not in up, up
    assert down == ["start"], down


# --- and again after a press -------------------------------------------------
# THE OPERATOR, 2026-09-24: he pressed ▶️ on his half-running group, the
# container came up - the overview said 2/2 - and the panel redrew itself as
#
#     ⚠️ Gameserver
#     Error: Could not retrieve status. Configuration missing or initial fetch
#     failed.
#
# The panel is built in TWO places: when a target is picked, and again after a
# button was pressed. The first one had learned about groups; the second had
# not. One builder now, asked by both, or a third place will make the same
# mistake a third time.

def test_the_refresh_after_a_press_builds_the_same_panel(world):
    import asyncio

    from cogs.group_control import admin_panel_embed, group_config_for

    class _Cog:
        status_cache_service = _cache({"alpha": True, "beta": True})

        async def _generate_status_embed_and_view(self, *args, **kwargs):
            raise AssertionError("a group was looked up as a container")

    embed = asyncio.run(admin_panel_embed(
        _Cog(), 42, "group:Gameserver", group_config_for("group:Gameserver"), {}, "Gameserver"))

    assert "Gameserver" in embed.title and "📁" in embed.title, embed.title
    assert "Admin" not in embed.title, embed.title
    assert "2/2" in embed.description, embed.description


def test_a_container_still_gets_its_admin_header(world):
    """Counter-check: the header and the colour a container's panel has."""
    import asyncio

    import discord

    from cogs.group_control import admin_panel_embed

    class _Cog:
        status_cache_service = _cache({"alpha": True})

        async def _generate_status_embed_and_view(self, *args, **kwargs):
            return discord.Embed(title="raw", description="x"), None, True

        async def get_status(self, config):
            return SimpleNamespace(success=True, is_running=True)

    embed = asyncio.run(admin_panel_embed(
        _Cog(), 42, "alpha", {"docker_name": "alpha", "name": "alpha"}, {}, "alpha"))

    assert "alpha" in embed.title, embed.title
    assert embed.color == discord.Color.green(), embed.color


def test_both_places_ask_the_one_builder():
    """Structural: the picking path and the after-a-press path."""
    import ast
    from pathlib import Path

    source = (Path(__file__).resolve().parents[2] / "cogs" / "control_ui.py").read_text(
        encoding="utf-8")
    calls = [ast.unparse(node.func) for node in ast.walk(ast.parse(source))
             if isinstance(node, ast.Call)]

    assert calls.count("admin_panel_embed") == 2, (
        f"the admin panel is built {calls.count('admin_panel_embed')} times from the "
        f"one builder; there are two places that build it")
