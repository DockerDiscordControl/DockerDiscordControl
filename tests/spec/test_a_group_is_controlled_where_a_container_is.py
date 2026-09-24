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
through docker_action_service_first(name, action), and `group:Gameserver` is a
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
    for name in ("alpha", "beta"):
        (containers / f"{name}.json").write_text(json.dumps(
            {"container_name": name, "docker_name": name, "active": True,
             "allowed_actions": ["status"]}), encoding="utf-8")

    from services.config import group_service

    group_service.reset_group_service()
    groups = group_service.get_group_service()
    groups.save_group("Gameserver", ["alpha", "beta"],
                      active=True, allowed_actions=["status", "restart"])
    return SimpleNamespace(groups=groups)


def _entries():
    from cogs import group_control

    return group_control.group_entries()


def test_the_list_offers_the_groups(world):
    """THE POINT: one menu, containers and groups in it."""
    entries = _entries()

    assert [entry["display"] for entry in entries] == ["Gameserver"]
    assert entries[0]["docker_name"] == "group:Gameserver", entries[0]


def test_a_group_brings_its_own_permissions(world):
    """Not its members'. A group that may only restart offers only restart."""
    from cogs import group_control

    config = group_control.group_config_for("group:Gameserver")

    assert config["allowed_actions"] == ["status", "restart"]
    assert config["docker_name"] == "group:Gameserver"
    assert config["name"] == "Gameserver"


def test_a_group_that_may_not_be_controlled_is_not_offered(world):
    """The group decides here too."""
    world.groups.save_group("Gameserver", ["alpha", "beta"], active=False)

    assert _entries() == []


def test_a_group_with_no_action_at_all_is_not_offered(world):
    """A menu entry that can do nothing is a menu entry that wastes a press."""
    world.groups.save_group("Gameserver", ["alpha", "beta"], allowed_actions=["status"])
    entries = _entries()

    assert entries == [], entries


def test_a_group_is_running_when_its_members_are(world):
    from cogs import group_control

    def cache(running):
        from services.docker_status.models import ContainerStatusResult

        return SimpleNamespace(get=lambda name: {"data": ContainerStatusResult.success_result(
            docker_name=name, display_name=name, is_running=running.get(name, False),
            cpu="1%", ram="1MB", uptime="1h", details_allowed=True)})

    assert group_control.group_is_running("Gameserver", cache({"alpha": True, "beta": True})) is True
    assert group_control.group_is_running("Gameserver", cache({})) is False
    # One up, one down: a press of either button still does something, so the
    # group counts as running and gets the stop button too.
    assert group_control.group_is_running("Gameserver", cache({"alpha": True})) is True


def test_the_admin_list_asks_for_them(world):
    """Structural, so the list cannot quietly stop offering groups.

    The list itself is built one level down since 2026-09-24 - both buttons
    ask controllable_entries() - so this reads the two questions that are
    still control_ui's own, and the group half is checked where it lives."""
    calls = [ast.unparse(node.func) for node in
             ast.walk(ast.parse((ROOT / "cogs" / "control_ui.py").read_text(encoding="utf-8")))
             if isinstance(node, ast.Call)]

    assert any("controllable_entries" in call for call in calls), (
        "nothing adds the groups to the admin list")
    assert any("group_config_for" in call for call in calls), (
        "nothing builds a group's configuration when one is picked")
    assert any("running_state_for" in call for call in calls), (
        "nothing answers whether a picked group is running")

    builder = [ast.unparse(node.func) for node in
               ast.walk(ast.parse((ROOT / "cogs" / "group_control.py").read_text(encoding="utf-8")))
               if isinstance(node, ast.Call)]

    assert any("group_entries" in call for call in builder), (
        "the one list stopped adding the groups")


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


# --- both buttons, one list -------------------------------------------------
# THE OPERATOR, 2026-09-24: in a CONTROL channel, the tools button offers no
# groups. It did not - and the reason is the defect this suite spent the night
# on. There are TWO buttons that open "choose something to control": the one in
# cogs/control_ui.py and AdminOverviewAdminButton in cogs/admin_overview.py,
# each building the list from get_all_servers() on its own. Wiring the groups
# into one of them left the other exactly as it was.

def test_both_buttons_ask_the_same_place(world):
    """One list, asked twice - not two lists that happen to agree."""
    import ast

    for module in ("cogs/control_ui.py", "cogs/admin_overview.py"):
        tree = ast.parse((ROOT / module).read_text(encoding="utf-8"))
        calls = [ast.unparse(node.func) for node in ast.walk(tree)
                 if isinstance(node, ast.Call)]

        assert any("controllable_entries" in call for call in calls), (
            f"{module} builds its own list instead of asking for one")


def test_the_one_list_holds_containers_and_groups(world):
    from cogs.group_control import controllable_entries

    servers = [{"docker_name": "alpha", "display_name": "alpha", "order": 2},
               {"docker_name": "beta", "display_name": ["Beta Server", "x"], "order": 1}]
    entries = controllable_entries(servers)
    by_name = {entry["docker_name"]: entry for entry in entries}

    assert "group:Gameserver" in by_name, entries
    assert by_name["alpha"]["display"] == "alpha"
    # A display name stored as a LIST is what the panel writes for some
    # containers; the dropdown must show the name, not "['Beta Server', 'x']".
    assert by_name["beta"]["display"] == "Beta Server"


def test_the_groups_come_after_the_containers(world):
    from cogs.group_control import controllable_entries

    entries = controllable_entries([{"docker_name": "alpha", "order": 999}])
    orders = [entry["order"] for entry in entries]

    assert orders == sorted(orders), orders
    assert entries[-1]["docker_name"] == "group:Gameserver", entries


def test_an_entry_without_a_name_is_left_out(world):
    """Counter-check on the move: the old loops both skipped those."""
    from cogs.group_control import controllable_entries

    entries = controllable_entries([{"order": 1}, {"docker_name": "", "order": 2}])

    assert [entry["docker_name"] for entry in entries] == ["group:Gameserver"]
