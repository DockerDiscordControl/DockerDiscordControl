# -*- coding: utf-8 -*-
"""A container panel shows what it knows instead of offering to expand.

THE FINDING. With the expand button gone (2026-09-25,
tests/spec/test_no_control_flips_an_expand_state.py) the status embed still
had two renderings, and picked between them on ``expanded_states``. The
collapsed one ends with

    │ • ▼ Expand for details

which now names a control that is on no view. It is also the only line of
that box written in bare English - every neighbour comes from the translated
strings above it - so in thirty-nine of the forty languages it was English
anyway.

WHY THE COLLAPSED RENDERING CANNOT BE REACHED ON PURPOSE. ``expanded_states``
is a ONE-WAY LATCH: every writer sets True (cogs/control_ui.py:506, :1775),
nothing sets False, nothing removes an entry and nothing saves it, so a
container is "collapsed" only until its admin panel is first opened - and the
panel itself sets the flag before it draws. ``force_collapse`` is the other
half of the same switch and every live caller passes False; the one place
that passed True, ``_send_all_server_statuses``, stopped building container
embeds altogether when the per-container design was deleted.

So the collapsed box could only appear on a path that reaches the embed
builder without the admin panel having set the flag - the error fallback in
``ActionButton.callback``, where the panel it draws has no expand button
either. The operator would be told to press something that is not there.

WHAT CHANGES FOR HIM: nothing he has seen. The panel he opens already sets
the flag, so it already shows CPU, RAM and uptime. Only the unreachable half
goes, and with it the state that chose between them.

HOW THIS TEST CAN FAIL: a container panel that hides its details behind an
offer to expand, or any text for a container that names such a control.

COUNTER-CHECK (2026-09-25): red before - with no entry in ``expanded_states``
the description carried "Expand for details" and no CPU line at all.
"""

import ast
import asyncio
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from cogs.docker_control import DockerControlCog
from services.docker_status.models import ContainerStatusResult

PROJECT = Path(__file__).resolve().parents[2]

SERVER = {"docker_name": "web", "name": "web", "display_name": "web",
          "allowed_actions": ["status", "start", "stop", "restart"]}


def _description(*, running=True, details_allowed=True):
    """The real embed, built the way the admin panel builds it.

    ``expanded_states`` is left EMPTY on purpose: that is the state a
    container is in until somebody opens its panel, and it is exactly the
    state that used to produce the offer to expand.
    """
    result = ContainerStatusResult.success_result(
        docker_name="web", display_name="web", is_running=running,
        cpu="1%", ram="1024 MB", uptime="1h", details_allowed=details_allowed)
    entry = {"data": result, "timestamp": datetime.now(timezone.utc)}

    cog = object.__new__(DockerControlCog)
    cog.status_cache_service = SimpleNamespace(get=lambda name: entry)
    cog.pending_actions = {}
    cog.status_refresh_interval_seconds = 120
    cog.cache_ttl_seconds = 300
    cog.mech_expanded_states = {}
    cog.expanded_states = {}

    info_service = MagicMock()
    info_service.get_container_info.return_value = SimpleNamespace(success=False, data=None)
    with patch("cogs.status_handlers.get_server_config_service",
               lambda: SimpleNamespace(get_all_servers=lambda: [SERVER])), \
            patch("services.infrastructure.container_info_service.get_container_info_service",
                  return_value=info_service):
        embed, _view, _running = asyncio.run(
            cog._generate_status_embed_and_view(1, "web", SERVER, {"language": "en"}))
    return embed.description


def test_a_running_container_shows_its_details():
    """THE FINDING: the panel hid CPU, RAM and uptime behind a button that
    no longer exists."""
    description = _description()

    for expected in ("CPU", "RAM", "1%", "1024 MB", "1h"):
        assert expected in description, f"{expected!r} is missing:\n{description}"


def test_nothing_offers_to_expand_it():
    """The other half: no offer to press what is not there."""
    description = _description()

    assert "Expand" not in description, (
        f"the panel offers a control that is on no view:\n{description}")


