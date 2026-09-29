# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Control UI components for Discord interaction."""

import asyncio
from collections import OrderedDict
from services.config.config_service import load_config
from services.config.server_config_service import get_server_config_service
import discord
import time
from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING
from discord.ui import View, Button

if TYPE_CHECKING:
    from .docker_control import DockerControlCog

from utils.time_utils import format_datetime_with_timezone
from .control_helpers import (_admin_may_control, _admin_may_control_task, refused_while_busy,
                              _channel_has_permission, _get_pending_embed,
                              _is_registered_admin, is_private_panel_message)
from .action_effect import not_confirmed_embed, panel_embed_after, wait_until_the_action_took_effect
from utils.logging_utils import get_module_logger
from services.infrastructure.container_info_service import MAX_CUSTOM_TEXT
from services.infrastructure.action_logger import log_user_action
from .translation_manager import _
from .ddc_ui import NOTICE_STAYS_FOR, DDCView, PrivateView
from .group_control import (group_entries, is_group_target, admin_control_view,
                            admin_panel_embed, running_state_for)

logger = get_module_logger('control_ui')

# =============================================================================
# ULTRA-PERFORMANCE CACHING SYSTEM FOR TOGGLE OPERATIONS
# =============================================================================

# Global caches for performance optimization
_timestamp_format_cache = {}      # Cache for formatted timestamps
_view_cache = {}                 # Cache for view objects
_box_element_cache = OrderedDict()  # Cache for box elements (LRU via OrderedDict)
_container_static_data = {}      # Cache for static container data
_view_template_cache = {}        # Cache for view templates per container state

# Description templates for fast string generation
# {player_line} is the optional game-server player-count line ("│ Players: x/y\n" or "", from format_player_line).
# It must mirror the background status-loop renderer (cogs/status_handlers.py) so the count
# does NOT flicker away when the user toggles Expand/Collapse.

def _clear_caches():
    """Clears all performance caches - called periodically."""
    _timestamp_format_cache.clear()
    _view_cache.clear()
    _box_element_cache.clear()
    _container_static_data.clear()
    _view_template_cache.clear()
    logger.info("All performance caches cleared")

# =============================================================================
# BOX ELEMENT CACHING
# =============================================================================

def _get_cached_box_elements(display_name: str, box_width: int = 28) -> dict:
    """Cache for box header/footer per container - 98% faster."""
    cache_key = f"{display_name}_{box_width}"
    if cache_key not in _box_element_cache:
        header_text = f"── {display_name} "
        max_name_len = box_width - 4
        if len(header_text) > max_name_len:
            header_text = header_text[:max_name_len-1] + "… "
        padding_width = max(1, box_width - 1 - len(header_text))

        _box_element_cache[cache_key] = {
            'header_line': f"┌{header_text}{'─' * padding_width}",
            'footer_line': f"└{'─' * (box_width - 1)}"
        }

        # LRU eviction: remove oldest entries if cache too large
        if len(_box_element_cache) > 50:
            # Remove 10 oldest entries at once (batch cleanup)
            for _ in range(10):
                if len(_box_element_cache) > 50:
                    _box_element_cache.popitem(last=False)
    else:
        # Move to end for LRU
        _box_element_cache.move_to_end(cache_key)

    return _box_element_cache[cache_key]

# =============================================================================
# OPTIMIZATION 4: ULTRA-FAST STATIC CONTAINER DATA CACHING
# =============================================================================

def _get_container_static_data(display_name: str, docker_name: str) -> dict:
    """Cache for static container data that never changes - 80% faster."""
    if display_name not in _container_static_data:
        _container_static_data[display_name] = {
            'custom_id_start': f"start_{docker_name}",
            'custom_id_stop': f"stop_{docker_name}",
            'custom_id_restart': f"restart_{docker_name}",
            'box_elements': _get_cached_box_elements(display_name, 28),
            'short_name': display_name[:20] + "..." if len(display_name) > 23 else display_name
        }

        # Prevent cache from growing too large (keep last 100 containers)
        if len(_container_static_data) > 100:
            oldest_key = next(iter(_container_static_data))
            del _container_static_data[oldest_key]

    return _container_static_data[display_name]

# =============================================================================
# PERMISSION CACHING
# =============================================================================

def _get_cached_channel_permission(channel_id: int, permission_key: str, current_config: dict) -> bool:
    """The channel's permission as the given configuration says NOW.

    No cache any more (the name stays for its callers). It cached under a key
    built from config['_cache_timestamp'], which nothing ever sets, and the
    hot-reload after a panel save did not clear it - a revoked control right
    stayed effective until the 5-minute cache clear. The operator decided on
    2026-09-16 that a revoked right is ineffective immediately (SPEC.md Z5),
    and the lookup it saved is a dictionary read (review A4).
    """
    return _channel_has_permission(channel_id, permission_key, current_config)

# =============================================================================
# ULTRA-OPTIMIZED ACTION BUTTON CLASS
# =============================================================================

def _log_background_task_exception(task: asyncio.Task, label: str) -> None:
    """Done-callback helper: log (instead of silently swallowing) a background task's exception."""
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error(f"[ACTION_BTN] Background task '{label}' failed: {exc}", exc_info=exc)


def _make_action_done_callback(cog, docker_name: str, pending_entry: dict, label: str):
    """Build the done-callback for a background Docker action task.

    Logs any exception and always releases the container's pending_actions entry - but only
    if it is still the entry this action created (a newer action may have replaced it).
    """
    def _on_done(task: asyncio.Task) -> None:
        _log_background_task_exception(task, label)
        if cog.pending_actions.get(docker_name) is pending_entry:
            del cog.pending_actions[docker_name]
    return _on_done


# Discord shows at most this many options in one select. It is a hard limit of
# the platform, not a choice DDC gets to make.
DISCORD_SELECT_LIMIT = 25


# The two option values that mean "turn the page" rather than "this container".
# They cannot collide with a container name: Docker names cannot contain spaces
# or the arrow characters.
SELECT_PAGE_PREV = "__ddc_page_prev__"
SELECT_PAGE_NEXT = "__ddc_page_next__"

# Room for both arrows on every page, so the page boundaries are the same
# whichever direction the operator arrives from. Page 1 could hold one more
# (it has no way back), but then "previous" from page 2 would land somewhere
# else than page 1 started, which is how off-by-one paging bugs are made.
CONTAINERS_PER_PAGE = DISCORD_SELECT_LIMIT - 2


def _page_of(containers, page):
    """The slice of `containers` shown on `page`, and whether there is more.

    E37 repaired the silence around ``containers[:25]``: the placeholder said
    "(25/30)" and a warning named the five that were dropped. The operator
    could see the list was cut - they still could not reach what was cut off.

    This is the answer the project had already built once, for the 31 days of
    a month (``SimpleMonthdayDropdown``, review B21): the list pages, and
    nothing is left out. A list that fits in one select is untouched and shows
    no arrows at all, because paging that announces itself when it is not
    needed is a regression for every install that has seven containers.
    """
    if len(containers) <= DISCORD_SELECT_LIMIT:
        return containers, False, False

    start = page * CONTAINERS_PER_PAGE
    shown = containers[start:start + CONTAINERS_PER_PAGE]
    return shown, page > 0, (start + CONTAINERS_PER_PAGE) < len(containers)


