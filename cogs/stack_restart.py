# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Restart one Compose stack from the Admin Overview (roadmap Phase 4c).

The stack button of the Admin Overview (AdminOverviewRestartStackButton in
admin_overview.py) offers the stacks of the active servers; picking one asks
for confirmation, and the confirming press restarts that stack's running
containers with the routine "Restart All" uses.

The stacks come from the status cache (compose_project, the
com.docker.compose.project label). Every press reads the admin list at that
moment (Z5); like the other bulk buttons no channel permission is asked
(SPEC.md B2). The confirming press reads the stack again rather than
trusting the list shown a moment ago - a container recreated into another
stack in between is not restarted with its old one.

Services are reached through the admin_overview module, so the one seam the
bulk-button tests patch covers this flow as well.
Test: tests/spec/test_a_stack_can_be_restarted_from_discord.py
"""

import asyncio
import logging
from typing import Dict, List

import discord
from discord.ui import Button, Select

from cogs import admin_overview as ao
from cogs.translation_manager import _
from .ddc_ui import DDCView

logger = logging.getLogger('ddc.stack_restart')

MAX_OPTIONS = 25  # Discord's limit for one select menu


def _project_of(entry):
    data = (entry or {}).get('data')
    return getattr(data, 'compose_project', None) or None


def stacks_of(servers, cache) -> Dict[str, List[dict]]:
    """{stack: [server, ...]} for the active servers, in the server order."""
    stacks: Dict[str, List[dict]] = {}
    for server in servers:
        if not isinstance(server, dict) or not server.get('active', True):
            continue
        name = server.get('docker_name')
        project = _project_of(cache.get(name)) if name else None
        if project:
            stacks.setdefault(project, []).append(server)
    return stacks


def current_stacks() -> Dict[str, List[dict]]:
    return stacks_of(ao.get_server_config_service().get_all_servers(), ao.get_status_cache_service())


async def _is_admin(interaction) -> bool:
    """The admin list at the moment of this press; unreadable means no."""
    try:
        return await ao.get_admin_service().is_user_admin_async(str(interaction.user.id))
    except (AttributeError, ImportError, RuntimeError) as e:
        logger.error(f"Could not check admin status for the stack restart: {e}", exc_info=True)
        return False


async def offer_stacks(cog, channel_id: int, interaction) -> None:
    """The first press: the stacks to choose from, for an admin."""
    if not await _is_admin(interaction):
        await interaction.followup.send(_("❌ You don't have permission for this action."), ephemeral=True)
        return
    stacks = current_stacks()
    if not stacks:
        await interaction.followup.send(
            _("ℹ️ None of the active containers belongs to a Compose stack."), ephemeral=True)
        return
    names = {stack: [s['docker_name'] for s in members] for stack, members in stacks.items()}
    if len(names) > MAX_OPTIONS:
        logger.info(f"Stack restart: {len(names)} stacks, the menu shows the first {MAX_OPTIONS}")
    embed = discord.Embed(title=_("🔄 Restart a stack"),
                          description=_("Choose the Compose stack to restart."),
                          color=discord.Color.orange())
    await interaction.followup.send(embed=embed, view=StackPickView(cog, channel_id, names), ephemeral=True)


class StackPickView(DDCView):
    def __init__(self, cog, channel_id: int, stacks: Dict[str, List[str]]):
        super().__init__(timeout=60)
        self.add_item(StackSelect(cog, channel_id, stacks))
        self.add_item(ao.CancelBulkActionButton())


class StackSelect(Select):
    def __init__(self, cog, channel_id: int, stacks: Dict[str, List[str]]):
        self.cog = cog
        self.channel_id = channel_id
        self.stacks = dict(list(stacks.items())[:MAX_OPTIONS])
        options = [discord.SelectOption(label=stack[:100], value=stack,
                                        description=_("{count} containers").format(count=len(members)))
                   for stack, members in self.stacks.items()]
        super().__init__(placeholder=_("Choose a stack"), options=options,
                         custom_id="restart_stack_select", min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction) -> None:
        stack = self.values[0]
        members = ", ".join(f"`{name}`" for name in self.stacks.get(stack, []))
        embed = discord.Embed(
            title=_("⚠️ Confirm Restart Stack"),
            description=_("Restart the running containers of the stack **{stack}**?\n\n{members}").format(
                stack=stack, members=members),
            color=discord.Color.orange())
        await interaction.response.edit_message(embed=embed, view=RestartStackConfirmationView(
            self.cog, self.channel_id, stack))


class RestartStackConfirmationView(DDCView):
    def __init__(self, cog, channel_id: int, stack: str):
        super().__init__(timeout=30)
        self.add_item(ConfirmRestartStackButton(cog, channel_id, stack))
        self.add_item(ao.CancelBulkActionButton())


class ConfirmRestartStackButton(Button):
    def __init__(self, cog, channel_id: int, stack: str):
        self.cog = cog
        self.channel_id = channel_id
        self.stack = stack
        super().__init__(style=discord.ButtonStyle.danger, label=_("Yes, Restart Stack"),
                         custom_id="confirm_restart_stack")

    async def callback(self, interaction: discord.Interaction) -> None:
        try:
            await interaction.response.defer()
        except (discord.errors.NotFound, discord.errors.HTTPException) as e:
            logger.warning(f"Stack restart confirmation could not be answered: {e}")
            return
        if not await _is_admin(interaction):
            await interaction.followup.send(_("❌ You don't have permission for this action."), ephemeral=True)
            return
        if getattr(self.cog, '_bulk_operation_in_progress', False):
            await interaction.followup.send(_("⏳ Another bulk operation is in progress. Please wait."),
                                            ephemeral=True)
            return
        self.cog._bulk_operation_in_progress = True
        try:
            members = current_stacks().get(self.stack, [])
            if not members:
                await interaction.followup.send(
                    _("❌ The stack **{stack}** has no active containers any more.").format(stack=self.stack),
                    ephemeral=True)
                return
            from services.docker_service.docker_action_service import docker_action_service_first
            logger.info(f"Restart stack {self.stack}: {[m['docker_name'] for m in members]}")
            counts = await ao._restart_running_servers(members, docker_action_service_first)
            embed = discord.Embed(
                title=_("🔄 Stack {stack} restarted").format(stack=self.stack),
                description=ao._restart_summary(counts),
                color=discord.Color.green() if counts["failed"] == 0 else discord.Color.orange())
            await interaction.followup.send(embed=embed, ephemeral=True)
            asyncio.create_task(self._refresh_overview_later())
        finally:
            self.cog._bulk_operation_in_progress = False

    async def _refresh_overview_later(self):
        try:
            await asyncio.sleep(5)
            await ao._refresh_tracked_admin_overview(self.cog, self.channel_id)
        except (discord.errors.DiscordException, RuntimeError, AttributeError) as e:
            logger.error(f"Error updating admin overview after the stack restart: {e}", exc_info=True)
