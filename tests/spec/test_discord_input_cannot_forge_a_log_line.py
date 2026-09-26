# -*- coding: utf-8 -*-
"""Text typed into Discord cannot start a line of its own in the DDC log.

THE FINDING (Discord-input audit, 2026-09-26, F8): the /info container name
is free text (autocomplete only suggests) and the donation modal's name is
too; both were written into the log as they came. A modified client can send
a line break, and "vrising\\n2026-09-26 12:00:00 CEST - ddc.auth - WARNING -
Admin login from 10.0.0.5" reads, in the log the operator trusts, like a line
DDC wrote. The panel shows the log as text, so this is no XSS - it is a lie
in the one place the operator goes to find out what happened.

HOW THIS TEST CAN FAIL: it runs /info and the donation modal with a line
break in the text and reads every log record; none may carry the forged
line on a line of its own.

COUNTER-CHECK (2026-09-26): red before on both.
"""

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

FORGED = "FORGED - ddc.auth - WARNING - admin login"
EVIL = f"vrising\n{FORGED}"


def _forged_lines(caplog):
    return [r.getMessage() for r in caplog.records if f"\n{FORGED}" in r.getMessage()]


def test_the_info_command_logs_the_name_on_one_line(caplog):
    from cogs.slash_commands import SlashCommandsMixin

    cog = MagicMock()
    cog._check_spam_protection = AsyncMock(return_value=False)  # stop right after the log line
    ctx = MagicMock()
    ctx.author.id = 1
    ctx.channel_id = 2
    with caplog.at_level(logging.DEBUG):
        asyncio.run(SlashCommandsMixin.info_command.callback(cog, ctx, EVIL))

    assert not _forged_lines(caplog), _forged_lines(caplog)


def test_the_donation_modal_logs_the_name_on_one_line(caplog):
    from cogs.donation_ui import DonationBroadcastModal

    modal = DonationBroadcastModal.__new__(DonationBroadcastModal)
    modal.donation_manager_available = False
    modal.bot = MagicMock()
    modal.name_input = SimpleNamespace(value=EVIL)
    modal.amount_input = SimpleNamespace(value="")
    modal.share_input = SimpleNamespace(value="")
    inter = MagicMock()
    inter.response.send_message = AsyncMock()
    inter.followup.send = AsyncMock(return_value=MagicMock(delete=AsyncMock()))
    inter.edit_original_response = AsyncMock()
    inter.user.name = "someone"
    inter.user.id = 7
    with caplog.at_level(logging.DEBUG), \
         patch("cogs.donation_ui.load_config", return_value={"channel_permissions": {}}):
        asyncio.run(modal.callback(inter))

    assert not _forged_lines(caplog), _forged_lines(caplog)