def _page_arrows(containers, page, has_prev, has_next):
    """The arrow options that lead out of this page.

    The labels are numbers and an arrow, deliberately without ``_()``: they
    carry no words, so they need no entry in the forty catalogues and read the
    same in every language. ``SimpleMonthdayDropdown`` made the same choice for
    the same reason.
    """
    before, after = [], []
    if has_prev:
        first = (page - 1) * CONTAINERS_PER_PAGE + 1
        before.append(discord.SelectOption(
            label=f"←  {first} - {first + CONTAINERS_PER_PAGE - 1}",
            value=SELECT_PAGE_PREV))
    if has_next:
        first = (page + 1) * CONTAINERS_PER_PAGE + 1
        after.append(discord.SelectOption(
            label=f"{first} - {min(first + CONTAINERS_PER_PAGE - 1, len(containers))}  →",
            value=SELECT_PAGE_NEXT))
    return before, after


def _paged_placeholder(placeholder, containers, page, paged):
    """"Select a container... (24-30/30)" - numbers, so no catalogue entry."""
    if not paged:
        return placeholder
    start = page * CONTAINERS_PER_PAGE + 1
    end = min(start + CONTAINERS_PER_PAGE - 1, len(containers))
    return f"{placeholder} ({start}-{end}/{len(containers)})"


async def _turn_page(dropdown, interaction, containers, rebuild):
    """Swap this dropdown for the neighbouring page, in the same row.

    The same move ``SimpleMonthdayDropdown._turn_page`` makes: the view keeps
    its identity, only the select is exchanged, so nothing else on the message
    is disturbed.
    """
    step = 1 if dropdown.values[0] == SELECT_PAGE_NEXT else -1
    row = getattr(dropdown, 'row', None)
    view = dropdown.view
    view.remove_item(dropdown)
    other = rebuild(dropdown.page + step)
    if row is not None:
        other.row = row
    view.add_item(other)
    await interaction.response.edit_message(view=view)


