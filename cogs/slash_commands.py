# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""The slash commands of DockerControlCog and the helpers only they use.

Moved out of cogs/docker_control.py unchanged on 2026-09-22 (roadmap Phase 3,
the cog split): /serverstatus, /ss, /control, /addadmin, /help, /ping,
/donate, /info, the spam brake they share and the donate interaction.
py-cord collects slash commands from the cog's whole class hierarchy, so a
mixin carries them; tests/spec/test_buttons_on_old_messages_keep_working.py
pins the eight command names across the move.

AddAdminModal and DonationView come from donation_ui.py (moved there in step
6 of the split, which removed the circular import that step 2 had to avoid).
"""

import asyncio
import logging
import time
from datetime import datetime, timezone

import discord
from discord.ext import commands

from services.config.config_service import load_config
from services.config.server_config_service import get_server_config_service
from utils.logging_utils import setup_logger

from .control_helpers import _channel_has_permission, container_select, get_guild_id
from .donation_ui import AddAdminModal, DonationView
from .ddc_ui import NOTICE_STAYS_FOR
from .translation_manager import _

# Same logger name as the cog: log lines and log-based tests read as before the move.
logger = setup_logger('ddc.docker_control', level=logging.INFO)


class SlashCommandsMixin:
    """Slash commands, mixed into DockerControlCog."""


    # --- Slash Commands ---
    async def _check_spam_protection(self, ctx: discord.ApplicationContext, command_name: str) -> bool:
        """Check spam protection for a command. Returns True if command can proceed, False if on cooldown."""
        from services.infrastructure.spam_protection_service import get_spam_protection_service
        spam_manager = get_spam_protection_service()

        # Through the service, identified as a COMMAND. Before, this path kept
        # its own books in a dictionary it attached FROM OUTSIDE to the service
        # object (spam_manager._command_cooldowns): never cleaned up, unknown to
        # the service - and the command per-minute limit from the panel had no
        # effect, because it counts in add_user_cooldown. That was the last of
        # thirteen places with their own books.
        # kind="command" exists since commit 8f47f7c; without it, /info and the
        # info button would share a bucket.
        # A command with cooldown 0 has no per-command pause but still counts
        # into the minute window: "0" does not mean "exempt from the per-minute
        # limit".
        if spam_manager.is_enabled():
            try:
                if spam_manager.is_on_cooldown(ctx.author.id, command_name, kind="command"):
                    remaining = int(
                        spam_manager.get_remaining_cooldown(ctx.author.id, command_name, kind="command")
                    )
                    try:
                        # Check if we need to use followup (for commands that defer early).
                        # serverstatus is deliberately missing: it checks BEFORE its
                        # defer, so a followup would have no response to attach to.
                        if command_name in ['donate', 'donatebroadcast', 'ss']:
                            await ctx.followup.send(_("❌ Command on cooldown. Try again in {remaining} seconds.").format(remaining=remaining))
                        else:
                            await ctx.respond(_("❌ Command on cooldown. Try again in {remaining} seconds.").format(remaining=remaining), ephemeral=True)
                    except (discord.errors.HTTPException, discord.errors.NotFound):
                        # If response fails, still prevent command execution
                        pass
                    return False
                spam_manager.add_user_cooldown(ctx.author.id, command_name, kind="command")
            except (RuntimeError, AttributeError, KeyError) as e:
                logger.error(f"Spam protection error for command '{command_name}': {e}", exc_info=True)

        return True

    @commands.slash_command(name="serverstatus", description=_("Shows the status of all containers"), guild_ids=get_guild_id())
    async def serverstatus(self, ctx: discord.ApplicationContext):
        """Shows an overview of all server statuses in a single message."""
        try:
            # Spam protection BEFORE the defer (operator decision 2026-09-19):
            # the defer below is public, and a refusal after it replaced the
            # "thinking..." message for the whole channel. Before it, the refusal
            # goes to the user only via respond(ephemeral=True). Cost: one read of
            # the configuration before the defer - with an overloaded bot a
            # slightly higher risk of "Unknown interaction".
            if not await self._check_spam_protection(ctx, "serverstatus"):
                return

            # CRITICAL: Defer early to prevent Discord timeout (must respond within 3 seconds)
            # ROBUST: Handle "Unknown interaction" gracefully (happens when bot is slow/overloaded)
            try:
                await ctx.defer()
            except discord.NotFound as e:
                if e.code == 10062:  # Unknown interaction
                    logger.error(f"⚠️ Interaction expired before defer - bot was too slow! User needs to retry. Error: {e}")
                    # Cannot respond anymore - interaction is dead. User needs to retry the command.
                    return
                else:
                    raise  # Re-raise other NotFound errors

            # Import translation function locally to ensure it's accessible
            from .translation_manager import _ as translate

            # Check if the channel has serverstatus permission AND is NOT a control channel
            # Status commands (/ss, /serverstatus) should ONLY work in status channels
            channel_has_status_perm = _channel_has_permission(ctx.channel.id, 'serverstatus', self.config)
            channel_is_control = _channel_has_permission(ctx.channel.id, 'control', self.config)

            if not channel_has_status_perm or channel_is_control:
                embed = discord.Embed(
                    title=translate("⚠️ Permission Denied"),
                    description=translate("The /serverstatus command is only allowed in status channels, not in control channels."),
                    color=discord.Color.red()
                )
                await ctx.followup.send(embed=embed, ephemeral=True)
                return

            config = load_config()
            if not config:
                await ctx.followup.send(_("Error: Could not load configuration."), ephemeral=True, delete_after=NOTICE_STAYS_FOR)
                return

            # DOCKER CONNECTIVITY CHECK: Check before attempting to get container status
            from services.infrastructure.docker_connectivity_service import get_docker_connectivity_service, DockerConnectivityRequest, DockerErrorEmbedRequest

            connectivity_service = get_docker_connectivity_service()
            connectivity_request = DockerConnectivityRequest(timeout_seconds=5.0)
            connectivity_result = await connectivity_service.check_connectivity(connectivity_request)

            if not connectivity_result.is_connected:
                logger.warning(f"[SERVERSTATUS] Docker connectivity failed: {connectivity_result.error_message}")

                # Create Docker connectivity error embed using service
                lang = config.get('language', 'de')
                embed_request = DockerErrorEmbedRequest(
                    error_message=connectivity_result.error_message,
                    language=lang,
                    context='serverstatus'
                )
                embed_result = connectivity_service.create_error_embed_data(embed_request)

                if not embed_result.success:
                    logger.error(f"Failed to create Docker connectivity error embed: {embed_result.error}", exc_info=True)
                    await ctx.followup.send(_("Error creating connectivity status message."), ephemeral=True, delete_after=NOTICE_STAYS_FOR)
                    return

                # Create Discord embed from service result
                embed = discord.Embed(
                    title=embed_result.title,
                    description=embed_result.description,
                    color=embed_result.color
                )
                embed.set_footer(text=embed_result.footer_text)

                await ctx.followup.send(embed=embed)
                return

            # Get all servers and sort them by the 'order' field from container configurations
            # SERVICE FIRST: Use ServerConfigService instead of direct config access
            server_config_service = get_server_config_service()
            servers = server_config_service.get_all_servers()
            ordered_servers = sorted(servers, key=lambda s: s.get('order', 999))

            channel_id = ctx.channel.id

            # SERVICE FIRST: Log decision for manual /ss command (always proceeds but logs settings)
            try:
                from services.discord.status_overview_service import log_channel_update_decision
                log_channel_update_decision(
                    channel_id=channel_id,
                    global_config=config,
                    last_update_time=None,  # Manual commands ignore timing
                    reason="manual_serverstatus_command"
                )
            except (ImportError, AttributeError, RuntimeError) as service_error:
                logger.warning(f"SERVICE_FIRST: Error logging decision for manual /ss command: {service_error}")

            embed, animation_file = await self._create_overview_embed_collapsed(ordered_servers, config, force_refresh=True)

            # The overview's buttons: Mech, info, admin, help
            from .control_ui import MechView
            view = MechView(self, channel_id)

            # FIX B: serialize delete-old + post + track against other overview posters
            # (inactivity regenerate, event recreate, recovery) to prevent duplicate overviews.
            async with self._get_channel_lock(ctx.channel.id):
                # Delete old overview message if it exists (prevents duplicate messages)
                if ctx.channel.id in self.channel_server_message_ids and "overview" in self.channel_server_message_ids[ctx.channel.id]:
                    old_message_id = self.channel_server_message_ids[ctx.channel.id]["overview"]
                    try:
                        old_message = await ctx.channel.fetch_message(old_message_id)
                        await old_message.delete()
                        logger.debug(f"Deleted old overview message {old_message_id} in channel {ctx.channel.id}")
                    except discord.NotFound:
                        logger.debug(f"Old overview message {old_message_id} not found (already deleted)")
                    except (discord.Forbidden, discord.HTTPException) as e:
                        logger.warning(f"Could not delete old overview message {old_message_id}: {e}")

                # EDGE CASE: Safely send embed with animation and button
                try:
                    if animation_file:
                        # Validate file before sending
                        if hasattr(animation_file, 'fp') and animation_file.fp:
                            message = await ctx.followup.send(embed=embed, file=animation_file, view=view)
                            logger.info("✅ Sent /ss with animation and Mechonate button")
                        else:
                            logger.warning("Animation file invalid, sending without animation")
                            message = await ctx.followup.send(embed=embed, view=view)
                    else:
                        logger.warning("No animation file attached, sending embed only")
                        message = await ctx.followup.send(embed=embed, view=view)
                except discord.HTTPException as e:
                    logger.error(f"Discord error sending animation: {e}", exc_info=True)
                    # Fallback: Send without animation but with button
                    try:
                        message = await ctx.followup.send(embed=embed, view=view)
                    except (RuntimeError, OSError, ValueError) as fallback_error:
                        logger.error(f"Critical: Could not send embed at all: {fallback_error}")
                        await ctx.followup.send(_("Error generating server status overview."), ephemeral=True, delete_after=NOTICE_STAYS_FOR)
                        return

                # Update tracking information
                now_utc = datetime.now(timezone.utc)

                # Update message update time
                if ctx.channel.id not in self.last_message_update_time:
                    self.last_message_update_time[ctx.channel.id] = {}
                self.last_message_update_time[ctx.channel.id]["overview"] = now_utc

                # Track the message ID
                if ctx.channel.id not in self.channel_server_message_ids:
                    self.channel_server_message_ids[ctx.channel.id] = {}
                self.channel_server_message_ids[ctx.channel.id]["overview"] = message.id
                self._persist_tracked_message_ids()  # FIX C: survive restart -> no duplicate

            # Set last channel activity
            self.last_channel_activity[ctx.channel.id] = now_utc

        except (discord.errors.DiscordException, RuntimeError, ValueError) as e:
            logger.error(f"Error in serverstatus command: {e}", exc_info=True)
            try:
                await ctx.followup.send(_("An error occurred while generating the overview."), ephemeral=True, delete_after=NOTICE_STAYS_FOR)
            except (discord.errors.DiscordException, RuntimeError, OSError) as e:
                logger.error(f"Error generating overview: {e}", exc_info=True)

    @commands.slash_command(name="ss", description=_("Shortcut: Shows the status of all containers"), guild_ids=get_guild_id())
    async def ss(self, ctx):
        """Shortcut for the serverstatus command."""
        # Directly call serverstatus (it has its own spam protection check)
        await self.serverstatus(ctx)

    @commands.slash_command(name="control", description=_("Shows admin control overview for all containers"), guild_ids=get_guild_id())
    async def control(self, ctx: discord.ApplicationContext):
        """Show admin overview with all containers including CPU/RAM info and bulk actions."""
        try:
            # Check spam protection first
            if not await self._check_spam_protection(ctx, "control"):
                return

            # Defer the response to prevent timeout
            await ctx.defer(ephemeral=False)  # Not ephemeral, like /ss

            # Import translation function locally to ensure it's accessible
            from .translation_manager import _ as translate

            # Check if the channel has control permission
            # Control commands work in channels with control=True (regardless of serverstatus setting)
            channel_has_control_perm = _channel_has_permission(ctx.channel.id, 'control', self.config)

            if not channel_has_control_perm:
                embed = discord.Embed(
                    title=translate("⚠️ Permission Denied"),
                    description=translate("The /control command is only allowed in control channels, not in status channels."),
                    color=discord.Color.red()
                )
                await ctx.followup.send(embed=embed, ephemeral=True)
                return

            # Load configuration
            config = load_config()
            if not config:
                await ctx.followup.send(_("❌ Could not load configuration."))
                return

            # Get all server configurations
            # SERVICE FIRST: Use ServerConfigService instead of direct config access
            server_config_service = get_server_config_service()
            servers = server_config_service.get_all_servers()
            if not servers:
                await ctx.followup.send(_("❌ No servers configured."))
                return

            # Sort servers by order
            ordered_servers = sorted(servers, key=lambda s: s.get('order', 999))

            # Create Admin Overview embed with CPU and RAM info
            # Don't unpack into `_` - that would make the translation function local (UnboundLocalError)
            embed, _animation_file, has_running = await self._create_admin_overview_embed(ordered_servers, config, force_refresh=True)

            # Import AdminOverviewView from admin_overview module
            from .admin_overview import AdminOverviewView

            # Create the Admin Overview view with buttons
            view = AdminOverviewView(self, ctx.channel_id, has_running)

            # Send the Admin Overview message and track it for updates
            # FIX B: serialize post+track against other overview posters for this channel.
            async with self._get_channel_lock(ctx.channel_id):
                # Delete the admin overview we track before posting the next one -
                # what /ss does for its overview. Without it the old message stayed
                # in the channel, untracked: a second admin panel, frozen at the
                # moment it was posted, with buttons that still work.
                tracked_old = (self.channel_server_message_ids.get(ctx.channel_id) or {}).get('admin_overview')
                if tracked_old:
                    channel = self.bot.get_channel(ctx.channel_id)
                    try:
                        if channel:
                            await channel.get_partial_message(tracked_old).delete()
                            logger.debug(f"Deleted old admin overview {tracked_old} in channel {ctx.channel_id}")
                    except discord.NotFound:
                        pass
                    except (discord.Forbidden, discord.HTTPException) as e:
                        # Remembered so a later regenerate clears it (see
                        # _delete_tracked_overview_messages)
                        logger.warning(f"Could not delete old admin overview {tracked_old}: {e}")
                        self.__dict__.setdefault('_undeleted_messages', {}).setdefault(
                            ctx.channel_id, set()).add(tracked_old)

                message = await ctx.followup.send(embed=embed, view=view)

                # Track message for automatic updates (like /ss)
                channel_id = ctx.channel_id
                if channel_id not in self.channel_server_message_ids:
                    self.channel_server_message_ids[channel_id] = {}
                self.channel_server_message_ids[channel_id]['admin_overview'] = message.id
                self._persist_tracked_message_ids()  # FIX C: survive restart -> no duplicate

            logger.info(f"Control command used by {ctx.author} in {ctx.channel.name}")

        except (discord.errors.DiscordException, RuntimeError, ValueError) as e:
            logger.error(f"Error in control command: {e}", exc_info=True)
            try:
                if not ctx.response.is_done():
                    await ctx.respond(_("❌ Error showing control overview."))
                else:
                    await ctx.followup.send(_("❌ Error showing control overview."))
            except (discord.errors.DiscordException, RuntimeError):
                pass

    @commands.slash_command(name="addadmin", description=_("Add a user to the admin list"), guild_ids=get_guild_id())
    async def addadmin(self, ctx: discord.ApplicationContext):
        """Add a Discord user to the admin list via modal."""
        try:
            # Import translation function locally to ensure it's accessible
            from .translation_manager import _ as translate

            # The same brake every other command of this cog asks for. This one
            # opens a modal that writes to the admin list, and it was the only
            # command anybody could repeat as fast as Discord allows (review B38).
            if not await self._check_spam_protection(ctx, "addadmin"):
                return

            # Check channel permissions
            channel_has_control_perm = _channel_has_permission(ctx.channel.id, 'control', self.config)
            channel_has_status_perm = _channel_has_permission(ctx.channel.id, 'serverstatus', self.config)

            # Determine if user can use this command
            if channel_has_control_perm:
                # Control channel: any user in control channel can add admins
                # (Control channels are already restricted to admins by design)
                pass
            elif channel_has_status_perm:
                # Status channel: only existing admins can add new admins
                from services.admin.admin_service import get_admin_service
                admin_service = get_admin_service()
                user_is_admin = admin_service.is_user_admin(ctx.author.id)

                if not user_is_admin:
                    embed = discord.Embed(
                        title=translate("⚠️ Permission Denied"),
                        description=translate("Only admins can add new admins in status channels. Use this command in a control channel or ask an existing admin."),
                        color=discord.Color.red()
                    )
                    await ctx.respond(embed=embed, ephemeral=True)
                    return
            else:
                # Neither control nor status channel
                embed = discord.Embed(
                    title=translate("⚠️ Permission Denied"),
                    description=translate("The /addadmin command can only be used in control or status channels."),
                    color=discord.Color.red()
                )
                await ctx.respond(embed=embed, ephemeral=True)
                return

            # Show the modal to add admin
            modal = AddAdminModal()
            await ctx.send_modal(modal)

        except Exception as e:
            logger.error(f"Error in /addadmin command: {e}", exc_info=True)
            try:
                from .translation_manager import _ as translate
                if not ctx.response.is_done():
                    await ctx.respond(translate("❌ An error occurred. Please try again."), ephemeral=True)
                else:
                    await ctx.followup.send(translate("❌ An error occurred. Please try again."), ephemeral=True, delete_after=NOTICE_STAYS_FOR)
            except (discord.errors.DiscordException, RuntimeError):
                pass

    # Decorator adjusted
    @commands.slash_command(name="help", description=_("Displays help for available commands"), guild_ids=get_guild_id())
    async def help_command(self, ctx: discord.ApplicationContext):
        # IMMEDIATELY defer to prevent timeout - this MUST be first!
        try:
            await ctx.defer(ephemeral=True)
        except Exception:
            # Interaction already expired - nothing we can do
            return

        # Check spam protection after deferring
        if not await self._check_spam_protection(ctx, "help"):
            try:
                await ctx.followup.send(".", delete_after=0.1)
            except Exception:
                pass
            return
        """Displays help information about available commands."""
        embed = discord.Embed(
            title=_("DDC Help & Information"),
            color=discord.Color.blue()
        )

        # Tip as first field with spacing
        embed.add_field(name=f"**{_('Tip')}**", value=f"{_('Use /info <servername> to get detailed information about containers with ℹ️ indicators.')}" + "\n\u200b", inline=False)

        # General Commands (work everywhere)
        embed.add_field(name=f"**{_('General Commands')}**", value=f"`/help` - {_('Shows this help message.')}\n`/ping` - {_('Checks the bot latency.')}\n`/donate` - {_('Shows donation information to support the project.')}" + "\n\u200b", inline=False)

        # Status Channel Commands
        embed.add_field(name=f"**{_('Status Channel Commands')}**", value=f"`/serverstatus` or `/ss` - {_('Displays the status of all configured Docker containers.')}\n`/info <container>` - {_('Shows detailed container information.')}" + "\n\u200b", inline=False)

        # Control Channel Commands
        embed.add_field(name=f"**{_('Control Channel Commands')}**", value=f"`/control` - {_('(Re)generates the main control panel message in channels configured for it.')}\n**{_('Container Control')}:** {_('Click control buttons under container status panels to start, stop, or restart.')}\n**{_('Task Management')}:** {_('Click ⏰ button under container control panels to add/delete scheduled tasks.')}" + "\n\u200b", inline=False)

        # Add status indicators explanation. 🟡 was missing here and shown in
        # the overview all along - the two helps had drifted apart.
        embed.add_field(name=f"**{_('Status Indicators')}**", value=f"🟢 {_('Container is online')}\n🔴 {_('Container is offline')}\n❓ {_('Container not found')}\n🔄 {_('Container status loading')}\n🟡 {_('Action pending (starting/stopping)')}" + "\n\u200b", inline=False)

        # The group section, from the one place that writes it.
        from cogs.group_control import group_help_field

        _group_help = group_help_field()
        embed.add_field(name=_group_help[0], value=_group_help[1], inline=False)

        # Add info system explanation
        embed.add_field(name=f"**{_('Info System')}**", value=f"ℹ️ {_('Click for container details')}\n🔒 {_('Protected info (control channels only)')}\n🔓 {_('Public info available')}" + "\n\u200b", inline=False)

        # Add task management explanation
        embed.add_field(name=f"**{_('Task Scheduling')}**", value=f"⏰ {_('Click to manage scheduled tasks')}\n➕ **{_('Add Task')}** - {_('Schedule container actions (daily, weekly, monthly, yearly, once)')}\n❌ **{_('Delete Tasks')}** - {_('Remove scheduled tasks for the container')}" + "\n\u200b", inline=False)

        # Add control buttons explanation (no spacing after last field)
        embed.add_field(name=f"**{_('Control Buttons (Admin Channels)')}**", value=f"📝 {_('Edit container info text')}\n📋 {_('View container logs')}", inline=False)
        embed.set_footer(text="https://ddc.bot")

        try:
            await ctx.followup.send(embed=embed, ephemeral=True)
        except (discord.errors.DiscordException, RuntimeError, ValueError, OSError) as e:
            logger.error(f"Failed to send help message: {e}", exc_info=True)
            # Fallback - try to send minimal message
            try:
                await ctx.followup.send(_("Help information is temporarily unavailable."), ephemeral=True, delete_after=NOTICE_STAYS_FOR)
            except Exception:
                pass

    @commands.slash_command(name="ping", description=_("Shows the bot's latency"), guild_ids=get_guild_id())
    async def ping_command(self, ctx: discord.ApplicationContext):
        # Check spam protection first
        if not await self._check_spam_protection(ctx, "ping"):
            return
        latency = round(self.bot.latency * 1000)
        ping_message = _("Pong! Latency: {latency:.2f} ms").format(latency=latency)
        embed = discord.Embed(title="🏓", description=ping_message, color=discord.Color.blurple())
        await ctx.respond(embed=embed)

    @commands.slash_command(name="donate", description=_("Show donation information to support the project"), guild_ids=get_guild_id())
    async def donate_command(self, ctx: discord.ApplicationContext):
        """Show donation links to support DockerDiscordControl development."""
        # IMMEDIATELY defer to prevent timeout - this MUST be first!
        try:
            await ctx.defer(ephemeral=True)
        except Exception:
            # Interaction already expired - nothing we can do
            return

        # NOW check if donations are disabled
        try:
            from services.donation.donation_utils import is_donations_disabled
            if is_donations_disabled():
                # The SAME answer the donate BUTTON gives for the same state
                # (_handle_donate_interaction below). This used to be
                # `followup.send(".")` WITHOUT ephemeral - which after an
                # ephemeral defer is a PUBLIC message, so a "." flickered in the
                # channel while the caller's own response was never filled and
                # they were left on Discord's "thinking" state. One state, one
                # answer. The way in is ordinary: entering the premium key while
                # DDC runs leaves /donate registered until the next restart.
                try:
                    await ctx.followup.send(embed=discord.Embed(
                        title=_("🔐 Premium Features Active"),
                        description=_("Donations are disabled via premium key. "
                                      "Thank you for supporting DDC!"),
                        color=0xFFD700), ephemeral=True)
                except (RuntimeError, ValueError, KeyError, OSError,
                        discord.errors.DiscordException) as e:
                    logger.debug(f"Could not tell the caller donations are off: {e}")
                return
        except (ImportError, AttributeError, RuntimeError) as e:
            logger.debug(f"Donation check failed: {e}")

        # Check spam protection
        if not await self._check_spam_protection(ctx, "donate"):
            return

        try:
            # Donations enabled - show normal donation UI
            # Check MechService availability
            mech_service_available = False
            try:
                from services.mech.mech_service import get_mech_service
                mech_service = get_mech_service()
                mech_service_available = True
            except Exception:
                pass

            # Create donation embed
            embed = discord.Embed(
                title=_('Support DockerDiscordControl'),
                description=_(
                    'If DDC helps you, please consider supporting ongoing development. '
                    'Donations help cover hosting, CI, maintenance, and feature work.'
                ),
                color=0x00ff41
            )
            embed.add_field(
                name=_('Choose your preferred method:'),
                value=_('Click one of the buttons below to support DDC development'),
                inline=False
            )
            embed.set_footer(text="https://ddc.bot")

            # Send with or without view (use followup since we deferred)
            try:
                view = DonationView(mech_service_available, bot=self.bot)
                message = await ctx.followup.send(embed=embed, view=view)
                # Update view with message reference and start auto-delete timer
                view.message = message
                view.auto_delete_task = asyncio.create_task(view.start_auto_delete_timer())
                # Both of those live in memory only. A restart inside the ~15
                # minutes would leave this message standing with a button that
                # does nothing, so the id is remembered and the next start
                # clears it away (app/bot/startup_steps/donation_panels.py).
                if ctx.channel_id not in self.channel_server_message_ids:
                    self.channel_server_message_ids[ctx.channel_id] = {}
                self.channel_server_message_ids[ctx.channel_id]["donation"] = message.id
                self._persist_tracked_message_ids()
            except Exception:
                await ctx.followup.send(embed=embed)

        except Exception as e:  # noqa: BLE001
            # Broad on purpose, and it ANSWERS. This was the only command whose
            # handler just logged, while the global handler steps aside for
            # donation commands believing they answer themselves. Both doors
            # were shut: the user watched Discord's "thinking" state for ever,
            # tried again, hit the cooldown - which does answer - and concluded
            # the bot was slow. The mech service also raises DDCBaseException,
            # which the old three-type tuple did not cover.
            logger.error(f"Error in donate command: {e}", exc_info=True)
            try:
                await ctx.followup.send(
                    _("❌ The donation panel could not be shown. The reason is in "
                      "the DDC log."),
                    ephemeral=True, delete_after=NOTICE_STAYS_FOR)
            except (discord.errors.DiscordException, RuntimeError) as answer_error:
                # Nothing left to answer with - the channel may forbid even this.
                logger.error(f"Could not tell the user either: {answer_error}")

    @commands.slash_command(name="info", description=_("Show container information"), guild_ids=get_guild_id())
    async def info_command(self, ctx: discord.ApplicationContext,
                           container_name: str = discord.Option(description=_("The Docker container name"), autocomplete=container_select)):
        """Shows container information with appropriate buttons based on channel permissions."""
        # Log command invocation for debugging with unique tracking
        import time
        import uuid
        call_id = str(uuid.uuid4())[:8]
        timestamp = time.time()
        logger.info(f"INFO COMMAND INVOKED: call_id={call_id}, container={container_name}, user={ctx.author.id}, channel={ctx.channel_id}, interaction_id={ctx.interaction.id if hasattr(ctx, 'interaction') else 'unknown'}, timestamp={timestamp}")

        try:
            # Check spam protection first
            if not await self._check_spam_protection(ctx, "info"):
                return

            # Try to defer immediately, but handle timeout gracefully
            deferred = False
            try:
                if not ctx.response.is_done():
                    await ctx.response.defer(ephemeral=True)
                    deferred = True
                    logger.debug(f"Successfully deferred /info command for {container_name}")
                else:
                    logger.debug(f"Interaction response already done for /info command, will use followup")
                    deferred = True  # We'll use followup
            except discord.errors.NotFound:
                # Interaction already timed out, but we can still try to respond
                logger.debug(f"Interaction already timed out for /info command, attempting direct response")
                deferred = False
            except (discord.errors.DiscordException, RuntimeError) as e:
                logger.warning(f"Failed to defer /info command: {e}")
                deferred = False

            # Check if this channel has 'info' permission
            from .control_helpers import _channel_has_permission
            config = self.config
            has_info_permission = _channel_has_permission(ctx.channel_id, 'info', config) if config else False

            if not has_info_permission:
                if deferred:
                    await ctx.followup.send(_("You do not have permission to use the info command in this channel."), ephemeral=True, delete_after=NOTICE_STAYS_FOR)
                else:
                    await ctx.respond(_("You do not have permission to use the info command in this channel."), ephemeral=True)
                return

            # Check if container exists in config
            # SERVICE FIRST: Use ServerConfigService instead of direct config access
            server_config_service = get_server_config_service()
            servers = server_config_service.get_all_servers()
            server_config = next((s for s in servers if s.get('docker_name') == container_name), None)
            if not server_config:
                if deferred:
                    await ctx.followup.send(_("Container '{container}' not found in configuration.").format(container=container_name), ephemeral=True, delete_after=NOTICE_STAYS_FOR)
                else:
                    await ctx.respond(_("Container '{container}' not found in configuration.").format(container=container_name), ephemeral=True)
                return

            # Load container info to check if info is enabled
            from services.infrastructure.container_info_service import get_container_info_service
            info_service = get_container_info_service()
            info_result = info_service.get_container_info(container_name)

            # More robust checking with better error handling
            if not info_result.success:
                logger.warning(f"Failed to load container info for {container_name}: {info_result.error if hasattr(info_result, 'error') else 'Unknown error'}")
                if deferred:
                    await ctx.followup.send(_("Could not load container information for '{container}'.").format(container=container_name), ephemeral=True, delete_after=NOTICE_STAYS_FOR)
                else:
                    await ctx.respond(_("Could not load container information for '{container}'.").format(container=container_name), ephemeral=True)
                return

            if not info_result.data:
                logger.warning(f"No container info data found for {container_name}")
                if deferred:
                    await ctx.followup.send(_("Container information is not configured for '{container}'.").format(container=container_name), ephemeral=True, delete_after=NOTICE_STAYS_FOR)
                else:
                    await ctx.respond(_("Container information is not configured for '{container}'.").format(container=container_name), ephemeral=True)
                return

            # Debug the enabled flag
            enabled_value = info_result.data.enabled
            logger.info(f"DEBUG INFO COMMAND: {call_id} - Container {container_name} enabled value: {enabled_value} (type: {type(enabled_value)})")

            if not enabled_value:
                logger.info(f"Container info is disabled for {container_name} - call_id: {call_id}")
                if deferred:
                    await ctx.followup.send(_("Container information is not enabled for '{container}'.").format(container=container_name), ephemeral=True, delete_after=NOTICE_STAYS_FOR)
                else:
                    await ctx.respond(_("Container information is not enabled for '{container}'.").format(container=container_name), ephemeral=True)
                return

            # Convert ContainerInfo to dict for compatibility
            info_config = info_result.data.to_dict()

            # Check if this is a control channel
            has_control = _channel_has_permission(ctx.channel_id, 'control', config) if config else False

            # Generate info embed using the same logic as StatusInfoButton
            from .status_info_integration import StatusInfoButton
            info_button = StatusInfoButton(self, server_config, info_config)
            embed = await info_button._generate_info_embed(include_protected=has_control)

            # Create view with appropriate buttons based on channel type
            view = None
            if has_control:
                # Control channel: Show admin buttons (Edit Info, Protected Info Edit, Debug)
                from .status_info_integration import ContainerInfoAdminView
                view = ContainerInfoAdminView(self, server_config, info_config)
            else:
                # Status channel: Show protected info button if enabled
                if info_config.get('protected_enabled', False):
                    from .status_info_integration import ProtectedInfoOnlyView
                    view = ProtectedInfoOnlyView(self, server_config, info_config)

            # Send response - check for race condition with autocomplete first
            try:
                # Check if interaction has already been acknowledged (race condition with autocomplete)
                if ctx.interaction.response.is_done():
                    logger.warning(f"Interaction already acknowledged for /info {container_name} - call_id: {call_id}. Using followup instead.")
                    if view:
                        await ctx.followup.send(embed=embed, view=view, ephemeral=True)
                    else:
                        await ctx.followup.send(embed=embed, ephemeral=True)
                elif deferred:
                    logger.debug(f"Sending followup response for /info {container_name}")
                    if view:
                        await ctx.followup.send(embed=embed, view=view, ephemeral=True)
                    else:
                        await ctx.followup.send(embed=embed, ephemeral=True)
                else:
                    logger.debug(f"Sending direct response for /info {container_name}")
                    if view:
                        await ctx.respond(embed=embed, view=view, ephemeral=True)
                    else:
                        await ctx.respond(embed=embed, ephemeral=True)
            except discord.errors.NotFound:
                logger.warning(f"Interaction expired for /info {container_name}, cannot send response")
                return
            except discord.errors.HTTPException as e:
                logger.error(f"HTTP error sending /info response for {container_name}: {e}", exc_info=True)
                return

            logger.info(f"INFO COMMAND COMPLETED: call_id={call_id}, container={container_name}, user={ctx.author.id}, channel={ctx.channel_id}, info={has_info_permission}, control={has_control}, deferred={deferred}, timestamp={time.time()}")
            return  # Important: Return here to prevent fall-through to error handling

        except (discord.errors.DiscordException, RuntimeError, ValueError) as e:
            logger.error(f"Error in info command for {container_name}: {e}", exc_info=True)
            # Try to send error message if possible
            try:
                if 'deferred' in locals() and deferred:
                    await ctx.followup.send(_("An error occurred while retrieving container information."), ephemeral=True, delete_after=NOTICE_STAYS_FOR)
                else:
                    await ctx.respond(_("An error occurred while retrieving container information."), ephemeral=True)
            except Exception:
                pass  # If we can't send error message, just log it

    async def _send_message_with_files(self, target, embed, file, view=None):
        """Helper to send messages with either single file or no files."""
        if file:
            # WEBP EMBEDDING SUCCESS: Use combined method (embed + file in same message)
            # The fix was preserving .webp extension instead of forcing .gif
            logger.debug(f"Sending combined message with WebP animation: {file.filename}")

            # Combined method (single message with embed + file)
            if view:
                return await target.send(embed=embed, file=file, view=view)
            else:
                return await target.send(embed=embed, file=file)
        else:
            # No files - and then the embed must not point at one. The overview
            # builder sets attachment://mech_animation.webp so an EDIT keeps the
            # attachment already on the message; on a fresh send without a file
            # that is a broken image (the first /ss in a channel).
            if embed.image and (embed.image.url or "").startswith("attachment://"):
                embed.set_image(url=None)
            if view:
                return await target.send(embed=embed, view=view)
            else:
                return await target.send(embed=embed)

    async def _handle_donate_interaction(self, interaction):
        """Handle Mechonate button interaction - shows donation options."""
        try:

            # Check if MechService is available
            try:
                from services.mech.mech_service import get_mech_service
                # Test if we can get the service
                mech_service = get_mech_service()
                mech_service_available = True
                logger.info("MechService is available for donations")
            except (ImportError, AttributeError, RuntimeError) as e:
                mech_service_available = False
                logger.warning(f"MechService not available: {e}")

            # Check if donations are disabled by premium key (now use config service)
            try:
                from services.config.config_service import get_config_service
                config_service = get_config_service()
                config = config_service.get_config()
                donations_disabled = bool(config.get('donation_disable_key'))
            except Exception:
                donations_disabled = False

            if donations_disabled:
                embed = discord.Embed(
                    title=_("🔐 Premium Features Active"),
                    description=_("Donations are disabled via premium key. Thank you for supporting DDC!"),
                    color=0xFFD700  # Gold color
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

            # Create donation embed (same as /donate command)
            embed = discord.Embed(
                title=_('Support DockerDiscordControl'),
                description=_(
                    'If DDC helps you, please consider supporting ongoing development. '
                    'Donations help cover hosting, CI, maintenance, and feature work.'
                ),
                color=0x00ff41
            )
            embed.add_field(
                name=_('Choose your preferred method:'),
                value=_('Click one of the buttons below to support DDC development'),
                inline=False
            )
            embed.set_footer(text="https://ddc.bot")

            # Create view with donation buttons
            try:
                view = DonationView(mech_service_available, bot=self.bot, private=True)
                # Note: Ephemeral messages don't need auto-delete as they're private
                await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
                logger.info(f"Mechonate button used by user {interaction.user.name} ({interaction.user.id})")
            except (ImportError, AttributeError, RuntimeError) as view_error:
                logger.error(f"Error creating DonationView: {view_error}", exc_info=True)
                # Fallback without view
                await interaction.response.send_message(embed=embed, ephemeral=True)

        except (discord.errors.DiscordException, RuntimeError, ValueError) as e:
            logger.error(f"Error in _handle_donate_interaction: {e}", exc_info=True)
            try:
                error_embed = discord.Embed(
                    title=_("❌ Error"),
                    description=_("An error occurred while showing donation information. Please try again later."),
                    color=discord.Color.red()
                )
                await interaction.response.send_message(embed=error_embed, ephemeral=True)
            except Exception:
                # If we can't respond, it means the interaction was already responded to
                pass
