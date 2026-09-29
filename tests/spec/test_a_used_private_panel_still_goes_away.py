# -*- coding: utf-8 -*-
"""A private panel that was used still takes itself away when it times out.

THE FINDING (stage 4 review before v3.1.0, section 38 pass 4 F8): as soon as
somebody presses anything on a private panel, py-cord 2.6.1 replaces
view.message with interaction.message - a plain discord.Message
(View._dispatch_item: "self.message = interaction.message"). At the timeout
DDCView.on_timeout called message.delete() on it, which is DELETE
/channels/{id}/messages/{id}; for an ephemeral message Discord answers 404.
The NotFound went to DEBUG and the dead panel stayed - for every panel that
had actually been used. Example: the 🔧 maintenance panel - pick a container,
wait five minutes, and it stays.

THE CONTRACT: the message DDC sent the panel with (a WebhookMessage, whose
delete() goes through the interaction's own route) is remembered before the
first press replaces it, and the timeout deletes through it.

HOW THIS TEST CAN FAIL: a used panel is deleted over the channel route again.

It goes through py-cord's own dispatch (View._dispatch_item) on the real
MaintenanceView.

COUNTER-CHECK (2026-09-29): red before the change.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest

from cogs.watchdog_maintenance import MaintenanceView


class _SentPanel(discord.WebhookMessage):
    """What followup.send(..., wait=True) returns - only what on_timeout reads."""

    def __init__(self):
        self.id = 42
        self.flags = SimpleNamespace(ephemeral=True)
        self._state = SimpleNamespace(_view_store=SimpleNamespace(_synced_message_views={}))
        self.deleted = AsyncMock()

    async def delete(self, *args, **kwargs):
        await self.deleted()


@pytest.mark.asyncio
async def test_a_panel_that_was_used_is_deleted_through_its_own_route(monkeypatch):
    monkeypatch.setattr("cogs.ddc_ui.is_private_panel_message", lambda message: True)
    view = MaintenanceView(["web"], {})
    view.message = sent = _SentPanel()

    plain = SimpleNamespace(id=42, flags=SimpleNamespace(ephemeral=True),
                            _state=sent._state,
                            delete=AsyncMock(side_effect=discord.NotFound(
                                SimpleNamespace(status=404, reason="Not Found"), "Unknown Message")))
    interaction = SimpleNamespace(message=plain, response=SimpleNamespace(defer=AsyncMock()))
    monkeypatch.setattr(view, "_scheduled_task", AsyncMock())
    view._dispatch_item(view.select, interaction)       # py-cord's own dispatch

    await view.on_timeout()

    assert sent.deleted.await_count == 1, (
        "the used panel was deleted over the channel route (404 for an ephemeral "
        "message) and stayed")
