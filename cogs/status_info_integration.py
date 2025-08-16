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
import os
from typing import Dict, Any, Optional, List
from utils.logging_utils import get_module_logger
from utils.container_info_manager import get_container_info_manager
from utils.time_utils import get_datetime_imports

# Get datetime imports
datetime, timedelta, timezone, time = get_datetime_imports()
from utils.common_helpers import get_public_ip
from .translation_manager import _
import asyncio
import aiohttp

logger = get_module_logger('status_info_integration')

class ContainerInfoAdminView(discord.ui.View):
    """
    Admin view for container info with Edit and Debug buttons (control channels only).
    """
    
    def __init__(self, cog_instance, server_config: Dict[str, Any], info_config: Dict[str, Any]):
        # Extend timeout to 30 minutes for Info messages (they are not frequently used)
        super().__init__(timeout=1800)  # 30 minute timeout
        self.cog = cog_instance
        self.server_config = server_config
        self.info_config = info_config
        self.container_name = server_config.get('docker_name')
        
        # Add Edit Info button
        self.add_item(EditInfoButton(cog_instance, server_config, info_config))
        
        # Add Debug button
        self.add_item(DebugLogsButton(cog_instance, server_config))
        

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
    
    async def callback(self, interaction: discord.Interaction):
        """Handle edit info button click."""
        # Check button cooldown first  
        from utils.spam_protection_manager import get_spam_protection_manager
        spam_manager = get_spam_protection_manager()
        
        if spam_manager.is_enabled():
            cooldown_seconds = spam_manager.get_button_cooldown("info")
            current_time = time.time()
            cooldown_key = f"button_info_{interaction.user.id}"
            
            if hasattr(self.cog, '_button_cooldowns'):
                if cooldown_key in self.cog._button_cooldowns:
                    last_use = self.cog._button_cooldowns[cooldown_key]
                    if current_time - last_use < cooldown_seconds:
                        remaining = cooldown_seconds - (current_time - last_use)
                        await interaction.response.send_message(
                            f"⏰ Please wait {remaining:.1f} more seconds before using this button again.", 
                            ephemeral=True
                        )
                        return
            else:
                self.cog._button_cooldowns = {}
            
            # Record button use
            self.cog._button_cooldowns[cooldown_key] = current_time
            
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
            
        except Exception as e:
            logger.error(f"Error opening edit info modal for {self.container_name}: {e}", exc_info=True)
            try:
                await interaction.response.send_message(
                    _("❌ Could not open edit modal. Please try again later."),
                    ephemeral=True
                )
            except:
                pass


