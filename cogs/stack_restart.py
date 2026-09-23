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
from typing import Dict, List, Tuple

import discord
from discord.ui import Button, Select

from cogs import admin_overview as ao
from cogs.translation_manager import _
from services.discord.embed_helper_service import fit_lines
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


def current_targets(want_stacks: bool = True) -> Dict[str, List[str]]:
    """{name: [container, ...]} - the operator's groups first, then Compose stacks.

    Two sources, one menu. The groups are what an Unraid server has (measured:
    0 of 37 containers carry a Compose label there); the stacks are what an
    installation built with docker-compose has. Dropping either would take a
    working button away from somebody.

    A group may name containers DDC no longer has - those are left out here, so
    the menu never offers to restart something that is not there.
    """
    targets: Dict[str, List[str]] = {}
    try:
        from services.config.group_service import get_group_service

        service = get_group_service()
        for group in service.get_groups():
            members = service.members_of(group.name)
            if members.containers:
                targets[group.name] = members.containers
    except OSError as e:
        # The button still offers the stacks; the groups are said to be missing
        # in the log rather than silently treated as "none defined".
        logger.error(f"Groups could not be read for the restart menu: {e}")

    if targets:
        # A group is enough to answer "is there anything to offer". Walking the
        # Compose stacks as well means reading every container file again, and
        # the admin overview asks this on every redraw (measured: 10 redraws =
        # 11 scans of the configuration). The stacks are gathered when the menu
        # is actually opened - offer_stacks calls this with want_stacks=True.
        if not want_stacks:
            return targets

    for stack, servers in current_stacks().items():
        targets.setdefault(stack, [s['docker_name'] for s in servers])
    return targets


def _servers_of(name: str) -> Tuple[List[dict], List[str]]:
    """(server entries, names that were left out) for a group or a Compose stack.

    Two filters drop members before anything is restarted: one for containers
    DDC no longer has (the group keeps naming them), one for containers that
    are switched off in DDC. Both were silent - the summary went out green over
    what was left, while the SAME group in a scheduled task is reported as a
    failure. Restarting the rest is right; calling it the whole group is not.
    """
    group_members = []
    missing = []
    try:
        from services.config.group_service import get_group_service

        members = get_group_service().members_of(name)
        if members.exists:
            group_members = members.containers
            missing = list(members.missing)
    except OSError as e:
        logger.error(f"Groups could not be read for the restart: {e}")

    wanted = group_members or current_targets().get(name) or []
    if not wanted:
        return [], missing
    all_servers = [s for s in ao.get_server_config_service().get_all_servers()
                   if isinstance(s, dict)]
    by_name = {s.get('docker_name'): s for s in all_servers if s.get('active', True)}
    inactive = {s.get('docker_name') for s in all_servers if not s.get('active', True)}
    missing += [container for container in wanted if container in inactive]
    return ([by_name[container] for container in wanted if container in by_name], missing)


async def _is_admin(interaction) -> bool:
    """The admin list at the moment of this press. Closed if it cannot be read -
    and then said in those words: "no permission" sends an admin looking for a
    list they were never removed from (the bulk buttons say it that way too)."""
    try:
        if await ao.get_admin_service().is_user_admin_async(str(interaction.user.id)):
            return True
        await interaction.followup.send(_("❌ You don't have permission for this action."), ephemeral=True)
        return False
    except (AttributeError, ImportError, RuntimeError) as e:
        logger.error(f"Could not check admin status for the stack restart: {e}", exc_info=True)
        await interaction.followup.send(
            _("❌ Your permission could not be checked. Nothing was done."), ephemeral=True)
        return False