class ActionButton(Button):
    """Ultra-optimized button for Start, Stop, Restart actions."""
    cog: 'DockerControlCog'

    def __init__(self, cog_instance: 'DockerControlCog', server_config: dict, action: str, style: discord.ButtonStyle, label: str, emoji: str, row: int):
        self.cog = cog_instance
        self.action = action
        self.server_config = server_config
        self.docker_name = server_config.get('docker_name')
        self.display_name = server_config.get('display_name', self.docker_name)

        # Use cached static data for custom_id
        static_data = _get_container_static_data(self.display_name, self.docker_name)
        custom_id = static_data.get(f'custom_id_{action}', f"{action}_{self.docker_name}")

        super().__init__(style=style, label=label, custom_id=custom_id, row=row, emoji=emoji)

    def _headline(self) -> str:
        return f"**{self.display_name}** · {_(self.action.capitalize())}\n"

    def _failed_embed(self) -> discord.Embed:
        """What a press that could not be completed says."""
        embed = discord.Embed(
            title=_("❌ Server Action Failed"),
            # The action heads the text; "processed (Restart)" was no sentence (2026-09-27).
            description=self._headline() + _("The action could not be carried out."),
            color=discord.Color.red())
        embed.set_footer(text="https://ddc.bot")
        return embed

    async def _say_the_panel_is_stale(self, interaction, *, action_done: bool) -> None:
        """Take the message off an intermediate state when the press fell over.

        A press leaves the message on the pending embed with view=None - no
        buttons - and only the background refresh ever edits it again. When
        that refresh died with a type the handlers did not list, the message
        stayed on "pending" for good: visible, permanent, and wrong. (Until
        2026-09-24 it stood on a "⏳ Processing... please wait ~15 seconds"
        embed instead; that one is gone, the stuck message is not.) The container was fine and
        controllable from a freshly rendered panel; it was THIS message that
        was dead, and it is the one the operator is looking at (review D31).

        The two cases are not the same thing and must not share a sentence:
        after the action ran, only the refresh failed, and saying "the action
        failed" there would be a lie in the other direction.
        """
        if action_done:
            embed = discord.Embed(
                title=_("⚠️ Status could not be refreshed"),
                description=self._headline() + _("Done - only this panel could not be updated. "
                                                 "Use /control for a fresh one."),
                color=0xffa500)
            embed.set_footer(text="https://ddc.bot")
        else:
            embed = self._failed_embed()
        try:
            await interaction.edit_original_response(embed=embed, view=None)
        except (discord.NotFound, discord.HTTPException) as e:
            logger.warning(f"[ACTION_BTN] Could not replace the stale panel for "
                           f"{self.display_name}: {e}")

    async def callback(self, interaction: discord.Interaction) -> None:
        """Callback for Start, Stop, Restart actions."""
        # Check button-specific spam protection
        from services.infrastructure.spam_protection_service import get_spam_protection_service
        spam_service = get_spam_protection_service()

        if spam_service.is_enabled():
            try:
                if spam_service.is_on_cooldown(interaction.user.id, self.action):
                    remaining_time = spam_service.get_remaining_cooldown(interaction.user.id, self.action)
                    await interaction.response.send_message(
                        _("⏰ Please wait {remaining:.1f} seconds before using the '{action}' button again.").format(
                            remaining=remaining_time, action=self.action
                        ),
                        ephemeral=True, delete_after=NOTICE_STAYS_FOR
                    )
                    return
                spam_service.add_user_cooldown(interaction.user.id, self.action)
            except (RuntimeError, AttributeError, KeyError) as e:
                logger.error(f"Spam protection error for button '{self.action}': {e}", exc_info=True)

        config = load_config()
        if not config:
            await interaction.response.send_message(_("Error: Could not load configuration."), ephemeral=True, delete_after=NOTICE_STAYS_FOR)
            return

        user = interaction.user
        await interaction.response.defer()

        # Check if channel exists
        if not interaction.channel:
            await interaction.followup.send(_("Error: Could not determine channel."), ephemeral=True, delete_after=NOTICE_STAYS_FOR)
            return

        # Only the CURRENT channel permission decides. Previously an "Admin Control"
        # title short-circuited this check (`is_admin_control or ...`), which put the
        # authorization into a Discord message instead of the configuration: a panel
        # posted while the channel had the right kept working after the right was
        # withdrawn, for as long as the message existed. Decided by the operator on
        # 2026-09-16: old panels become ineffective immediately.
        #
        # The lines that computed `is_admin_control` here were dead after that fix -
        # nothing read the value any more - and are gone.
        #
        # CORRECTION 2026-09-17: this comment used to claim the same heuristic at
        # :1019/:1072 "only steers what is displayed and grants nothing". That was
        # wrong. Those two decided whether ContainerInfoAdminView gets built, and
        # that view carries TaskManagementButton unconditionally - a path to
        # delete_task(). They granted a right and are corrected as well.
        # See SPEC.md Z5 and B1.
        #
        # CORRECTION 2026-09-19: removing the title put NOTHING in its place, and
        # the title had been the only way registered admins got through in a
        # STATUS channel - which is what the admin list exists for (SPEC.md B2).
        # The operator was refused there. A registered admin passes again, read
        # from the CURRENT admin list, not from the message.
        # The admin branch is narrowed to the containers this admin was assigned
        # (review F2). No assignment means every container, so nothing changes
        # for an admin who has none - which is every admin until somebody makes
        # one. The channel branch in front of it is untouched: B1 stands.
        channel_has_control = (_get_cached_channel_permission(interaction.channel.id, 'control', config)
                               or _admin_may_control(user.id, self.docker_name))

        if not channel_has_control:
            await interaction.followup.send(_("This action is not allowed in this channel."), ephemeral=True, delete_after=NOTICE_STAYS_FOR)
            return

        allowed_actions = self.server_config.get('allowed_actions', [])
        if self.action not in allowed_actions:
            await interaction.followup.send(
                _("❌ Action '{action}' is not allowed for container '{container}'.").format(
                    action=self.action, container=self.display_name
                ),
                ephemeral=True, delete_after=NOTICE_STAYS_FOR
            )
            return

        logger.info(f"[ACTION_BTN] {self.action.upper()} action for '{self.display_name}' triggered by {user.name}")

        if await refused_while_busy(self.cog, self.docker_name, self.display_name, interaction):
            return  # one action per container at a time (control_helpers)
        pending_entry = {
            'action': self.action,
            'timestamp': datetime.now(timezone.utc),
            'user': str(user),
            'display_name': self.display_name  # Store for display purposes
        }
        self.cog.pending_actions[self.docker_name] = pending_entry

        try:
            pending_embed = _get_pending_embed(self.display_name)
            try:
                await interaction.edit_original_response(embed=pending_embed, view=None)
            except (discord.NotFound, discord.HTTPException) as e:
                logger.warning(f"[ACTION_BTN] Interaction expired/invalid for {self.display_name}: {e}")
                # The action never runs - don't leave the container stuck in "pending"
                if self.cog.pending_actions.get(self.docker_name) is pending_entry:
                    del self.cog.pending_actions[self.docker_name]
                return

            log_user_action(
                action=f"DOCKER_{self.action.upper()}",
                target=self.display_name,
                user=str(user),
                source="Discord Button",
                details=f"Container: {self.docker_name}"
            )

            async def run_docker_action():
                # Whether Docker has actually carried the action out. It decides
                # which of the two things a failure below is allowed to claim
                # (review D31).
                action_done = False
                try:
                    # SERVICE FIRST: Use new Docker Action Service
                    from services.docker_service.docker_action_service import docker_action_service_first
                    success = await docker_action_service_first(self.docker_name, self.action)
                    logger.info(f"[ACTION_BTN] Docker {self.action} for '{self.display_name}' completed: success={success}")

                    if not success:
                        # The result used to be logged and nothing else: a failed action
                        # went on like a successful one - "processing", then the
                        # unchanged status - and the user was never told (SPEC.md Z3,
                        # review A5). The service turns Docker errors into False.
                        if self.cog.pending_actions.get(self.docker_name) is pending_entry:
                            del self.cog.pending_actions[self.docker_name]
                        failed_embed = self._failed_embed()
                        try:
                            await interaction.edit_original_response(embed=failed_embed, view=None)
                        except (discord.NotFound, discord.HTTPException) as e:
                            logger.warning(f"[ACTION_BTN] Could not show the failure for {self.display_name}: {e}")
                        return

                    action_done = True

                    if self.docker_name in self.cog.pending_actions:
                        del self.cog.pending_actions[self.docker_name]

                    # Invalidate BOTH caches for this container to force fresh status - use docker_name as key!
                    # 1. StatusCacheService (used for periodic updates)
                    if self.cog.status_cache_service.get(self.docker_name):
                        logger.info(f"[ACTION_BTN] Invalidating StatusCacheService cache for {self.display_name} (docker: {self.docker_name})")
                        self.cog.status_cache_service.remove(self.docker_name)

                    # 2. ContainerStatusService (has its own 30s cache!)
                    from services.infrastructure.container_status_service import get_container_status_service
                    container_status_service = get_container_status_service()
                    container_status_service.invalidate_container(self.docker_name)
                    logger.info(f"[ACTION_BTN] Invalidating ContainerStatusService cache for {self.docker_name}")

                    # What the press did, waited for where that question
                    # belongs: a container waits for itself, a group for all
                    # of its members (cogs/action_effect.py). It returns the
                    # moment it knows, so nothing after it waits on a clock.
                    took_effect = await wait_until_the_action_took_effect(
                        self.cog, self.docker_name, self.display_name, self.action)

                    # Which of the two panels this button sits on, asked of
                    # the message itself (cogs/control_helpers.py explains the
                    # two wrong answers that came before).
                    is_admin_message = False
                    try:
                        is_admin_message = is_private_panel_message(interaction.message)
                        logger.info(f"[ACTION_BTN] Private panel: {is_admin_message}")
                    except (discord.errors.DiscordException, AttributeError, KeyError) as e:
                        logger.error(f"[ACTION_BTN] Error checking admin status: {e}", exc_info=True)

                    # A "Processing... please wait ~15 seconds" message used to
                    # stand here, after the waiting above had already finished,
                    # and was followed by a blind sleep(15). The operator sat
                    # through it on containers that were up in three seconds
                    # (2026-09-24). The wait answers as soon as it knows; the
                    # only thing left to say is when it never did.
                    if took_effect is False:
                        try:
                            await interaction.edit_original_response(
                                embed=not_confirmed_embed(self.display_name, self.action),
                                view=None)
                        except (discord.NotFound, discord.HTTPException) as e:
                            logger.warning(f"[ACTION_BTN] Failed to show the notice: {e}")

                    # Both views (Admin Control + Server Overview), redrawn now:
                    # the state they are drawn from was confirmed above.
                    async def update_all_views():
                        try:
                            # No refresh here: the wait above just asked every
                            # target and wrote the answers. A second pass made
                            # sense when a blind sleep sat between them; without
                            # it, it asked the same questions again and left the
                            # overview seventeen seconds behind the panel.
                            logger.info(f"[ACTION_BTN] Updating status overview for {self.display_name}")

                            # FIRST: Update Admin Control message (if it was an admin control action)
                            if is_admin_message:
                                try:
                                    self.server_config['_is_admin_control'] = True

                                    # Generate admin control embed.
                                    # NOT `_`: this function calls the translation
                                    # function, and binding `_` anywhere makes it
                                    # local for the WHOLE scope (review E38 - the
                                    # same mistake as E34, caught by the same
                                    # guard two hours later).
                                    admin_embed = await admin_panel_embed(
                                        self.cog, interaction.channel.id, self.docker_name,
                                        self.server_config, config, self.display_name)
                                    is_running, _known = await running_state_for(
                                        self.cog, self.docker_name, self.server_config)

                                    admin_view = admin_control_view(
                                        self.cog, self.server_config, is_running)

                                    if admin_embed:
                                        await interaction.edit_original_response(
                                            embed=panel_embed_after(took_effect, admin_embed,
                                                                    self.display_name, self.action),
                                            view=admin_view)
                                        logger.info(f"[ACTION_BTN] Updated Admin Control message for {self.display_name}")

                                    self.server_config.pop('_is_admin_control', None)
                                except (discord.errors.DiscordException, RuntimeError) as e:
                                    logger.error(f"[ACTION_BTN] Failed to update Admin Control message: {e}", exc_info=True)
                            else:
                                # Update normal control message
                                try:
                                    normal_embed, normal_view, _running = await self.cog._generate_status_embed_and_view(
                                        interaction.channel.id,
                                        self.display_name,
                                        self.server_config,
                                        config
                                    )
                                    if normal_embed:
                                        await interaction.edit_original_response(
                                            embed=panel_embed_after(took_effect, normal_embed,
                                                                    self.display_name, self.action),
                                            view=normal_view)
                                        logger.info(f"[ACTION_BTN] Updated control message for {self.display_name}")
                                except (discord.errors.DiscordException, RuntimeError) as e:
                                    logger.error(f"[ACTION_BTN] Failed to update control message: {e}", exc_info=True)

                            # SECOND: Update all Server Overview status messages for this container
                            # THIRD: Update Overview and Admin Overview messages
                            if hasattr(self.cog, 'channel_server_message_ids'):
                                for channel_id, server_messages in self.cog.channel_server_message_ids.items():
                                    # Update Server Overview (collapsed view)
                                    if 'overview' in server_messages:
                                        try:
                                            await self.cog._update_overview_message(channel_id, server_messages['overview'], 'overview')
                                            logger.info(f"[ACTION_BTN] Updated overview in channel {channel_id}")
                                        except Exception as e:
                                            logger.error(f"[ACTION_BTN] Failed to update overview: {e}")

                                    # Update Admin Overview
                                    if 'admin_overview' in server_messages:
                                        try:
                                            await self.cog._update_overview_message(channel_id, server_messages['admin_overview'], 'admin_overview')
                                            logger.info(f"[ACTION_BTN] Updated admin_overview in channel {channel_id}")
                                        except Exception as e:
                                            logger.error(f"[ACTION_BTN] Failed to update admin_overview: {e}")

                        except asyncio.CancelledError:
                            # The bot is going down - the panel is the least of it.
                            raise
                        except BaseException as e:
                            # Deliberately not a type list. At this point the
                            # message stands on the pending embed with no
                            # buttons and only this task ever edits it again,
                            # so whatever went wrong it must not be left there
                            # (review D31).
                            logger.error(f"[ACTION_BTN] Error in update_all_views: {e}", exc_info=True)
                            await self._say_the_panel_is_stale(interaction, action_done=True)

                    # Create background task for BOTH Admin Control + Server Overview updates
                    update_task = asyncio.create_task(update_all_views())
                    update_task.add_done_callback(
                        lambda t: _log_background_task_exception(t, f"update views for {self.docker_name}"))

                except asyncio.CancelledError:
                    if self.docker_name in self.cog.pending_actions:
                        del self.cog.pending_actions[self.docker_name]
                    raise
                except BaseException as e:
                    # Same reason as in update_all_views: the message is sitting
                    # on the pending or the processing embed and nothing else
                    # will touch it (review D31).
                    logger.error(f"[ACTION_BTN] Error in background Docker {self.action}: {e}", exc_info=True)
                    # Remove from pending_actions - use docker_name as key!
                    if self.docker_name in self.cog.pending_actions:
                        del self.cog.pending_actions[self.docker_name]
                    await self._say_the_panel_is_stale(interaction, action_done=action_done)

            # Create task; the done-callback logs exceptions and always clears pending_actions
            task = asyncio.create_task(run_docker_action())
            task.add_done_callback(_make_action_done_callback(
                self.cog, self.docker_name, pending_entry, f"docker {self.action} for {self.docker_name}"))

        except (discord.errors.DiscordException, RuntimeError, OSError) as e:
            logger.error(f"[ACTION_BTN] Error handling {self.action} for '{self.display_name}': {e}", exc_info=True)
            # Remove from pending_actions - use docker_name as key!
            if self.docker_name in self.cog.pending_actions:
                del self.cog.pending_actions[self.docker_name]
        except BaseException:
            # Anything else: take the mark back, then let it travel on. The
            # clause above reports what it knows how to report and swallows it;
            # this one changes NOTHING about what is swallowed, it only undoes
            # the mark. Without it a KeyError or TypeError from
            # _get_pending_embed or log_user_action left the container marked
            # as pending for an action that never ran - its control buttons
            # gone, a yellow "Pending" in their place. Not forever:
            # docker_control sweeps an entry older than 120 s on the next
            # render. Two minutes of a state the user is shown and that is not
            # true (review D17).
            #
            # Deliberately NOT `except Exception` with a log-and-swallow: two
            # spec tests prove the permission gate by raising a marker through
            # this method, and swallowing it here would hide a real error as
            # well as their marker.
            if self.docker_name in self.cog.pending_actions:
                del self.cog.pending_actions[self.docker_name]
            raise