class LiveLogView(discord.ui.View):
    """View for live-updating debug logs with refresh controls."""
    
    def __init__(self, container_name: str, auto_refresh: bool = False):
        # Get configuration from environment variables
        timeout_seconds = int(os.getenv('DDC_LIVE_LOGS_TIMEOUT', '120'))
        self.refresh_interval = int(os.getenv('DDC_LIVE_LOGS_REFRESH_INTERVAL', '5'))
        self.max_refreshes = int(os.getenv('DDC_LIVE_LOGS_MAX_REFRESHES', '12'))
        
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
        except Exception as e:
            logger.error(f"Auto-recreation error: {e}")
    
    async def _recreate_view(self):
        """Recreate the Live Logs message with a fresh view."""
        try:
            if not self.message_ref:
                return
            
            logger.info(f"Auto-recreating Live Logs view for container {self.container_name}")
            
            # Get current logs
            logs = await self._get_container_logs()
            
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
            
        except Exception as e:
            logger.error(f"Failed to recreate Live Logs view for {self.container_name}: {e}")
    
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
                logs = await self._get_container_logs()
                
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
                    except Exception as e:
                        logger.error(f"Auto-refresh update failed for message {self.message_ref.id}: {e}")
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
                    except Exception as e:
                        logger.debug(f"Failed to update buttons after auto-refresh end: {e}")
                        
        except asyncio.CancelledError:
            logger.debug("Auto-refresh cancelled")
        except Exception as e:
            logger.error(f"Auto-refresh error: {e}")
    
    async def manual_refresh(self, interaction: discord.Interaction):
        """Manual refresh button."""
        # Check button cooldown first
        from utils.spam_protection_manager import get_spam_protection_manager
        spam_manager = get_spam_protection_manager()
        
        if spam_manager.is_enabled():
            cooldown_seconds = spam_manager.get_button_cooldown("live_refresh")
            current_time = time.time()
            cooldown_key = f"button_refresh_{interaction.user.id}"
            
            # Simple cooldown tracking on the view
            if not hasattr(self, '_button_cooldowns'):
                self._button_cooldowns = {}
            
            if cooldown_key in self._button_cooldowns:
                last_use = self._button_cooldowns[cooldown_key]
                if current_time - last_use < cooldown_seconds:
                    remaining = cooldown_seconds - (current_time - last_use)
                    await interaction.response.send_message(
                        f"⏰ Please wait {remaining:.1f} more seconds before refreshing again.", 
                        ephemeral=True
                    )
                    return
            
            # Record button use
            self._button_cooldowns[cooldown_key] = current_time
        
        try:
            # Immediately send response to avoid timeout
            await interaction.response.send_message(_("🔄 Refreshing logs..."), ephemeral=True, delete_after=1)
            
            # Get updated logs
            logs = await self._get_container_logs()
            
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
                except Exception as edit_error:
                    logger.debug(f"Manual refresh edit failed: {edit_error}")
            else:
                logger.warning("Manual refresh failed - no logs retrieved")
                
        except Exception as e:
            logger.error(f"Manual refresh error: {e}")
    
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
                    logs = await self._get_container_logs()
                    embed = discord.Embed(
                        title=f"⏹️ Debug Logs - {self.container_name}",
                        description=f"```\n{logs}\n```",
                        color=0xff6600,
                        timestamp=datetime.now(timezone.utc)
                    )
                    embed.set_footer(text="⏹️ Auto-refresh stopped • Click Start to restart")
                    
                    try:
                        await self.message_ref.edit(embed=embed, view=self)
                    except Exception as e:
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
                    logs = await self._get_container_logs()
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
                    except Exception as e:
                        logger.debug(f"Failed to update message after restart: {e}")
                else:
                    logger.debug("Auto-refresh restarted but no message reference")
            
        except Exception as e:
            logger.error(f"Toggle updates error: {e}")
    
    
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
                except Exception as e:
                    logger.debug(f"Failed to update message on timeout: {e}")
        except Exception as e:
            logger.error(f"Error in on_timeout: {e}")
    
    async def _get_container_logs(self) -> str:
        """Get the last 50 log lines for the container."""
        try:
            import docker
            from utils.docker_utils import get_docker_client
            from utils.common_helpers import validate_container_name
            
            # Validate container name for security
            if not validate_container_name(self.container_name):
                return f"Invalid container name format: {self.container_name}"
            
            client = get_docker_client()
            if not client:
                return "Docker client not available."
            
            # Get container with timeout protection
            import asyncio
            container = await asyncio.to_thread(client.containers.get, self.container_name)
            
            # Get logs (configured number of lines) with timeout
            tail_lines = int(os.getenv('DDC_LIVE_LOGS_TAIL_LINES', '50'))
            logs = await asyncio.to_thread(
                lambda: container.logs(tail=tail_lines, timestamps=True).decode('utf-8', errors='replace')
            )
            
            # Limit log output to prevent Discord message limits
            if len(logs) > 1800:  # Leave room for embed formatting
                logs = logs[-1800:]
                logs = "...\n" + logs
            
            return logs.strip() or "No logs available for this container."
            
        except docker.errors.NotFound:
            return f"Container '{self.container_name}' not found."
        except Exception as e:
            logger.debug(f"Error getting logs for {self.container_name}: {e}")
            return f"Error retrieving logs: {str(e)[:100]}"

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
    
    async def callback(self, interaction: discord.Interaction):
        """Handle debug logs button click with live-updating response."""
        # Check button cooldown first  
        from utils.spam_protection_manager import get_spam_protection_manager
        spam_manager = get_spam_protection_manager()
        
        if spam_manager.is_enabled():
            cooldown_seconds = spam_manager.get_button_cooldown("logs")  # Use logs cooldown
            current_time = time.time()
            cooldown_key = f"button_logs_{interaction.user.id}"
            
            if hasattr(self.cog, '_button_cooldowns'):
                if cooldown_key in self.cog._button_cooldowns:
                    last_use = self.cog._button_cooldowns[cooldown_key]
                    if current_time - last_use < cooldown_seconds:
                        remaining = cooldown_seconds - (current_time - last_use)
                        await interaction.response.send_message(
                            f"⏰ Please wait {remaining:.1f} more seconds before using this button again.", 
                            ephemeral=True
                        )
                        return
            else:
                self.cog._button_cooldowns = {}
            
            # Record button use
            self.cog._button_cooldowns[cooldown_key] = current_time
        
        try:
            # Check if Live Logs feature is enabled
            live_logs_enabled = os.getenv('DDC_LIVE_LOGS_ENABLED', 'true').lower() in ['true', '1', 'on', 'yes']
            
            if not live_logs_enabled:
                # Live Logs feature is disabled - show error message
                await interaction.response.send_message(
                    _("❌ Live Logs feature is currently disabled by administrator."),
                    ephemeral=True
                )
                return
            
            # Always use ephemeral (private) messages for Live Logs
            await interaction.response.defer(ephemeral=True)
            
            logger.info(f"Live debug logs (ephemeral) requested for container: {self.container_name}")
            
            # Check if auto-start is enabled via environment variable
            auto_start_enabled = os.getenv('DDC_LIVE_LOGS_AUTO_START', 'false').lower() in ['true', '1', 'on', 'yes']
            
            # Get initial logs
            log_lines = await self._get_container_logs()
            
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
            
        except Exception as e:
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
            except:
                pass
    
    async def _get_container_logs(self) -> str:
        """Get the last 50 log lines for the container."""
        try:
            import docker
            from utils.docker_utils import get_docker_client
            from utils.common_helpers import validate_container_name
            
            # Validate container name for security
            if not validate_container_name(self.container_name):
                return f"Invalid container name format: {self.container_name}"
            
            client = get_docker_client()
            if not client:
                return "Docker client not available."
            
            # Get container with timeout protection
            import asyncio
            container = await asyncio.to_thread(client.containers.get, self.container_name)
            
            # Get logs (configured number of lines) with timeout
            tail_lines = int(os.getenv('DDC_LIVE_LOGS_TAIL_LINES', '50'))
            logs = await asyncio.to_thread(
                lambda: container.logs(tail=tail_lines, timestamps=True).decode('utf-8', errors='replace')
            )
            
            # Limit log output to prevent Discord message limits
            if len(logs) > 1800:  # Leave room for embed formatting
                logs = logs[-1800:]
                logs = "...\n" + logs
            
            return logs.strip() or "No logs available for this container."
            
        except docker.errors.NotFound:
            return f"Container '{self.container_name}' not found."
        except Exception as e:
            logger.debug(f"Error getting logs for {self.container_name}: {e}")
            return f"Error retrieving logs: {str(e)[:100]}"

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
        info_manager = get_container_info_manager()
        self.info_config = info_manager.load_container_info(self.container_name)
        
        # Only add info button if info is enabled
        if self.info_config.get('enabled', False):
            self.add_item(StatusInfoButton(cog_instance, server_config, self.info_config))
    