async def offer_stacks(cog, channel_id: int, interaction) -> None:
    """The first press: the stacks to choose from, for an admin."""
    if not await _is_admin(interaction):
        return
    names = current_targets(want_stacks=True)
    if not names:
        await interaction.followup.send(
            _("ℹ️ There is no container group yet, and none of the active containers "
              "belongs to a Compose stack."), ephemeral=True)
        return
    description = _("Choose the group or Compose stack to restart.")
    if len(names) > MAX_OPTIONS:
        # A menu holds 25 options; say which part of the list is shown instead of
        # leaving the admin to wonder where their stack went.
        logger.info(f"Stack restart: {len(names)} stacks, the menu shows the first {MAX_OPTIONS}")
        description += "\n" + _("Showing the first {shown} of {total} stacks - {missing} are not "
                                "in the menu.").format(shown=MAX_OPTIONS, total=len(names),
                                                       missing=len(names) - MAX_OPTIONS)
    embed = discord.Embed(title=_("🔄 Restart a stack"), description=description,
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
        # The option's VALUE may hold 100 characters too, and a Compose project
        # name is the operator's, of any length - so the value is the position
        # in this menu and the name is looked up from it.
        self._by_value = {str(index): stack for index, stack in enumerate(self.stacks)}
        options = [discord.SelectOption(label=stack[:100], value=value,
                                        description=_("{count} containers").format(
                                            count=len(self.stacks[stack])))
                   for value, stack in self._by_value.items()]
        super().__init__(placeholder=_("Choose a stack"), options=options,
                         custom_id="restart_stack_select", min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction) -> None:
        stack = self._by_value.get(self.values[0], self.values[0])
        # Escaped and cut: the name and the member list are the operator's data,
        # and Discord refuses a description past 4096 characters
        members = fit_lines([f"`{name}`" for name in self.stacks.get(stack, [])], separator=", ",
                            limit=3500, more=lambda count: _("… and {count} more").format(count=count))
        embed = discord.Embed(
            title=_("⚠️ Confirm Restart Stack"),
            description=_("Restart the running containers of the stack **{stack}**?\n\n{members}").format(
                stack=discord.utils.escape_markdown(stack), members=members),
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
            return
        if getattr(self.cog, '_bulk_operation_in_progress', False):
            await interaction.followup.send(_("⏳ Another bulk operation is in progress. Please wait."),
                                            ephemeral=True)
            return
        self.cog._bulk_operation_in_progress = True
        try:
            # Both sources, like the menu: a group the operator defined is not in
            # current_stacks(), and looking only there told the admin "the stack
            # has no active containers any more" about a group full of them.
            members, not_touched = _servers_of(self.stack)
            if not members:
                await interaction.followup.send(
                    _("❌ **{stack}** has no active containers any more.").format(stack=self.stack),
                    ephemeral=True)
                return
            from services.docker_service.docker_action_service import docker_action_service_first
            logger.info(f"Restart stack {self.stack}: {[m['docker_name'] for m in members]}")
            counts = await ao._restart_running_servers(members, docker_action_service_first)
            summary = ao._restart_summary(counts)
            if not_touched:
                # Named, not swallowed: the same group in a scheduled task is a
                # failure when a member is gone, and a green embed over four of
                # seven is the "act on fewer and say done" this feature forbids.
                summary += "\n" + _("Not touched (not in DDC, or switched off): {names}").format(
                    names=", ".join(f"`{name}`" for name in not_touched[:20]))
            embed = discord.Embed(
                title=_("🔄 Stack {stack} restarted").format(
                    stack=discord.utils.escape_markdown(self.stack)[:180]),
                description=summary,
                color=discord.Color.green() if counts["failed"] == 0 else discord.Color.orange())
            await ao.answer_or_post(interaction, self.cog, self.channel_id, embed)
            asyncio.create_task(self._refresh_overview_later())
        finally:
            self.cog._bulk_operation_in_progress = False

    async def _refresh_overview_later(self):
        try:
            await asyncio.sleep(5)
            await ao._refresh_tracked_admin_overview(self.cog, self.channel_id)
        except (discord.errors.DiscordException, RuntimeError, AttributeError) as e:
            logger.error(f"Error updating admin overview after the stack restart: {e}", exc_info=True)
