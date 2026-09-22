# -*- coding: utf-8 -*-
"""Switching donations off really takes /donate off the bot.

No ``@covers`` marker: a finding, not a guarantee.

THE FINDING (stage 4 review, stage B, section 06 F7, re-checked 2026-09-20):
when the operator switches donations off, ``setup()`` tried to remove the two
commands with ``if cmd_name in bot.application_commands: del
bot.application_commands[cmd_name]``. In py-cord 2.6.1 (measured in the
running container) ``application_commands`` is a property that builds a new
LIST of command objects, so a string is never in it, the ``del`` never runs -
and had it run, it would have deleted from a throwaway list. The log line
"Removed /donate command - donations disabled" was written on a path that
removed nothing... and in fact never even reached that line. On top of that
the attempt ran before ``bot.add_cog(cog)``, when the cog's commands are not
on the bot yet: after ``add_cog`` they sit in ``pending_application_commands``
and ``application_commands`` is still empty.

Result for the operator: donations off in the web panel, /donate and
/donatebroadcast still there in Discord.
"""

from unittest.mock import patch

import discord
import pytest

from cogs.docker_control import _remove_donation_commands


class _DonationCommands(discord.Cog):
    """Stands in for the real cog: the two commands, and one that must stay."""

    @discord.slash_command(name="donate")
    async def donate(self, ctx):
        pass

    @discord.slash_command(name="donatebroadcast")
    async def donatebroadcast(self, ctx):
        pass

    @discord.slash_command(name="serverstatus")
    async def serverstatus(self, ctx):
        pass


def _bot_with_commands():
    bot = discord.Bot(intents=discord.Intents.default())
    bot.add_cog(_DonationCommands())
    return bot


def _names(bot):
    return sorted({command.name for command in bot.pending_application_commands}
                  | {command.name for command in bot.application_commands})


@pytest.mark.asyncio
async def test_the_commands_are_there_to_begin_with():
    """Guard against a blunt tool: an empty bot would pass the real test, too."""
    assert _names(_bot_with_commands()) == ["donate", "donatebroadcast", "serverstatus"]


@pytest.mark.asyncio
async def test_donations_off_removes_both_commands():
    bot = _bot_with_commands()

    with patch("services.donation.donation_utils.is_donations_disabled", return_value=True):
        _remove_donation_commands(bot)

    assert _names(bot) == ["serverstatus"], (
        "donations are switched off and the commands are still on the bot"
    )


@pytest.mark.asyncio
async def test_donations_on_keeps_them():
    bot = _bot_with_commands()

    with patch("services.donation.donation_utils.is_donations_disabled", return_value=False):
        _remove_donation_commands(bot)

    assert _names(bot) == ["donate", "donatebroadcast", "serverstatus"]
