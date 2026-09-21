# -*- coding: utf-8 -*-
"""A button that is shown is a button that will work.

THE FINDING (review D32, pass 2, section 02 F4):
`ControlView._channel_has_info_permission` returns True no matter what it is
asked. Its own body says so:

    # Note: We need the actual channel_id, but we don't have it in this context
    # This will be handled properly in the InfoButton callback
    return True  # Let InfoButton handle the actual permission check

So the Info button is added to every container's view, including in a channel
that has neither 'control' nor 'info' permission - a plain status channel,
which is an ordinary DDC setup. Pressing it is correctly refused by
`InfoButton.callback`, which does the real check. The button is simply there,
and always says no.

Two methods of the same name sit in this file: `InfoButton`'s does the real
work, `ControlView`'s claims to and does not. A name that means one thing in
one class and nothing in the other is how this survived being read.

The channel id it says it does not have is available at every call site -
including the one two lines above the caller
(`_control_allowed_for(channel_id, ...)`, control_ui.py:1014). It is now
passed in, and the check is the same one the callback makes, so what is shown
and what is allowed cannot disagree.

Where the channel id is genuinely unknown the old answer stands - show it and
let the callback refuse - because a default of "hide it" would silently take
the Info button away from an info-only channel if a caller ever forgot to
pass one. That case now says so in the log instead of passing quietly.
"""

from types import SimpleNamespace

import pytest

import cogs.control_ui as cui
from cogs.control_ui import ControlView, InfoButton

CONTROL_CHANNEL = 100
INFO_CHANNEL = 200
STATUS_CHANNEL = 300

PERMISSIONS = {
    (CONTROL_CHANNEL, 'control'): True,
    (CONTROL_CHANNEL, 'info'): True,
    (INFO_CHANNEL, 'control'): False,
    (INFO_CHANNEL, 'info'): True,
    (STATUS_CHANNEL, 'control'): False,
    (STATUS_CHANNEL, 'info'): False,
}


@pytest.fixture
def environment(monkeypatch):
    monkeypatch.setattr(cui, "load_config", lambda: {"servers": []})
    monkeypatch.setattr(
        "cogs.control_helpers._channel_has_permission",
        lambda channel_id, key, config=None: PERMISSIONS[(channel_id, key)])
    monkeypatch.setattr(
        "services.infrastructure.container_info_service.get_container_info_service",
        lambda: SimpleNamespace(get_container_info=lambda name: SimpleNamespace(
            success=True, data=SimpleNamespace(to_dict=lambda: {}))))
    return monkeypatch


def _view(channel_id, *, is_running, expanded=True):
    cog = SimpleNamespace(pending_actions={}, expanded_states={"nginx": expanded})
    server_config = {"docker_name": "nginx", "name": "nginx",
                     "allowed_actions": ["start", "stop", "restart"],
                     "allow_detailed_status": True}
    return ControlView(
        cog, server_config, is_running,
        channel_has_control_permission=PERMISSIONS[(channel_id, 'control')],
        channel_id=channel_id,
    )


def _has_info_button(view):
    return any(isinstance(child, InfoButton) for child in view.children)


@pytest.mark.parametrize("is_running", [True, False])
async def test_a_channel_with_no_info_permission_gets_no_info_button(environment, is_running):
    """The finding: a plain status channel."""
    view = _view(STATUS_CHANNEL, is_running=is_running)

    assert not _has_info_button(view), (
        "the Info button is offered in a channel that has no right to it - "
        "pressing it is refused, so it is a button that can only say no"
    )


async def test_an_info_channel_keeps_its_info_button(environment):
    """The counter-case that matters most.

    A channel with 'info' but not 'control' is exactly what the always-True
    answer was protecting. Hiding the button there would be a worse defect
    than showing it where it refuses.

    OFFLINE only, and that is not an oversight: for a RUNNING container the
    Info button sits inside `if channel_has_control_permission and
    is_expanded`, so a channel without control has never shown one there. My
    first version of this test demanded it for both, and the code was right.
    The case below pins that rule so the next reader does not have to find it
    the way I did.
    """
    view = _view(INFO_CHANNEL, is_running=False)

    assert _has_info_button(view), (
        "the channel has info permission and the button is gone"
    )


async def test_a_running_container_offers_info_only_where_it_offers_control(environment):
    """The rule as it stands, written down rather than assumed.

    For a running container every button - including Info - hangs off the
    control branch. A status channel therefore never saw one here anyway;
    what it did see, and what D32 is about, is the OFFLINE path above.
    """
    view = _view(INFO_CHANNEL, is_running=True)

    assert not _has_info_button(view)


@pytest.mark.parametrize("is_running", [True, False])
async def test_a_control_channel_keeps_its_info_button(environment, is_running):
    """Control permission grants info - that rule is unchanged."""
    view = _view(CONTROL_CHANNEL, is_running=is_running)

    assert _has_info_button(view)


async def test_without_a_channel_id_the_old_answer_stands(environment, caplog):
    """A caller that passes no channel id must not lose the button silently."""
    import logging

    cog = SimpleNamespace(pending_actions={}, expanded_states={"nginx": True})
    server_config = {"docker_name": "nginx", "name": "nginx",
                     "allowed_actions": ["start"], "allow_detailed_status": True}

    with caplog.at_level(logging.WARNING):
        view = ControlView(cog, server_config, False,
                           channel_has_control_permission=False)

    assert _has_info_button(view), (
        "a caller without a channel id lost the Info button, which would take "
        "it away from info-only channels too"
    )
    assert any("channel" in record.getMessage().lower()
               for record in caplog.records), (
        "the gap passed without a word in the log"
    )
