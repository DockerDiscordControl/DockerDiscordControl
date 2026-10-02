# -*- coding: utf-8 -*-
"""A container's private admin panel closes itself after five minutes without use.

THE OBSERVATION (operator, 2026-10-02): the container picker ("choose a
container to control") from the day before was still in the control
channel - their own private panel, the container picker turned into the group's admin panel. That panel
is a ControlView with no timeout at all, so it never expired; every other
private panel closes itself. Discord lets DDC delete a private message only
within fifteen minutes of the press, so it has to go in time or it stays
until dismissed by hand.

THE OPERATOR'S CHOICE: five minutes without use, like the other private
panels; each press starts them again (py-cord's view timeout).

HOW THIS TEST CAN FAIL: the admin panel lives for ever again, or the
timeout removes a message that is not private.

COUNTER-CHECK (2026-10-02): red before the change (timeout None).
"""

from types import SimpleNamespace

import pytest

from cogs.group_control import admin_control_view


def _panel():
    config = {"docker_name": "Icarus", "name": "Icarus", "allowed_actions": ["start", "stop", "restart"]}
    return admin_control_view(SimpleNamespace(pending_actions={}), config, is_running=True)


@pytest.mark.asyncio
async def test_the_panel_has_five_minutes():
    assert _panel().timeout == 300


@pytest.mark.asyncio
async def test_its_timeout_takes_the_private_message_and_only_that():
    deleted = []

    def message(ephemeral):
        async def delete():
            deleted.append(ephemeral)
        return SimpleNamespace(id=1, flags=SimpleNamespace(ephemeral=ephemeral), delete=delete, _state=None)

    for ephemeral in (True, False):
        view = _panel()
        view.message = message(ephemeral)
        await view.on_timeout()
    assert deleted == [True], "a public message was taken, or the private panel stayed"
