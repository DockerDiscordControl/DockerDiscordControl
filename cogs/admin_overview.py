# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Admin overview view for control channels - service first implementation."""

import discord
from discord.ui import View, Button
import asyncio
import logging

# SERVICE FIRST: Import all required services
from services.admin.admin_service import get_admin_service
from services.status.status_cache_service import get_status_cache_service
from services.config.server_config_service import get_server_config_service
from services.config.config_service import load_config  # Keep for backward compatibility
from cogs.translation_manager import _
from .ddc_ui import DDCView

logger = logging.getLogger('ddc.admin_overview')


async def _refresh_tracked_admin_overview(cog, channel_id: int) -> bool:
    """Refresh a channel's tracked Admin Overview message after a bulk action.

    Looks the message up by its tracked ID instead of matching the embed title, which is
    translated (e.g. "Admin-Übersicht") and therefore never matched in non-English setups.
    """
    tracked = getattr(cog, 'channel_server_message_ids', {}).get(channel_id) or {}
    message_id = tracked.get('admin_overview')
    if not message_id:
        logger.debug(f"No tracked admin overview in channel {channel_id} - nothing to refresh")
        return False
    return await cog._update_overview_message(channel_id, message_id, 'admin_overview')


async def _restart_running_servers(servers, action):
    """Restart the running ones of ``servers``; the counts, keyed "restarted"."""
    counts = await _act_on_running_servers(servers, action, "restart")
    return {"restarted": counts["done"], "failed": counts["failed"],
            "skipped": counts["skipped"], "unknown": counts["unknown"],
            "not_allowed": counts["not_allowed"]}


async def _act_on_running_servers(servers, action, verb: str):
    """Apply ``verb`` to the running ones of ``servers`` with ``action``; the counts.

    Shared by "Restart All", "Restart stack" and "Stop All", so all three treat
    a container they may not touch, one that is not running and one without a
    current status the same way - and pace themselves the same way. Stop All
    used to carry its own copy of this loop, and the copy kept the bug the
    restart path was fixed for: it paused on SUCCESSES.
    """
    attempted = 0  # counts calls, not successes: the pause is for the daemon
    done_count = 0
    failed_count = 0
    skipped_count = 0
    # Containers the status cache had nothing about. They used to land
    # in skipped_count, and the operator read "Skipped (not running)"
    # about a container that was never asked and never touched - a
    # measurement that was not taken, reported as one that was
    # (review D14).
    unknown_count = 0
    not_allowed_count = 0

    # Process containers with rate limiting
    for server in servers:
        if not isinstance(server, dict):
            continue

        docker_name = server.get('docker_name')
        if not docker_name or not isinstance(docker_name, str):
            continue

        # Respect per-container allowed_actions (same check as the single-container button)
        if verb not in server.get('allowed_actions', []):
            logger.info(f"Bulk {verb}: Skipping {docker_name} - '{verb}' not in allowed_actions")
            not_allowed_count += 1
            continue

        # SERVICE FIRST: Use StatusCacheService to check if container is running
        # IMPORTANT: Always use docker_name for cache lookups (stable identifier)
        status_cache_service = get_status_cache_service()
        cached_entry = status_cache_service.get(docker_name)

        # Extract is_running from cache data (ContainerStatusResult object)
        is_running = False
        status_known = bool(cached_entry and cached_entry.get('data'))
        if status_known:
            status_result = cached_entry['data']
            # Modern format: ContainerStatusResult dataclass
            from services.docker_status.models import ContainerStatusResult
            if isinstance(status_result, ContainerStatusResult):
                is_running = status_result.is_running
            # Backwards compatibility: old tuple format
            elif isinstance(status_result, tuple) and len(status_result) >= 2:
                is_running = status_result[1]

        if is_running:
            # One container, with timeout protection
            try:
                # Half a second between operations so the daemon is not overloaded.
                # Counted by attempts: tied to the successes it never paused at
                # all on a daemon where every call fails - the very case it is for.
                if attempted > 0:
                    await asyncio.sleep(0.5)
                attempted += 1

                # Set timeout for docker operation
                success = await asyncio.wait_for(
                    action(docker_name, verb),
                    timeout=30.0  # 30 second timeout per container
                )
                if success:
                    done_count += 1
                    logger.info(f"Successfully applied {verb} to {docker_name}")
                else:
                    failed_count += 1
                    logger.warning(f"Failed to {verb} {docker_name}")
            except asyncio.TimeoutError:
                logger.error(f"Timeout on {verb} for {docker_name}")
                failed_count += 1
            except (RuntimeError, OSError) as e:
                logger.error(f"Error on {verb} for {docker_name}: {e}", exc_info=True)
                failed_count += 1
        elif status_known:
            skipped_count += 1
        else:
            logger.warning(f"No cached status for {docker_name} - not touched, "
                           f"and reported as unchecked rather than as idle")
            unknown_count += 1

    return {"done": done_count, "failed": failed_count, "skipped": skipped_count,
            "unknown": unknown_count, "not_allowed": not_allowed_count}


