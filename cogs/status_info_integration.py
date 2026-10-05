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
from services.config.group_service import is_group_target
from services.infrastructure.container_info_service import get_container_info_service
from utils.time_utils import get_datetime_imports

# Get datetime imports
datetime, timedelta, timezone, time = get_datetime_imports()
from utils.common_helpers import get_public_ip
from .translation_manager import _
import asyncio
import aiohttp
from services.automation import get_auto_action_config_service
from .ddc_ui import (MAX_PRIVATE_SECONDS, NOTICE_STAYS_FOR, PROGRESS_STAYS_FOR, CloseButton, DDCView,
                     PrivateView)
# The task UI (buttons, dropdowns, creation and deletion views) lives in
# task_ui.py since the Phase 3 split; the names stay importable from here.
from .task_ui import (  # noqa: F401
    ActionDropdown,
    AddTaskButton,
    AutoActionButton,
    ContainerTaskDeleteButton,
    ContainerTaskDeleteView,
    CreateTaskButton,
    CycleDropdown,
    DeleteTasksButton,
    EARLIER_DAYS,
    FIRST_PAGE_LAST_DAY,
    LATER_DAYS,
    MonthDropdown,
    SimpleMonthdayDropdown,
    TaskCreationView,
    TaskManagementButton,
    TaskManagementView,
    TimeDropdown,
    WeekdayDropdown,
    YearDropdown,
    _TASK_ACTIONS,
    _get_allowed_task_actions,
)

logger = get_module_logger('status_info_integration')


async def _refused_at_the_press(interaction, container_name: str, *, deferred: bool = False) -> bool:
    """True (and answered) when the presser may no longer act on this container.

    Asked at the press (SPEC Z5), not when the panel was opened: the info admin
    view lives up to ten minutes. Only the 🔒 button asked (review F3); 📝 and 📋 edited the
    info and showed the logs after the channel had lost 'control' or the admin
    their assignment (stage 4 review before v3.1.0, section 09).
    """
    from .control_helpers import _channel_has_permission, _admin_may_control
    from services.config.config_service import load_config as _load_config
    if (_channel_has_permission(interaction.channel_id, 'control', _load_config())
            or _admin_may_control(interaction.user.id, container_name)):
        return False
    text = f"❌ {_('This action is not allowed in this channel.')}"
    if deferred:
        await interaction.followup.send(text, ephemeral=True, delete_after=NOTICE_STAYS_FOR)
    else:
        await interaction.response.send_message(text, ephemeral=True, delete_after=NOTICE_STAYS_FOR)
    return True

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
            # Through the one client factory (follows DOCKER_HOST, the v3.0
            # proxy). 60 s is docker-py's default, which this site used before.
            from services.docker_service.client_factory import build_docker_client
            client = build_docker_client(timeout=60)
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

class ContainerInfoAdminView(PrivateView):
    """
    Admin view for container info with Edit and Debug buttons (control channels only).
    """

    def __init__(self, cog_instance, server_config: Dict[str, Any], info_config: Dict[str, Any], message=None):
        # Set timeout to maximum (just under Discord's 15-minute limit)
        # Ten minutes without use: 890 s left no room once a press had started
        # the timeout again (2026-10-02)
        super().__init__(timeout=MAX_PRIVATE_SECONDS)
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
                        ephemeral=True, delete_after=NOTICE_STAYS_FOR
                    )
                    return
                spam_manager.add_user_cooldown(interaction.user.id, "protected_info_edit")
            except (RuntimeError, AttributeError, KeyError) as e:
                logger.error(f"Spam protection error for protected info edit button: {e}", exc_info=True)

        # This button carried NO check of its own - only the one that builds the
        # view around it, and that one does not know about container
        # assignments. The modal it opens is pre-filled with the protected
        # content AND the password, both in clear text, so opening it is
        # reading them. An assigned admin must not do that for somebody else's
        # container (review F3).
        if await _refused_at_the_press(interaction, self.container_name):
            return

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
                    ephemeral=True, delete_after=NOTICE_STAYS_FOR
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
                        ephemeral=True, delete_after=NOTICE_STAYS_FOR
                    )
                    return
                spam_manager.add_user_cooldown(interaction.user.id, "edit_info")
            except (RuntimeError, AttributeError, KeyError) as e:
                logger.error(f"Spam protection error for edit info button: {e}", exc_info=True)

        if await _refused_at_the_press(interaction, self.container_name):
            return

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
                    ephemeral=True, delete_after=NOTICE_STAYS_FOR
                )
            except Exception:
                pass

def live_log_timeout() -> int:
    """The live-log panel's timeout: the setting "Message timeout (s)", 30-600."""
    from utils.settings import get_setting
    return max(30, min(get_setting('DDC_LIVE_LOGS_TIMEOUT', 120), MAX_PRIVATE_SECONDS))


