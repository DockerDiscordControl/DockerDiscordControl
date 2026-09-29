# -*- coding: utf-8 -*-
"""A web-panel donation announcement that missed a channel says which one.

THE FINDING (stage 4 review before v3.1.0, section 06 pass 3 F1): an
announcement that reached some but not all of the channels that want it was
not flagged: the channel Discord could not find showed up only as a neutral
INFO line "found=False" and a DEBUG line. The ERROR fired only when NO
channel was reached - and the notification file is already deleted, so the
missed channel never gets it. The Discord path counts that case as failed.

THE CONTRACT: a channel that wants the announcement and cannot be found is
named at WARNING, and a partial result is said at WARNING.

HOW THIS TEST CAN FAIL: a missed channel is only INFO/DEBUG again.

It runs the loop body through setup(), as the Z8 test beside it does.

COUNTER-CHECK (2026-09-29): red before the change.
"""

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import cogs.docker_control as dc
from tests.spec.test_z8_web_donation_announcement_is_not_lost_silently import loop_body  # noqa: F401


def test_the_missed_channel_is_named(loop_body, monkeypatch, caplog):  # noqa: F811
    bot, body = loop_body
    monkeypatch.setattr(dc, "load_config", lambda: {"channel_permissions": {
        "111": {"donation_broadcasts": True}, "222": {"donation_broadcasts": True}}})
    found = SimpleNamespace(name="found", send=AsyncMock())
    bot.get_channel.side_effect = lambda cid: found if cid == 111 else None

    with caplog.at_level(logging.DEBUG):
        asyncio.run(body())

    warned = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("222" in m for m in warned), f"the missed channel was not named: {warned}"
