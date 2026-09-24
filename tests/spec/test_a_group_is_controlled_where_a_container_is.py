# -*- coding: utf-8 -*-
"""A group is picked and pressed in the same place a container is.

THE OPERATOR, 2026-09-24: remove the stack button, and show the group - a
group behaves like ONE container, only with several behind it.

Those two sentences belong together. The stack button (🗂️) opened a menu of
"groups and Compose stacks", which was the only way to act on a group from
Discord. Taking it away without giving the group a place would leave a group
that can be SEEN in the overview and touched nowhere. So the group moves to
where a container is already controlled: the admin button's list. One menu,
containers and groups in it, and the same buttons behind either.

WHAT MAKES THAT POSSIBLE is the seam built an hour earlier: every action goes
through docker_action_service_first(name, action), and `group:Icaruse` is a
name it understands (test_a_group_is_one_target_for_an_action.py). So a group
entry needs no new button, no new action path - only a configuration shaped
like a container's, with the GROUP's own permissions in it.

A GROUP'S "IS IT RUNNING" is its members': running when ANY of them is. The
buttons a container offers depend on it - stop for a running one, start for a
stopped one - and a group of two with one up gets both, which is right: either
press does something. Requiring all of them would hide the stop button on a
half-started group, which is the moment an operator most wants it.

THE STACK BUTTON GOES with the menu it opened. What it could do, the admin
list can do, for groups; Compose stacks are still found by the panel's sort
button, and on the operator's own server 0 of 26 containers carry that label.

HOW THIS TEST CAN FAIL: a group missing from the list, a group offered with a
container's permissions instead of its own, or the stack button coming back.

COUNTER-CHECK (2026-09-24): red before - the list held containers only, and
the row still carried the stack button.
"""

import ast
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
OVERVIEW = ROOT / "cogs" / "admin_overview.py"


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
                      active=True, allowed_actions=["status", "restart"])
    return SimpleNamespace(groups=groups)


def _entries():
    from cogs import group_control

    return group_control.group_entries()


def test_the_list_offers_the_groups(world):
    """THE POINT: one menu, containers and groups in it."""
    entries = _entries()

    assert [entry["display"] for entry in entries] == ["Icaruse"]
    assert entries[0]["docker_name"] == "group:Icaruse", entries[0]


def test_a_group_brings_its_own_permissions(world):
    """Not its members'. A group that may only restart offers only restart."""
    from cogs import group_control

    config = group_control.group_config_for("group:Icaruse")

    assert config["allowed_actions"] == ["status", "restart"]
    assert config["docker_name"] == "group:Icaruse"
    assert config["name"] == "Icaruse"


def test_a_group_that_may_not_be_controlled_is_not_offered(world):
    """The group decides here too."""
    world.groups.save_group("Icaruse", ["Icarus", "Icarus2"], active=False)

    assert _entries() == []


def test_a_group_with_no_action_at_all_is_not_offered(world):
    """A menu entry that can do nothing is a menu entry that wastes a press."""
    world.groups.save_group("Icaruse", ["Icarus", "Icarus2"], allowed_actions=["status"])
    entries = _entries()

    assert entries == [], entries


def test_a_group_is_running_when_its_members_are(world):
    from cogs import group_control

    def cache(running):
        from services.docker_status.models import ContainerStatusResult

        return SimpleNamespace(get=lambda name: {"data": ContainerStatusResult.success_result(
            docker_name=name, display_name=name, is_running=running.get(name, False),
            cpu="1%", ram="1MB", uptime="1h", details_allowed=True)})

    assert group_control.group_is_running("Icaruse", cache({"Icarus": True, "Icarus2": True})) is True
    assert group_control.group_is_running("Icaruse", cache({})) is False
    # One up, one down: a press of either button still does something, so the
    # group counts as running and gets the stop button too.
    assert group_control.group_is_running("Icaruse", cache({"Icarus": True})) is True


def test_the_admin_list_asks_for_them(world):
    """Structural, so the list cannot quietly stop offering groups."""
    source = (ROOT / "cogs" / "control_ui.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    calls = [ast.unparse(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)]

    assert any("group_entries" in call for call in calls), (
        "nothing adds the groups to the admin list")
    assert any("group_config_for" in call for call in calls), (
        "nothing builds a group's configuration when one is picked")
    assert any("running_state_for" in call for call in calls), (
        "nothing answers whether a picked group is running")


def test_the_stack_button_is_not_drawn_any_more():
    """It opened the only menu a group had; the admin list is that place now.

    Read as the CONDITION around it, not as its absence: the button is still
    built for bot.add_view, or a click on yesterday's message would answer
    nothing. What must be gone is the branch that draws it for a new one."""
    tree = ast.parse(OVERVIEW.read_text(encoding="utf-8"))
    guards = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        if "AdminOverviewRestartStackButton" not in ast.unparse(node):
            continue
        guards.append(ast.unparse(node.test))

    assert guards, "the stack button is not built at all - old messages go quiet"
    assert guards == ["every_button"], (
        f"the stack button is still drawn on a condition of its own: {guards}")


def test_old_messages_with_that_button_still_answer():
    """A message posted yesterday still carries it, and py-cord answers a click
    only for the custom_ids it was registered with. The class stays, the
    drawing stops - the same rule
    tests/spec/test_buttons_on_old_messages_keep_working.py pins."""
    source = OVERVIEW.read_text(encoding="utf-8")

    assert "class AdminOverviewRestartStackButton" in source, (
        "the class is gone, so a click on an old message answers nothing")
