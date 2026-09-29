# -*- coding: utf-8 -*-
"""A live-log panel renewed before its timeout is not killed by the view it replaced.

THE FINDING (stage 4 review before v3.1.0, section 09 pass 4 F1): the live
log panel renews itself at 270 s with a fresh view, so it never reaches the
5-minute timeout. But the replaced view was never stopped: its own timeout
fired 30 s later, disabled its buttons and edited the SAME message back to
itself with the "view timed out" footer. From five minutes on the user saw
dead buttons, and the renewal promised the opposite.

THE CONTRACT: the replaced view lets go of the message and stops; its
timeout no longer touches the panel.

HOW THIS TEST CAN FAIL: the old view edits the panel after the renewal.

COUNTER-CHECK (2026-09-29): red before the change.
"""

from unittest.mock import AsyncMock, MagicMock

import discord

import cogs.status_info_integration as sii


async def test_the_old_view_leaves_the_renewed_panel_alone(monkeypatch):
    monkeypatch.setattr(sii, "container_logs_text", AsyncMock(return_value="x"))
    old = sii.LiveLogView("nginx")
    message = MagicMock()
    message.embeds = [discord.Embed(title="📄 Logs - nginx")]
    message.edit = AsyncMock()
    old.message_ref = message

    await old._recreate_view()
    renewed_with = message.edit.await_args.kwargs["view"]
    await old.on_timeout()

    assert message.edit.await_args.kwargs["view"] is renewed_with, (
        "the replaced view's timeout edited the renewed panel back to itself, buttons dead")
