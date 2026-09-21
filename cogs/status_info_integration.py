# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Status Info Integration                        #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #

"""
Smart integration of container info into status-only channels.
Provides read-only info display for channels with only /ss permission.
"""

import discord
from services.config.config_service import load_config
from discord.ui import View, Button
from typing import Dict, Any, Optional, List
from utils.logging_utils import get_module_logger
from services.infrastructure.container_info_service import get_container_info_service
from utils.time_utils import get_datetime_imports

# Get datetime imports
datetime, timedelta, timezone, time = get_datetime_imports()
from utils.common_helpers import get_public_ip
from .translation_manager import _
import asyncio
import aiohttp
from services.automation import get_auto_action_config_service

logger = get_module_logger('status_info_integration')

async def container_logs_text(container_name: str) -> str:
    """Get the last N log lines for a container, ready for a Discord embed.

    Stood twice, character for character, as a method on LiveLogView and on
    DebugLogsButton. Both used nothing but ``self.container_name``, so the copy
    had no reason beyond convenience - and a copy is a correction that only ever
    lands in one place. See docs/quality/STAGE0_INVENTORY.md section 7.
    """
    try:
        import docker
        import asyncio
        from utils.common_helpers import validate_container_name
        from utils.settings import get_setting

        # Validate container name for security
        if not validate_container_name(container_name):
            return f"Invalid container name format: {container_name}"

        # Use synchronous Docker client for stable log retrieval
        def get_logs_sync():
            client = docker.from_env()
            try:
                container = client.containers.get(container_name)
                tail_lines = get_setting('DDC_LIVE_LOGS_TAIL_LINES', 50)
                logs_bytes = container.logs(tail=tail_lines, timestamps=True)
                return logs_bytes.decode('utf-8', errors='replace')
            finally:
                client.close()

        # Run synchronous operation in thread pool to avoid blocking
        logs = await asyncio.get_event_loop().run_in_executor(None, get_logs_sync)

        # Limit log output to prevent Discord message limits
        if len(logs) > 1800:  # Leave room for embed formatting
            logs = logs[-1800:]
            logs = "...\n" + logs

        return logs.strip() or "No logs available for this container."

    except docker.errors.NotFound:
        return f"Container '{container_name}' not found."
    except (docker.errors.DockerException, RuntimeError, OSError) as e:
        logger.debug(f"Error getting logs for {container_name}: {e}")
        return f"Error retrieving logs: {str(e)[:100]}"

class ContainerInfoAdminView(discord.ui.View):
    """
    Admin view for container info with Edit and Debug buttons (control channels only).
    """

    def __init__(self, cog_instance, server_config: Dict[str, Any], info_config: Dict[str, Any], message=None):
        # Set timeout to maximum (just under Discord's 15-minute limit)
        super().__init__(timeout=890)  # 14.8 minutes timeout
        self.cog = cog_instance
        self.server_config = server_config
        self.info_config = info_config
        self.container_name = server_config.get('docker_name')
        self.message = message  # Store reference to the message for auto-delete
        self.auto_delete_task = None

        # Add Edit Info button
        self.add_item(EditInfoButton(cog_instance, server_config, info_config))

        # Add Protected Info Edit button (for editing protected info settings)
        self.add_item(ProtectedInfoEditButton(cog_instance, server_config, info_config))

        # Add Task Management button
        self.add_item(TaskManagementButton(cog_instance, server_config))

        # Add Debug button
        self.add_item(DebugLogsButton(cog_instance, server_config))

    async def on_timeout(self):
        """Called when the view times out."""
        try:
            # Cancel auto-delete task if it exists
            if self.auto_delete_task and not self.auto_delete_task.done():
                self.auto_delete_task.cancel()

            # Delete the message when timeout occurs
            if self.message:
                logger.info("ContainerInfoAdminView timeout reached, deleting message to prevent inactive buttons")
                try:
                    await self.message.delete()
                except discord.NotFound:
                    logger.debug("Message already deleted")
                except (discord.errors.DiscordException, RuntimeError, OSError) as e:
                    logger.error(f"Error deleting info message on timeout: {e}", exc_info=True)
        except (RuntimeError, ValueError, KeyError) as e:
            logger.error(f"Error in ContainerInfoAdminView.on_timeout: {e}", exc_info=True)

    async def start_auto_delete_timer(self):
        """Start the auto-delete timer that runs shortly before timeout."""
        try:
            # Wait for 885 seconds (14.75 minutes), then delete message
            # This gives us a 5-second buffer before Discord's timeout
            await asyncio.sleep(885)
            if self.message:
                logger.info("Auto-deleting info message before Discord timeout")
                try:
                    await self.message.delete()
                except discord.NotFound:
                    logger.debug("Message already deleted")
                except (discord.errors.DiscordException, RuntimeError, OSError) as e:
                    logger.error(f"Error auto-deleting info message: {e}", exc_info=True)
        except asyncio.CancelledError:
            logger.debug("Auto-delete timer cancelled")
        except (RuntimeError, ValueError, KeyError) as e:
            logger.error(f"Error in auto-delete timer: {e}", exc_info=True)


class ProtectedInfoEditButton(discord.ui.Button):
    """Protected Info Edit button for managing protected container information."""

    def __init__(self, cog_instance, server_config: Dict[str, Any], info_config: Dict[str, Any]):
        super().__init__(
            style=discord.ButtonStyle.secondary,
            emoji="🔒",
            label=None,
            custom_id=f"protected_edit_{server_config.get('docker_name')}"
        )
        self.cog = cog_instance
        self.server_config = server_config
        self.info_config = info_config
        self.container_name = server_config.get('docker_name')

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle protected info edit button click."""
        # Check button cooldown first
        from services.infrastructure.spam_protection_service import get_spam_protection_service
        spam_manager = get_spam_protection_service()

        # Through the service instead of past it. Before, the timestamp lived
        # under button_protected_edit_<user> in self.cog._button_cooldowns, and
        # only the DURATION came from the service. The per-minute limit from the
        # panel therefore had no effect here - it counts in add_user_cooldown,
        # and this path never got there. Own key with value 3 (the former
        # "info"), so that today's separate buckets STAY separate: a shared
        # "info" would merge three locks into one.
        if spam_manager.is_enabled():
            try:
                if spam_manager.is_on_cooldown(interaction.user.id, "protected_info_edit"):
                    remaining = spam_manager.get_remaining_cooldown(interaction.user.id, "protected_info_edit")
                    await interaction.response.send_message(
                        _("⏰ Please wait {remaining:.1f} more seconds before using this button again.").format(
                            remaining=remaining
                        ),
                        ephemeral=True
                    )
                    return
                spam_manager.add_user_cooldown(interaction.user.id, "protected_info_edit")
            except (RuntimeError, AttributeError, KeyError) as e:
                logger.error(f"Spam protection error for protected info edit button: {e}", exc_info=True)

        try:
            # Import modal from enhanced_info_modal_simple
            from .enhanced_info_modal_simple import ProtectedInfoModal

            # Get display name
            display_name = self.server_config.get('name', self.container_name)

            modal = ProtectedInfoModal(
                self.cog,
                container_name=self.container_name,
                display_name=display_name
            )

            await interaction.response.send_modal(modal)
            logger.info(f"Opened protected info edit modal for {self.container_name} for user {interaction.user.id}")

        except (RuntimeError, ValueError, KeyError) as e:
            logger.error(f"Error opening protected info edit modal for {self.container_name}: {e}", exc_info=True)
            try:
                await interaction.response.send_message(
                    _("❌ Could not open protected info edit modal. Please try again later."),
                    ephemeral=True
                )
            except Exception:
                pass

class EditInfoButton(discord.ui.Button):
    """Edit Info button for container info admin view."""

    def __init__(self, cog_instance, server_config: Dict[str, Any], info_config: Dict[str, Any]):
        super().__init__(
            style=discord.ButtonStyle.secondary,
            emoji="📝",
            label=None,
            custom_id=f"edit_info_{server_config.get('docker_name')}"
        )
        self.cog = cog_instance
        self.server_config = server_config
        self.info_config = info_config
        self.container_name = server_config.get('docker_name')

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle edit info button click."""
        # Check button cooldown first
        from services.infrastructure.spam_protection_service import get_spam_protection_service
        spam_manager = get_spam_protection_service()

        # Through the service instead of past it - same reason as in
        # ProtectedInfoEditButton. Own key "edit_info" with value 3, so the
        # formerly separate bucket stays separate.
        if spam_manager.is_enabled():
            try:
                if spam_manager.is_on_cooldown(interaction.user.id, "edit_info"):
                    remaining = spam_manager.get_remaining_cooldown(interaction.user.id, "edit_info")
                    await interaction.response.send_message(
                        _("⏰ Please wait {remaining:.1f} more seconds before using this button again.").format(
                            remaining=remaining
                        ),
                        ephemeral=True
                    )
                    return
                spam_manager.add_user_cooldown(interaction.user.id, "edit_info")
            except (RuntimeError, AttributeError, KeyError) as e:
                logger.error(f"Spam protection error for edit info button: {e}", exc_info=True)

        try:
            # Import modal from enhanced_info_modal_simple
            from .enhanced_info_modal_simple import SimplifiedContainerInfoModal

            # Get display name
            display_name = self.server_config.get('name', self.container_name)

            modal = SimplifiedContainerInfoModal(
                self.cog,
                container_name=self.container_name,
                display_name=display_name
            )

            await interaction.response.send_modal(modal)
            logger.info(f"Opened edit info modal for {self.container_name} for user {interaction.user.id}")

        except (RuntimeError, ValueError, KeyError) as e:
            logger.error(f"Error opening edit info modal for {self.container_name}: {e}", exc_info=True)
            try:
                await interaction.response.send_message(
                    _("❌ Could not open edit modal. Please try again later."),
                    ephemeral=True
                )
            except Exception:
                pass

