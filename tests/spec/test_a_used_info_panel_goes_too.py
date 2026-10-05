# -*- coding: utf-8 -*-
"""A container's info panel in a control channel goes at its timeout, used or not.

THE FINDING (2026-10-05, next to the live-log review): ContainerInfoAdminView
(📝 🔒 ⏰ 📋) kept an on_timeout and an 885-second timer of its own, both
deleting ``self.message``. After the first press py-cord replaces that with
the plain message, whose delete() is the channel route - a 404 for an
ephemeral message. So a panel that had been used stayed until dismissed by
hand, the same defect DDCView.on_timeout fixed for every other private panel
(stage 4 review before v3.1.0, section 38).

THE CONTRACT: at its timeout the panel is deleted through the message it was
sent with (or the last press), not through the channel route.

HOW THIS TEST CAN FAIL: the deletion goes to the plain message again.

COUNTER-CHECK (2026-10-05): red on the code before the change (the plain
message was asked, answered 404, and the panel stayed).
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import discord
import pytest

import cogs.status_info_integration as sii


class _Message:
    def __init__(self, gone=False):
        self.flags = SimpleNamespace(ephemeral=True)
        self.id = 42
        self.deleted = False
        self._gone = gone

    async def delete(self):
        if self._gone:
            raise discord.NotFound(SimpleNamespace(status=404, reason="Not Found"), "channel route")
        self.deleted = True


@pytest.mark.asyncio
async def test_a_pressed_info_panel_is_deleted_through_the_message_it_was_sent_with():
    view = sii.ContainerInfoAdminView(MagicMock(), {"docker_name": "nginx", "name": "nginx"}, {})
    sent, plain = _Message(), _Message(gone=True)
    view._sent_message = sent   # kept by DDCView._dispatch_item at the first press
    view.message = plain        # what py-cord sets at every press

    await view.on_timeout()

    assert sent.deleted, "the used info panel stayed: deletion went to the channel route"
