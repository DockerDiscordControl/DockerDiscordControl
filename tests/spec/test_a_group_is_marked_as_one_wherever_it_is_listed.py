# -*- coding: utf-8 -*-
"""A group is recognisable as a group, in both lists that hold one.

THE OPERATOR, 2026-09-24, on the first version of the Discord group display:

* the admin dropdown reads "Gameserver" between "Valheim" and "Enshrouded" with
  nothing to say it is not a container - he asked for an indicator;
* the separation in the ADMIN overview looked wrong, and it did: that view
  draws no box, it stacks blocks, so the `├──` divider and the leading `│`
  that fit the Server overview arrived there as stray pipes and dashes. He
  asked for a plain heading and lines shaped like the container lines above
  them.

THE BOX VIEW STAYS AS IT IS. He called that one pretty, and there the pipes
are the box: every container line is `│ 🟢 Name`, so the group lines are too.
One helper still writes both, because a group that appears in one view and not
another is the defect this whole feature was built against - it takes a style,
not a second implementation.

THE INDICATOR, chosen by the operator on 2026-09-24 after seeing the first
one: 📁. The retired group menu's 🗂️ renders large and colourful on Discord
and reads as clutter rather than as a collection; a folder is the calmest
thing that says "there is more inside".

AND ONLY THE GROUP CARRIES ONE. He was asked whether the containers should be
marked too and chose not to: the group is the only row with a symbol, and it
stands out for exactly that reason. A symbol on every row is a column the eye
reads instead of an exception it notices.

THE PANEL AND DISCORD MUST AGREE. The symbol is written in two places that
cannot import from each other - the cog and config-ui.js - so a case below
compares them. Two marks for one thing is how an operator ends up wondering
whether they mean the same.

HOW THIS TEST CAN FAIL: a dropdown that lists groups like containers, box
drawing in the admin overview, or a heading that stops naming what follows it.

COUNTER-CHECK (2026-09-24): red before - the dropdown option carried no emoji,
and the admin overview got the boxed lines.
"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]


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
                      active=True, allowed_actions=["status", "start", "stop", "restart"])
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


def _lines(boxed):
    from cogs import overview_embeds

    return overview_embeds.group_status_lines(
        _cache({"alpha": True, "beta": True}), lambda text: text, boxed=boxed)


# --- the admin overview: blocks, not a box ---------------------------------

def test_the_admin_overview_gets_no_box_drawing(world):
    """THE COMPLAINT: stray pipes and dashes in a view that draws no box."""
    lines = _lines(boxed=False)

    for line in lines:
        for drawing in ("│", "├", "└", "──"):
            assert drawing not in line, f"{drawing!r} in {line!r}"


def test_it_says_what_follows_it(world):
    lines = _lines(boxed=False)

    # The asterisks are Discord's bold, not part of the words.
    assert lines[0].strip().strip("*").endswith(":"), (
        f"the heading does not read as one: {lines[0]!r}")
    assert "Container groups" in lines[0]


def test_a_group_line_reads_like_a_container_line(world):
    """"Indikator Symbol, Gameserver 2/2" - the same shape as the lines above."""
    line = _lines(boxed=False)[1]

    assert line.startswith("🟢"), line
    assert "Gameserver" in line and "2/2" in line, line


# --- the server overview: the box he liked ---------------------------------

def test_the_box_view_keeps_its_box(world):
    """Counter-check: he called that one pretty, and there the pipes ARE the
    box - every container line starts with one."""
    lines = _lines(boxed=True)

    assert lines[0].startswith("├──"), lines[0]
    assert lines[1].startswith("│ "), lines[1]


def test_both_styles_show_the_same_groups(world):
    """One helper, two styles. A second implementation is how a group ends up
    in one view and not the other."""
    boxed = "\n".join(_lines(boxed=True))
    plain = "\n".join(_lines(boxed=False))

    for shown in ("Gameserver", "2/2", "🟢"):
        assert shown in boxed and shown in plain, shown


def test_nothing_is_added_when_there_are_no_groups(world):
    world.groups.delete_group("Gameserver")

    assert _lines(boxed=True) == []
    assert _lines(boxed=False) == []


# --- the dropdown ----------------------------------------------------------

def test_the_dropdown_marks_a_group(world):
    """THE COMPLAINT: "Gameserver" between "Valheim" and "Enshrouded", with
    nothing saying it is not a container."""
    from cogs.group_control import GROUP_EMOJI, group_entries

    entry = group_entries()[0]

    assert entry.get("emoji") == GROUP_EMOJI, entry
    assert GROUP_EMOJI == "📁", (
        f"the operator chose the folder; this is {GROUP_EMOJI!r}")


def test_only_the_group_is_marked(world):
    """His decision: the group is the only row with a symbol, and it stands
    out for exactly that reason."""
    from cogs.group_control import controllable_entries

    entries = controllable_entries([{"docker_name": "Valheim", "order": 1}])
    marked = [entry for entry in entries if entry.get("emoji")]

    assert [entry["docker_name"] for entry in marked] == ["group:Gameserver"], marked


def test_the_panel_uses_the_same_mark():
    """Two places that cannot import from each other. Two marks for one thing
    is how an operator ends up wondering whether they mean the same."""
    import re

    from cogs.group_control import GROUP_EMOJI

    source = (ROOT / "app" / "static" / "js" / "config-ui.js").read_text(encoding="utf-8")
    label = re.search(r"function adminAssignmentLabel.*?^\}", source,
                      re.S | re.M)

    assert label, "the panel's label rule is gone"
    assert GROUP_EMOJI in label.group(0), (
        f"the panel marks a group with something other than {GROUP_EMOJI!r}")


def test_the_option_carries_it(world):
    """The entry is only half of it - the option Discord draws is the other."""
    from cogs import control_ui

    dropdown = control_ui.AdminContainerDropdown(
        SimpleNamespace(), [{"name": "Valheim", "display": "Valheim",
                             "docker_name": "Valheim", "order": 1}]
        + control_ui.group_entries(), 42)
    by_value = {option.value: option for option in dropdown.options}

    assert by_value["Valheim"].emoji is None, "a container was marked as a group"
    marked = by_value["group:Gameserver"]

    assert marked.emoji is not None, "the group option carries no indicator"


# --- the spacing in the admin overview -------------------------------------
# THE OPERATOR, once the pipes were gone: the group section stands closer
# together than everything above it. It did - the whole block was appended as
# ONE entry, so the separator the view puts between container lines never got
# between the heading and the group under it.

def _admin_description(servers, entries):
    """The admin overview's description, rendered the way the view builds it."""
    import asyncio
    from datetime import datetime, timezone
    from unittest.mock import MagicMock, patch

    from cogs.docker_control import DockerControlCog

    cog = object.__new__(DockerControlCog)
    cog.status_cache_service = SimpleNamespace(get=entries.get)
    cog._status_update_semaphore = asyncio.Semaphore(1)
    cog._last_status_cache_refresh = 0.0
    cog._status_fetch_failed = set()
    cog.pending_actions = {}
    info_service = MagicMock()
    info_service.get_container_info.return_value = SimpleNamespace(success=False, data=None)
    with patch("cogs.overview_embeds.load_config", return_value={}), \
         patch("services.infrastructure.container_info_service.get_container_info_service",
               return_value=info_service):
        embed, _file, _running = asyncio.run(cog._create_admin_overview_embed(servers, {}))
    return embed.description