class LiveLogView(discord.ui.View):
    """View for live-updating debug logs with refresh controls."""

    def __init__(self, container_name: str, auto_refresh: bool = False):
        # Get configuration from environment variables
        from utils.settings import get_setting
        timeout_seconds = get_setting('DDC_LIVE_LOGS_TIMEOUT', 120)
        self.refresh_interval = get_setting('DDC_LIVE_LOGS_REFRESH_INTERVAL', 5)
        self.max_refreshes = get_setting('DDC_LIVE_LOGS_MAX_REFRESHES', 12)

        # Set timeout to 5 minutes, but auto-recreate before timeout
        super().__init__(timeout=300)
        self.container_name = container_name
        self.auto_refresh_enabled = auto_refresh
        self.auto_refresh_task = None
        self.refresh_count = 0
        self.message_ref = None  # Store message reference
        self.cog_instance = None  # Will be set when needed
        self.recreation_task = None  # Task for auto-recreation

        # Create all buttons in the correct order
        self._create_all_buttons()

        # Start auto-recreation task (recreate 30 seconds before timeout)
        self._start_auto_recreation()

    def _create_all_buttons(self):
        """Create all buttons in the correct order: Refresh, Start/Stop, Close."""
        # Clear all existing buttons
        self.clear_items()

        # 1. Refresh Button (Manual refresh)
        refresh_button = discord.ui.Button(
            emoji="🔄",
            style=discord.ButtonStyle.secondary,
            custom_id='manual_refresh'
        )
        refresh_button.callback = self.manual_refresh
        self.add_item(refresh_button)

        # 2. Start/Stop Toggle Button
        if self.auto_refresh_enabled:
            # Auto-refresh is ON - show STOP button
            button_emoji = "⏹️"
            button_style = discord.ButtonStyle.secondary
        else:
            # Auto-refresh is OFF - show PLAY button
            button_emoji = "▶️"
            button_style = discord.ButtonStyle.secondary

        toggle_button = discord.ui.Button(
            emoji=button_emoji,
            style=button_style,
            custom_id='toggle_auto_refresh'
        )
        toggle_button.callback = self.toggle_updates
        self.add_item(toggle_button)


    def _start_auto_recreation(self):
        """Start auto-recreation task to refresh the view before timeout."""
        import asyncio
        # Recreate 30 seconds before timeout (300s - 30s = 270s)
        self.recreation_task = asyncio.create_task(self._auto_recreation_loop())

    async def _auto_recreation_loop(self):
        """Auto-recreation loop that refreshes the view before timeout."""
        import asyncio
        try:
            # Wait for 270 seconds (30 seconds before timeout)
            await asyncio.sleep(270)

            # Only recreate if we have a message reference and the view is still active
            if self.message_ref and not self.is_finished():
                await self._recreate_view()

        except asyncio.CancelledError:
            logger.debug("Auto-recreation cancelled")
        except (discord.errors.DiscordException, RuntimeError, OSError) as e:
            logger.error(f"Auto-recreation error: {e}", exc_info=True)

    async def _recreate_view(self):
        """Recreate the Live Logs message with a fresh view."""
        try:
            if not self.message_ref:
                return

            logger.info(f"Auto-recreating Live Logs view for container {self.container_name}")

            # Get current logs
            logs = await container_logs_text(self.container_name)

            # Create new view with same state
            new_view = LiveLogView(self.container_name, self.auto_refresh_enabled)
            new_view.refresh_count = self.refresh_count
            new_view.cog_instance = self.cog_instance

            # Determine embed based on current state
            if self.auto_refresh_enabled and self.auto_refresh_task and not self.auto_refresh_task.done():
                # Auto-refresh is currently running
                remaining = self.max_refreshes - self.refresh_count
                embed = discord.Embed(
                    title=f"🔍 Live Logs - {self.container_name}",
                    description=f"```\n{logs}\n```",
                    color=0x00ff00,
                    timestamp=datetime.now(timezone.utc)
                )
                embed.set_footer(text=f"🔄 Auto-refreshing every {self.refresh_interval}s • {remaining} updates remaining")
            else:
                # Auto-refresh is not running
                embed = discord.Embed(
                    title=f"📄 Logs - {self.container_name}",
                    description=f"```\n{logs}\n```",
                    color=0x0099ff,
                    timestamp=datetime.now(timezone.utc)
                )
                embed.set_footer(text="📄 Static logs • Click ▶️ to start live updates")

            # Edit the message with new view
            await self.message_ref.edit(embed=embed, view=new_view)

            # Transfer message reference to new view
            new_view.message_ref = self.message_ref

            # Transfer auto-refresh task if running
            if self.auto_refresh_enabled and self.auto_refresh_task and not self.auto_refresh_task.done():
                # Cancel old task and start new one on new view
                self.auto_refresh_task.cancel()
                await new_view.start_auto_refresh(self.message_ref)

            # Cancel our own tasks since we're being replaced
            if self.auto_refresh_task:
                self.auto_refresh_task.cancel()
            if self.recreation_task:
                self.recreation_task.cancel()

            logger.info(f"Successfully recreated Live Logs view for container {self.container_name}")

        except (discord.errors.DiscordException, RuntimeError, OSError) as e:
            logger.error(f"Failed to recreate Live Logs view for {self.container_name}: {e}", exc_info=True)

    async def start_auto_refresh(self, message):
        """Start auto-refresh task for live updates."""
        if not self.auto_refresh_enabled:
            return

        import asyncio
        self.message_ref = message
        self.auto_refresh_task = asyncio.create_task(
            self._auto_refresh_loop()
        )

    async def _auto_refresh_loop(self):
        """Auto-refresh loop that updates logs at configured intervals."""
        import asyncio

        try:
            while self.refresh_count < self.max_refreshes and self.auto_refresh_enabled:
                await asyncio.sleep(self.refresh_interval)  # Wait configured interval

                self.refresh_count += 1

                # Get updated logs
                logs = await container_logs_text(self.container_name)

                if logs and self.message_ref:
                    # Update embed
                    embed = discord.Embed(
                        title=f"🔍 Live Logs - {self.container_name}",
                        description=f"```\n{logs}\n```",
                        color=0x00ff00,
                        timestamp=datetime.now(timezone.utc)
                    )

                    remaining = self.max_refreshes - self.refresh_count

                    if remaining > 0:
                        embed.set_footer(text=f"🔄 Auto-refreshing every {self.refresh_interval}s • {remaining} updates remaining")
                    else:
                        embed.set_footer(text="✅ Auto-refresh completed • Click ▶️ to restart live updates")
                        embed.color = 0x808080  # Change to gray when done
                        self.auto_refresh_enabled = False
                        self.auto_refresh_task = None  # Clear task reference
                        # Recreate all buttons with correct state (Stop -> Play)
                        self._create_all_buttons()

                    # Update message
                    try:
                        logger.debug(f"Auto-refresh updating message {self.message_ref.id} for container {self.container_name}")
                        await self.message_ref.edit(embed=embed, view=self)
                    except (discord.errors.DiscordException, RuntimeError, OSError) as e:
                        logger.error(f"Auto-refresh update failed for message {self.message_ref.id}: {e}", exc_info=True)
                        break

            # Ensure cleanup after loop ends
            if self.auto_refresh_enabled:
                self.auto_refresh_enabled = False
                self.auto_refresh_task = None
                # Update buttons one final time to show correct state
                self._create_all_buttons()
                if self.message_ref:
                    try:
                        await self.message_ref.edit(view=self)
                    except (discord.errors.HTTPException, discord.errors.NotFound) as e:
                        logger.debug(f"Failed to update buttons after auto-refresh end: {e}")

        except asyncio.CancelledError:
            logger.debug("Auto-refresh cancelled")
        except (discord.errors.DiscordException, RuntimeError, OSError) as e:
            logger.error(f"Auto-refresh error: {e}", exc_info=True)

    async def manual_refresh(self, interaction: discord.Interaction):
        """Manual refresh button."""
        # Check button cooldown first
        from services.infrastructure.spam_protection_service import get_spam_protection_service
        spam_manager = get_spam_protection_service()

        # Through the service instead of on the view. Before, the timestamp
        # lived under button_refresh_<user> in self._button_cooldowns - a
        # dictionary the view created for itself. Two consequences: the
        # per-minute LIMIT from the panel had no effect (it counts in
        # add_user_cooldown, and this path never got there), and the lock died
        # with the VIEW. That weighed especially here, because the live-log view
        # renews itself (_start_auto_recreation rebuilds it 30 seconds before the
        # timeout) - whoever waited that long lost every cooldown, without any
        # of it being visible. The message was also untranslated; the existing
        # catalog entry is used now. Refused via send_message, because nothing
        # has been acknowledged at this point.
        if spam_manager.is_enabled():
            try:
                if spam_manager.is_on_cooldown(interaction.user.id, "live_refresh"):
                    remaining = spam_manager.get_remaining_cooldown(interaction.user.id, "live_refresh")
                    await interaction.response.send_message(
                        _("⏰ Please wait {remaining:.1f} more seconds before using this button again.").format(
                            remaining=remaining
                        ),
                        ephemeral=True
                    )
                    return
                spam_manager.add_user_cooldown(interaction.user.id, "live_refresh")
            except (RuntimeError, AttributeError, KeyError) as e:
                logger.error(f"Spam protection error for live log refresh button: {e}", exc_info=True)

        try:
            # Immediately send response to avoid timeout
            await interaction.response.send_message(_("🔄 Refreshing logs..."), ephemeral=True, delete_after=1)

            # Get updated logs
            logs = await container_logs_text(self.container_name)

            if logs and self.message_ref:
                # Update the existing message for public messages
                embed = discord.Embed(
                    title=f"🔄 Debug Logs - {self.container_name}",
                    description=f"```\n{logs}\n```",
                    color=0x0099ff,
                    timestamp=datetime.now(timezone.utc)
                )
                embed.set_footer(text="🔄 Manually refreshed • Click again to update")

                try:
                    await self.message_ref.edit(embed=embed, view=self)
                    # Log refresh is visible in the message update, no additional confirmation needed
                except (discord.errors.HTTPException, discord.errors.NotFound) as edit_error:
                    logger.debug(f"Manual refresh edit failed: {edit_error}")
            else:
                logger.warning("Manual refresh failed - no logs retrieved")

        except (discord.errors.DiscordException, RuntimeError, OSError) as e:
            logger.error(f"Manual refresh error: {e}", exc_info=True)

    async def toggle_updates(self, interaction: discord.Interaction):
        """Toggle auto-refresh updates - stop or start based on current state."""
        try:
            # Immediately send response to avoid timeout
            await interaction.response.send_message(_("⏳ Updating..."), ephemeral=True, delete_after=1)

            # Check current state and toggle
            if self.auto_refresh_enabled and self.auto_refresh_task:
                # Currently running - STOP
                self.auto_refresh_task.cancel()
                self.auto_refresh_enabled = False

                # Update button state
                self._create_all_buttons()

                # Update embed
                if self.message_ref:
                    logs = await container_logs_text(self.container_name)
                    embed = discord.Embed(
                        title=f"⏹️ Debug Logs - {self.container_name}",
                        description=f"```\n{logs}\n```",
                        color=0xff6600,
                        timestamp=datetime.now(timezone.utc)
                    )
                    embed.set_footer(text="⏹️ Auto-refresh stopped • Click Start to restart")

                    try:
                        await self.message_ref.edit(embed=embed, view=self)
                    except (discord.errors.HTTPException, discord.errors.NotFound) as e:
                        logger.debug(f"Failed to update message after stop: {e}")
                else:
                    logger.debug("Auto-refresh stopped but no message reference")

            else:
                # Currently stopped - START
                self.refresh_count = 0
                self.auto_refresh_enabled = True

                # Update button state
                self._create_all_buttons()

                # Update embed and restart auto-refresh
                if self.message_ref:
                    logs = await container_logs_text(self.container_name)
                    embed = discord.Embed(
                        title=f"▶️ Live Logs - {self.container_name}",
                        description=f"```\n{logs}\n```",
                        color=0x00ff00,
                        timestamp=datetime.now(timezone.utc)
                    )
                    embed.set_footer(text=f"▶️ Auto-refresh restarted • Updating every {self.refresh_interval} seconds")

                    try:
                        await self.message_ref.edit(embed=embed, view=self)

                        # Restart auto-refresh task
                        import asyncio
                        self.auto_refresh_task = asyncio.create_task(
                            self._auto_refresh_loop()
                        )

                        pass  # Successful restart is visible in the message update
                    except (discord.errors.HTTPException, discord.errors.NotFound) as e:
                        logger.debug(f"Failed to update message after restart: {e}")
                else:
                    logger.debug("Auto-refresh restarted but no message reference")

        except (discord.errors.DiscordException, RuntimeError, OSError) as e:
            logger.error(f"Toggle updates error: {e}", exc_info=True)


    async def on_timeout(self):
        """Handle view timeout by disabling buttons."""
        try:
            # Cancel any running auto-refresh task
            if self.auto_refresh_task:
                self.auto_refresh_task.cancel()
                self.auto_refresh_enabled = False

            # Cancel recreation task if running
            if self.recreation_task:
                self.recreation_task.cancel()

            # Disable all buttons to show the view has timed out
            for item in self.children:
                if hasattr(item, 'disabled'):
                    item.disabled = True

            # Update the message to show buttons are disabled
            if self.message_ref:
                try:
                    # Get current embed and update it
                    current_embed = self.message_ref.embeds[0] if self.message_ref.embeds else None
                    if current_embed:
                        current_embed.set_footer(text="⏰ Live Logs view timed out • Use /info command to create new Live Logs")
                        current_embed.color = 0x808080  # Gray color
                        await self.message_ref.edit(embed=current_embed, view=self)
                    logger.info(f"Live Logs view timed out for container {self.container_name}")
                except (discord.errors.HTTPException, discord.errors.NotFound) as e:
                    logger.debug(f"Failed to update message on timeout: {e}")
        except (RuntimeError, ValueError, KeyError) as e:
            logger.error(f"Error in on_timeout: {e}", exc_info=True)

