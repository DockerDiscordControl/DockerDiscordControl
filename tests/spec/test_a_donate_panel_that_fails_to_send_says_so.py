# -*- coding: utf-8 -*-
"""A /donate panel that cannot be sent with its buttons says so, and logs why.

THE FINDING (stage 4 review before v3.1.0, section 05 pass 3 F2): any
failure building the DonationView or sending the panel with its buttons was
swallowed by a bare `except Exception` with no log line, and the fallback
posted the same embed - whose field says "Click one of the buttons below" -
without buttons, untracked, without its auto-delete timer.

THE CONTRACT: the failure is logged at ERROR with its traceback, and the
caller gets a private notice instead of a panel whose buttons are missing.

HOW THIS TEST CAN FAIL: a buttonless panel is posted again, or nothing is
logged.

COUNTER-CHECK (2026-09-29): red before the change; a panel that sends is
unchanged (test_donate_is_no_megaphone.py).
"""

import logging
from unittest.mock import MagicMock

import discord

from tests.spec.test_donate_is_no_megaphone import _Ctx, _run_donate


def test_a_panel_that_cannot_be_sent_is_not_resent_without_buttons(monkeypatch, caplog):
    ctx = _Ctx(channel_id=55)
    sent = ctx.followup.send

    async def _send(*args, **kwargs):
        if "view" in kwargs:
            raise discord.HTTPException(MagicMock(status=400, reason="Bad Request"), "component")
        return await sent(*args, **kwargs)
    ctx.followup.send = _send

    with caplog.at_level(logging.WARNING):
        _run_donate(ctx, monkeypatch)

    promised = [m for m in ctx.sent if m["embed"] is not None and any(
        "button" in (field.value or "").lower() for field in m["embed"].fields)]
    assert not promised, "a panel promising buttons was posted without any"
    assert any(r.levelno >= logging.ERROR and r.exc_info for r in caplog.records), (
        "the failure left no line in the log")
    assert ctx.sent and all(m["ephemeral"] for m in ctx.sent), "the caller was not told privately"