async def answer_or_post(interaction, cog, channel_id: int, embed) -> None:
    """The result of a bulk action, to the presser - or to the channel.

    A bulk run may take longer than the 15 minutes Discord keeps an
    interaction's follow-up token alive; the summary must not be lost with it.
    """
    try:
        await interaction.followup.send(embed=embed, ephemeral=True)
        return
    except (discord.errors.NotFound, discord.errors.HTTPException) as error:
        logger.warning(f"Bulk action: the presser could not be answered ({error}) - "
                       f"posting the summary in channel {channel_id}")
    channel = getattr(getattr(cog, 'bot', None), 'get_channel', lambda _cid: None)(channel_id)
    if channel is None:
        logger.error(f"Bulk action: channel {channel_id} not reachable - the summary is only in this "
                     f"log: {embed.description}")
        return
    try:
        await channel.send(embed=embed)
    except (discord.errors.DiscordException, RuntimeError, OSError) as error:
        logger.error(f"Bulk action: the summary could not be posted either ({error}): {embed.description}")


def _restart_summary(counts) -> str:
    """The result text of a bulk restart."""
    description = _("Successfully restarted: **{count}** containers").format(count=counts["restarted"])
    if counts["failed"] > 0:
        description += _("\nFailed: **{count}** containers").format(count=counts["failed"])
    if counts["skipped"] > 0:
        description += _("\nSkipped (not running): **{count}** containers").format(count=counts["skipped"])
    if counts["unknown"] > 0:
        description += _("\nNot checked (no current status): **{count}** containers").format(count=counts["unknown"])
    if counts["not_allowed"] > 0:
        description += _("\nSkipped (action not allowed): **{count}** containers").format(count=counts["not_allowed"])
    return description


def _there_is_a_group_or_a_stack() -> bool:
    """True when the group/stack button has something to offer.

    Read on every render of the overview, so it never raises: a failure here
    must not cost the admin the whole view, only this one button.
    """
    try:
        from cogs.stack_restart import current_targets

        # want_stacks=False: one group is enough to answer this, and the stacks
        # cost a full scan of the container configuration - on every redraw.
        return bool(current_targets(want_stacks=False))
    except Exception as e:  # noqa: BLE001 - one button is not worth a broken overview
        logger.error(f"Could not tell whether there are groups or stacks: {e}", exc_info=True)
        return False


class AdminOverviewView(DDCView):
    """View for admin overview in control channels with bulk container management."""

    def __init__(self, cog_instance, channel_id: int, has_running_containers: bool,
                 every_button: bool = False):
        """``every_button`` is for bot.add_view: a message posted while a group
        existed still carries that button, and py-cord answers a click only for
        the custom_ids it was registered with. Drawing skips it, routing must
        not (tests/spec/test_buttons_on_old_messages_keep_working.py).
        """
        super().__init__(timeout=None)
        self.cog = cog_instance
        self.channel_id = channel_id
        self.has_running_containers = has_running_containers

        # Add buttons
        self.add_item(AdminOverviewAdminButton(cog_instance, channel_id))
        self.add_item(AdminOverviewRestartAllButton(cog_instance, channel_id, enabled=has_running_containers))
        self.add_item(AdminOverviewStopAllButton(cog_instance, channel_id, enabled=has_running_containers))
        # Only when there is something to offer - a group the operator defined or
        # a Compose stack DDC found. A button that can do nothing still takes a
        # place in a row that holds five.
        if every_button or _there_is_a_group_or_a_stack():
            self.add_item(AdminOverviewRestartStackButton(cog_instance, channel_id,
                                                          enabled=has_running_containers))
        self.add_item(AdminOverviewDonateButton(cog_instance, channel_id))

