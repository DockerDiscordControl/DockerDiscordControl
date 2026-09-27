# -*- coding: utf-8 -*-
"""The help describes the bot as it is, and both ways to it show the same help.

THE OPERATOR (2026-09-27), with a screenshot of the ❓ help: "can you update
the help?" Two helps were written separately - `/help` in slash_commands.py
and the ❓ button in control_ui.py - and both had fallen behind: the ❓ one
named two of seven commands, its "Admin panel" listed info text and logs
(which live behind ℹ️), and neither mentioned the container admin panel,
🔧 maintenance, the 🗂️ stack restart or the ✕ close button.

HOW THIS TEST CAN FAIL:
* both entry points render their embed; they must be the same help;
* every slash command DDC registers must be named in it - a new command
  that the help forgets turns this red;
* the buttons added since v2.4 must be explained;
* Discord refuses a field over 1024 characters or an embed over 6000.

COUNTER-CHECK (2026-09-27): red before - the ❓ help named only /ss and
/control, and neither help knew 🔧, 🗂️ or ✕.
"""

import ast
import asyncio
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

ROOT = Path(__file__).resolve().parents[2]


def _registered_commands():
    names = set()
    for path in (ROOT / "cogs").glob("*.py"):
        names |= set(re.findall(r'slash_command\(\s*name="([a-z]+)"', path.read_text(encoding="utf-8")))
    return names


def _text(embed):
    return "\n".join(f"{f.name}\n{f.value}" for f in embed.fields)


def _slash_help(monkeypatch):
    from cogs.slash_commands import SlashCommandsMixin

    sent = []
    ctx = MagicMock()
    ctx.defer = AsyncMock()
    ctx.followup.send = AsyncMock(side_effect=lambda *a, **k: sent.append(k.get("embed")))
    cog = MagicMock()
    cog._check_spam_protection = AsyncMock(return_value=True)
    asyncio.run(SlashCommandsMixin.help_command.callback(cog, ctx))
    return sent[0]


def _button_help(monkeypatch):
    import cogs.control_ui as control_ui

    monkeypatch.setattr(
        "services.infrastructure.spam_protection_service.get_spam_protection_service",
        lambda: MagicMock(is_enabled=lambda: False))
    button = next(cls for name, cls in vars(control_ui).items()
                  if name.endswith("HelpButton") and isinstance(cls, type))
    instance = button.__new__(button)
    instance.cog = MagicMock()
    instance.channel_id = 1
    sent = []
    interaction = MagicMock()
    interaction.user.id = 7
    interaction.user.name = "someone"
    interaction.response.defer = AsyncMock()
    interaction.response.is_done = MagicMock(return_value=True)
    interaction.followup.send = AsyncMock(side_effect=lambda *a, **k: sent.append(k.get("embed")))
    asyncio.run(button.callback(instance, interaction))
    return sent[0]


def test_both_ways_show_the_same_help(monkeypatch):
    slash, button = _slash_help(monkeypatch), _button_help(monkeypatch)
    assert slash is not None and button is not None
    assert _text(slash) == _text(button), "/help and the ❓ button show different helps"


def test_every_registered_command_is_named(monkeypatch):
    text = _text(_slash_help(monkeypatch))
    missing = [c for c in sorted(_registered_commands()) if f"/{c}" not in text]
    assert not missing, f"commands the help forgets: {missing}"


def test_the_newer_buttons_are_explained(monkeypatch):
    text = _text(_slash_help(monkeypatch))
    for mark in ("🔧", "🗂️", "✕", "⏰", "📋", "📝"):
        assert mark in text, f"{mark} is not explained"


def test_discord_accepts_it(monkeypatch):
    embed = _slash_help(monkeypatch)
    assert all(len(f.value) <= 1024 and len(f.name) <= 256 for f in embed.fields)
    assert len(embed) <= 6000 and len(embed.fields) <= 25
