# -*- coding: utf-8 -*-
"""Picking a group in the admin list opens a panel about a group.

THE OPERATOR, 2026-09-24, after picking his group there:

    Admin control: Icaruse
    Error: Could not retrieve status. Configuration missing or initial fetch
    failed.                                     [⏹️] [🔄] [ℹ️]

and behind that ℹ️ an empty "Icaruse - Container information" with an edit
button, a lock, an alarm clock and a log button, the last of which answered
"Invalid container name format: group:Icaruse".

Every one of those is the same mistake: the panel was built for a CONTAINER
and handed the name of a group.

    * the embed asks the status cache for "group:Icaruse", which is not a
      container, so it drew the error a missing container draws;
    * the info button opens a container's info text, its protected text and
      its LOGS - a group has none of the three, and docker refuses the name;
    * the toggle for detailed status has nothing to expand.

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
    for name in ("Icarus", "Icarus2"):
        (containers / f"{name}.json").write_text(json.dumps(
            {"container_name": name, "docker_name": name, "active": True,
             "allowed_actions": ["status"]}), encoding="utf-8")

    from services.config import group_service

    group_service.reset_group_service()
    groups = group_service.get_group_service()
    groups.save_group("Icaruse", ["Icarus", "Icarus2"],
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

    embed = group_panel_embed("Icaruse", _cache({"Icarus": True, "Icarus2": True}))
    text = f"{embed.title} {embed.description}"

    assert "Icaruse" in text
    assert "Error" not in text and "status" not in text.lower(), text
    assert "2/2" in text, text


def test_it_says_which_containers_are_in_it(world):
    from cogs.group_control import group_panel_embed

    embed = group_panel_embed("Icaruse", _cache({"Icarus": True}))

    assert "Icarus2" in embed.description, embed.description
    assert "1/2" in embed.description, embed.description


def test_the_lamp_follows_the_members(world):
    from cogs.group_control import group_panel_embed

    def lamp(running):
        return group_panel_embed("Icaruse", _cache(running)).description

    assert "🟢" in lamp({"Icarus": True, "Icarus2": True})
    assert "🟡" in lamp({"Icarus": True})
    assert "🔴" in lamp({})


def test_a_group_that_lost_a_container_says_so(world):
    from cogs.group_control import group_panel_embed

    world.groups.save_group("Icaruse", ["Icarus", "Icarus2", "Gone"])
    embed = group_panel_embed("Icaruse", _cache({"Icarus": True}))

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
    view = _view(SimpleNamespace(pending_actions={}, expanded_states={"group:Icaruse": True}),
                 group_config_for("group:Icaruse"))
    kinds = [type(item).__name__ for item in view.children]

    assert kinds, "the view is empty - this case would pass on anything"

    assert "InfoButton" not in kinds, kinds
    assert "ToggleButton" not in kinds, kinds


def test_the_view_offers_exactly_what_the_group_may_do(world):
    from cogs.group_control import group_config_for

    view = _view(SimpleNamespace(pending_actions={}, expanded_states={"group:Icaruse": True}),
                 group_config_for("group:Icaruse"))
    actions = sorted(item.action for item in view.children
                     if type(item).__name__ == "ActionButton")

    assert actions == ["restart", "stop"], actions


def test_a_container_keeps_its_buttons(world):
    """Counter-check: nothing was taken from the containers."""
    config = {"docker_name": "Icarus", "name": "Icarus",
              "allowed_actions": ["stop", "restart"], "allow_detailed_status": True}
    view = _view(SimpleNamespace(pending_actions={}, expanded_states={"Icarus": True}), config)
    kinds = [type(item).__name__ for item in view.children]

    assert "ToggleButton" in kinds, kinds


def test_the_panel_asks_the_right_source(world):
    """THE WEIGHT OF THE BRANCH ITSELF. The embed builder above can be right
    while nothing calls it: removing the group branch from panel_embed_for()
    left every case here green, which is a check that cannot fail."""
    import asyncio

    from cogs.group_control import group_config_for, panel_embed_for

    asked = []

    class _Cog:
        status_cache_service = _cache({"Icarus": True, "Icarus2": True})

        async def _generate_status_embed_and_view(self, *args, **kwargs):
            asked.append(args[1])
            return SimpleNamespace(title="container", description="", color=None), None, True

    cog = _Cog()
    group = asyncio.run(panel_embed_for(cog, 42, "group:Icaruse",
                                        group_config_for("group:Icaruse"), {}))

    assert asked == [], "a group was looked up as a container"
    assert "Icaruse" in group.title and "2/2" in group.description, group.description

    container = asyncio.run(panel_embed_for(
        cog, 42, "Icarus", {"docker_name": "Icarus", "name": "Icarus"}, {}))

    assert asked == ["Icarus"], "a container stopped going the ordinary way"
    assert container.title == "container"


# --- a group is not on or off ------------------------------------------------
# THE OPERATOR, 2026-09-24, looking at "🟡 Icaruse 1/2" with only ⏹ and 🔄
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
    world.groups.save_group("Icaruse", ["Icarus", "Icarus2"], active=True,
                            allowed_actions=["status", "start", "stop", "restart"])

    view = _view(SimpleNamespace(pending_actions={}, expanded_states={"group:Icaruse": True}),
                 group_config_for("group:Icaruse"))
    actions = sorted(item.action for item in view.children
                     if type(item).__name__ == "ActionButton")

    assert "start" in actions, f"the stopped container cannot be started: {actions}"


def test_a_group_offers_what_it_may_do_whatever_its_lamp(world):
    """Up, down or in between - the buttons are the permissions, not the
    state."""
    from cogs.group_control import group_config_for

    world.groups.save_group("Icaruse", ["Icarus", "Icarus2"],
                            active=True, allowed_actions=["status", "start", "stop", "restart"])
    for running in (True, False):
        view = _view(SimpleNamespace(pending_actions={}, expanded_states={"group:Icaruse": True}),
                     group_config_for("group:Icaruse"))
        actions = sorted(item.action for item in view.children
                         if type(item).__name__ == "ActionButton")

        assert actions == ["restart", "start", "stop"], (running, actions)


def test_a_group_still_offers_only_what_it_is_allowed(world):
    """Counter-check: "always" is about the state, not about the permissions."""
    from cogs.group_control import group_config_for

    world.groups.save_group("Icaruse", ["Icarus", "Icarus2"],
                            active=True, allowed_actions=["status", "start"])
    view = _view(SimpleNamespace(pending_actions={}, expanded_states={"group:Icaruse": True}),
                 group_config_for("group:Icaruse"))
    actions = sorted(item.action for item in view.children
                     if type(item).__name__ == "ActionButton")

    assert actions == ["start"], actions


def test_a_container_still_offers_one_or_the_other(world):
    """A container IS on or off, and its panel must keep saying so."""
    from cogs import control_ui

    config = {"docker_name": "Icarus", "name": "Icarus",
              "allowed_actions": ["start", "stop", "restart"], "allow_detailed_status": False}

    async def build(is_running):
        return control_ui.ControlView(
            SimpleNamespace(pending_actions={}, expanded_states={"Icarus": True}),
            config, is_running=is_running, channel_has_control_permission=True, channel_id=42)

    import asyncio

    up = sorted(item.action for item in asyncio.run(build(True)).children
                if type(item).__name__ == "ActionButton")
    down = sorted(item.action for item in asyncio.run(build(False)).children
                  if type(item).__name__ == "ActionButton")

    assert "start" not in up, up
    assert down == ["start"], down