class LiveLogView(DDCView):
    """A private panel with a container's latest log lines, refreshed on request or live.

    IT ENDS LIKE EVERY PRIVATE PANEL: after the setting "Message timeout (s)"
    without use, DDCView.on_timeout deletes it. Until v3.1.0 the setting was read
    and dropped, the panel had a fixed 300 s and rebuilt itself every 270 s, so it
    never timed out and was never deleted. Fifteen minutes after it was opened
    Discord refused the next rebuild, and a dead panel stayed whose buttons only
    answered "interaction failed".
    """

    def __init__(self, container_name: str, auto_refresh: bool = False):
        from utils.settings import get_setting
        super().__init__(timeout=live_log_timeout())
        self.refresh_interval = get_setting('DDC_LIVE_LOGS_REFRESH_INTERVAL', 5)
        self.max_refreshes = get_setting('DDC_LIVE_LOGS_MAX_REFRESHES', 12)
        self.container_name = container_name
        self.auto_refresh_enabled = auto_refresh
        self.auto_refresh_task = None
        self.refresh_count = 0
        self.message_ref = None  # Store message reference
        self.cog_instance = None  # Will be set when needed

        # Create all buttons in the correct order
        self._create_all_buttons()

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

        # The Close this method's own comment has promised since it was
        # written. It is added here and not by PrivateView because
        # _create_all_buttons clears the view and runs again on every
        # refresh, which would take an inherited button away.
        self.add_item(CloseButton())

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
                        embed.set_footer(text=_("🔄 Auto-refreshing every {seconds}s • {remaining} updates remaining").format(
                    seconds=self.refresh_interval, remaining=remaining))
                    else:
                        embed.set_footer(text=_("✅ Auto-refresh completed • Click ▶️ to restart live updates"))
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
                        ephemeral=True, delete_after=NOTICE_STAYS_FOR
                    )
                    return
                spam_manager.add_user_cooldown(interaction.user.id, "live_refresh")
            except (RuntimeError, AttributeError, KeyError) as e:
                logger.error(f"Spam protection error for live log refresh button: {e}", exc_info=True)

        try:
            # Immediately send response to avoid timeout
            await interaction.response.send_message(_("🔄 Refreshing logs..."), ephemeral=True, delete_after=PROGRESS_STAYS_FOR)

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
                embed.set_footer(text=_("🔄 Manually refreshed • Click again to update"))

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
            await interaction.response.send_message(_("⏳ Updating..."), ephemeral=True, delete_after=PROGRESS_STAYS_FOR)

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
                    embed.set_footer(text=_("⏹️ Auto-refresh stopped • Click Start to restart"))

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
                    embed.set_footer(text=_("▶️ Auto-refresh restarted • Updating every {seconds} seconds").format(
                        seconds=self.refresh_interval))

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
        """Stop the live updates, then go like every private panel."""
        if self.auto_refresh_task:
            self.auto_refresh_task.cancel()
        self.auto_refresh_enabled = False
        await super().on_timeout()

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
                            ephemeral=True, delete_after=NOTICE_STAYS_FOR
                        )
                        return
                    spam_manager.add_user_cooldown(interaction.user.id, "logs")
                except (RuntimeError, AttributeError, KeyError) as e:
                    logger.error(f"Spam protection error for debug logs button: {e}", exc_info=True)

            if await _refused_at_the_press(interaction, self.container_name, deferred=True):
                return

            # Check if Live Logs feature is enabled
            from utils.settings import get_setting
            live_logs_enabled = get_setting('DDC_LIVE_LOGS_ENABLED', True, bool)

            if not live_logs_enabled:
                # Live Logs feature is disabled - show error message
                await interaction.followup.send(
                    _("❌ Live Logs are currently disabled by the administrator."),
                    ephemeral=True, delete_after=NOTICE_STAYS_FOR
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
                    _("❌ Could not retrieve debug logs for this container."),
                    ephemeral=True, delete_after=NOTICE_STAYS_FOR
                )

        except (RuntimeError, ValueError, KeyError) as e:
            logger.error(f"Error getting live debug logs for {self.container_name}: {e}", exc_info=True)
            try:
                if interaction.response.is_done():
                    await interaction.followup.send(
                        _("❌ Error retrieving debug logs. Please try again later."),
                        ephemeral=True, delete_after=NOTICE_STAYS_FOR
                    )
                else:
                    await interaction.response.send_message(
                        _("❌ Error retrieving debug logs. Please try again later."),
                        ephemeral=True, delete_after=NOTICE_STAYS_FOR
                    )
            except Exception:
                pass