def test_a_container_that_may_not_show_details_still_says_so():
    """Counter-check: the operator can forbid the detailed status, and that
    refusal is not the same as hiding it behind a button."""
    description = _description(details_allowed=False)

    assert "CPU" not in description, description
    assert "not allowed" in description.lower(), description


def test_a_stopped_container_reports_no_uptime():
    """Counter-check: the other branch of the same box is untouched."""
    description = _description(running=False)

    assert "N/A" in description, description
    assert "CPU" not in description, description


def _embed_text_pieces(tree):
    """Every string DDC puts INTO an embed description.

    Asked of the tree, and of the two ways this code builds one: a piece
    appended to a ``..._parts`` list, and a ``description=`` argument. Log
    lines, cache keys and docstrings are not text the operator reads, and a
    first version that took every string in a function flagged the mech's
    own working comments while the one line that matters sat among them.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg == "description":
            yield node.value
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in ("append", "extend"):
            continue
        if not ast.unparse(node.func.value).endswith("_parts"):
            continue
        yield from node.args


def _offers_to_expand(piece):
    """String constants inside one such piece that name an expand control.

    Asked of the CONSTANTS, so this docstring and the comments explaining
    the removal cannot trip it - the mistake five of my own scans made today
    - and an f-string is reached through its parts.
    """
    for sub in ast.walk(piece):
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            if "expand" in sub.value.lower():
                yield sub.lineno, sub.value.strip()


def test_no_text_for_a_container_names_an_expand_control():
    """The rule behind the finding, asked everywhere rather than at the one
    line that showed it."""
    offenders = []
    for path in sorted((PROJECT / "cogs").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for piece in _embed_text_pieces(tree):
            for line, text in _offers_to_expand(piece):
                offenders.append(f"{path.name}:{line}: {text[:60]}")

    assert offenders == [], (
        f"a container's text names a control that is on no view: {offenders}")


def test_the_scan_has_subjects_and_would_see_one():
    """The counter-check ten sabotages have walked past. Two halves: the
    scan must actually find embed text, and it must react to the exact line
    that was there."""
    subjects = [piece
                for path in sorted((PROJECT / "cogs").glob("*.py"))
                for piece in _embed_text_pieces(
                    ast.parse(path.read_text(encoding="utf-8")))]

    assert len(subjects) > 10, f"only {len(subjects)} pieces of embed text found"

    sabotage = ast.parse(
        'description_parts.append(f"│ • ▼ Expand for details")')
    pieces = list(_embed_text_pieces(sabotage))

    assert len(pieces) == 1, pieces
    assert list(_offers_to_expand(pieces[0])), "the scan did not see the removed line"


def test_the_mech_classes_were_not_touched_by_this_removal():
    """The opposite mistake: taking something away that was not the subject.

    THIS CASE USED TO CLAIM MORE THAN IT CHECKED. It said "the mech really
    does expand and collapse, with two buttons that work" and proved it with
    ``hasattr`` - which shows only that a class is DEFINED. The operator
    said, again, that there is no toggle button and that it belonged to the
    old Discord overview, and he was right a second time:

        MechView, the view actually posted on the overview, carries
        AdminButton, HelpButton, InfoDropdownButton and MechDetailsButton -
        no expand, no collapse.

        MechExpandButton and MechCollapseButton appear only inside
        PersistentMechExpandView / PersistentMechCollapseView in
        cogs/docker_control.py, which exist to be handed to bot.add_view()
        so that buttons on OLD messages still answer after a restart. No
        posted view carries them.

        config/mech_state.json on the running system holds one channel, at
        false, last written 2026-09-16. Ten months of logs name mech_expand
        and mech_collapse zero times.

    So the mech's expand state cannot be reached either, and that is a
    finding of its own with its own decision to take - not something to fold
    into this removal, which was about the container box. What this case can
    honestly hold is the boundary: THIS change did not touch the mech.
    """
    from cogs import control_ui

    assert hasattr(control_ui, "MechExpandButton")
    assert hasattr(control_ui, "MechCollapseButton")