class DebugLogsButton(discord.ui.Button):
    """Debug logs button for container info admin view with live updates."""

    def __init__(self, cog_instance, server_config: Dict[str, Any]):
        super().__init__(
            style=discord.ButtonStyle.secondary,
            emoji="📋",
            label=None,
            custom_id=f"debug_logs_{server_config.get('docker_name')}"
        )
        self.cog = cog_instance
        self.server_config = server_config
        self.container_name = server_config.get('docker_name')

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle debug logs button click with live-updating response."""
        try:
            # Try to defer immediately to avoid timeout
            try:
                await interaction.response.defer(ephemeral=True)
            except discord.errors.NotFound:
                logger.warning(f"Debug logs interaction expired for {self.container_name}")
                return
            except (discord.errors.DiscordException, RuntimeError, OSError) as e:
                logger.error(f"Error deferring debug logs interaction: {e}", exc_info=True)
                return

            # Check button cooldown after deferring
            from services.infrastructure.spam_protection_service import get_spam_protection_service
            spam_manager = get_spam_protection_service()

            # Through the service instead of past it. Before, this place kept
            # its own books: timestamp under button_logs_<user> in
            # self.cog._button_cooldowns, while only the DURATION came from the
            # service. As a result the per-minute LIMIT from the panel had no
            # effect here - it counts in add_user_cooldown, and this path never
            # got there. The cooldown worked, the per-minute limit did not;
            # exactly the mix nobody notices.
            # Key, duration and bucket stay unchanged ("logs", 10 s, not used as
            # a lock anywhere else). New is only that the press is recorded and
            # so counts towards the per-minute limit.
            # Refused via followup, because it was acknowledged above.
            if spam_manager.is_enabled():
                try:
                    if spam_manager.is_on_cooldown(interaction.user.id, "logs"):
                        remaining = spam_manager.get_remaining_cooldown(interaction.user.id, "logs")
                        await interaction.followup.send(
                            _("⏰ Please wait {remaining:.1f} more seconds before using this button again.").format(
                                remaining=remaining
                            ),
                            ephemeral=True
                        )
                        return
                    spam_manager.add_user_cooldown(interaction.user.id, "logs")
                except (RuntimeError, AttributeError, KeyError) as e:
                    logger.error(f"Spam protection error for debug logs button: {e}", exc_info=True)

            # Check if Live Logs feature is enabled
            from utils.settings import get_setting
            live_logs_enabled = get_setting('DDC_LIVE_LOGS_ENABLED', True, bool)

            if not live_logs_enabled:
                # Live Logs feature is disabled - show error message
                await interaction.followup.send(
                    _("❌ Live Logs feature is currently disabled by administrator."),
                    ephemeral=True
                )
                return

            logger.info(f"Live debug logs (ephemeral) requested for container: {self.container_name}")

            # Check if auto-start is enabled via environment variable
            auto_start_enabled = get_setting('DDC_LIVE_LOGS_AUTO_START', False, bool)

            # Get initial logs
            log_lines = await container_logs_text(self.container_name)

            if log_lines:
                # Create live log view - auto-refresh based on setting
                view = LiveLogView(self.container_name, auto_refresh=auto_start_enabled)
                view.cog_instance = self.cog  # Set cog reference for recreation

                # Create debug embed with appropriate title and color
                if auto_start_enabled:
                    # Auto-start enabled - show live indicator
                    embed = discord.Embed(
                        title=f"🔍 Live Logs - {self.server_config.get('name', self.container_name)}",
                        description=f"```\n{log_lines}\n```",
                        color=0x00ff00  # Green for live
                    )
                    embed.set_footer(text="https://ddc.bot")
                else:
                    # Auto-start disabled - show static logs
                    embed = discord.Embed(
                        title=f"📄 Logs - {self.server_config.get('name', self.container_name)}",
                        description=f"```\n{log_lines}\n```",
                        color=0x808080  # Gray for static
                    )
                    embed.set_footer(text=_("https://ddc.bot • Click ▶️ to start live updates"))

                # Send ephemeral message
                message = await interaction.followup.send(embed=embed, view=view, ephemeral=True)

                if auto_start_enabled:
                    logger.info(f"Created live debug message (ephemeral) with auto-refresh for container {self.container_name}")
                    # Start auto-refresh
                    await view.start_auto_refresh(message)
                else:
                    logger.info(f"Created static debug message (ephemeral) for container {self.container_name} - auto-start disabled")
                    # Store message reference for manual start later
                    view.message_ref = message

                logger.info(f"Debug logs displayed for {self.container_name} for user {interaction.user.id} (auto-start: {auto_start_enabled})")
            else:
                await interaction.followup.send(
                    "❌ Could not retrieve debug logs for this container.",
                    ephemeral=True
                )

        except (RuntimeError, ValueError, KeyError) as e:
            logger.error(f"Error getting live debug logs for {self.container_name}: {e}", exc_info=True)
            try:
                if interaction.response.is_done():
                    await interaction.followup.send(
                        "❌ Error retrieving debug logs. Please try again later.",
                        ephemeral=True
                    )
                else:
                    await interaction.response.send_message(
                        "❌ Error retrieving debug logs. Please try again later.",
                        ephemeral=True
                    )
            except Exception:
                pass

class StatusInfoView(discord.ui.View):
    """
    View for status-only channels that provides info display without control buttons.
    Only shows info button when container has info enabled.
    """

    def __init__(self, cog_instance, server_config: Dict[str, Any], is_running: bool):
        super().__init__(timeout=None)  # Persistent view
        self.cog = cog_instance
        self.server_config = server_config
        self.is_running = is_running
        self.container_name = server_config.get('docker_name')

        # Load container info to check if info is enabled
        info_service = get_container_info_service()
        info_result = info_service.get_container_info(self.container_name)
        self.info_config = info_result.data.to_dict() if info_result.success else {}

        # Only add info button if info is enabled
        if self.info_config.get('enabled', False):
            self.add_item(StatusInfoButton(cog_instance, server_config, self.info_config))

        # Add Protected Info button if protected info is enabled (for password validation)
        if self.info_config.get('protected_enabled', False):
            self.add_item(ProtectedInfoButton(cog_instance, server_config, self.info_config))

class ProtectedInfoOnlyView(discord.ui.View):
    """
    View for /info command in status channels that only shows protected info button.
    """

    def __init__(self, cog_instance, server_config: Dict[str, Any], info_config: Dict[str, Any]):
        super().__init__(timeout=1800)  # 30 minute timeout
        self.cog = cog_instance
        self.server_config = server_config
        self.info_config = info_config

        # Only add Protected Info button (no regular info button since we're already showing info)
        if self.info_config.get('protected_enabled', False):
            self.add_item(ProtectedInfoButton(cog_instance, server_config, self.info_config))

class StatusInfoButton(discord.ui.Button):
    """
    Info button for status channels - shows container info in ephemeral message.
    """

    def __init__(self, cog_instance, server_config: Dict[str, Any], info_config: Dict[str, Any]):
        # Truncate container name for mobile display (max 20 chars)
        display_name = server_config.get('name', server_config.get('docker_name', 'Container'))
        truncated_name = display_name[:20] + "." if len(display_name) > 20 else display_name

        super().__init__(
            style=discord.ButtonStyle.secondary,
            emoji="ℹ️",
            label=truncated_name,
            custom_id=f"status_info_{server_config.get('docker_name')}"
        )
        self.cog = cog_instance
        self.server_config = server_config
        self.info_config = info_config
        self.container_name = server_config.get('docker_name')

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle info button click - show ephemeral info embed."""
        try:
            await interaction.response.defer(ephemeral=True)

            # Check if this is a control channel
            from .control_helpers import _channel_has_permission

            config = load_config()
            has_control = _channel_has_permission(interaction.channel_id, 'control', config) if config else False

            # Generate info embed (with protected info if in control channel)
            embed = await self._generate_info_embed(include_protected=has_control)

            # Enhanced debug logging
            logger.info(f"StatusInfoButton callback - Channel ID: {interaction.channel_id} (type: {type(interaction.channel_id)}), has_control: {has_control}")
            if config:
                channel_perms = config.get('channel_permissions', {}).get(str(interaction.channel_id))
                logger.info(f"Channel permissions for {interaction.channel_id}: {channel_perms}")
                logger.info(f"All channel permissions keys: {list(config.get('channel_permissions', {}).keys())}")
                # Test the permission function directly
                test_result = _channel_has_permission(interaction.channel_id, 'control', config)
                logger.info(f"Direct _channel_has_permission test result: {test_result}")
            else:
                logger.warning("Config is None or empty!")

            # Create view with admin buttons if in control channel
            view = None
            if has_control:
                logger.info(f"Creating ContainerInfoAdminView for {self.container_name}")
                view = ContainerInfoAdminView(self.cog, self.server_config, self.info_config)
            else:
                logger.info(f"Not creating admin view - has_control is False")

            # Send with or without view based on availability
            if view:
                await interaction.followup.send(embed=embed, view=view, ephemeral=True)
            else:
                await interaction.followup.send(embed=embed, ephemeral=True)
            logger.info(f"Displayed container info for {self.container_name} to user {interaction.user.id} (control: {has_control})")

        except (RuntimeError, ValueError, KeyError) as e:
            logger.error(f"Error in status info callback for {self.container_name}: {e}", exc_info=True)
            try:
                error_embed = discord.Embed(
                    title="❌ Error",
                    description=_("Could not load container information. Please try again later."),
                    color=discord.Color.red()
                )
                await interaction.followup.send(embed=error_embed, ephemeral=True)
            except Exception:
                pass  # Ignore errors in error handling

    async def _generate_info_embed(self, include_protected: bool = False) -> discord.Embed:
        """Generate the container info embed for display.

        Args:
            include_protected: Whether to include protected information (for control channels)
        """
        display_name = self.server_config.get('name', self.container_name)

        # Load fresh container info data to get latest protected info
        from services.infrastructure.container_info_service import get_container_info_service
        info_service = get_container_info_service()
        info_result = info_service.get_container_info(self.container_name)
        fresh_info_config = info_result.data.to_dict() if info_result.success else self.info_config

        # Create embed with container branding
        embed = discord.Embed(
            title=f"📋 {display_name} - Container Info",
            color=0x3498db
        )

        # Build description content
        description_parts = []

        # Add custom text if provided
        custom_text = fresh_info_config.get('custom_text', '').strip()
        if custom_text:
            description_parts.append(f"{custom_text}")

        # Add IP information if enabled
        if fresh_info_config.get('show_ip', False):
            ip_info = await self._get_ip_info(fresh_info_config)
            if ip_info:
                description_parts.append(ip_info)

        # Add protected information if in control channel and enabled
        if include_protected and fresh_info_config.get('protected_enabled', False):
            protected_content = fresh_info_config.get('protected_content', '').strip()
            if protected_content:
                description_parts.append("\n**🔐 Protected Information:**")
                description_parts.append(protected_content)

        # Add container status info
        status_info = self._get_status_info()
        if status_info:
            description_parts.append(status_info)

        # Set description if we have any content
        if description_parts:
            embed.description = "\n".join(description_parts)

        embed.set_footer(text="https://ddc.bot")
        return embed

    async def _get_ip_info(self, info_config: dict) -> Optional[str]:
        """Get IP information for the container."""
        custom_ip = info_config.get('custom_ip', '').strip()
        custom_port = info_config.get('custom_port', '').strip()
        # At method level, not inside the branch below: the WAN branch appends
        # the same port and is only reached when custom_ip is empty, so an
        # import inside the custom_ip branch would never have run for it.
        from .control_helpers import validate_custom_address, validate_custom_port

        if custom_ip:
            # Validate custom IP/hostname format for security
            if validate_custom_address(custom_ip):
                # Add port if provided
                address = custom_ip
                if validate_custom_port(custom_port):
                    address = f"{custom_ip}:{custom_port}"
                return f"🔗 **Custom Address:** {address}"
            else:
                logger.warning(f"Invalid custom address format: {custom_ip}")
                return "🔗 **Custom Address:** [Invalid Format]"

        # Try to get WAN IP
        try:
            from utils.common_helpers import get_wan_ip_async
            wan_ip = await get_wan_ip_async()
            if wan_ip:
                # Add port if provided
                address = wan_ip
                if validate_custom_port(custom_port):
                    address = f"{wan_ip}:{custom_port}"
                return f"**Public IP:** {address}"
        except (OSError, RuntimeError, ValueError) as e:
            logger.debug(f"Could not get WAN IP for {self.container_name}: {e}")

        return "**IP:** Auto-detection failed"


    def _get_status_info(self) -> Optional[str]:
        """Get current container status information."""
        # Status information (State/Uptime) is already displayed in the main status embed above,
        # so we don't need to duplicate it in the info section
        return None

