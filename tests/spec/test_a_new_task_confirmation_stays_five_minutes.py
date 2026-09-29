# -*- coding: utf-8 -*-
"""The confirmation of a new restart/stop task stays for five minutes.

THE FINDING (stage 4 review, targeted pass R2-1): the confirmation carries two
dropdowns (wait for empty, warning). The ✕ would sit alone on a third row, so
under the rule of 2026-09-27 it was dropped and the panel was given the
one-minute auto-close - although the view asked for 300 s. One minute is too
short to read the task and choose two options.

THE OPERATOR (2026-09-29): five minutes for this confirmation. The ✕ still
does not stand alone; only the minute does not apply. A view says so with
``KEEPS_ITS_TIMEOUT``.

COUNTER-CHECK: red before the change (timeout 60); the plain select-only
panel below must still get the one minute, or the exemption leaked into the
rule itself.
"""

import discord
import pytest

from cogs.ddc_ui import AUTO_CLOSE_SECONDS, CloseButton, PrivateView
from cogs.task_player_options import TaskPlayerOptionsView


class _SelectOnly(PrivateView):
    def __init__(self):
        super().__init__(timeout=300)
        self.add_item(discord.ui.Select(options=[discord.SelectOption(label="a")]))


@pytest.mark.asyncio
async def test_the_task_confirmation_keeps_its_five_minutes():
    view = TaskPlayerOptionsView("t1", "nginx")
    assert view.timeout == 300, f"the confirmation closes after {view.timeout} s"
    assert not any(isinstance(i, CloseButton) for i in view.children), \
        "the ✕ stands alone on a row again"


@pytest.mark.asyncio
async def test_other_panels_still_close_after_a_minute():
    assert _SelectOnly().timeout == AUTO_CLOSE_SECONDS
