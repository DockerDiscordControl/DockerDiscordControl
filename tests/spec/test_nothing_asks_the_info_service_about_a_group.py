# -*- coding: utf-8 -*-
"""A group has no info section, so nothing asks for one.

FROM THE OPERATOR'S LOG (2026-09-24), three times around a single group panel:

    ERROR - Error loading info for group:Icaruse: Invalid container name:
            'group:Icaruse'

Nothing breaks. `get_container_info` rejects the name, the caller reads the
failure as "no info configured" and returns the embed unchanged, which is the
right outcome. But it is written to the log at ERROR, and a log that reports an
error for a thing working exactly as designed is a log nobody reads twice - the
next real error arrives among them.

A CONTAINER'S INFO IS A CONTAINER'S. It lives in config/containers/<name>.json,
a group has no such file and is never meant to have one, and the info button is
already not drawn for a group (cogs/control_ui.py). The remaining caller is the
status embed enrichment, which is handed whatever the panel is showing.

So it asks the same question the rest of the group work asks - is this target a
group - and stops, instead of finding out by having a service refuse the name.

HOW THIS TEST CAN FAIL: a caller handing a group target to the info service.

COUNTER-CHECK (2026-09-24): red before - the enrichment called the service and
the service logged the refusal.
"""

import logging
from unittest.mock import patch

import discord
import pytest


@pytest.fixture
def embed():
    return discord.Embed(title="Gameserver", description="1/2")


def _enhance(server_config, embed):
    from cogs.status_info_integration import create_enhanced_status_embed

    return create_enhanced_status_embed(embed, server_config, info_indicator=True)


def test_a_group_is_not_looked_up(embed):
    """THE FINDING: the service was asked and refused the name."""
    with patch("services.infrastructure.container_info_service.get_container_info_service") as service:
        result = _enhance({"docker_name": "group:Gameserver", "name": "Gameserver"}, embed)

        assert service.call_count == 0, "the info service was asked about a group"
    assert result is embed, "a group's embed must come back untouched"


def test_a_group_logs_nothing_at_error(embed, caplog):
    """The point of the finding: the log stays clean."""
    with caplog.at_level(logging.ERROR):
        _enhance({"docker_name": "group:Gameserver", "name": "Gameserver"}, embed)

    assert [r.message for r in caplog.records] == []


def test_a_container_is_still_looked_up(embed):
    """Counter-check that the guard did not switch the feature off: without
    it, the case above would pass for every container too."""
    with patch("cogs.status_info_integration.get_container_info_service") as service:
        service.return_value.get_container_info.return_value.success = False
        _enhance({"docker_name": "alpha", "name": "alpha"}, embed)

        assert service.return_value.get_container_info.call_args[0][0] == "alpha"


def test_the_admin_marker_still_skips_too(embed):
    """The guard sits beside an existing one and must not have replaced it."""
    with patch("cogs.status_info_integration.get_container_info_service") as service:
        result = _enhance({"docker_name": "alpha", "_is_admin_control": True}, embed)

        assert service.call_count == 0
    assert result is embed


def test_no_caller_hands_a_group_to_the_info_service():
    """THE RATCHET, read from the syntax tree: every call to
    get_container_info in the cogs, and where its argument comes from.

    Listed rather than swept - the sweep is the list. A new caller that can be
    reached with a group target has to be looked at, and this is where that
    happens.
    """
    import ast
    from pathlib import Path

    project = Path(__file__).resolve().parents[2]
    # Callers that can only ever see a container: they iterate the configured
    # containers, where a group does not appear.
    known = {
        "cogs/overview_embeds.py",          # walks the container list
        "cogs/slash_commands.py",           # /info <container>, name from the command
        "cogs/enhanced_info_modal_simple.py",   # a modal opened from a container
        "cogs/status_info_integration.py",  # guarded, see the cases above
        # ControlView.__init__ builds a group's panel too, and USED TO ask here
        # before it knew that - two of the three ERROR lines in the operator's
        # log came from this one. The group branch now returns above the
        # lookup, which is pinned by its own case below.
        "cogs/control_ui.py",
    }
    callers = set()
    for path in sorted((project / "cogs").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "get_container_info"):
                callers.add(path.relative_to(project).as_posix())

    assert callers <= known, (
        f"a new caller of get_container_info: {sorted(callers - known)} - can it be "
        "reached with a group target?")


def test_the_group_panel_returns_before_the_lookup():
    """FOUND BY THE LIST ABOVE, not by me: ControlView.__init__ asked the info
    service at the top and only recognised a group forty lines further down, so
    every group panel build logged a refusal. Read from the syntax tree - the
    order of the two statements is the whole fix."""
    import ast
    from pathlib import Path

    source = (Path(__file__).resolve().parents[2] / "cogs" / "control_ui.py").read_text(
        encoding="utf-8")
    tree = ast.parse(source)
    view = next(node for node in ast.walk(tree)
                if isinstance(node, ast.ClassDef) and node.name == "ControlView")
    init = next(node for node in view.body
                if isinstance(node, ast.FunctionDef) and node.name == "__init__")

    asks = [node.lineno for node in ast.walk(init)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get_container_info"]
    returns_for_a_group = [node.lineno for node in ast.walk(init)
                           if isinstance(node, ast.If)
                           and "is_group_target" in ast.unparse(node.test)
                           and any(isinstance(inner, ast.Return)
                                   for inner in ast.walk(node))]

    assert asks, "the lookup is gone - this case would pass for the wrong reason"
    assert returns_for_a_group, "ControlView no longer leaves early for a group"
    assert min(returns_for_a_group) < min(asks), (
        f"the group leaves at line {min(returns_for_a_group)} but the info service "
        f"is asked at {min(asks)} - a group still logs a refusal on every build")


def test_the_guard_is_the_shared_question():
    """Not a string comparison of its own: the spelling lives in one place
    (services/config/group_service.py) and everybody imports it."""
    import ast
    from pathlib import Path

    source = (Path(__file__).resolve().parents[2] / "cogs"
              / "status_info_integration.py").read_text(encoding="utf-8")
    names = {alias.name for node in ast.walk(ast.parse(source))
             if isinstance(node, ast.ImportFrom) for alias in node.names}

    assert "is_group_target" in names