class ProtectedInfoButton(discord.ui.Button):
    """
    Protected Info button for status-only channels - opens password validation modal.
    """

    def __init__(self, cog_instance, server_config: Dict[str, Any], info_config: Dict[str, Any]):
        super().__init__(
            style=discord.ButtonStyle.secondary,
            emoji="🔐",
            label=None,
            custom_id=f"protected_info_{server_config.get('docker_name')}"
        )
        self.cog = cog_instance
        self.server_config = server_config
        self.info_config = info_config
        self.container_name = server_config.get('docker_name')

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle protected info button click - open password validation modal."""
        # Check button cooldown first
        from services.infrastructure.spam_protection_service import get_spam_protection_service
        spam_manager = get_spam_protection_service()

        # Through the service instead of past it - same reason as in
        # ProtectedInfoEditButton. Own key "protected_info" with value 3, so the
        # formerly separate bucket stays separate.
        if spam_manager.is_enabled():
            try:
                if spam_manager.is_on_cooldown(interaction.user.id, "protected_info"):
                    remaining = spam_manager.get_remaining_cooldown(interaction.user.id, "protected_info")
                    await interaction.response.send_message(
                        _("⏰ Please wait {remaining:.1f} more seconds before using this button again.").format(
                            remaining=remaining
                        ),
                        ephemeral=True
                    )
                    return
                spam_manager.add_user_cooldown(interaction.user.id, "protected_info")
            except (RuntimeError, AttributeError, KeyError) as e:
                logger.error(f"Spam protection error for protected info button: {e}", exc_info=True)

        try:
            # Import password validation modal from enhanced_info_modal_simple
            from .enhanced_info_modal_simple import PasswordValidationModal

            # Get display name
            display_name = self.server_config.get('name', self.container_name)

            modal = PasswordValidationModal(
                self.cog,
                container_name=self.container_name,
                display_name=display_name,
                container_info=self.info_config
            )

            await interaction.response.send_modal(modal)
            logger.info(f"Opened password validation modal for {self.container_name} for user {interaction.user.id}")

        except (RuntimeError, ValueError, KeyError) as e:
            logger.error(f"Error opening password validation modal for {self.container_name}: {e}", exc_info=True)
            try:
                await interaction.response.send_message(
                    _("❌ Could not open protected info modal. Please try again later."),
                    ephemeral=True
                )
            except Exception:
                pass

def create_enhanced_status_embed(
    original_embed: discord.Embed,
    server_config: Dict[str, Any],
    info_indicator: bool = False
) -> discord.Embed:
    """
    Enhance a status embed with info indicators for status channels.

    Args:
        original_embed: The original status embed
        server_config: Server configuration
        info_indicator: Whether to add info indicator to the embed

    Returns:
        Enhanced embed with info indicators
    """
    if not info_indicator:
        return original_embed

    # Skip enrichments for Admin Control messages
    if server_config.get('_is_admin_control', False):
        return original_embed

    try:
        # Load container info
        container_name = server_config.get('docker_name')
        info_service = get_container_info_service()
        info_result = info_service.get_container_info(container_name)
        info_config = info_result.data.to_dict() if info_result.success else {}

        if not info_config.get('enabled', False):
            return original_embed

        # Add info indicator to embed description
        if original_embed.description:
            # Look for the closing ``` to insert info indicator
            description = original_embed.description

            # Find the last occurrence of ``` (closing code block)
            last_code_block = description.rfind('```')
            if last_code_block != -1:
                # Insert info indicator before closing code block
                before_closing = description[:last_code_block]
                after_closing = description[last_code_block:]

                # Add info line inside the box
                info_line = "│ ℹ️ *Additional info available*\n"

                # Insert before the footer line (look for └ character)
                footer_pos = before_closing.rfind('└')
                if footer_pos != -1:
                    # Find start of footer line (last \n before └)
                    footer_line_start = before_closing.rfind('\n', 0, footer_pos)
                    if footer_line_start != -1:
                        enhanced_description = (
                            before_closing[:footer_line_start + 1] +
                            info_line +
                            before_closing[footer_line_start + 1:] +
                            after_closing
                        )
                        original_embed.description = enhanced_description

        # Add subtle footer enhancement
        current_footer = original_embed.footer.text if original_embed.footer else ""

        # Security: Validate URL properly to prevent malicious URLs like:
        # - "https://evil-ddc.bot" (would pass simple endswith check)
        # - "Visit https://ddc.bot.evil.com • https://ddc.bot" (would affect multiple URLs with replace)
        # Use exact match for the complete footer or validate suffix properly
        if current_footer == "https://ddc.bot":
            # Exact match - safe to enhance
            enhanced_footer = "ℹ️ Info Available • https://ddc.bot"
            original_embed.set_footer(text=enhanced_footer)
        elif current_footer.endswith(" • https://ddc.bot") or current_footer.endswith(" https://ddc.bot"):
            # Footer ends with separator + our URL - safe to enhance
            # Only replace the exact suffix at the end, not all occurrences
            if current_footer.endswith(" • https://ddc.bot"):
                prefix = current_footer.removesuffix(" • https://ddc.bot")
                enhanced_footer = prefix + " • ℹ️ Info Available • https://ddc.bot"
            else:
                prefix = current_footer.removesuffix(" https://ddc.bot")
                enhanced_footer = prefix + " ℹ️ Info Available • https://ddc.bot"
            original_embed.set_footer(text=enhanced_footer)

        logger.debug(f"Enhanced status embed with info indicator for {container_name}")

    except (KeyError, ValueError, RuntimeError) as e:
        logger.error(f"Error enhancing status embed: {e}", exc_info=True)

    return original_embed

class TaskManagementButton(discord.ui.Button):
    """Task Management button for container info admin view."""

    def __init__(self, cog_instance, server_config: Dict[str, Any]):
        super().__init__(
            style=discord.ButtonStyle.secondary,
            emoji="⏰",
            label=None,
            custom_id=f"task_management_{server_config.get('docker_name')}"
        )
        self.cog = cog_instance
        self.server_config = server_config
        self.container_name = server_config.get('docker_name')

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle task management button click."""
        try:
            # Try to defer immediately, but handle the case where interaction has already expired
            try:
                await interaction.response.defer(ephemeral=True)
                deferred = True
            except discord.errors.NotFound:
                # Interaction has already expired (>3 seconds)
                logger.warning(f"Task management interaction expired for {self.container_name}")
                return  # Can't send any response if interaction expired
            except (discord.errors.DiscordException, RuntimeError, OSError) as e:
                logger.error(f"Error deferring task management interaction: {e}", exc_info=True)
                return

            # Check spam protection after deferring
            from services.infrastructure.spam_protection_service import get_spam_protection_service
            spam_service = get_spam_protection_service()
            # Through the service instead of an attribute on the button - same
            # reason as in InfoDropdownButton in control_ui.py. The lock lived on
            # the object and vanished with it; the per-minute limit from the
            # panel had no effect here, and the message was untranslated.
            if spam_service.is_enabled():
                try:
                    if spam_service.is_on_cooldown(interaction.user.id, "tasks"):
                        remaining = spam_service.get_remaining_cooldown(interaction.user.id, "tasks")
                        await interaction.followup.send(
                            _("⏰ Please wait {remaining:.1f} more seconds before using this button again.").format(
                                remaining=remaining
                            ),
                            ephemeral=True
                        )
                        return
                    spam_service.add_user_cooldown(interaction.user.id, "tasks")
                except (RuntimeError, AttributeError, KeyError) as e:
                    logger.error(f"Spam protection error for task management button: {e}", exc_info=True)

            # Show task list directly
            await self._show_task_list(interaction)

        except (RuntimeError, ValueError, KeyError) as e:
            logger.error(f"Error in task management button: {e}", exc_info=True)
            try:
                await interaction.followup.send("❌ Error opening task management.", ephemeral=True)
            except Exception:
                pass

    async def _show_task_list(self, interaction: discord.Interaction):
        """Show task list for this container."""
        try:
            # Response already deferred in callback, no need to defer again

            # Get all tasks for this container
            from services.scheduling.scheduler import load_tasks, get_tasks_for_container

            tasks = get_tasks_for_container(self.container_name)

            if not tasks:
                embed = discord.Embed(
                    title=f"⏰ No Tasks for {self.container_name}",
                    description="No scheduled tasks found for this container.",
                    color=discord.Color.orange()
                )
                view = TaskManagementView(self.cog, self.container_name)
                await interaction.followup.send(embed=embed, view=view, ephemeral=True)
                return

            # Create task list embed
            embed = discord.Embed(
                title=f"⏰ {_('Scheduled Tasks for {container}').format(container=self.container_name)}",
                color=discord.Color.blue()
            )

            for i, task in enumerate(tasks[:10]):  # Limit to 10 tasks to avoid embed size limits
                # Format last run
                last_run_str = _("Never")
                if task.last_run_ts:
                    from datetime import datetime
                    last_run_dt = datetime.fromtimestamp(task.last_run_ts)
                    last_run_str = last_run_dt.strftime("%Y-%m-%d %H:%M")
                    if task.last_run_success is not None:
                        status_icon = "✅" if task.last_run_success else "❌"
                        last_run_str += f" {status_icon}"

                # Format next run
                next_run_str = _("Not scheduled")
                if task.next_run_ts:
                    from datetime import datetime
                    next_run_dt = datetime.fromtimestamp(task.next_run_ts)
                    next_run_str = next_run_dt.strftime("%Y-%m-%d %H:%M")

                # Active status
                status_icon = "🟢" if task.is_active else "🔴"

                embed.add_field(
                    name=f"{status_icon} {task.action.upper()} - {task.cycle}",
                    value=f"**{_('Last Run')}:** {last_run_str}\n**{_('Next Run')}:** {next_run_str}\n**{_('ID')}:** `{task.task_id}`",
                    inline=False
                )

            if len(tasks) > 10:
                embed.set_footer(text=f"{_('Showing first {count} of {total} tasks').format(count=10, total=len(tasks))}")

            # Add management buttons
            view = TaskManagementView(self.cog, self.container_name)
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)

        except (RuntimeError, ValueError, KeyError) as e:
            logger.error(f"Error showing task list: {e}", exc_info=True)
            try:
                await interaction.followup.send("❌ Error loading task list.", ephemeral=True)
            except Exception:
                pass  # Interaction might have expired