class StatusInfoButton(discord.ui.Button):
    """
    Info button for status channels - shows container info in ephemeral message.
    """
    
    def __init__(self, cog_instance, server_config: Dict[str, Any], info_config: Dict[str, Any]):
        super().__init__(
            style=discord.ButtonStyle.secondary,
            emoji="ℹ️",
            label="Info",
            custom_id=f"status_info_{server_config.get('docker_name')}"
        )
        self.cog = cog_instance
        self.server_config = server_config
        self.info_config = info_config
        self.container_name = server_config.get('docker_name')
    
    async def callback(self, interaction: discord.Interaction):
        """Handle info button click - show ephemeral info embed."""
        try:
            await interaction.response.defer(ephemeral=True)
            
            # Generate info embed
            embed = await self._generate_info_embed()
            
            # Check if this is a control channel to show admin buttons
            from .control_helpers import _channel_has_permission
            from utils.config_cache import get_cached_config
            
            config = get_cached_config()
            has_control = _channel_has_permission(interaction.channel_id, 'control', config) if config else False
            
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
            
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)
            logger.info(f"Displayed container info for {self.container_name} to user {interaction.user.id} (control: {has_control})")
            
        except Exception as e:
            logger.error(f"Error in status info callback for {self.container_name}: {e}", exc_info=True)
            try:
                error_embed = discord.Embed(
                    title="❌ Error",
                    description=_("Could not load container information. Please try again later."),
                    color=discord.Color.red()
                )
                await interaction.followup.send(embed=error_embed, ephemeral=True)
            except:
                pass  # Ignore errors in error handling
    
    async def _generate_info_embed(self) -> discord.Embed:
        """Generate the container info embed for display."""
        display_name = self.server_config.get('name', self.container_name)
        
        # Create embed with container branding
        embed = discord.Embed(
            title=f"📋 {display_name} - Container Info",
            color=0x3498db
        )
        
        # Build description content
        description_parts = []
        
        # Add custom text if provided
        custom_text = self.info_config.get('custom_text', '').strip()
        if custom_text:
            description_parts.append(f"```\n{custom_text}\n```")
        
        # Add IP information if enabled
        if self.info_config.get('show_ip', False):
            ip_info = await self._get_ip_info()
            if ip_info:
                description_parts.append(ip_info)
        
        # Add container status info
        status_info = self._get_status_info()
        if status_info:
            description_parts.append(status_info)
        
        # Set description if we have any content
        if description_parts:
            embed.description = "\n".join(description_parts)
        
        embed.set_footer(text="https://ddc.bot")
        return embed
    
    async def _get_ip_info(self) -> Optional[str]:
        """Get IP information for the container."""
        custom_ip = self.info_config.get('custom_ip', '').strip()
        custom_port = self.info_config.get('custom_port', '').strip()
        
        if custom_ip:
            # Validate custom IP/hostname format for security
            if self._validate_custom_address(custom_ip):
                # Add port if provided
                address = custom_ip
                if custom_port and custom_port.isdigit():
                    address = f"{custom_ip}:{custom_port}"
                return f"🔗 **Custom Address:** {address}"
            else:
                logger.warning(f"Invalid custom address format: {custom_ip}")
                return "🔗 **Custom Address:** [Invalid Format]"
        
        # Try to get WAN IP
        try:
            wan_ip = await self._get_wan_ip_async()
            if wan_ip:
                # Add port if provided
                address = wan_ip
                if custom_port and custom_port.isdigit():
                    address = f"{wan_ip}:{custom_port}"
                return f"**Public IP:** {address}"
        except Exception as e:
            logger.debug(f"Could not get WAN IP for {self.container_name}: {e}")
        
        return "**IP:** Auto-detection failed"
    
    async def _get_wan_ip_async(self) -> Optional[str]:
        """Async version of WAN IP detection using aiohttp."""
        services = [
            'https://api.ipify.org',
            'https://ifconfig.me/ip', 
            'https://icanhazip.com'
        ]
        
        timeout = aiohttp.ClientTimeout(total=5.0)
        
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                for service in services:
                    try:
                        async with session.get(service) as response:
                            if response.status == 200:
                                ip = (await response.text()).strip()
                                if self._is_valid_ip(ip):
                                    return ip
                    except Exception as e:
                        logger.debug(f"Service {service} failed: {e}")
                        continue
                        
        except Exception as e:
            logger.debug(f"WAN IP detection failed: {e}")
            
        return None
    
    def _is_valid_ip(self, ip: str) -> bool:
        """Basic IP validation."""
        import socket
        try:
            socket.inet_aton(ip)
            return True
        except socket.error:
            return False
    
    def _validate_custom_address(self, address: str) -> bool:
        """Validate custom IP/hostname format for security."""
        import re
        
        # Limit length to prevent abuse
        if len(address) > 255:
            return False
            
        # Allow IPs
        ip_pattern = r'^(\d{1,3}\.){3}\d{1,3}$'
        if re.match(ip_pattern, address):
            # Validate IP octets
            octets = address.split('.')
            for octet in octets:
                if int(octet) > 255:
                    return False
            return True
        
        # Allow hostnames with ports
        hostname_pattern = r'^[a-zA-Z0-9.-]+(\:[0-9]{1,5})?$'
        if re.match(hostname_pattern, address):
            # Additional validation: no double dots, no leading/trailing dots
            if '..' in address or address.startswith('.') or address.endswith('.'):
                return False
            return True
            
        return False
    
    def _get_status_info(self) -> Optional[str]:
        """Get current container status information."""
        # Status information (State/Uptime) is already displayed in the main status embed above,
        # so we don't need to duplicate it in the info section
        return None

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
    
    try:
        # Load container info
        container_name = server_config.get('docker_name')
        info_manager = get_container_info_manager()
        info_config = info_manager.load_container_info(container_name)
        
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
        if "https://ddc.bot" in current_footer:
            enhanced_footer = current_footer.replace("https://ddc.bot", "ℹ️ Info Available • https://ddc.bot")
            original_embed.set_footer(text=enhanced_footer)
        
        logger.debug(f"Enhanced status embed with info indicator for {container_name}")
        
    except Exception as e:
        logger.error(f"Error enhancing status embed: {e}", exc_info=True)
    
    return original_embed

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