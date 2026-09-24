# -*- coding: utf-8 -*-
"""A group stands in the Discord overview, the way it stands in the panel.

THE OPERATOR, 2026-09-24, with a screenshot of the server overview listing
seven containers and no group: he could not see his group in Discord. He is
right, and it is the half of his decision I had not built. A group carries its
own Active and its own four actions
(test_a_group_carries_its_own_permissions.py), the panel shows it as a row in
the container table, and the bot honoured those permissions wherever a group
already acted - the restart menu, a scheduled task, a rule. But nothing SHOWED
it. In Discord the group existed only inside a menu behind a button.

That a group behaves like a container IN THE DISPLAY too was the whole
instruction, and the overview is the display.

WHAT A GROUP'S LINE SAYS: the same shape as a container's - a lamp, the name,
and a count - and the count is the one thing a container cannot have: how many
of its members are running. Green when they all are, red when none is, yellow
when they disagree, because a group of two with one up is neither.

THE GROUP DECIDES, here too. A group the operator switched off does not
appear, and neither does one he did not allow to report status. That is the
same rule the restart menu and the tasks follow.

SET APART, like in the panel: the containers first, then a divider, then the
groups. A group listed among the containers would read as a container with a
strange name - the operator said that about the panel, and it is truer here,
where there is no second column to explain anything.

ONE HELPER, THREE EMBEDS. The expanded, the collapsed and the admin overview
each build their own status block; a group added to one of them only is a
group that appears and disappears depending on which view is open.

HOW THIS TEST CAN FAIL: showing a group that may not be shown, hiding one that
may, losing the count, or letting one of the three views drift.

COUNTER-CHECK (2026-09-24): red before - there was no helper and no group line
anywhere in the bot.
"""

import ast
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
EMBEDS = ROOT / "cogs" / "overview_embeds.py"
BUILDERS = ("_create_overview_embed_expanded", "_create_overview_embed_collapsed",
            "_create_admin_overview_embed")


@pytest.fixture
def world(tmp_path, monkeypatch):
    """Two containers - one running, one not - and a group holding both."""
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    containers = tmp_path / "containers"
    containers.mkdir()
    for name in ("alpha", "beta"):
        (containers / f"{name}.json").write_text(json.dumps(
            {"container_name": name, "docker_name": name, "active": True,
             "allowed_actions": ["status"]}), encoding="utf-8")

    from services.config import group_service

    group_service.reset_group_service()
    group_service.get_group_service().save_group(
        "Gameserver", ["alpha", "beta"],
        active=True, allowed_actions=["status", "start", "stop", "restart"])
    return SimpleNamespace(groups=group_service.get_group_service())


def _cache(running):
    """A status cache service answering for the names in `running`."""
    from services.docker_status.models import ContainerStatusResult

    def get(name):
        if name not in running:
            return None
        return {"data": ContainerStatusResult.success_result(
            docker_name=name, display_name=name, is_running=running[name],
            cpu="1%", ram="1MB", uptime="1h", details_allowed=True)}

    return SimpleNamespace(get=get)


def _lines(cache):
    from cogs import overview_embeds

    return overview_embeds.group_status_lines(cache, lambda text: text)


def test_a_group_has_a_line_of_its_own(world):
    """THE OPERATOR'S SCREENSHOT: seven containers and no group."""
    lines = _lines(_cache({"alpha": True, "beta": True}))

    assert any("Gameserver" in line for line in lines), lines


def test_the_line_says_how_many_of_its_members_run(world):
    lines = "\n".join(_lines(_cache({"alpha": True, "beta": False})))

    assert "1/2" in lines, lines


def test_all_running_reads_differently_from_none_running(world):
    """Green, red and yellow are the container lamps; a group of two with one
    up is neither of the first two."""
    all_up = "\n".join(_lines(_cache({"alpha": True, "beta": True})))
    none_up = "\n".join(_lines(_cache({"alpha": False, "beta": False})))
    mixed = "\n".join(_lines(_cache({"alpha": True, "beta": False})))

    assert "🟢" in all_up and "2/2" in all_up
    assert "🔴" in none_up and "0/2" in none_up
    assert "🟡" in mixed, mixed


def test_a_switched_off_group_is_not_shown(world):
    world.groups.save_group("Gameserver", ["alpha", "beta"], active=False)
    lines = _lines(_cache({"alpha": True, "beta": True}))

    assert lines == [], lines


def test_a_group_that_may_not_report_status_is_not_shown(world):
    """The group decides here too - the same rule the restart menu follows."""
    world.groups.save_group("Gameserver", ["alpha", "beta"],
                            allowed_actions=["restart"])
    lines = _lines(_cache({"alpha": True, "beta": True}))

    assert lines == [], lines


def test_without_groups_nothing_is_added(world, tmp_path):
    """Counter-check: an operator with no groups sees exactly what he saw
    before - no divider, no empty heading."""
    world.groups.delete_group("Gameserver")
    lines = _lines(_cache({"alpha": True}))

    assert lines == [], lines


def test_the_groups_are_set_apart_from_the_containers(world):
    """A group listed among the containers reads as a container with a strange
    name."""
    lines = _lines(_cache({"alpha": True, "beta": True}))

    assert len(lines) >= 2, lines
    assert "Gameserver" not in lines[0], (
        "the first line is already a group - nothing separates them")


def test_a_group_that_lost_a_container_says_so(world):
    """The same warning the panel gives: a group acting on fewer containers
    than it names must not look complete."""
    world.groups.save_group("Gameserver", ["alpha", "beta", "Gone"])
    lines = "\n".join(_lines(_cache({"alpha": True, "beta": True})))

    assert "⚠" in lines or "Gone" in lines, lines


def test_all_three_views_show_them(world):
    """One helper, three embeds. A group added to one view only appears and
    disappears depending on which one is open."""
    tree = ast.parse(EMBEDS.read_text(encoding="utf-8"))
    missing = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name not in BUILDERS:
            continue
        calls = [ast.unparse(inner.func) for inner in ast.walk(node)
                 if isinstance(inner, ast.Call)]
        if not any("group_status_lines" in call for call in calls):
            missing.append(node.name)

    assert missing == [], f"these views do not show the groups: {missing}"