class TaskManagementView(discord.ui.View):
    """View with buttons for task management (Add Task, Delete Tasks, Auto-Action)."""

    def __init__(self, cog_instance, container_name: str):
        super().__init__(timeout=300)  # 5 minute timeout
        self.cog = cog_instance
        self.container_name = container_name

        # Add Task button (green)
        self.add_item(AddTaskButton(cog_instance, container_name))

        # Delete Tasks button (red)
        self.add_item(DeleteTasksButton(cog_instance, container_name))

        # Auto-Action button (blue)
        self.add_item(AutoActionButton(cog_instance, container_name))

class AddTaskButton(discord.ui.Button):
    """Button to add a new scheduled task."""

    def __init__(self, cog_instance, container_name: str):
        super().__init__(
            style=discord.ButtonStyle.green,
            label=_("Add Task"),
            custom_id=f"add_task_{container_name}"
        )
        self.cog = cog_instance
        self.container_name = container_name

    async def callback(self, interaction: discord.Interaction) -> None:
        """Show task creation with dropdowns."""
        try:
            logger.info(f"AddTaskButton clicked for container: {self.container_name}")

            # Acknowledge first: the allowed-actions lookup reads all container
            # configs and could outlast Discord's 3 s limit (10062 Unknown interaction)
            await interaction.response.defer(ephemeral=True)
            allowed_actions = await asyncio.to_thread(_get_allowed_task_actions, self.container_name)

            # Create dropdown-based task creation
            view = TaskCreationView(self.cog, self.container_name, allowed_actions=allowed_actions)
            if not view.allowed_actions:
                await interaction.followup.send(
                    f"❌ {_('No schedulable actions (start/stop/restart) are allowed for {container}.').format(container=self.container_name)}",
                    ephemeral=True
                )
                return

            embed = discord.Embed(
                title=f"⏰ {_('Create Task: {container}').format(container=self.container_name)}",
                description=_("Use the dropdowns below to configure your task:"),
                color=discord.Color.green()
            )

            embed.add_field(
                name=f"📋 {_('Instructions')}",
                value=_("1. Select Cycle Type\n2. Select Action\n3. Select Time and day/date\n4. Click 'Create Task'"),
                inline=False
            )

            await interaction.followup.send(
                embed=embed,
                view=view,
                ephemeral=True
            )

        except (RuntimeError, ValueError, KeyError) as e:
            logger.error(f"Error in add task button: {e}", exc_info=True)
            if interaction.response.is_done():
                await interaction.followup.send(f"❌ {_('Error showing task help.')}", ephemeral=True)
            else:
                await interaction.response.send_message(f"❌ {_('Error showing task help.')}", ephemeral=True)

class DeleteTasksButton(discord.ui.Button):
    """Button to open task delete panel."""

    def __init__(self, cog_instance, container_name: str):
        super().__init__(
            style=discord.ButtonStyle.red,
            label=_("Delete Tasks"),
            custom_id=f"delete_tasks_{container_name}"
        )
        self.cog = cog_instance
        self.container_name = container_name

    async def callback(self, interaction: discord.Interaction) -> None:
        """Open task delete panel using existing /task_delete_panel functionality."""
        try:
            await interaction.response.defer(ephemeral=True)

            # Call the existing task delete panel functionality
            # This will use the same logic as the /task_delete_panel command
            from services.scheduling.scheduler import load_tasks, get_tasks_for_container

            tasks = get_tasks_for_container(self.container_name)

            if not tasks:
                await interaction.followup.send(
                    f"⏰ No tasks found for {self.container_name} to delete.",
                    ephemeral=True
                )
                return

            # Create container-specific task delete view
            view = ContainerTaskDeleteView(self.cog, tasks, self.container_name)

            embed = discord.Embed(
                title=f"❌ {_('Delete Tasks: {container}').format(container=self.container_name)}",
                description=f"{_('Click any button below to delete the corresponding task for **{container}**:').format(container=self.container_name)}",
                color=discord.Color.red()
            )

            # Add legend
            embed.add_field(
                name=_("Legend"),
                value=_("O = Once, D = Daily, W = Weekly, M = Monthly, Y = Yearly"),
                inline=False
            )

            embed.add_field(
                name=_("Found Tasks"),
                value=f"{_('{count} active tasks for {container}').format(count=len(tasks), container=self.container_name)}",
                inline=False
            )

            await interaction.followup.send(embed=embed, view=view, ephemeral=True)

        except (RuntimeError, ValueError, KeyError) as e:
            logger.error(f"Error in delete tasks button: {e}", exc_info=True)
            await interaction.followup.send(f"❌ {_('Error opening task delete panel.')}", ephemeral=True)