def _world_entries():
    from datetime import datetime, timezone

    from services.docker_status.models import ContainerStatusResult

    return {name: {"data": ContainerStatusResult.success_result(
        docker_name=name, display_name=name, is_running=True, cpu="1%", ram="1024 MB",
        uptime="1h", details_allowed=True), "timestamp": datetime.now(timezone.utc)}
        for name in ("alpha", "beta")}


def test_the_group_section_is_spaced_like_the_containers(world):
    """THE COMPLAINT: it stood closer together than everything above it."""
    servers = [{"docker_name": name, "name": name, "display_name": name,
                "allowed_actions": ["restart"]} for name in ("alpha", "beta")]
    description = _admin_description(servers, _world_entries())

    separator = "\nㅤ\n"
    assert separator in description, "the view stopped separating its lines"
    blocks = description.split(separator)
    heading = [block for block in blocks if "Container groups" in block]

    assert heading, f"the heading is not a block of its own: {description!r}"
    assert "Gameserver" not in heading[0], (
        "the heading and the group line are one block, so nothing spaces them")
    assert any("Gameserver" in block for block in blocks), description


def test_the_header_still_counts_containers_only(world):
    """Counter-check: the groups are blocks like the containers now, and the
    header must not start counting them."""
    import re

    servers = [{"docker_name": name, "name": name, "display_name": name,
                "allowed_actions": ["restart"]} for name in ("alpha", "beta")]
    description = _admin_description(servers, _world_entries())
    line = next(l for l in description.splitlines() if l.startswith("Container:"))

    assert int(re.findall(r"(\d+)", line)[0]) == 2, line