# =============================================================================
# ULTRA-OPTIMIZED CONTROL VIEW CLASS
# =============================================================================

class ControlView(DDCView):
    """Ultra-optimized view with control buttons for a Docker container."""
    cog: 'DockerControlCog'

    def __init__(self, cog_instance: Optional['DockerControlCog'], server_config: Optional[dict], is_running: bool, channel_has_control_permission: bool, channel_id: Optional[int] = None):
        super().__init__(timeout=None)
        self.cog = cog_instance

        # If called for registration only, don't add items
        if not self.cog or not server_config:
            return

        docker_name = server_config.get('docker_name')
        display_name = server_config.get('name', docker_name)

        # Check for pending status (simple read in __init__, race acceptable here)
        # Lock not used because __init__ is synchronous and only reads.
        # Keyed by DOCKER name like every writer of pending_actions. This read the
        # display name, so for "V-Rising"/"vrising" the admin panel - which builds
        # this view without a pending check of its own - offered start/stop while an
        # action was still running: a second Docker action in parallel (review A2).
        is_pending = docker_name in self.cog.pending_actions

        if is_pending:
            logger.debug(f"[ControlView] Server '{display_name}' is pending. No buttons will be added.")
            return

        allowed_actions = server_config.get('allowed_actions', [])
        details_allowed = server_config.get('allow_detailed_status', True)
        # A GROUP IS NOT ON OR OFF (operator, 2026-09-24). A container is, so
        # its panel offers stop-and-restart OR start. A group has a COUNT, and
        # at 1/2 all three do something: start the one that is down, stop the
        # one that is up, restart what is running. So it offers everything it
        # is allowed, always, and the lamp in its embed says where it stands.
        #
        # IT ANSWERS BEFORE THE INFO LOOKUP BELOW. A group has no info text and
        # no logs; asking made the info service refuse the name and log an
        # ERROR on every panel build (operator's log, 2026-09-24).
        if is_group_target(docker_name):
            if channel_has_control_permission:
                for action, style, emoji in (
                        ("start", discord.ButtonStyle.secondary, "▶️"),
                        ("stop", discord.ButtonStyle.secondary, "⏹️"),
                        ("restart", discord.ButtonStyle.secondary, "🔄")):
                    if action in allowed_actions:
                        self.add_item(ActionButton(cog_instance, server_config, action,
                                                   style, None, emoji, row=0))
            return

        # Load info from service
        from services.infrastructure.container_info_service import get_container_info_service
        info_service = get_container_info_service()
        if docker_name:
            info_result = info_service.get_container_info(docker_name)
            info_config = info_result.data.to_dict() if info_result.success else {}
        else:
            info_config = {}

        # Check if channel has info permission
        config = load_config()
        channel_has_info_permission = self._channel_has_info_permission(
            channel_has_control_permission, config, channel_id)

        # Add buttons based on state and permissions
        if is_running:
            # NO EXPAND BUTTON. A ➕/➖ toggle stood here, added only when
            # allow_toggle was true - which no live caller ever passed, and
            # which five months of recorded presses never once produced
            # (tests/spec/test_no_control_flips_an_expand_state.py).
            #
            # Action buttons when expanded and channel has control
            if channel_has_control_permission:
                button_row = 0
                if "stop" in allowed_actions:
                    self.add_item(ActionButton(cog_instance, server_config, "stop", discord.ButtonStyle.secondary, None, "⏹️", row=button_row))
                if "restart" in allowed_actions:
                    self.add_item(ActionButton(cog_instance, server_config, "restart", discord.ButtonStyle.secondary, None, "🔄", row=button_row))

                # Info button comes AFTER action buttons (rightmost position)
                # In control channels, show info button for all expanded containers (allows adding info)
                if channel_has_info_permission:
                    self.add_item(InfoButton(cog_instance, server_config, row=button_row))
        else:
            # Start button for offline containers
            if channel_has_control_permission and "start" in allowed_actions:
                self.add_item(ActionButton(cog_instance, server_config, "start", discord.ButtonStyle.secondary, None, "▶️", row=0))

            # Info button for offline containers - rightmost position
            # In control channels, show info button for all expanded containers (allows adding info)
            if channel_has_info_permission:
                self.add_item(InfoButton(cog_instance, server_config, row=0))

    def _channel_has_info_permission(self, channel_has_control_permission: bool,
                                     config: dict, channel_id: Optional[int]) -> bool:
        """Whether this channel may see the Info button. Control also grants info.

        This used to end in `return True` under the note "We need the actual
        channel_id, but we don't have it in this context". It did have it: the
        channel id is at hand at every call site, including the one two lines
        above the caller (`_control_allowed_for(channel_id, ...)`). So the Info
        button was added to every view, including in a channel with neither
        permission - a plain status channel, which is an ordinary setup - where
        pressing it is correctly refused by InfoButton's own check. A button
        that is shown and can only say no (review D32).

        It is now the same check the callback makes, so what is offered and
        what is allowed cannot disagree.

        Without a channel id the old answer stands, deliberately: defaulting to
        "hide it" would take the Info button away from an info-only channel the
        moment a caller forgot to pass one, which is the worse of the two
        mistakes. That case says so in the log rather than passing quietly.
        """
        from .control_helpers import _channel_has_permission
        # If we already know they have control permission, they can access info
        if channel_has_control_permission:
            return True
        if channel_id is None:
            logger.warning("[ControlView] No channel id given - offering the Info "
                           "button without checking, InfoButton will decide")
            return True
        return _channel_has_permission(channel_id, 'info', config)