class StatusInfoView(DDCView):
    """
    View for status-only channels that provides info display without control buttons.
    Every container has the info button (v3.1.0): restarts, health and, on a game
    server, who is playing are there even without a text set. A group has none.
    """

    def __init__(self, cog_instance, server_config: Dict[str, Any], is_running: bool):
        super().__init__(timeout=None)  # Persistent view
        self.cog = cog_instance
        self.server_config = server_config
        self.is_running = is_running
        self.container_name = server_config.get('docker_name')

        self.info_config = {}
        if is_group_target(self.container_name):
            return  # a group has no info section and no info button

        info_result = get_container_info_service().get_container_info(self.container_name)
        self.info_config = info_result.data.to_dict() if info_result.success else {}
        self.add_item(StatusInfoButton(cog_instance, server_config, self.info_config))

        # Add Protected Info button if protected info is enabled (for password validation)
        if self.info_config.get('protected_enabled', False):
            self.add_item(ProtectedInfoButton(cog_instance, server_config, self.info_config))

class ProtectedInfoOnlyView(PrivateView):
    """
    View for /info command in status channels that only shows protected info button.
    """

    def __init__(self, cog_instance, server_config: Dict[str, Any], info_config: Dict[str, Any]):
        # Ten minutes: thirty outlived the fifteen in which DDC may delete it
        super().__init__(timeout=MAX_PRIVATE_SECONDS)
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
        # The same "info" brake as the control panel's info button. This one sits
        # in the PUBLIC status channels and had none (spam audit 2026-09-26).
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
                logger.error(f"Spam protection error for status info button: {e}", exc_info=True)
        try:
            await interaction.response.defer(ephemeral=True)

            # The channel's control permission - or a registered admin (SPEC.md
            # B2: the admin list exists for the status channels, and this button
            # sits in them). As on the admin panel's info button
            # (control_ui.InfoButton): what the embed SHOWS is not narrowed, the
            # CONTROLS follow the admin's container assignment (operator,
            # 2026-09-29; stage 4 review before v3.1.0, section 09).
            from .control_helpers import _admin_may_control, _channel_has_permission, _is_registered_admin

            config = load_config()
            channel_control = _channel_has_permission(interaction.channel_id, 'control', config) if config else False
            has_control = channel_control or _is_registered_admin(interaction.user.id)
            may_control = channel_control or _admin_may_control(interaction.user.id, self.container_name)

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
            if may_control:
                logger.info(f"Creating ContainerInfoAdminView for {self.container_name}")
                view = ContainerInfoAdminView(self.cog, self.server_config, self.info_config)
            else:
                logger.info(f"Not creating admin view - no control here and no admin of it")

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
        from services.infrastructure.container_info_service import (MAX_CUSTOM_TEXT,
                                                                     get_container_info_service)
        info_service = get_container_info_service()
        info_result = info_service.get_container_info(self.container_name)
        fresh_info_config = info_result.data.to_dict() if info_result.success else self.info_config

        # Create embed with container branding
        embed = discord.Embed(
            title=_("📋 {name} - Container Info").format(name=display_name),
            color=0x3498db
        )

        # The operator's own words first - the address and the text members need
        # to join - then the game server, then Docker, each group apart by a blank
        # line (operator, 2026-09-28: his text stood last on one path, first on
        # the other). The game server's port completes an address without one.
        from .info_extras import address_line, info_extras
        extras = await info_extras(self.server_config)
        own = []

        # Text and address only while the info is switched on: every container
        # opens this display since v3.1.0, and a switched-off text stays hidden.
        shown = bool(fresh_info_config.get('enabled', False))
        if shown and fresh_info_config.get('show_ip', False):
            address = await address_line(fresh_info_config, extras.port)
            if address:
                own.append(address)
        # Cut here too: a file written by hand or by an older version can hold
        # more than the save allows, and Discord refuses an over-long description.
        custom_text = fresh_info_config.get('custom_text', '').strip()[:MAX_CUSTOM_TEXT] if shown else ''
        if custom_text:
            own.append(custom_text)

        # Add protected information if in control channel and enabled.
        #
        # A SET PASSWORD WINS over control permission (operator's decision,
        # review F3). This used to hand the content out on control permission
        # alone, while the dropdown path two files over asks for the password
        # in EVERY channel - measured with a password set: the secret went
        # straight into the embed. A password that protects on one path and not
        # on the other protects nothing. Without a password "protected" is
        # protected by nothing anyway, and a control channel has always shown
        # it; that half is unchanged.
        has_password = bool(str(fresh_info_config.get('protected_password') or '').strip())
        if include_protected and fresh_info_config.get('protected_enabled', False) \
                and not has_password:
            protected_content = fresh_info_config.get('protected_content', '').strip()
            if protected_content:
                own.append("**🔐 Protected Information:**")
                own.append(protected_content)

        description = "\n\n".join(block for block in ["\n".join(own)] + extras.blocks() if block)
        if description:
            embed.description = description

        embed.set_footer(text="https://ddc.bot")
        return embed

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
                        ephemeral=True, delete_after=NOTICE_STAYS_FOR
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
                    ephemeral=True, delete_after=NOTICE_STAYS_FOR
                )
            except Exception:
                pass

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