class AutoActionButton(discord.ui.Button):
    """Button to show Auto-Actions affecting this container."""

    def __init__(self, cog_instance, container_name: str):
        super().__init__(
            style=discord.ButtonStyle.blurple,
            label=_("Auto-Action"),
            custom_id=f"auto_action_{container_name}"
        )
        self.cog = cog_instance
        self.container_name = container_name

    async def callback(self, interaction: discord.Interaction) -> None:
        """Show all Auto-Actions that affect this container."""
        try:
            await interaction.response.defer(ephemeral=True)

            # Get Auto-Action rules from config service
            config_service = get_auto_action_config_service()
            all_rules = config_service.get_rules()

            # Filter rules that target this container
            matching_rules = [
                rule for rule in all_rules
                if self.container_name in rule.action.containers
            ]

            if not matching_rules:
                embed = discord.Embed(
                    title=f"🤖 {_('Auto-Actions for {container}').format(container=self.container_name)}",
                    description=_("No Auto-Actions configured for this container."),
                    color=discord.Color.orange()
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return

            # Create embed with matching rules
            embed = discord.Embed(
                title=f"🤖 {_('Auto-Actions for {container}').format(container=self.container_name)}",
                description=f"{_('Found {count} Auto-Action(s) targeting this container:').format(count=len(matching_rules))}",
                color=discord.Color.blue()
            )

            for rule in matching_rules[:10]:  # Limit to 10 rules
                # Status icon
                status_icon = "🟢" if rule.enabled else "🔴"

                # Action emoji
                action_emojis = {
                    "RESTART": "🔄",
                    "STOP": "⏹️",
                    "START": "▶️",
                    "NOTIFY": "📢"
                }
                action_emoji = action_emojis.get(rule.action.type, "⚡")

                # Keywords preview (max 3)
                keywords_preview = ", ".join(rule.trigger.keywords[:3])
                if len(rule.trigger.keywords) > 3:
                    keywords_preview += f" (+{len(rule.trigger.keywords) - 3})"

                # Build field value
                field_value = (
                    f"**{_('Action')}:** {action_emoji} {rule.action.type}\n"
                    f"**{_('Keywords')}:** `{keywords_preview or _('None')}`\n"
                    f"**{_('Cooldown')}:** {rule.cooldown_minutes} min\n"
                    f"**{_('Priority')}:** {rule.priority}"
                )

                if rule.trigger.regex_pattern:
                    regex_preview = rule.trigger.regex_pattern[:30]
                    if len(rule.trigger.regex_pattern) > 30:
                        regex_preview += "..."
                    field_value += f"\n**Regex:** `{regex_preview}`"

                embed.add_field(
                    name=f"{status_icon} {rule.name}",
                    value=field_value,
                    inline=True
                )

            # Add footer with hint
            embed.set_footer(text=_("Manage Auto-Actions in the Web UI"))

            await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            logger.error(f"Error in auto action button: {e}", exc_info=True)
            await interaction.followup.send(f"❌ {_('Error loading Auto-Actions.')}", ephemeral=True)


# Actions that can be scheduled as tasks (services.scheduling.scheduler.VALID_ACTIONS)
_TASK_ACTIONS = ("start", "stop", "restart")


def _get_allowed_task_actions(container_name: str) -> List[str]:
    """Return the schedulable actions allowed for a container (its allowed_actions)."""
    try:
        from services.config.server_config_service import get_server_config_service
        for server in get_server_config_service().get_all_servers():
            if server.get('docker_name') == container_name:
                allowed = server.get('allowed_actions') or []
                return [action for action in _TASK_ACTIONS if action in allowed]
    except (ImportError, AttributeError, RuntimeError, OSError, ValueError) as e:
        logger.error(f"Error loading allowed actions for {container_name}: {e}", exc_info=True)
    return []


class TaskCreationView(discord.ui.View):
    """View for task creation using sequential dropdowns."""

    def __init__(self, cog_instance, container_name: str, allowed_actions: Optional[List[str]] = None):
        super().__init__(timeout=300)
        self.cog = cog_instance
        self.container_name = container_name
        # Only actions the container allows may be scheduled (looked up if not given)
        self.allowed_actions = (allowed_actions if allowed_actions is not None
                                else _get_allowed_task_actions(container_name))

        # Task configuration state
        self.selected_cycle = None
        self.selected_action = None
        self.selected_time = None
        self.selected_day = None
        self.selected_month = None
        self.selected_year = None

        # Start with only cycle dropdown
        self.add_item(CycleDropdown())

        # Add create button (initially disabled and hidden)
        self.create_button = CreateTaskButton(self.cog, self.container_name)
        self.create_button.disabled = True
        self.create_button.row = 4  # Always on the last row

    def check_ready(self):
        """Check if all required fields are selected and enable create button."""
        if self.selected_cycle == 'daily':
            ready = self.selected_action and self.selected_time
        elif self.selected_cycle == 'weekly':
            ready = self.selected_action and self.selected_day and self.selected_time
        elif self.selected_cycle == 'monthly':
            ready = self.selected_action and self.selected_day and self.selected_time
        elif self.selected_cycle == 'yearly':
            ready = self.selected_action and self.selected_day and self.selected_month and self.selected_time
        elif self.selected_cycle == 'once':
            ready = self.selected_action and self.selected_day and self.selected_month and self.selected_year and self.selected_time
        else:
            ready = False

        # Add or update create button
        if ready:
            if self.create_button not in self.children:
                self.create_button.row = 4  # Ensure it's always on row 4
                self.add_item(self.create_button)
            self.create_button.disabled = False
        else:
            if self.create_button in self.children:
                self.create_button.disabled = True

    def clear_dropdowns_after(self, keep_until_row: int):
        """Remove all dropdowns after a certain row."""
        items_to_remove = []
        for item in self.children:
            if hasattr(item, 'row') and item.row is not None and item.row > keep_until_row and item != self.create_button:
                items_to_remove.append(item)
        for item in items_to_remove:
            self.remove_item(item)

    def get_next_available_row(self):
        """Get the next available row for a dropdown."""
        # Find the highest row number in use
        max_row = -1
        for item in self.children:
            if item != self.create_button and not isinstance(item, discord.ui.Button):
                if hasattr(item, 'row') and item.row is not None:
                    max_row = max(max_row, item.row)

        # Return the next row (but max 3 for dropdowns, keeping 4 for button)
        next_row = max_row + 1
        if next_row > 3:
            # If we're out of rows, we need to remove some dropdowns first
            logger.warning(f"No more rows available! Max row in use: {max_row}")
            return 3
        return next_row


class CycleDropdown(discord.ui.Select):
    """Dropdown for selecting task cycle."""

    def __init__(self):
        options = [
            discord.SelectOption(label=_("Daily"), description=_("Run every day"), emoji="📅", value="daily"),
            discord.SelectOption(label=_("Weekly"), description=_("Run weekly on specific day"), emoji="📆", value="weekly"),
            discord.SelectOption(label=_("Monthly"), description=_("Run monthly on specific day"), emoji="🗓️", value="monthly"),
            discord.SelectOption(label=_("Yearly"), description=_("Run yearly on specific date"), emoji="📊", value="yearly"),
            discord.SelectOption(label=_("Once"), description=_("Run once at specific date"), emoji="⚡", value="once")
        ]

        super().__init__(placeholder=_("Choose cycle type..."), options=options, row=0)

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle cycle selection and show action dropdown."""
        self.view.selected_cycle = self.values[0]

        # Clear any existing dropdowns after this one
        self.view.clear_dropdowns_after(0)

        # Reset selections
        self.view.selected_action = None
        self.view.selected_day = None
        self.view.selected_month = None
        self.view.selected_year = None
        self.view.selected_time = None

        # Add action dropdown
        action_dropdown = ActionDropdown(self.view.allowed_actions)
        action_dropdown.row = self.view.get_next_available_row()
        self.view.add_item(action_dropdown)

        embed = discord.Embed(
            title=f"⏰ Create Task: {self.view.container_name}",
            description=f"✅ **Cycle:** {self.values[0].title()}\n\nNow choose the action...",
            color=discord.Color.blue()
        )

        await interaction.response.edit_message(embed=embed, view=self.view)

class ActionDropdown(discord.ui.Select):
    """Dropdown for selecting task action."""

    def __init__(self, allowed_actions: Optional[List[str]] = None):
        options = [
            discord.SelectOption(label=_("Start"), description=_("Start the container"), emoji="▶️", value="start"),
            discord.SelectOption(label=_("Stop"), description=_("Stop the container"), emoji="⏹️", value="stop"),
            discord.SelectOption(label=_("Restart"), description=_("Restart the container"), emoji="🔄", value="restart")
        ]
        # Only offer actions the container's config allows
        if allowed_actions is not None:
            options = [option for option in options if option.value in allowed_actions]

        super().__init__(placeholder=_("Choose action..."), options=options, row=1)

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle action selection and show next dropdown based on cycle."""
        self.view.selected_action = self.values[0]

        # Clear any existing dropdowns after this one
        self.view.clear_dropdowns_after(self.row if hasattr(self, 'row') else 1)

        # Reset subsequent selections
        self.view.selected_day = None
        self.view.selected_month = None
        self.view.selected_year = None
        self.view.selected_time = None

        # Add next dropdown based on cycle type
        if self.view.selected_cycle == 'daily':
            # Daily only needs time
            time_dropdown = TimeDropdown()
            time_dropdown.row = self.view.get_next_available_row()
            self.view.add_item(time_dropdown)
        elif self.view.selected_cycle == 'weekly':
            # Weekly needs weekday first
            weekday_dropdown = WeekdayDropdown()
            weekday_dropdown.row = self.view.get_next_available_row()
            self.view.add_item(weekday_dropdown)
        elif self.view.selected_cycle == 'monthly':
            # Monthly needs day of month first
            day_dropdown = SimpleMonthdayDropdown()
            day_dropdown.row = self.view.get_next_available_row()
            self.view.add_item(day_dropdown)
        elif self.view.selected_cycle == 'yearly':
            # Yearly needs day first
            day_dropdown = SimpleMonthdayDropdown()
            day_dropdown.row = self.view.get_next_available_row()
            self.view.add_item(day_dropdown)
        elif self.view.selected_cycle == 'once':
            # Once needs day first
            day_dropdown = SimpleMonthdayDropdown()
            day_dropdown.row = self.view.get_next_available_row()
            self.view.add_item(day_dropdown)

        embed = discord.Embed(
            title=f"⏰ Create Task: {self.view.container_name}",
            description=f"✅ **Cycle:** {self.view.selected_cycle.title()}\n✅ **Action:** {self.values[0].title()}\n\nContinue with the next selection...",
            color=discord.Color.blue()
        )

        await interaction.response.edit_message(embed=embed, view=self.view)

FIRST_PAGE_LAST_DAY = 24   # 24 days plus the option that turns the page = 25
LATER_DAYS = "later_days"
EARLIER_DAYS = "earlier_days"


class SimpleMonthdayDropdown(discord.ui.Select):
    """Day of the month, 1-31, in two pages.

    Discord shows at most 25 options in one select, and a month has 31 days.
    The list used to hold 24 hand-picked days and simply left out the 5th, 6th,
    11th, 17th, 18th, 26th and 29th - no hint, no reason, and for the 29th and
    31st no way at all to schedule a task at the end of the month (review B21).
    Now the first page carries the days 1-24 and a last option that turns to
    25-31, which in turn offers the way back.
    """

    def __init__(self, page: int = 1):
        self.page = page
        if page == 1:
            options = [discord.SelectOption(label=f"{day:02d}", value=str(day))
                       for day in range(1, FIRST_PAGE_LAST_DAY + 1)]
            # Numbers and an arrow, deliberately without _(): the label carries no
            # words, so it needs no entry in the 41 catalogs and reads the same in
            # every language.
            options.append(discord.SelectOption(label="25 - 31  →", value=LATER_DAYS))
        else:
            options = [discord.SelectOption(label="←  1 - 24", value=EARLIER_DAYS)]
            options += [discord.SelectOption(label=f"{day:02d}", value=str(day))
                        for day in range(FIRST_PAGE_LAST_DAY + 1, 32)]

        # Dynamic row assignment to avoid conflicts
        super().__init__(placeholder=_("Choose day..."), options=options)

    async def _turn_page(self, interaction: discord.Interaction) -> None:
        """Swap this dropdown for the other page, in the same row."""
        row = getattr(self, 'row', None)
        self.view.remove_item(self)
        other_page = SimpleMonthdayDropdown(page=2 if self.values[0] == LATER_DAYS else 1)
        if row is not None:
            other_page.row = row
        self.view.add_item(other_page)
        await interaction.response.edit_message(view=self.view)

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle day selection."""
        if self.values[0] in (LATER_DAYS, EARLIER_DAYS):
            await self._turn_page(interaction)
            return

        self.view.selected_day = self.values[0]

        # Clear any existing dropdowns after this one
        self.view.clear_dropdowns_after(self.row if hasattr(self, 'row') else 2)

        # Add next dropdown based on cycle
        if self.view.selected_cycle == 'monthly':
            # Monthly: after day comes time
            # Remove day dropdown to make room (value already saved)
            self.view.remove_item(self)

            time_dropdown = TimeDropdown()
            time_dropdown.row = self.view.get_next_available_row()
            self.view.add_item(time_dropdown)
        elif self.view.selected_cycle == 'yearly':
            # Yearly: after day comes month
            month_dropdown = MonthDropdown()
            month_dropdown.row = self.view.get_next_available_row()
            self.view.add_item(month_dropdown)
        elif self.view.selected_cycle == 'once':
            # Once: after day comes month
            month_dropdown = MonthDropdown()
            month_dropdown.row = self.view.get_next_available_row()
            self.view.add_item(month_dropdown)

        embed = discord.Embed(
            title=f"⏰ Create Task: {self.view.container_name}",
            description=f"✅ **Cycle:** {self.view.selected_cycle.title()}\n✅ **Action:** {self.view.selected_action.title()}\n✅ **Day:** {self.values[0]}\n\nContinue...",
            color=discord.Color.blue()
        )

        await interaction.response.edit_message(embed=embed, view=self.view)

class MonthDropdown(discord.ui.Select):
    """Dropdown for selecting month."""

    def __init__(self):
        months = [
            _("January"), _("February"), _("March"), _("April"), _("May"), _("June"),
            _("July"), _("August"), _("September"), _("October"), _("November"), _("December")
        ]

        options = []
        for i, month in enumerate(months, 1):
            options.append(discord.SelectOption(
                label=month,
                value=str(i)
            ))

        # Dynamic row assignment
        super().__init__(placeholder=_("Choose month..."), options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle month selection."""
        self.view.selected_month = self.values[0]

        # Clear any existing dropdowns after this one
        self.view.clear_dropdowns_after(self.row if hasattr(self, 'row') else 3)

        # Add next dropdown based on cycle
        if self.view.selected_cycle == 'yearly':
            # Yearly: after month comes time
            # Remove day and month dropdowns to make room (values already saved)
            items_to_remove = []
            for item in self.view.children:
                if isinstance(item, (SimpleMonthdayDropdown, MonthDropdown)):
                    items_to_remove.append(item)
            for item in items_to_remove:
                self.view.remove_item(item)

            # Now add time dropdown
            time_dropdown = TimeDropdown()
            time_dropdown.row = self.view.get_next_available_row()
            self.view.add_item(time_dropdown)
        elif self.view.selected_cycle == 'once':
            # Once: after month comes year
            # Remove day AND month dropdowns to make room (values already saved)
            items_to_remove = []
            for item in self.view.children:
                if isinstance(item, (SimpleMonthdayDropdown, MonthDropdown)):
                    items_to_remove.append(item)
            for item in items_to_remove:
                self.view.remove_item(item)

            year_dropdown = YearDropdown()
            year_dropdown.row = self.view.get_next_available_row()
            self.view.add_item(year_dropdown)

        embed = discord.Embed(
            title=f"⏰ Create Task: {self.view.container_name}",
            description=f"✅ **Cycle:** {self.view.selected_cycle.title()}\n✅ **Action:** {self.view.selected_action.title()}\n✅ **Day:** {self.view.selected_day}\n✅ **Month:** {self.values[0]}\n\nContinue...",
            color=discord.Color.blue()
        )

        await interaction.response.edit_message(embed=embed, view=self.view)

class YearDropdown(discord.ui.Select):
    """Dropdown for selecting year."""

    def __init__(self):
        from datetime import datetime
        current_year = datetime.now().year

        options = []
        for year in range(current_year, current_year + 11):  # Current year + 10 years
            options.append(discord.SelectOption(
                label=str(year),
                value=str(year)
            ))

        # Dynamic row assignment
        super().__init__(placeholder=_("Choose year..."), options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle year selection."""
        self.view.selected_year = self.values[0]

        # After year comes time (for once)
        # Remove previous dropdowns to make room (values already saved)
        items_to_remove = []
        for item in self.view.children:
            if isinstance(item, (SimpleMonthdayDropdown, MonthDropdown, YearDropdown)):
                items_to_remove.append(item)
        for item in items_to_remove:
            self.view.remove_item(item)

        time_dropdown = TimeDropdown()
        time_dropdown.row = self.view.get_next_available_row()
        self.view.add_item(time_dropdown)

        embed = discord.Embed(
            title=f"⏰ Create Task: {self.view.container_name}",
            description=f"✅ **Cycle:** {self.view.selected_cycle.title()}\n✅ **Action:** {self.view.selected_action.title()}\n✅ **Day:** {self.view.selected_day}\n✅ **Month:** {self.view.selected_month}\n✅ **Year:** {self.values[0]}\n\nNow choose the time...",
            color=discord.Color.blue()
        )

        await interaction.response.edit_message(embed=embed, view=self.view)

class TimeDropdown(discord.ui.Select):
    """Dropdown for selecting task time."""

    def __init__(self):
        # Common times throughout the day
        times = []
        for hour in range(0, 24):  # Every hour
            time_str = f"{hour:02d}:00"
            label = f"{time_str}"
            times.append(discord.SelectOption(label=label, value=time_str))

        # Dynamic row assignment
        super().__init__(placeholder=_("Choose time..."), options=times[:24])

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle time selection - final step."""
        self.view.selected_time = self.values[0]
        self.view.check_ready()

        # Build summary of selections
        summary = [f"✅ **{_('Cycle:')}** {_(self.view.selected_cycle.title())}"]
        summary.append(f"✅ **{_('Action:')}** {_(self.view.selected_action.title())}")

        if self.view.selected_cycle == 'weekly':
            summary.append(f"✅ **{_('Weekday:')}** {_(self.view.selected_day.title())}")
        elif self.view.selected_cycle in ['monthly', 'yearly', 'once']:
            summary.append(f"✅ **{_('Day:')}** {self.view.selected_day}")

        if self.view.selected_cycle in ['yearly', 'once']:
            # Get month name
            months = [_("January"), _("February"), _("March"), _("April"), _("May"), _("June"),
                     _("July"), _("August"), _("September"), _("October"), _("November"), _("December")]
            month_name = months[int(self.view.selected_month) - 1]
            summary.append(f"✅ **{_('Month:')}** {month_name}")

        if self.view.selected_cycle == 'once':
            summary.append(f"✅ **{_('Year:')}** {self.view.selected_year}")

        summary.append(f"✅ **{_('Time:')}** {self.values[0]}")

        embed = discord.Embed(
            title=f"⏰ {_('Create Task: {container}').format(container=self.view.container_name)}",
            description="\n".join(summary) + f"\n\n**{_('Task configuration complete! Click Create Task to save.')}**",
            color=discord.Color.green()
        )

        await interaction.response.edit_message(embed=embed, view=self.view)

class WeekdayDropdown(discord.ui.Select):
    """Dropdown for selecting weekday."""

    def __init__(self):
        options = [
            discord.SelectOption(label=_("Monday"), value="monday"),
            discord.SelectOption(label=_("Tuesday"), value="tuesday"),
            discord.SelectOption(label=_("Wednesday"), value="wednesday"),
            discord.SelectOption(label=_("Thursday"), value="thursday"),
            discord.SelectOption(label=_("Friday"), value="friday"),
            discord.SelectOption(label=_("Saturday"), value="saturday"),
            discord.SelectOption(label=_("Sunday"), value="sunday")
        ]

        # Dynamic row assignment
        super().__init__(placeholder=_("Choose weekday..."), options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle weekday selection."""
        self.view.selected_day = self.values[0]

        # Clear any existing dropdowns after this one
        self.view.clear_dropdowns_after(self.row if hasattr(self, 'row') else 2)

        # Add time dropdown (final step for weekly)
        # Remove weekday dropdown to make room (value already saved)
        self.view.remove_item(self)

        time_dropdown = TimeDropdown()
        time_dropdown.row = self.view.get_next_available_row()
        self.view.add_item(time_dropdown)

        embed = discord.Embed(
            title=f"⏰ Create Task: {self.view.container_name}",
            description=f"✅ **Cycle:** {self.view.selected_cycle.title()}\n✅ **Action:** {self.view.selected_action.title()}\n✅ **Weekday:** {self.values[0].title()}\n\nNow choose the time...",
            color=discord.Color.blue()
        )

        await interaction.response.edit_message(embed=embed, view=self.view)

# Seven classes stood here (1979-2264): MonthdayDropdown, YeardayDropdown,
# ManualDateView, DaySelectDropdown, MonthSelectDropdown, ConfirmDateButton and
# DateDropdown - a second, older way to pick a date that nothing ever built. It
# stored a date as one "DD.MM" string, which CreateTaskButton below reads with
# int(), and its day list cut 1-31 down to the first 25 with options[:25]. Both
# would have been real defects on a path a user can reach; here they were a trap
# for whoever reads the file (review B22). The live way asks for day and month
# separately: SimpleMonthdayDropdown + MonthDropdown.

class CreateTaskButton(discord.ui.Button):
    """Button to directly create the task."""

    def __init__(self, cog_instance, container_name: str):
        super().__init__(
            style=discord.ButtonStyle.primary,
            label=_("Create Task"),
            emoji="✅"
            # Row will be set dynamically when adding to view
        )
        self.cog = cog_instance
        self.container_name = container_name

    async def callback(self, interaction: discord.Interaction) -> None:
        """Directly create task with selected parameters."""
        # Validate all required fields
        missing = []
        if not self.view.selected_cycle:
            missing.append(_("Cycle"))
        if not self.view.selected_action:
            missing.append(_("Action"))
        if not self.view.selected_time:
            missing.append(_("Time"))
        if self.view.selected_cycle in ['weekly', 'monthly', 'yearly', 'once'] and not self.view.selected_day:
            missing.append(_("Day/Date"))

        if missing:
            await interaction.response.send_message(f"❌ {_('Please select: {missing}').format(missing=', '.join(missing))}", ephemeral=True)
            return

        # Imported before try so the except clause below can reference it
        from services.scheduling.schedule_helpers import ScheduleValidationError

        try:
            await interaction.response.defer(ephemeral=True)

            # The channel's CURRENT 'schedule' permission, or a registered admin
            # (SPEC.md B2) - the same rule as the twin that DELETES a task
            # (ContainerTaskDeleteButton). Creating one was checked nowhere: neither
            # at the click nor here, so the same thing needed a permission on one path
            # and none on the other, and a view still open after a revocation kept
            # creating tasks for up to ~890 s (SPEC.md Z5, review B3).
            # An assigned admin may only make tasks for their own containers
            # (review F2); the channel branch in front of it is untouched.
            from .control_helpers import _channel_has_permission, _admin_may_control
            if not (_channel_has_permission(interaction.channel_id, 'schedule', load_config())
                    or _admin_may_control(interaction.user.id, self.container_name)):
                await interaction.followup.send(
                    f"❌ {_('This action is not allowed in this channel.')}",
                    ephemeral=True
                )
                return

            # Re-check allowed actions at creation time (config may have changed)
            if self.view.selected_action not in _get_allowed_task_actions(self.container_name):
                error_msg = _("You don't have permission to perform '{action}' on '{container}'.").format(
                    action=self.view.selected_action, container=self.container_name
                )
                await interaction.followup.send(f"❌ {error_msg}", ephemeral=True)
                return

            # Import required modules
            from services.scheduling.scheduler import ScheduledTask, add_task, parse_time_string, parse_weekday_string
            from services.scheduling.schedule_helpers import validate_task_before_creation
            from services.infrastructure.action_logger import log_user_action
            import uuid
            import time

            # Parse time
            hour, minute = parse_time_string(self.view.selected_time)

            # Parse day/date based on cycle type
            day_val = None
            weekday_val = None
            month_val = None
            year_val = None

            if self.view.selected_cycle == 'weekly':
                weekday_val = parse_weekday_string(self.view.selected_day)
            elif self.view.selected_cycle == 'monthly':
                day_val = int(self.view.selected_day)
            elif self.view.selected_cycle == 'yearly':
                # We now have separate day and month fields
                day_val = int(self.view.selected_day)
                month_val = int(self.view.selected_month)
            elif self.view.selected_cycle == 'once':
                # We now have separate day, month and year fields
                day_val = int(self.view.selected_day)
                month_val = int(self.view.selected_month)
                year_val = int(self.view.selected_year)

            # Create ScheduledTask
            task = ScheduledTask(
                task_id=str(uuid.uuid4()),
                container_name=self.container_name,
                action=self.view.selected_action,
                cycle=self.view.selected_cycle,
                hour=hour,
                minute=minute,
                day=day_val if self.view.selected_cycle != 'weekly' else None,
                weekday=weekday_val,
                month=month_val if self.view.selected_cycle in ['yearly', 'once'] else None,
                year=year_val if self.view.selected_cycle == 'once' else None,
                created_by=str(interaction.user),
                created_at=time.time(),
                # Configured timezone, like the slash commands
                timezone_str=load_config().get('timezone', 'Europe/Berlin')
            )

            # Calculate next run time
            task.calculate_next_run()

            # Validate and save
            validate_task_before_creation(task)

            if add_task(task):
                # Log the action
                log_user_action(
                    action="TASK_CREATE_BUTTON",
                    target=self.container_name,
                    user=str(interaction.user),
                    source="Task Button",
                    details=f"Action: {self.view.selected_action}, Cycle: {self.view.selected_cycle}, Time: {self.view.selected_time}"
                )

                # Success embed
                embed = discord.Embed(
                    title=f"✅ {_('Task Created Successfully!')}",
                    description=f"{_('Task has been created for **{container}**').format(container=self.container_name)}",
                    color=discord.Color.green()
                )

                embed.add_field(
                    name=f"📋 {_('Configuration')}",
                    value=f"**{_('Action')}:** {_(self.view.selected_action.title())}\n"
                          f"**{_('Cycle')}:** {_(self.view.selected_cycle.title())}\n"
                          f"**{_('Time')}:** {self.view.selected_time}\n" +
                          (f"**{_('Day/Date')}:** {self.view.selected_day}" if self.view.selected_day else ""),
                    inline=False
                )

                # Format next run time (in the task's timezone, i.e. the configured one)
                next_run_dt = task.get_next_run_datetime()
                if next_run_dt:
                    next_run = next_run_dt.strftime('%Y-%m-%d %H:%M %Z')
                    embed.add_field(
                        name=f"⏰ {_('Next Run')}",
                        value=f"`{next_run}`",
                        inline=True
                    )

                embed.add_field(
                    name=f"🔍 {_('Task ID')}",
                    value=f"`{task.task_id}`",
                    inline=True
                )

                await interaction.followup.send(embed=embed, ephemeral=True)

            else:
                await interaction.followup.send(
                    f"❌ {_('Failed to create task. Please check for time conflicts or try again.')}",
                    ephemeral=True
                )

        except ScheduleValidationError as e:
            # Validation messages are user-facing (e.g. time conflict, time in the past)
            logger.info(f"Task creation for {self.container_name} rejected: {e}")
            await interaction.followup.send(f"❌ **{_('Error')}**: {str(e)[:200]}", ephemeral=True)
        except (RuntimeError, ValueError, KeyError) as e:
            logger.error(f"Error creating task: {e}", exc_info=True)
            error_msg = str(e)
            if "collision" in error_msg.lower():
                await interaction.followup.send(
                    f"❌ **{_('Time Conflict')}**: {_('Another task is already scheduled within 10 minutes of this time for {container}').format(container=self.container_name)}.",
                    ephemeral=True
                )
            elif "past" in error_msg.lower():
                await interaction.followup.send(
                    f"❌ **{_('Invalid Time')}**: {_('The scheduled time is in the past. Please select a future time.')}.",
                    ephemeral=True
                )
            else:
                await interaction.followup.send(
                    f"❌ **{_('Error')}**: {error_msg[:200]}",
                    ephemeral=True
                )

def should_show_info_in_status_channel(channel_id: int, config: Dict[str, Any]) -> bool:
    """
    Check if info integration should be shown in a status channel.

    Args:
        channel_id: Discord channel ID
        config: Bot configuration

    Returns:
        True if info should be shown in this status channel
    """
    from .control_helpers import _channel_has_permission

    # Check if this channel has control permission
    has_control = _channel_has_permission(channel_id, 'control', config)

    # For now, show info integration in all status channels where containers are displayed
    # This includes both control channels (as additional feature) and status-only channels
    # The StatusInfoView will be used only for status-only channels, control channels use ControlView
    return True

class ContainerTaskDeleteView(discord.ui.View):
    """View for deleting tasks specific to a container."""

    def __init__(self, cog_instance, tasks: list, container_name: str):
        super().__init__(timeout=300)  # 5 minute timeout
        self.cog = cog_instance
        self.container_name = container_name

        # Add delete buttons for each task (max 25 due to Discord limits)
        max_tasks = min(len(tasks), 25)
        for i, task in enumerate(tasks[:max_tasks]):
            task_id = task.task_id

            # Create detailed description for button
            action = task.action.upper()
            cycle_abbrev = {
                'once': 'O',
                'daily': 'D',
                'weekly': 'W',
                'monthly': 'M',
                'yearly': 'Y'
            }.get(task.cycle, '?')

            # Get action emoji
            action_emojis = {
                'START': '▶️',
                'STOP': '⏹️',
                'RESTART': '🔄'
            }
            action_emoji = action_emojis.get(action, '⚙️')

            # Build detailed time and date info in the task's own timezone (older
            # tasks may use another zone than the configured one), with a marker
            time_info = ""
            next_run = task.get_next_run_datetime() if getattr(task, 'next_run_ts', None) else None
            if next_run:
                if task.cycle == 'once':
                    # For once: show full date and time "O:13.08.27 14h"
                    time_info = f":{next_run.strftime('%d.%m.%y %Hh')}"
                elif task.cycle == 'daily':
                    # For daily: show hour "D:17h"
                    time_info = f":{next_run.strftime('%Hh')}"
                elif task.cycle == 'weekly':
                    # For weekly: show day and hour "W:Mo 17h"
                    weekday_abbrev = ['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So'][next_run.weekday()]
                    time_info = f":{weekday_abbrev} {next_run.strftime('%Hh')}"
                elif task.cycle == 'monthly':
                    # For monthly: show day and hour "M:15. 17h"
                    time_info = f":{next_run.strftime('%d. %Hh')}"
                elif task.cycle == 'yearly':
                    # For yearly: show month.day and hour "Y:13.08 22h"
                    time_info = f":{next_run.strftime('%d.%m %Hh')}"
                else:
                    # Fallback: just show time
                    time_info = f":{next_run.strftime('%Hh')}"
                tz_marker = next_run.strftime('%Z')
                if tz_marker:
                    time_info += f" {tz_marker}"
            elif hasattr(task, 'time_str') and task.time_str:
                # Fallback to time_str if available
                time_info = f":{task.time_str}"

            task_description = f"{cycle_abbrev}{time_info} {action_emoji}"

            # Limit description length for button
            if len(task_description) > 35:
                task_description = task_description[:32] + "..."

            row = i // 5  # 5 buttons per row
            self.add_item(ContainerTaskDeleteButton(cog_instance, task_id, task_description, row))

class ContainerTaskDeleteButton(discord.ui.Button):
    """Button to delete a specific task."""

    def __init__(self, cog_instance, task_id: str, description: str, row: int):
        super().__init__(
            style=discord.ButtonStyle.red,
            label=description,
            custom_id=f"delete_task_{task_id}",
            row=row
        )
        self.cog = cog_instance
        self.task_id = task_id
        self.description = description

    async def callback(self, interaction: discord.Interaction) -> None:
        """Delete the task."""
        try:
            await interaction.response.defer(ephemeral=True)

            from services.scheduling.scheduler import delete_task, find_task_by_id
            from services.infrastructure.action_logger import log_user_action
            from .control_helpers import _channel_has_permission, _admin_may_control_task

            # Deleting a scheduled task needs the 'schedule' permission of the
            # CURRENT channel. The twin button in control_ui.py:1276 checks it;
            # this path did not, so whoever held 'control' but deliberately not
            # 'schedule' could still delete tasks here. Same action, same right.
            # See SPEC.md Z5 - the assurance holds on EVERY path or not at all.
            # A registered admin may delete as well (SPEC.md B2): this is the
            # button of the admin info view, which admins open in status
            # channels. Added 2026-09-19 after the operator was refused there.
            config = load_config()
            # Via the task's container - same rule as its twin in control_ui
            # (review F2).
            if not (_channel_has_permission(interaction.channel_id, 'schedule', config)
                    or _admin_may_control_task(interaction.user.id, self.task_id)):
                await interaction.followup.send(
                    f"❌ {_('You do not have permission to delete tasks in this channel.')}",
                    ephemeral=True
                )
                return

            # Find the task first to get info for logging
            task = find_task_by_id(self.task_id)
            if not task:
                await interaction.followup.send(
                    f"❌ {_('Task not found (may have already been deleted)')}",
                    ephemeral=True
                )
                return

            # Delete the task
            success = delete_task(self.task_id)

            if success:
                # Log the action
                log_user_action(
                    action="TASK_DELETE_BUTTON",
                    target=task.container_name,
                    user=str(interaction.user),
                    source="Task Delete Button",
                    details=f"Deleted task: {task.cycle} {task.action} for {task.container_name}"
                )

                # Success response
                embed = discord.Embed(
                    title=f"✅ {_('Task Deleted')}",
                    description=f"{_('Successfully deleted task: **{description}**').format(description=self.description)}",
                    color=discord.Color.green()
                )

                embed.add_field(
                    name=_('Task Details'),
                    value=f"{_('Container')}: {task.container_name}\n{_('Action')}: {_(task.action.title())}\n{_('Cycle')}: {_(task.cycle.title())}",
                    inline=False
                )

                await interaction.followup.send(embed=embed, ephemeral=True)

                # Remove this button from the view
                self.view.remove_item(self)

                # Update the original message to remove the deleted task button
                try:
                    await interaction.edit_original_response(view=self.view)
                except Exception:
                    # If editing fails, it's not critical
                    pass

            else:
                await interaction.followup.send(
                    f"❌ {_('Failed to delete task: **{description}**').format(description=self.description)}",
                    ephemeral=True
                )

        except (RuntimeError, ValueError, KeyError) as e:
            logger.error(f"Error deleting task {self.task_id}: {e}", exc_info=True)
            await interaction.followup.send(
                f"❌ {_('Error occurred while deleting task.')}",
                ephemeral=True
            )