async def _admin_button_braked(interaction: discord.Interaction, name: str) -> bool:
    """Spam brake for the admin overview's buttons. True means: refused.

    None of these five asked the service at all - not the two bulk actions that
    restart or stop every running container, and not the donate button, which
    builds a fresh view on every press from a panel that is registered with
    add_view and therefore works on every overview ever posted.

    The name is the WHOLE name, because get_button_cooldown matches that first
    and only then the "mech_<slider>_" prefix rule. Each of these has an entry
    in the defaults and in the panel's save list, so the operator can see and
    change it - a name without one brakes by the five-second fallback and
    cannot be adjusted.
    """
    from services.infrastructure.spam_protection_service import get_spam_protection_service

    spam_service = get_spam_protection_service()
    if not spam_service.is_enabled():
        return False
    try:
        if spam_service.is_on_cooldown(interaction.user.id, name):
            remaining = spam_service.get_remaining_cooldown(interaction.user.id, name)
            await interaction.response.send_message(
                _("⏰ Please wait {remaining:.1f} more seconds before using this button again.").format(
                    remaining=remaining),
                ephemeral=True)
            return True
        spam_service.add_user_cooldown(interaction.user.id, name)
    except (RuntimeError, AttributeError, KeyError) as e:
        logger.error(f"Spam protection error for button '{name}': {e}", exc_info=True)
    return False


