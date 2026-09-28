# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""The one help DDC shows - for `/help` and for the ❓ button alike.

THE OPERATOR (2026-09-27), with a screenshot of the ❓ help: "can you update
the help?" There were two helps, written separately in slash_commands.py and
control_ui.py. They had drifted apart before (a comment said so), and by then
both described a bot that no longer existed: the ❓ one knew two commands, and
its "Admin panel" listed info text and logs, which moved behind ℹ️ long ago,
while the container admin panel, 🔧 maintenance, the stack restart and the
task buttons appeared nowhere. One builder now serves both, so the two cannot
drift again.

IT CALLS _() ITSELF, like group_help_field: the check that every bot string
is a catalogue key reads the literals handed to the translation function in
the module that imports it.
"""

from __future__ import annotations

import discord

from .translation_manager import _

SPACER = "\n​"


def help_fields():
    """[(name, value)] of the help, in the order it is shown."""
    from cogs.group_control import group_help_field

    fields = [
        (_("Commands"),
         f"`/serverstatus` · `/ss` - {_('(Re)generates the Server Overview panel in status channels')}\n"
         f"`/control` - {_('(Re)generates the Admin Overview in control channels')}\n"
         f"`/info <container>` - {_('Shows detailed container information.')}\n"
         f"`/addadmin` - {_('Add a user to the admin list')}\n"
         f"`/donate` - {_('Shows donation information to support the project.')}\n"
         f"`/ping` - {_('Checks the bot latency.')}\n"
         f"`/help` - {_('Shows this help message.')}"),
        (_("Status Indicators"),
         f"🟢 {_('Container is online')}\n"
         f"⚠️ {_('Container runs, the game server in it does not answer')}\n"
         f"🔴 {_('Container is offline')}\n"
         f"❓ {_('Container not found')}\n"
         f"🔄 {_('Container status loading')}\n"
         f"🟡 {_('Action pending (start, stop or restart)')}"),
        (_("Buttons"),
         f"**{_('Mech')}** - {_('Shows detailed mech stats and the donation system')}\n"
         f"ℹ️ **{_('Info')}** - {_('Shows container details and, on a game server, who plays')}\n"
         f"🛠️ **{_('Admin')}** - {_('Opens admin control panel')}\n"
         f"❓ **{_('Help')}** - {_('Shows this help message')}"),
        (_("Container Controls"),
         f"▶️ **{_('Start')}** - {_('Starts the container')}\n"
         f"⏹️ **{_('Stop')}** - {_('Stops the container')}\n"
         f"🔄 **{_('Restart')}** - {_('Restarts the container')}"),
    ]
    group_name, group_value = group_help_field()
    fields.append((group_name.strip("*"), group_value.rstrip("​").rstrip("\n")))
    fields += [
        (_("Admin Overview"),
         f"🛠️ {_('Pick a container or group and open its admin panel')}\n"
         f"🔄 {_('Restart all containers')}\n"
         f"⏹️ {_('Stop all containers')}\n"
         f"💖 {_('Support DDC')}"),
        (_("Container admin panel"),
         f"▶️ ⏹️ 🔄 {_('Start, stop or restart it')}\n"
         f"ℹ️ {_('Its info, with 📝 info text, ⏰ scheduled tasks and 📋 logs')}\n"
         f"🔧 {_('Watchdog maintenance: no alerts and no restarts while you work on it - shown when a watchdog rule watches it')}\n"
         f"✕ {_('Closes the panel; a panel without it closes itself after a minute')}"),
        (_("Task Scheduling"),
         f"⏰ {_('Click to manage scheduled tasks')}\n"
         f"➕ **{_('Add Task')}** - {_('Schedule container actions (daily, weekly, monthly, yearly, once)')}\n"
         f"❌ **{_('Delete Tasks')}** - {_('Remove scheduled tasks for the container')}"),
        (_("Info System"),
         f"ℹ️ {_('Click for container details')}\n"
         f"🔒 {_('Protected info (control channels only)')}\n"
         f"🔓 {_('Public info available')}"),
    ]
    return fields


def help_embed() -> discord.Embed:
    """The finished help embed; a blank line between sections, none after the last."""
    embed = discord.Embed(title=_("DDC Help & Information"), color=discord.Color.blue())
    fields = help_fields()
    for index, (name, value) in enumerate(fields):
        spacer = SPACER if index < len(fields) - 1 else ""
        embed.add_field(name=f"**{name}**", value=value + spacer, inline=False)
    embed.set_footer(text="https://ddc.bot")
    return embed
