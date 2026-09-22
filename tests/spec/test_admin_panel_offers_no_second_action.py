# -*- coding: utf-8 -*-
"""While an action runs on a container, no panel offers start/stop/restart again.

No ``@covers`` marker: a finding, not a guarantee.

THE FINDING (stage 4 review pass 1, section 02 F3, re-checked 2026-09-19):
``ControlView.__init__`` looked up ``pending_actions`` with the DISPLAY name;
every writer of ``pending_actions`` uses the DOCKER name. The status path
checks pending itself before building the view, but the admin panel
(``AdminContainerDropdown``, control_ui.py) builds ``ControlView`` directly.
For a container whose names differ ("V-Rising" / "vrising") the admin panel
therefore offered the action buttons while an action was still running - a
second Docker action on the same container, in parallel.
"""

from unittest.mock import MagicMock

import pytest

from cogs.control_ui import ControlView

SERVER = {"docker_name": "vrising", "name": "V-Rising",
          "allowed_actions": ["start", "stop", "restart"]}


# Stopped: the start button is always offered. Running: stop/restart only in the
# expanded view (control_ui.py ControlView.__init__) - the admin panel's case for
# a running container once it has been expanded.
STATES = [(False, False), (True, True)]
IDS = ["stopped", "running-expanded"]


def _view(pending, running, expanded):
    cog = MagicMock()
    cog.pending_actions = pending
    cog.expanded_states = {"vrising": expanded}
    return ControlView(cog, dict(SERVER), is_running=running,
                       channel_has_control_permission=True, allow_toggle=False)


def _action_buttons(view):
    return [c for c in view.children if type(c).__name__ == "ActionButton"]


@pytest.mark.asyncio
@pytest.mark.parametrize("running, expanded", STATES, ids=IDS)
async def test_a_running_action_hides_the_action_buttons(running, expanded):
    view = _view({"vrising": {"action": "restart"}}, running, expanded)
    assert _action_buttons(view) == [], (
        f"{len(_action_buttons(view))} action button(s) offered while 'vrising' has an "
        f"action running"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("running, expanded", STATES, ids=IDS)
async def test_without_a_running_action_the_buttons_are_there(running, expanded):
    """Counter-check: otherwise 'never any buttons' would pass the test above.

    It did, in the first version of this file: with a running, collapsed
    container the view has no action buttons at all, and the test above was
    green for that reason alone.
    """
    assert _action_buttons(_view({}, running, expanded)), "no action buttons at all"