class AdminOverviewAdminButton(Button):
    """Admin button for accessing individual container controls."""

    def __init__(self, cog_instance, channel_id: int):
        self.cog = cog_instance
        self.channel_id = channel_id

        super().__init__(
            style=discord.ButtonStyle.secondary,
            label=None,
            emoji="🛠️",
            custom_id=f"admin_overview_admin_{channel_id}",
            row=0
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        """Show container selection dropdown for admin control."""
        if await _admin_button_braked(interaction, "admin_overview_admin"):
            return
        # Edge case: Immediately defer to avoid timeout
        try:
            await interaction.response.defer(ephemeral=True)
            deferred = True
        except discord.errors.NotFound:
            logger.warning(f"Admin button interaction expired for channel {self.channel_id}")
            return
        except (discord.errors.HTTPException, discord.errors.DiscordException) as e:
            logger.error(f"Error deferring admin button interaction: {e}", exc_info=True)
            return

        try:
            # Note: In control channels, all users have access to admin controls
            # No admin user check needed here (unlike Server Overview in status channels)

            # SERVICE FIRST: Use ServerConfigService to get containers
            server_config_service = get_server_config_service()
            # Use get_all_servers() to get full container data including 'order' field
            all_servers = server_config_service.get_all_servers()

            if not all_servers:
                await interaction.followup.send(
                    _("❌ No containers found in configuration."),
                    ephemeral=True
                )
                return

            # Sort containers by order field (from Web UI configuration)
            containers = sorted(all_servers, key=lambda s: s.get('order', 999))

            # Transform to the format expected by AdminContainerSelectView
            formatted_containers = []
            for server in containers:
                docker_name = server.get('docker_name')
                if docker_name:
                    # Get display name from server config
                    display_name = server.get('display_name', [docker_name, docker_name])
                    if isinstance(display_name, list) and len(display_name) > 0:
                        display_name = display_name[0]

                    formatted_containers.append({
                        'display': display_name,
                        'docker_name': docker_name,
                        'order': server.get('order', 999)  # Include order for dropdown sorting
                    })

            containers = formatted_containers

            if not containers:
                await interaction.followup.send(
                    _("❌ No valid containers found in configuration."),
                    ephemeral=True
                )
                return

            # Import AdminContainerSelectView from control_ui
            try:
                from .control_ui import AdminContainerSelectView
            except ImportError as e:
                logger.error(f"Failed to import AdminContainerSelectView: {e}")
                await interaction.followup.send(
                    _("❌ Internal error. Please try again later."),
                    ephemeral=True
                )
                return

            # Create dropdown view with containers list
            view = AdminContainerSelectView(self.cog, containers, self.channel_id,
                                            user_id=interaction.user.id)
            await interaction.followup.send(
                _("Select a container to control:"),
                view=view,
                ephemeral=True
            )

        except (discord.errors.DiscordException, ImportError, AttributeError, KeyError) as e:
            logger.error(f"Error in admin overview admin button: {e}", exc_info=True)
            try:
                # followup, not response: every one of these callbacks DEFERS
                # at the top, so is_done() is already True by the time an error
                # gets here and the whole branch was unreachable - the operator
                # was left on a spinner with only a log line.
                await interaction.followup.send(
                        _("❌ Error accessing admin controls."),
                        ephemeral=True
                    )
            except (discord.errors.NotFound, discord.errors.HTTPException):
                pass

class AdminOverviewRestartAllButton(Button):
    """Button to restart all running containers with confirmation."""

    def __init__(self, cog_instance, channel_id: int, enabled: bool):
        self.cog = cog_instance
        self.channel_id = channel_id

        super().__init__(
            style=discord.ButtonStyle.primary,
            label=None,
            emoji="🔄",
            custom_id=f"admin_overview_restart_all_{channel_id}",
            row=0,
            disabled=not enabled
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        """Ask for confirmation before restarting all containers."""
        if await _admin_button_braked(interaction, "admin_overview_restart_all"):
            return
        # Edge case: Immediately defer to avoid timeout
        try:
            await interaction.response.defer(ephemeral=True)
        except discord.errors.NotFound:
            logger.warning(f"Restart all interaction expired for channel {self.channel_id}")
            return
        except (discord.errors.HTTPException, discord.errors.DiscordException) as e:
            logger.error(f"Error deferring restart all interaction: {e}", exc_info=True)
            return

        try:
            # SERVICE FIRST: Use AdminService to check permissions
            admin_service = get_admin_service()
            user_id = str(interaction.user.id)

            # Check if user is admin using service.
            #
            # The admin list and NOT the channel's permission - SPEC.md B2:
            # the list exists so that admins may act where channel membership
            # alone permits nothing. Both review passes read the missing
            # channel check here as a critical hole (pass 1 section 01 F1,
            # pass 2 F1/F2) and both were wrong. Adding one would refuse the
            # operator in a status channel. Pinned by
            # tests/spec/test_the_bulk_buttons_answer_to_the_admin_list.py.
            is_admin = await admin_service.is_user_admin_async(user_id)
            if not is_admin:
                await interaction.followup.send(
                    _("❌ You don't have permission to restart all containers."),
                    ephemeral=True
                )
                return

            # Edge case: Check if button is already disabled
            if self.disabled:
                await interaction.followup.send(
                    _("❌ No running containers to restart."),
                    ephemeral=True
                )
                return

            # Create confirmation view
            view = RestartAllConfirmationView(self.cog, self.channel_id)
            embed = discord.Embed(
                title=_("⚠️ Confirm Restart All"),
                description=_("Are you sure you want to restart ALL running containers?\n\nThis will temporarily disrupt all services."),
                color=discord.Color.orange()
            )
            await interaction.followup.send(
                embed=embed,
                view=view,
                ephemeral=True
            )

        except (discord.errors.DiscordException, ImportError, KeyError, RuntimeError) as e:
            logger.error(f"Error in restart all button: {e}", exc_info=True)
            try:
                # followup, not response: every one of these callbacks DEFERS
                # at the top, so is_done() is already True by the time an error
                # gets here and the whole branch was unreachable - the operator
                # was left on a spinner with only a log line.
                await interaction.followup.send(
                        _("❌ Error processing restart all request."),
                        ephemeral=True
                    )
            except (discord.errors.NotFound, discord.errors.HTTPException):
                pass

class AdminOverviewStopAllButton(Button):
    """Button to stop all running containers with confirmation."""

    def __init__(self, cog_instance, channel_id: int, enabled: bool):
        self.cog = cog_instance
        self.channel_id = channel_id

        super().__init__(
            style=discord.ButtonStyle.danger,
            label=None,
            emoji="⏹️",
            custom_id=f"admin_overview_stop_all_{channel_id}",
            row=0,
            disabled=not enabled
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        """Ask for confirmation before stopping all containers."""
        if await _admin_button_braked(interaction, "admin_overview_stop_all"):
            return
        # Edge case: Immediately defer to avoid timeout
        try:
            await interaction.response.defer(ephemeral=True)
        except discord.errors.NotFound:
            logger.warning(f"Stop all interaction expired for channel {self.channel_id}")
            return
        except (discord.errors.HTTPException, discord.errors.DiscordException) as e:
            logger.error(f"Error deferring stop all interaction: {e}", exc_info=True)
            return

        try:
            # SERVICE FIRST: Use AdminService to check permissions
            admin_service = get_admin_service()
            user_id = str(interaction.user.id)

            # Check if user is admin using service.
            #
            # The admin list and NOT the channel's permission - SPEC.md B2:
            # the list exists so that admins may act where channel membership
            # alone permits nothing. Both review passes read the missing
            # channel check here as a critical hole (pass 1 section 01 F1,
            # pass 2 F1/F2) and both were wrong. Adding one would refuse the
            # operator in a status channel. Pinned by
            # tests/spec/test_the_bulk_buttons_answer_to_the_admin_list.py.
            is_admin = await admin_service.is_user_admin_async(user_id)
            if not is_admin:
                await interaction.followup.send(
                    _("❌ You don't have permission to stop all containers."),
                    ephemeral=True
                )
                return

            # Edge case: Check if button is already disabled
            if self.disabled:
                await interaction.followup.send(
                    _("❌ No running containers to stop."),
                    ephemeral=True
                )
                return

            # Create confirmation view
            view = StopAllConfirmationView(self.cog, self.channel_id)
            embed = discord.Embed(
                title=_("🚨 Confirm Stop All"),
                description=_("Are you sure you want to STOP ALL running containers?\n\n**WARNING:** This will shut down all services!"),
                color=discord.Color.red()
            )
            await interaction.followup.send(
                embed=embed,
                view=view,
                ephemeral=True
            )

        except (discord.errors.DiscordException, ImportError, KeyError, RuntimeError) as e:
            logger.error(f"Error in stop all button: {e}", exc_info=True)
            try:
                # followup, not response: every one of these callbacks DEFERS
                # at the top, so is_done() is already True by the time an error
                # gets here and the whole branch was unreachable - the operator
                # was left on a spinner with only a log line.
                await interaction.followup.send(
                        _("❌ Error processing stop all request."),
                        ephemeral=True
                    )
            except (discord.errors.NotFound, discord.errors.HTTPException):
                pass

class AdminOverviewRestartStackButton(Button):
    """Button to restart one Compose stack; the flow is in cogs/stack_restart.py."""

    def __init__(self, cog_instance, channel_id: int, enabled: bool):
        self.cog = cog_instance
        self.channel_id = channel_id

        super().__init__(
            style=discord.ButtonStyle.primary,
            # No label: with one, this was the only wide button in the row and
            # the whole overview grew with it (operator, 2026-09-23).
            label=None,
            emoji="🗂️",
            custom_id=f"admin_overview_restart_stack_{channel_id}",
            row=0,
            disabled=not enabled
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if await _admin_button_braked(interaction, "admin_overview_restart_stack"):
            return
        try:
            await interaction.response.defer(ephemeral=True)
        except (discord.errors.NotFound, discord.errors.HTTPException) as e:
            logger.warning(f"Restart stack interaction could not be answered: {e}")
            return
        from .stack_restart import offer_stacks
        await offer_stacks(self.cog, self.channel_id, interaction)

class AdminOverviewDonateButton(Button):
    """Donate button for supporting the project."""

    def __init__(self, cog_instance, channel_id: int):
        self.cog = cog_instance
        self.channel_id = channel_id

        super().__init__(
            style=discord.ButtonStyle.success,  # Green button
            label=None,  # No text, only icon
            emoji="💖",  # Heart icon for donations
            custom_id=f"admin_overview_donate_{channel_id}",
            row=0
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        """Execute /donate command when clicked."""
        if await _admin_button_braked(interaction, "admin_overview_donate"):
            return
        # Edge case: Immediately defer to avoid timeout
        try:
            await interaction.response.defer(ephemeral=True)
        except discord.errors.NotFound:
            logger.warning(f"Donate button interaction expired for channel {self.channel_id}")
            return
        except (discord.errors.HTTPException, discord.errors.DiscordException) as e:
            logger.error(f"Error deferring donate button interaction: {e}", exc_info=True)
            return

        try:
            # Check if donations are disabled
            try:
                from services.donation.donation_utils import is_donations_disabled
                if is_donations_disabled():
                    # Donations disabled, send minimal response
                    try:
                        await interaction.followup.send(".", delete_after=0.1)
                    except (discord.errors.HTTPException, discord.errors.NotFound) as e:
                        logger.debug(f"Failed to send donation disabled response: {e}")
                    return
            except ImportError as e:
                logger.warning(f"Donation utils not available: {e}")
            except (AttributeError, RuntimeError) as e:
                logger.debug(f"Donation check failed: {e}")

            # Create donation embed (matching the /donate command)
            from .translation_manager import _ as translate

            embed = discord.Embed(
                title=translate('Support DockerDiscordControl'),
                description=translate(
                    'If DDC helps you, please consider supporting ongoing development. '
                    'Donations help cover hosting, CI, maintenance, and feature work.'
                ),
                color=0x00ff41  # Green color
            )
            embed.add_field(
                name=translate('Choose your preferred method:'),
                value=translate('Click one of the buttons below to support DDC development'),
                inline=False
            )

            # Create donation view with buttons
            # Check MechService availability (same as /donate command)
            mech_service_available = False
            try:
                from services.mech.mech_service import get_mech_service
                mech_service = get_mech_service()
                mech_service_available = True
            except (ImportError, AttributeError, ModuleNotFoundError, RuntimeError):
                pass

            # Import DonationView from docker_control
            from .docker_control import DonationView
            view = DonationView(mech_service_available, bot=self.cog.bot)

            # Send the donation embed with buttons
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)

        except (discord.errors.DiscordException, ImportError, AttributeError) as e:
            logger.error(f"Error in donate button: {e}", exc_info=True)
            try:
                # followup, not response: every one of these callbacks DEFERS
                # at the top, so is_done() is already True by the time an error
                # gets here and the whole branch was unreachable - the operator
                # was left on a spinner with only a log line.
                await interaction.followup.send(
                        _("❌ Error processing donate request."),
                        ephemeral=True
                    )
            except (discord.errors.NotFound, discord.errors.HTTPException):
                pass

# =============================================================================
# CONFIRMATION VIEWS FOR BULK ACTIONS
# =============================================================================

class RestartAllConfirmationView(DDCView):
    """Confirmation view for restarting all containers."""

    def __init__(self, cog_instance, channel_id: int):
        super().__init__(timeout=30)
        self.cog = cog_instance
        self.channel_id = channel_id

        # Add confirm and cancel buttons
        self.add_item(ConfirmRestartAllButton(cog_instance, channel_id))
        self.add_item(CancelBulkActionButton())

class StopAllConfirmationView(DDCView):
    """Confirmation view for stopping all containers."""

    def __init__(self, cog_instance, channel_id: int):
        super().__init__(timeout=30)
        self.cog = cog_instance
        self.channel_id = channel_id

        # Add confirm and cancel buttons
        self.add_item(ConfirmStopAllButton(cog_instance, channel_id))
        self.add_item(CancelBulkActionButton())

class ConfirmRestartAllButton(Button):
    """Button to confirm restart all action."""

    def __init__(self, cog_instance, channel_id: int):
        self.cog = cog_instance
        self.channel_id = channel_id

        super().__init__(
            style=discord.ButtonStyle.danger,
            label=_("Yes, Restart All"),
            custom_id="confirm_restart_all"
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        """Execute restart all containers."""
        # Edge case: Defer immediately
        try:
            await interaction.response.defer()
        except discord.errors.NotFound:
            logger.warning("Restart all confirmation interaction expired")
            return
        except (discord.errors.HTTPException, discord.errors.DiscordException) as e:
            logger.error(f"Error deferring restart all confirmation: {e}", exc_info=True)
            return

        # The admin list again, at THIS press. The first button checked it up
        # to 30 seconds ago; this is a separate interaction, and the Z5
        # clarification says the list is read at the moment of the press and
        # never from a message. Without it this callback authorised nothing at
        # all - its only protection was that Discord does not deliver an
        # ephemeral message's interaction to anybody else (review D36).
        #
        # NO channel check here, deliberately: SPEC.md B2 - the global admin
        # list exists so that admins may act where channel membership alone
        # permits nothing. Adding one would refuse the operator in a status
        # channel, which is exactly the regression the Z5 fix of 2026-09-16/17
        # caused and that had to be undone on 2026-09-19. Both review passes
        # read this as a hole; it is a decision. See
        # tests/spec/test_the_bulk_buttons_answer_to_the_admin_list.py.
        try:
            admin_service = get_admin_service()
            if not await admin_service.is_user_admin_async(str(interaction.user.id)):
                await interaction.followup.send(
                    _("❌ You don't have permission for this action."),
                    ephemeral=True
                )
                return
        except (AttributeError, ImportError, RuntimeError) as e:
            # A permission that cannot be read is not a permission granted.
            logger.error(f"Could not check admin status for bulk action: {e}", exc_info=True)
            await interaction.followup.send(
                _("❌ Your permission could not be checked. Nothing was done."),
                ephemeral=True
            )
            return

        # Edge case: Prevent concurrent bulk operations
        if hasattr(self.cog, '_bulk_operation_in_progress'):
            if self.cog._bulk_operation_in_progress:
                await interaction.followup.send(
                    _("⏳ Another bulk operation is in progress. Please wait."),
                    ephemeral=True
                )
                return

        # Set operation lock
        self.cog._bulk_operation_in_progress = True

        try:
            # SERVICE FIRST: Use ServerConfigService to get server configurations
            server_config_service = get_server_config_service()
            all_servers = server_config_service.get_all_servers()

            # CRITICAL: Filter to only ACTIVE containers (as shown in Admin Overview)
            # A missing 'active' field means active (same default as ServerConfigService)
            servers = [s for s in all_servers if s.get('active', True)]

            if not servers:
                await interaction.followup.send(
                    _("❌ No active servers configured."),
                    ephemeral=True
                )
                return

            logger.info(f"Restart All: Processing {len(servers)} active containers (filtered from {len(all_servers)} total)")

            # Import docker service with error handling
            try:
                from services.docker_service.docker_action_service import docker_action_service_first
            except ImportError as e:
                logger.error(f"Failed to import docker action service: {e}")
                await interaction.followup.send(
                    _("❌ Docker service unavailable. Operation cancelled."),
                    ephemeral=True
                )
                return

            counts = await _restart_running_servers(servers, docker_action_service_first)
            failed_count = counts["failed"]
            description = _restart_summary(counts)

            embed = discord.Embed(
                title=_("🔄 Restart All Complete"),
                description=description,
                color=discord.Color.green() if failed_count == 0 else discord.Color.orange()
            )
            await answer_or_post(interaction, self.cog, self.channel_id, embed)

            # Update admin overview after a delay (but don't wait for it)
            asyncio.create_task(self._delayed_overview_update())

        except (ImportError, KeyError, RuntimeError, asyncio.TimeoutError) as e:
            logger.error(f"Critical error in restart all: {e}", exc_info=True)
            try:
                await interaction.followup.send(
                    _("❌ An error occurred during the restart operation."),
                    ephemeral=True
                )
            except (discord.errors.NotFound, discord.errors.HTTPException):
                pass
        finally:
            # Always release the lock
            self.cog._bulk_operation_in_progress = False

    async def _delayed_overview_update(self):
        """Update admin overview after a delay."""
        try:
            await asyncio.sleep(5)
            await self._update_admin_overview()
        except RuntimeError as e:
            logger.error(f"Error updating admin overview after restart: {e}", exc_info=True)

    async def _update_admin_overview(self):
        """Update admin overview message after bulk action."""
        try:
            await _refresh_tracked_admin_overview(self.cog, self.channel_id)
        except (discord.errors.DiscordException, ImportError, AttributeError) as e:
            logger.error(f"Error updating admin overview: {e}", exc_info=True)

class ConfirmStopAllButton(Button):
    """Button to confirm stop all action."""

    def __init__(self, cog_instance, channel_id: int):
        self.cog = cog_instance
        self.channel_id = channel_id

        super().__init__(
            style=discord.ButtonStyle.danger,
            label=_("Yes, Stop All"),
            custom_id="confirm_stop_all"
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        """Execute stop all containers."""
        # Edge case: Defer immediately
        try:
            await interaction.response.defer()
        except discord.errors.NotFound:
            logger.warning("Stop all confirmation interaction expired")
            return
        except (discord.errors.HTTPException, discord.errors.DiscordException) as e:
            logger.error(f"Error deferring stop all confirmation: {e}", exc_info=True)
            return

        # The admin list again, at THIS press. The first button checked it up
        # to 30 seconds ago; this is a separate interaction, and the Z5
        # clarification says the list is read at the moment of the press and
        # never from a message. Without it this callback authorised nothing at
        # all - its only protection was that Discord does not deliver an
        # ephemeral message's interaction to anybody else (review D36).
        #
        # NO channel check here, deliberately: SPEC.md B2 - the global admin
        # list exists so that admins may act where channel membership alone
        # permits nothing. Adding one would refuse the operator in a status
        # channel, which is exactly the regression the Z5 fix of 2026-09-16/17
        # caused and that had to be undone on 2026-09-19. Both review passes
        # read this as a hole; it is a decision. See
        # tests/spec/test_the_bulk_buttons_answer_to_the_admin_list.py.
        try:
            admin_service = get_admin_service()
            if not await admin_service.is_user_admin_async(str(interaction.user.id)):
                await interaction.followup.send(
                    _("❌ You don't have permission for this action."),
                    ephemeral=True
                )
                return
        except (AttributeError, ImportError, RuntimeError) as e:
            # A permission that cannot be read is not a permission granted.
            logger.error(f"Could not check admin status for bulk action: {e}", exc_info=True)
            await interaction.followup.send(
                _("❌ Your permission could not be checked. Nothing was done."),
                ephemeral=True
            )
            return

        # Edge case: Prevent concurrent bulk operations
        if hasattr(self.cog, '_bulk_operation_in_progress'):
            if self.cog._bulk_operation_in_progress:
                await interaction.followup.send(
                    _("⏳ Another bulk operation is in progress. Please wait."),
                    ephemeral=True
                )
                return

        # Set operation lock
        self.cog._bulk_operation_in_progress = True

        try:
            # SERVICE FIRST: Use ServerConfigService to get server configurations
            server_config_service = get_server_config_service()
            all_servers = server_config_service.get_all_servers()

            # CRITICAL: Filter to only ACTIVE containers (as shown in Admin Overview)
            # A missing 'active' field means active (same default as ServerConfigService)
            servers = [s for s in all_servers if s.get('active', True)]

            if not servers:
                await interaction.followup.send(
                    _("❌ No active servers configured."),
                    ephemeral=True
                )
                return

            logger.info(f"Stop All: Processing {len(servers)} active containers (filtered from {len(all_servers)} total)")

            # Import docker service with error handling
            try:
                from services.docker_service.docker_action_service import docker_action_service_first
            except ImportError as e:
                logger.error(f"Failed to import docker action service: {e}")
                await interaction.followup.send(
                    _("❌ Docker service unavailable. Operation cancelled."),
                    ephemeral=True
                )
                return

            # One loop for all three bulk buttons (_act_on_running_servers):
            # this used to be a copy of the restart loop, and the copy kept the
            # bug the restart path was fixed for - it paused on SUCCESSES, so a
            # daemon where every stop fails got no pause at all.
            counts = await _act_on_running_servers(servers, docker_action_service_first, "stop")
            stopped_count = counts["done"]
            failed_count = counts["failed"]
            skipped_count = counts["skipped"]
            unknown_count = counts["unknown"]
            not_allowed_count = counts["not_allowed"]

            # Send result message
            description = _("Successfully stopped: **{count}** containers").format(count=stopped_count)
            if failed_count > 0:
                description += _("\nFailed: **{count}** containers").format(count=failed_count)
            if skipped_count > 0:
                description += _("\nSkipped (not running): **{count}** containers").format(count=skipped_count)
            if unknown_count > 0:
                description += _("\nNot checked (no current status): **{count}** containers").format(count=unknown_count)
            if not_allowed_count > 0:
                description += _("\nSkipped (action not allowed): **{count}** containers").format(count=not_allowed_count)

            embed = discord.Embed(
                title=_("⏹️ Stop All Complete"),
                description=description,
                color=discord.Color.green() if failed_count == 0 else discord.Color.orange()
            )
            await answer_or_post(interaction, self.cog, self.channel_id, embed)

            # Update admin overview after a delay (but don't wait for it)
            asyncio.create_task(self._delayed_overview_update())

        except (ImportError, KeyError, RuntimeError, asyncio.TimeoutError) as e:
            logger.error(f"Critical error in stop all: {e}", exc_info=True)
            try:
                await interaction.followup.send(
                    _("❌ An error occurred during the stop operation."),
                    ephemeral=True
                )
            except (discord.errors.NotFound, discord.errors.HTTPException):
                pass
        finally:
            # Always release the lock
            self.cog._bulk_operation_in_progress = False

    async def _delayed_overview_update(self):
        """Update admin overview after a delay."""
        try:
            await asyncio.sleep(5)
            await self._update_admin_overview()
        except RuntimeError as e:
            logger.error(f"Error updating admin overview after stop: {e}", exc_info=True)

    async def _update_admin_overview(self):
        """Update admin overview message after bulk action."""
        try:
            await _refresh_tracked_admin_overview(self.cog, self.channel_id)
        except (discord.errors.DiscordException, ImportError, AttributeError) as e:
            logger.error(f"Error updating admin overview: {e}", exc_info=True)

class CancelBulkActionButton(Button):
    """Button to cancel bulk action."""

    def __init__(self):
        super().__init__(
            style=discord.ButtonStyle.secondary,
            label=_("Cancel"),
            custom_id="cancel_bulk_action"
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        """Cancel the bulk action."""
        try:
            await interaction.response.edit_message(
                content=_("✅ Action cancelled."),
                embed=None,
                view=None
            )
        except discord.errors.NotFound:
            logger.warning("Cancel button interaction expired")
        except (discord.errors.HTTPException, discord.errors.DiscordException) as e:
            logger.error(f"Error in cancel button: {e}", exc_info=True)