# =============================================================================
# INFO BUTTON COMPONENT
# =============================================================================

class InfoButton(Button):
    """Button for displaying container information."""

    def __init__(self, cog_instance: 'DockerControlCog', server_config: dict, row: int):
        self.cog = cog_instance
        self.server_config = server_config
        self.docker_name = server_config.get('docker_name')
        self.display_name = server_config.get('name', self.docker_name)

        super().__init__(
            style=discord.ButtonStyle.secondary,
            label=None,
            emoji="ℹ️",
            custom_id=f"info_{self.docker_name}",
            row=row
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        """Display container info with admin buttons in control channels."""
        # Check spam protection for info button
        from services.infrastructure.spam_protection_service import get_spam_protection_service
        spam_service = get_spam_protection_service()

        if spam_service.is_enabled():
            try:
                if spam_service.is_on_cooldown(interaction.user.id, "info"):
                    remaining_time = spam_service.get_remaining_cooldown(interaction.user.id, "info")
                    await interaction.response.send_message(
                        _("⏰ Please wait {remaining:.1f} seconds before using the info button again.").format(
                            remaining=remaining_time
                        ),
                        ephemeral=True, delete_after=NOTICE_STAYS_FOR
                    )
                    return
                spam_service.add_user_cooldown(interaction.user.id, "info")
            except (RuntimeError, AttributeError, KeyError) as e:
                logger.error(f"Spam protection error for info button: {e}", exc_info=True)
        try:
            await interaction.response.defer(ephemeral=True)


            config = load_config()
            channel_id = interaction.channel.id if interaction.channel else None

            # Check if user is admin (admins can access info in any channel)
            from services.admin.admin_service import get_admin_service
            admin_service = get_admin_service()
            user_id = str(interaction.user.id)
            is_admin = admin_service.is_user_admin(user_id)

            # Check if channel has info permission (skip check for admins)
            if not is_admin and not self._channel_has_info_permission(channel_id, config):
                await interaction.followup.send(
                    _("❌ You don't have permission to view container info in this channel."),
                    ephemeral=True, delete_after=NOTICE_STAYS_FOR
                )
                return

            # Get info configuration from service
            from services.infrastructure.container_info_service import get_container_info_service
            info_service = get_container_info_service()
            docker_name = self.server_config.get('docker_name')
            if docker_name:
                info_result = info_service.get_container_info(docker_name)
                info_config = info_result.data.to_dict() if info_result.success else {}
            else:
                info_config = {}
            if not info_config.get('enabled', False):
                # Check if user can edit (in control channels, users can add info)
                from .control_helpers import _channel_has_permission

                # Only the CURRENT channel permission decides. The title of the
                # message used to short-circuit this ("Admin Control" in the embed
                # title), which meant a panel posted while the channel still had
                # the right stayed usable after the right was taken away. The view
                # built below carries TaskManagementButton unconditionally
                # (status_info_integration.py:55) and therefore a path to
                # delete_task() - so this was not display, it granted a right.
                # Same correction as :304. See SPEC.md Z5.
                # A registered admin counts as well (SPEC.md B2) - see :304.
                has_control = ((_channel_has_permission(channel_id, 'control', config) if config else False)
                               or _is_registered_admin(interaction.user.id))

                if has_control:
                    # Create empty info template with Edit/Log buttons
                    display_name = self.server_config.get('display_name', 'Unknown')

                    # Create default empty info config
                    empty_info_config = {
                        'enabled': True,
                        'info_text': 'Click Edit to add container information.',
                        'ip_url': '',
                        'port': '',
                        'show_ip': False
                    }

                    # Generate info embed using the empty template
                    from .status_info_integration import StatusInfoButton, ContainerInfoAdminView
                    from .control_helpers import _channel_has_permission

                    info_button = StatusInfoButton(self.cog, self.server_config, empty_info_config)

                    # Reuse the has_control flag determined above (current channel
                    # permission only - the admin-control title no longer counts).
                    embed = await info_button._generate_info_embed(include_protected=has_control)

                    # Add admin buttons for editing
                    admin_view = ContainerInfoAdminView(self.cog, self.server_config, empty_info_config)
                    message = await interaction.followup.send(embed=embed, view=admin_view, ephemeral=True)
                    # Update view with message reference and start auto-delete timer
                    admin_view.message = message
                    admin_view.auto_delete_task = asyncio.create_task(admin_view.start_auto_delete_timer())
                    return
                # Without control the display opens all the same: restarts, health, players (v3.1.0)

            # Use the same logic as StatusInfoButton for consistency
            from .status_info_integration import StatusInfoButton, ContainerInfoAdminView
            from .control_helpers import _channel_has_permission

            # Generate info embed using StatusInfoButton logic
            info_button = StatusInfoButton(self.cog, self.server_config, info_config)

            # The CURRENT channel permission or a registered admin decides - see the
            # note above and :304. SPEC.md Z5 and B2.
            has_control = ((_channel_has_permission(channel_id, 'control', config) if config else False)
                           or _is_registered_admin(interaction.user.id))

            # Generate embed with protected info if in control channel
            embed = await info_button._generate_info_embed(include_protected=has_control)

            view = None
            if has_control:
                view = ContainerInfoAdminView(self.cog, self.server_config, info_config)
                logger.info(f"InfoButton (ControlView) created admin view for {docker_name} in control channel {channel_id}")

                message = await interaction.followup.send(embed=embed, view=view, ephemeral=True)
                # Update view with message reference and start auto-delete timer
                view.message = message
                view.auto_delete_task = asyncio.create_task(view.start_auto_delete_timer())
            else:
                logger.warning(f"InfoButton (ControlView) no control permission for {docker_name} in channel {channel_id}")
                await interaction.followup.send(embed=embed, ephemeral=True)

        except (discord.errors.DiscordException, RuntimeError, OSError) as e:
            logger.error(f"[INFO_BTN] Error showing info for '{self.display_name}': {e}", exc_info=True)
            await interaction.followup.send(
                _("❌ An error occurred. Please try again."),
                ephemeral=True, delete_after=NOTICE_STAYS_FOR
            )

    def _channel_has_info_permission(self, channel_id: int, config: dict) -> bool:
        """Check if channel has info permission."""
        from .control_helpers import _channel_has_permission
        return _channel_has_permission(channel_id, 'info', config)

# =============================================================================
# TASK DELETE COMPONENTS
# =============================================================================

class TaskDeleteButton(Button):
    """Button for deleting a specific scheduled task."""

    def __init__(self, cog_instance: 'DockerControlCog', task_id: str, task_description: str, row: int):
        self.cog = cog_instance
        self.task_id = task_id
        self.task_description = task_description

        super().__init__(
            style=discord.ButtonStyle.danger,
            label=task_description,
            custom_id=f"task_delete_{task_id}",
            row=row
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        """Deletes the scheduled task."""
        # Check spam protection for task delete
        from services.infrastructure.spam_protection_service import get_spam_protection_service
        spam_service = get_spam_protection_service()

        if spam_service.is_enabled():
            try:
                if spam_service.is_on_cooldown(interaction.user.id, "task_delete"):
                    remaining_time = spam_service.get_remaining_cooldown(interaction.user.id, "task_delete")
                    # The existing, translated catalog entry instead of an English
                    # f-string - house pattern as in SPEC.md B10.
                    await interaction.response.send_message(
                        _("⏰ Please wait {remaining:.1f} more seconds before using this button again.").format(
                            remaining=remaining_time
                        ),
                        ephemeral=True, delete_after=NOTICE_STAYS_FOR
                    )
                    return
                spam_service.add_user_cooldown(interaction.user.id, "task_delete")
            except (RuntimeError, AttributeError, KeyError) as e:
                logger.error(f"Spam protection error for task delete button: {e}", exc_info=True)

        user = interaction.user
        logger.info(f"[TASK_DELETE_BTN] Task deletion '{self.task_id}' triggered by {user.name}")

        try:
            await interaction.response.defer(ephemeral=True)

            # Check if channel exists
            if not interaction.channel:
                await interaction.followup.send(_("Error: Could not determine channel."), ephemeral=True, delete_after=NOTICE_STAYS_FOR)
                return

            from services.scheduling.scheduler import delete_task

            config = load_config()
            # A registered admin may delete as well (SPEC.md B2) - the same rule as
            # the twin in status_info_integration.py; same action, same right.
            # Via the task's container: a task acts on one, so an assigned admin
            # may only delete the tasks of their own (review F2).
            if not (_get_cached_channel_permission(interaction.channel.id, 'schedule', config)
                    or _admin_may_control_task(interaction.user.id, self.task_id)):
                await interaction.followup.send(_("You do not have permission to delete tasks in this channel."), ephemeral=True, delete_after=NOTICE_STAYS_FOR)
                return

            if delete_task(self.task_id):
                log_user_action(
                    action="TASK_DELETE",
                    target=f"Task {self.task_id}",
                    user=str(user),
                    source="Discord Button",
                    details=f"Task: {self.task_description}"
                )

                await interaction.followup.send(
                    _("✅ Task **{task_description}** has been deleted successfully.").format(task_description=self.task_description),
                    ephemeral=True, delete_after=NOTICE_STAYS_FOR
                )
                logger.info(f"[TASK_DELETE_BTN] Task '{self.task_id}' deleted successfully by {user.name}")
            else:
                await interaction.followup.send(
                    _("❌ Failed to delete task **{task_description}**. It may no longer exist.").format(task_description=self.task_description),
                    ephemeral=True, delete_after=NOTICE_STAYS_FOR
                )
                logger.warning(f"[TASK_DELETE_BTN] Failed to delete task '{self.task_id}' for {user.name}")

        except (discord.errors.DiscordException, RuntimeError, KeyError) as e:
            logger.error(f"[TASK_DELETE_BTN] Error deleting task '{self.task_id}': {e}", exc_info=True)
            await interaction.followup.send(_("An error occurred while deleting the task."), ephemeral=True, delete_after=NOTICE_STAYS_FOR)

class InfoDropdownButton(Button):
    """Button to show container info selection dropdown from /ss messages."""

    def __init__(self, cog_instance: 'DockerControlCog', channel_id: int):
        self.cog = cog_instance
        self.channel_id = channel_id

        super().__init__(
            style=discord.ButtonStyle.secondary,
            label=None,
            emoji="ℹ️",  # Info emoji
            custom_id=f"info_button_{channel_id}",
            row=0
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        """Show container selection dropdown when clicked."""
        # Acknowledge immediately (container config is read from disk below); reply via followup.
        try:
            await interaction.response.defer(ephemeral=True)
        except discord.errors.NotFound:
            logger.warning(f"Info button interaction expired for channel {self.channel_id}")
            return
        except discord.errors.HTTPException as e:
            logger.error(f"Error deferring info button interaction: {e}", exc_info=True)
            return

        try:
            # Apply spam protection
            from services.infrastructure.spam_protection_service import get_spam_protection_service
            spam_service = get_spam_protection_service()
            # Through the service instead of an attribute on the button. Before,
            # the timestamp lived in _last_click_<user> ON THE OBJECT - a lock
            # that vanished the next time the view was rebuilt. Only the DURATION
            # came from the service, so the per-minute limit from the panel had
            # no effect here: it counts in add_user_cooldown, and this path never
            # got there. The message was also untranslated; the existing catalog
            # entry is used now.
            if spam_service.is_enabled():
                try:
                    if spam_service.is_on_cooldown(interaction.user.id, "info"):
                        remaining = spam_service.get_remaining_cooldown(interaction.user.id, "info")
                        await interaction.followup.send(
                            _("⏰ Please wait {remaining:.1f} more seconds before using this button again.").format(
                                remaining=remaining
                            ),
                            ephemeral=True, delete_after=NOTICE_STAYS_FOR
                        )
                        return
                    spam_service.add_user_cooldown(interaction.user.id, "info")
                except (RuntimeError, AttributeError, KeyError) as e:
                    logger.error(f"Spam protection error for info dropdown button: {e}", exc_info=True)

            # SERVICE FIRST: Use ServerConfigService instead of direct file access
            server_config_service = get_server_config_service()
            all_servers = server_config_service.get_all_servers()

            # Every container has an info display since v3.1.0, not only those with a text set
            containers_with_info = []
            for container_data in all_servers:
                try:
                    info_config = container_data.get('info', {})
                    container_name = container_data.get('container_name', container_data.get('docker_name'))
                    display_name = container_data.get('display_name', [container_name, container_name])
                    if isinstance(display_name, list) and len(display_name) > 0:
                        display_name = display_name[0]

                    # Remove " Server" suffix if present
                    if display_name.endswith(' Server'):
                        display_name = display_name[:-7]  # Remove last 7 characters (" Server")

                    containers_with_info.append({
                        'name': container_name,
                        'display': display_name,
                        'protected': info_config.get('protected_enabled', False),
                        'order': container_data.get('order', 999)  # Include order field directly
                    })
                except (RuntimeError, ValueError, KeyError) as e:
                    logger.error(f"Error processing container data: {e}", exc_info=True)
                    continue

            if not containers_with_info:
                await interaction.followup.send(_("ℹ️ No active containers have information configured."), ephemeral=True, delete_after=NOTICE_STAYS_FOR)
                return

            # Sort containers by the 'order' field (same as Admin Overview)
            # Ensure order is converted to int for proper sorting
            containers_with_info.sort(key=lambda x: int(x.get('order', 999)))

            # Create view with dropdown
            view = ContainerInfoSelectView(self.cog, containers_with_info)

            embed = discord.Embed(
                title=_("Container Information"),
                description=_("Select a container from the dropdown to view its information:"),
                color=discord.Color.blue()
            )

            # Send as ephemeral response (interaction was deferred above)
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)

            logger.info(f"Info selection shown for user {interaction.user.name} in channel {self.channel_id}")

        except (discord.errors.DiscordException, RuntimeError, ValueError, KeyError) as e:
            logger.error(f"Error showing info selection: {e}", exc_info=True)
            try:
                await interaction.followup.send(_("❌ An error occurred. Please try again."), ephemeral=True, delete_after=NOTICE_STAYS_FOR)
            except (discord.errors.DiscordException, RuntimeError):
                # Interaction may have expired
                pass

class ContainerInfoSelectView(PrivateView):
    """View with dropdown for selecting a container to view info."""

    def __init__(self, cog_instance: 'DockerControlCog', containers: list):
        super().__init__(timeout=180)  # 3 minutes timeout
        self.cog = cog_instance

        # Add dropdown
        self.add_item(ContainerInfoDropdown(cog_instance, containers))

class ContainerInfoDropdown(discord.ui.Select):
    """Dropdown for selecting a container."""

    def __init__(self, cog_instance: 'DockerControlCog', containers: list, page: int = 0):
        self.cog = cog_instance
        self.containers = containers
        self.page = page

        # Create options from containers, one page at a time (review E37)
        placeholder = _("Select a container...")
        shown, has_prev, has_next = _page_of(containers, page)
        before, after = _page_arrows(containers, page, has_prev, has_next)
        options = list(before)
        for container in shown:
            options.append(discord.SelectOption(
                label=container['display'],
                value=container['name']
            ))
        options.extend(after)

        super().__init__(
            placeholder=_paged_placeholder(placeholder, containers, page,
                                           has_prev or has_next),
            options=options,
            min_values=1,
            max_values=1,
            custom_id="container_info_select"
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle container selection."""
        try:
            if self.values[0] in (SELECT_PAGE_PREV, SELECT_PAGE_NEXT):
                await _turn_page(
                    self, interaction, self.containers,
                    lambda page: ContainerInfoDropdown(self.cog, self.containers, page=page))
                return

            selected_container = self.values[0]

            # Get container info and full container data
            from services.config.config_service import load_config

            # SERVICE FIRST: Use ServerConfigService to get container configuration
            server_config_service = get_server_config_service()
            container_data = None

            # Try to get container by docker_name
            container_data = server_config_service.get_server_by_docker_name(selected_container)

            # If not found by name, try by docker_name
            if not container_data:
                all_servers = server_config_service.get_all_servers()
                for server in all_servers:
                    if (server.get('container_name') == selected_container or
                        server.get('docker_name') == selected_container or
                        server.get('name') == selected_container):
                        container_data = server
                        break

            if not container_data:
                await interaction.response.edit_message(
                    content=_("❌ Container '{name}' not found").format(name=selected_container),
                    embed=None,
                    view=None
                )
                return

            info_config = container_data.get('info', {})


            # Check channel type for protected info WITHOUT password
            is_control_channel = False
            channel = interaction.channel
            if channel:
                # Check if this is a control channel
                from services.config.config_service import load_config
                config = load_config()
                # The channel's real 'control' permission - or a registered admin
                # (SPEC.md B2), like every other permission decision in this file.
                # This read channel_config['allow_start'/'allow_stop'], keys a channel
                # configuration does not have (they live under 'commands'), so the
                # answer was always False and protected content without a password was
                # never shown in a control channel (review A8).
                is_control_channel = (_get_cached_channel_permission(channel.id, 'control', config)
                                      or _is_registered_admin(interaction.user.id))

                # Log channel type for debugging
                logger.debug(f"Channel {channel.id} - is_control: {is_control_channel}, protected_enabled: {info_config.get('protected_enabled', False)}")

            # Build the info message
            display_name = container_data.get('display_name', [selected_container])
            if isinstance(display_name, list) and len(display_name) > 0:
                display_name = display_name[0]

            # Acknowledge before the game query, the Docker lookup and the WAN
            # address: together they can outlast Discord's 3 seconds, and the
            # answer then failed with "This interaction failed" (final check
            # before v3.1.0). The ℹ️ button defers the same way.
            try:
                await interaction.response.defer()
            except discord.NotFound:
                logger.warning(f"Info dropdown interaction for {selected_container} expired before it was answered")
                return

            embed = discord.Embed(title=f"ℹ️ {display_name}", color=discord.Color.blue())
            # The operator's address and text first, then the game server, then
            # Docker - the order of the ℹ️ button (status_info_integration.py);
            # this path used to put his text last, as a field below it all.
            from services.infrastructure.container_info_service import MAX_CUSTOM_TEXT
            from .info_extras import address_line, info_extras
            extras = await info_extras(container_data)
            own = []
            if info_config.get('enabled', False):
                if info_config.get('show_ip', False):
                    own.append(await address_line(info_config, extras.port))
                own.append(str(info_config.get('custom_text') or '').strip()[:MAX_CUSTOM_TEXT])
            blocks = ["\n".join(line for line in own if line)] + extras.blocks()
            embed.description = "\n\n".join(block for block in blocks if block) or None

            # Handle protected information
            if info_config.get('protected_enabled', False):
                # Check if password is set
                if info_config.get('protected_password'):
                    # Password protection - show button in ALL channels
                    view = PasswordProtectedView(self.cog, container_data, info_config)

                    embed.add_field(
                        name="🔒 " + _("Protected Information"),
                        value=_("This container has password-protected information. Click the button below to access it."),
                        inline=False
                    )

                    await interaction.edit_original_response(embed=embed, view=view)
                else:
                    # No password set - only show in control channels
                    if is_control_channel:
                        # Show protected content directly in control channels
                        if info_config.get('protected_content'):
                            embed.add_field(
                                name="🔓 " + _("Additional Information"),
                                value=info_config['protected_content'],
                                inline=False
                            )
                        await interaction.edit_original_response(embed=embed, view=None)
                    else:
                        # In status channels, show info about needing control channel
                        embed.add_field(
                            name="🔒 " + _("Protected Information"),
                            value=_("Protected information is available for this container but can only be accessed in control channels."),
                            inline=False
                        )
                        await interaction.edit_original_response(embed=embed, view=None)
            else:
                # No protected info at all
                await interaction.edit_original_response(embed=embed, view=None)

            logger.info(f"Container info shown for {selected_container} to user {interaction.user.name}")

        except (RuntimeError, ValueError, KeyError) as e:
            logger.error(f"Error handling container selection: {e}", exc_info=True)
            try:
                if not interaction.response.is_done():
                    await interaction.response.edit_message(
                        content=_("❌ An error occurred. Please try again."),
                        embed=None,
                        view=None
                    )
                else:
                    await interaction.followup.send(_("❌ An error occurred. Please try again."), ephemeral=True, delete_after=NOTICE_STAYS_FOR)
            except (discord.errors.DiscordException, RuntimeError):
                pass

class PasswordProtectedView(PrivateView):
    """View with button for entering password to access protected info."""

    def __init__(self, cog_instance: 'DockerControlCog', server_config: dict, info_config: dict):
        super().__init__(timeout=180)  # 3 minutes timeout
        self.cog = cog_instance
        self.server_config = server_config
        self.info_config = info_config

        # Add password button
        self.add_item(PasswordButton(cog_instance, server_config, info_config))

class PasswordButton(Button):
    """Button to enter password for protected information."""

    def __init__(self, cog_instance: 'DockerControlCog', server_config: dict, info_config: dict):
        self.cog = cog_instance
        self.server_config = server_config
        self.info_config = info_config

        super().__init__(
            style=discord.ButtonStyle.primary,
            label=_("Enter Password"),
            emoji="🔐",
            custom_id="password_button"
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        """Show modal for password entry."""
        try:
            # Show password modal
            from .enhanced_info_modal_simple import PasswordValidationModal

            # Extract container name and display name from server_config
            container_name = self.server_config.get('container_name', self.server_config.get('docker_name', 'Unknown'))
            display_name = self.server_config.get('display_name', [container_name, container_name])
            if isinstance(display_name, list) and len(display_name) > 0:
                display_name = display_name[0]

            modal = PasswordValidationModal(
                self.cog,
                container_name,
                display_name,
                self.info_config
            )
            await interaction.response.send_modal(modal)

        except (RuntimeError, ValueError, KeyError) as e:
            logger.error(f"Error showing password modal: {e}", exc_info=True)
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(_("❌ An error occurred. Please try again."), ephemeral=True, delete_after=NOTICE_STAYS_FOR)
                else:
                    await interaction.followup.send(_("❌ An error occurred. Please try again."), ephemeral=True, delete_after=NOTICE_STAYS_FOR)
            except (discord.errors.DiscordException, RuntimeError):
                pass

class HelpButton(Button):
    """Button to show help information from /ss messages."""

    def __init__(self, cog_instance: 'DockerControlCog', channel_id: int):
        self.cog = cog_instance
        self.channel_id = channel_id

        super().__init__(
            style=discord.ButtonStyle.secondary,
            label=None,
            emoji="❔",  # Grey question mark emoji for help
            custom_id=f"help_button_{channel_id}",
            row=0
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        """Show help information when clicked."""
        # Acknowledge immediately (every _() below reloads the config); reply via followup.
        try:
            await interaction.response.defer(ephemeral=True)
        except discord.errors.NotFound:
            logger.warning(f"Help button interaction expired for channel {self.channel_id}")
            return
        except discord.errors.HTTPException as e:
            logger.error(f"Error deferring help button interaction: {e}", exc_info=True)
            return

        try:
            # Apply spam protection
            from services.infrastructure.spam_protection_service import get_spam_protection_service
            spam_service = get_spam_protection_service()
            # Through the service instead of an attribute on the button - same
            # reason as in InfoDropdownButton.
            if spam_service.is_enabled():
                try:
                    if spam_service.is_on_cooldown(interaction.user.id, "help"):
                        remaining = spam_service.get_remaining_cooldown(interaction.user.id, "help")
                        await interaction.followup.send(
                            _("⏰ Please wait {remaining:.1f} more seconds before using this button again.").format(
                                remaining=remaining
                            ),
                            ephemeral=True, delete_after=NOTICE_STAYS_FOR
                        )
                        return
                    spam_service.add_user_cooldown(interaction.user.id, "help")
                except (RuntimeError, AttributeError, KeyError) as e:
                    logger.error(f"Spam protection error for help button: {e}", exc_info=True)

            # Call the help command implementation directly

            # The one help, shared with /help (cogs/help_embed.py).
            from .help_embed import help_embed
            embed = help_embed()

            # Send as ephemeral response (interaction was deferred above)
            await interaction.followup.send(embed=embed, ephemeral=True)

            logger.info(f"Help shown for user {interaction.user.name} in channel {self.channel_id}")

        except (discord.errors.DiscordException, RuntimeError, ValueError, KeyError) as e:
            logger.error(f"Error showing help: {e}", exc_info=True)
            try:
                await interaction.followup.send(_("❌ An error occurred. Please try again."), ephemeral=True, delete_after=NOTICE_STAYS_FOR)
            except (discord.errors.DiscordException, RuntimeError):
                # Interaction may have expired
                pass
