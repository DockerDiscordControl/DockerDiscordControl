# -*- coding: utf-8 -*-
"""One extension that fails to load does not keep the next one from loading.

THE FINDING (stage 4 review before v3.1.0, section 33 pass 3 F4 + pass 4
F1): load_extensions_step loads docker_control, auto_action_monitor and
translation_monitor in turn, and its comment says a failing one must not
stop the others. But py-cord raises discord.ExtensionFailed /
ExtensionNotFound / NoEntryPointError - ExtensionError, none of the types
the handler listed. A failing auto_action_monitor escaped the loop, and the
channel translation was never loaded. (The later startup steps still ran:
the sequence guards each step.)

THE CONTRACT: a failing extension is logged and the others still load;
docker_control stays the one whose failure stops the step, as before.

HOW THIS TEST CAN FAIL: an ExtensionError escapes the loop again.

COUNTER-CHECK (2026-09-29): the first case red before the change, the
docker_control case green before and after.
"""

import logging
from types import SimpleNamespace

import discord
import pytest

from app.bot.startup_context import StartupContext
from app.bot.startup_steps.commands import load_extensions_step


def _bot(failing):
    loaded = []

    def _load(name):
        if name == failing:
            raise discord.ExtensionFailed(name, ValueError("broken"))
        loaded.append(name)
    return SimpleNamespace(extensions={}, load_extension=_load), loaded


def _context(bot):
    return StartupContext(bot=bot, runtime=SimpleNamespace(logger=logging.getLogger("test.ext")))


async def test_the_translation_still_loads_after_a_failing_monitor():
    bot, loaded = _bot("cogs.auto_action_monitor")
    await load_extensions_step(_context(bot))
    assert "cogs.translation_monitor" in loaded, "a failing extension stopped the next one"


async def test_a_failing_docker_control_still_stops_the_step():
    bot, loaded = _bot("cogs.docker_control")
    with pytest.raises(discord.ExtensionError):
        await load_extensions_step(_context(bot))
