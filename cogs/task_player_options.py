# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""The player options of a task created in Discord (v3.1.0).

A restart or stop task can wait until nobody plays and warn beforehand
(services/scheduling/player_gate.py). In the web panel these are three fields;
in Discord the task is built from dropdowns in five rows, and a one-time task
already fills all of them. So the options come AFTER the task exists: the
confirmation carries two dropdowns with fixed steps, and each choice is saved at
once - through normalize_options, like the panel, and with the same notice when
the player count cannot be read.
"""

import asyncio
from typing import List, Optional

import discord

from services.config.config_service import load_config
from utils.logging_utils import get_module_logger
from .ddc_ui import NOTICE_STAYS_FOR, PrivateView
from .translation_manager import _

logger = get_module_logger('task_player_options')

WAIT_STEPS = (0, 60, 120, 240)          # minutes; 0 = run at the scheduled time
WARN_STEPS = (0, 5, 10, 15, 30)         # minutes before


def _may_edit(interaction: discord.Interaction, container_name: str) -> bool:
    """The rule that let the task be created: the channel's schedule permission or an admin."""
    from .control_helpers import _channel_has_permission, _admin_may_control
    return (_channel_has_permission(interaction.channel_id, 'schedule', load_config())
            or _admin_may_control(interaction.user.id, container_name))


def _save(task_id: str, change: dict) -> tuple:
    """(task, None, warnings) or (None, reason, []) - the options merged, checked, saved."""
    from services.scheduling.scheduler import find_task_by_id, update_task
    from services.scheduling.player_gate import normalize_options, query_problems
    task = find_task_by_id(task_id)
    if task is None:
        return None, _("The task does not exist any more."), []
    merged = dict(task.options or {})
    merged.update(change)
    if not merged.get("wait_for_empty"):
        merged.pop("max_wait_minutes", None)
    options, error = normalize_options(merged, task.action)
    if error:
        return None, error, []
    task.options = options
    if not update_task(task, check_collision=False):
        return None, _("The task could not be saved."), []
    warnings: List[str] = []
    if options.get("wait_for_empty"):
        problems = query_problems(task.container_name, getattr(task, 'target_is_group', False))
        if problems:
            warnings.append(_("The player count cannot be read, so the server counts as empty "
                              "and the task runs at its time: {problems}").format(problems="; ".join(problems)))
    return task, None, warnings


class WaitForEmptySelect(discord.ui.Select):
    def __init__(self, task_id: str, container_name: str, row: int = 0):
        self.task_id = task_id
        self.container_name = container_name
        options = [discord.SelectOption(label=_("Run at its time"), value="0", emoji="⏰", default=True)]
        for minutes in WAIT_STEPS[1:]:
            options.append(discord.SelectOption(
                label=_("Only when nobody plays - at most {hours} h").format(hours=minutes // 60),
                value=str(minutes), emoji="👥"))
        super().__init__(placeholder=_("Wait for an empty server?"), options=options, row=row)

    async def callback(self, interaction: discord.Interaction) -> None:
        minutes = int(self.values[0])
        change = ({"wait_for_empty": True, "max_wait_minutes": minutes} if minutes
                  else {"wait_for_empty": False})
        await _answer(interaction, self.task_id, self.container_name, change)


class WarnSelect(discord.ui.Select):
    def __init__(self, task_id: str, container_name: str, row: int = 1):
        self.task_id = task_id
        self.container_name = container_name
        options = [discord.SelectOption(label=_("No warning"), value="0", emoji="🔕", default=True)]
        for minutes in WARN_STEPS[1:]:
            options.append(discord.SelectOption(
                label=_("Warn in Discord {minutes} minutes before").format(minutes=minutes),
                value=str(minutes), emoji="⚠️"))
        super().__init__(placeholder=_("Warn the players before?"), options=options, row=row)

    async def callback(self, interaction: discord.Interaction) -> None:
        await _answer(interaction, self.task_id, self.container_name,
                      {"warn_minutes": int(self.values[0])})


async def _answer(interaction: discord.Interaction, task_id: str, container_name: str, change: dict) -> None:
    if not _may_edit(interaction, container_name):
        await interaction.response.send_message(
            f"❌ {_('This action is not allowed in this channel.')}",
            ephemeral=True, delete_after=NOTICE_STAYS_FOR)
        return
    # Acknowledge first, then save in a worker thread: _save takes the tasks
    # lock and writes tasks.json (often on a network mount - rule B8 in the
    # scheduler), and asks for the player count. On the loop it stalled the
    # bot and could miss Discord's 3 seconds; an exception out of it left
    # "This interaction failed" (second review before v3.1.0).
    await interaction.response.defer(ephemeral=True)
    try:
        task, error, warnings = await asyncio.to_thread(_save, task_id, change)
    except Exception as e:  # noqa: BLE001 - whatever it was, the member gets an answer
        logger.error(f"Saving the player options of task {task_id} failed: {e}", exc_info=True)
        await interaction.followup.send(f"❌ {_('Could not save the change.')}", ephemeral=True,
                                        delete_after=NOTICE_STAYS_FOR)
        return
    if error:
        await interaction.followup.send(f"❌ {error}", ephemeral=True, delete_after=NOTICE_STAYS_FOR)
        return
    from services.scheduling.player_gate import describe
    text = f"✅ {_('Saved')}: {describe(task.options) or _('runs at its time, no warning')}"
    if warnings:
        text += "\n⚠️ " + " ".join(warnings)
    await interaction.followup.send(text, ephemeral=True, delete_after=NOTICE_STAYS_FOR)


class TaskPlayerOptionsView(PrivateView):
    """The two dropdowns under the confirmation of a new restart/stop task."""

    def __init__(self, task_id: str, container_name: str, timeout: Optional[float] = 300):
        super().__init__(timeout=timeout)
        self.add_item(WaitForEmptySelect(task_id, container_name, row=0))
        self.add_item(WarnSelect(task_id, container_name, row=1))
