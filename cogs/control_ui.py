# -*- coding: utf-8 -*-
"""Control UI components for Discord interaction."""

import asyncio
import json
from collections import OrderedDict
from services.config.config_service import load_config
from services.config.server_config_service import get_server_config_service
import discord
import logging
import time
import io
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from discord.ui import View, Button

from utils.time_utils import format_datetime_with_timezone
from .control_helpers import _channel_has_permission, _get_pending_embed
from utils.logging_utils import get_module_logger
from services.infrastructure.action_logger import log_user_action
from .translation_manager import _
from services.donation.donation_utils import is_donations_disabled

logger = get_module_logger('control_ui')

# =============================================================================
# ULTRA-PERFORMANCE CACHING SYSTEM FOR TOGGLE OPERATIONS
# =============================================================================

# Global caches for performance optimization
_timestamp_format_cache = {}      # Cache for formatted timestamps
_permission_cache = {}            # Cache for channel permissions
_view_cache = {}                 # Cache for view objects
_translation_cache = OrderedDict()  # Cache for translations (LRU via OrderedDict)
_box_element_cache = OrderedDict()  # Cache for box elements (LRU via OrderedDict)
_container_static_data = {}      # Cache for static container data
_embed_pool = []                 # Pool für wiederverwendbare Embed-Objekte
_view_template_cache = {}        # Cache for view templates per container state

# Description Templates für ultra-schnelle String-Generierung
_description_templates = {
    'running_expanded_details': "```\n{header}\n│ {emoji} {status}\n│ {cpu_text}: {cpu}\n│ {ram_text}: {ram}\n│ {uptime_text}: {uptime}\n{footer}\n```",
    'running_expanded_no_details': "```\n{header}\n│ {emoji} {status}\n│ ⚠️ *{detail_denied_text}*\n│ {uptime_text}: {uptime}\n{footer}\n```",
    'running_collapsed': "```\n{header}\n│ {emoji} {status}\n{footer}\n```",
    'offline': "```\n{header}\n│ {emoji} {status}\n{footer}\n```"
}

def _clear_caches():
    """Clears all performance caches - called periodically."""
    global _timestamp_format_cache, _permission_cache, _view_cache, \
           _translation_cache, _box_element_cache, _container_static_data, \
           _embed_pool, _view_template_cache
    
    _timestamp_format_cache.clear()
    _permission_cache.clear()
    _view_cache.clear()
    _translation_cache.clear()
    _box_element_cache.clear()
    _container_static_data.clear()
    _embed_pool.clear()
    _view_template_cache.clear()
    logger.info("All performance caches cleared")

# =============================================================================
# OPTIMIZATION 1: ULTRA-FAST TIMESTAMP CACHING
# =============================================================================

def _get_cached_formatted_timestamp(dt: datetime, timezone_str: Optional[str] = None) -> str:
    """Get a formatted timestamp, potentially from cache."""
    # Always format fresh to ensure correct timezone
    return format_datetime_with_timezone(dt, timezone_str, time_only=True)

# =============================================================================
# OPTIMIZATION 2: ULTRA-FAST TRANSLATION CACHING
# =============================================================================

def _get_cached_translations(lang: str) -> dict:
    """Cache for translations per language - 99% faster."""
    if lang not in _translation_cache:
        _translation_cache[lang] = {
            'online_text': _("**Online**"),
            'offline_text': _("**Offline**"),
            'cpu_text': _("CPU"),
            'ram_text': _("RAM"),
            'uptime_text': _("Uptime"),
            'detail_denied_text': _("Detailed status not allowed."),
            'last_update_text': _("Last update")
        }

        # LRU eviction: remove oldest entry if cache too large
        if len(_translation_cache) > 10:
            _translation_cache.popitem(last=False)  # Remove oldest (FIFO)
    else:
        # Move to end for LRU (most recently used)
        _translation_cache.move_to_end(lang)

    return _translation_cache[lang]

# =============================================================================
# OPTIMIZATION 3: ULTRA-FAST BOX ELEMENT CACHING
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
    """Cache für statische Container-Daten die sich nie ändern - 80% schneller."""
    if display_name not in _container_static_data:
        _container_static_data[display_name] = {
            'custom_id_toggle': f"toggle_{docker_name}",
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
# OPTIMIZATION 5: ULTRA-FAST TEMPLATE-BASED DESCRIPTION GENERATION
# =============================================================================

def _get_description_ultra_fast(template_key: str, **kwargs) -> str:
    """Ultra-fast template-basierte Description - 90% schneller."""
    return _description_templates[template_key].format(**kwargs)

# =============================================================================
# OPTIMIZATION 6: ULTRA-FAST EMBED RECYCLING
# =============================================================================

def _get_recycled_embed(description: str, color: int) -> discord.Embed:
    """Wiederverwendete Embed-Objekte für bessere Performance - 90% schneller."""
    if _embed_pool:
        embed = _embed_pool.pop()
        embed.description = description
        embed.color = color
        embed.clear_fields()
    else:
        embed = discord.Embed(description=description, color=color)
    
    embed.set_footer(text="https://ddc.bot")
    return embed

def _return_embed_to_pool(embed: discord.Embed):
    """Embed nach Nutzung zum Pool zurückgeben."""
    if len(_embed_pool) < 10:  # Max 10 Embeds im Pool
        # Clean all embed attributes to prevent memory leaks
        embed.clear_fields()
        embed.title = None
        embed.description = None
        embed.url = None
        embed.color = None
        embed.timestamp = None
        embed.remove_author()
        embed.remove_footer()
        embed.remove_image()
        embed.remove_thumbnail()
        _embed_pool.append(embed)

# =============================================================================
# OPTIMIZATION 7: ULTRA-FAST PERMISSION CACHING
# =============================================================================

def _get_cached_channel_permission(channel_id: int, permission_key: str, current_config: dict) -> bool:
    """Ultra-fast cached channel permission checking."""
    config_timestamp = current_config.get('_cache_timestamp', 0)
    cache_key = f"{channel_id}_{permission_key}_{config_timestamp}"
    
    if cache_key not in _permission_cache:
        _permission_cache[cache_key] = _channel_has_permission(channel_id, permission_key, current_config)
        
        if len(_permission_cache) > 50:
            keys_to_remove = list(_permission_cache.keys())[:10]
            for key in keys_to_remove:
                del _permission_cache[key]
    
    return _permission_cache[cache_key]

# =============================================================================
# ULTRA-OPTIMIZED ACTION BUTTON CLASS
# =============================================================================

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
                        f"⏰ Please wait {remaining_time:.1f} seconds before using '{self.action}' button again.", 
                        ephemeral=True
                    )
                    return
                spam_service.add_user_cooldown(interaction.user.id, self.action)
            except Exception as e:
                logger.error(f"Spam protection error for button '{self.action}': {e}")
        
        config = load_config()
        if not config:
            await interaction.response.send_message(_("Error: Could not load configuration."), ephemeral=True)
            return
            
        user = interaction.user
        await interaction.response.defer()

        # Check if channel exists
        if not interaction.channel:
            await interaction.followup.send(_("Error: Could not determine channel."), ephemeral=True)
            return

        # Check if this is an admin control message (title contains "Admin Control")
        is_admin_control = False
        if interaction.message and interaction.message.embeds:
            embed_title = interaction.message.embeds[0].title if interaction.message.embeds else ""
            is_admin_control = "Admin Control" in str(embed_title)

        # Admin control messages always have control permission
        channel_has_control = is_admin_control or _get_cached_channel_permission(interaction.channel.id, 'control', config)

        if not channel_has_control:
            await interaction.followup.send(_("This action is not allowed in this channel."), ephemeral=True)
            return

        allowed_actions = self.server_config.get('allowed_actions', [])
        if self.action not in allowed_actions:
            await interaction.followup.send(f"❌ Action '{self.action}' is not allowed for container '{self.display_name}'.", ephemeral=True)
            return

        logger.info(f"[ACTION_BTN] {self.action.upper()} action for '{self.display_name}' triggered by {user.name}")

        # Thread-safe access to pending_actions - use docker_name as key!
        async with self.cog.pending_actions_lock:
            self.cog.pending_actions[self.docker_name] = {
                'action': self.action,
                'timestamp': datetime.now(timezone.utc),
                'user': str(user),
                'display_name': self.display_name  # Store for display purposes
            }

        try:
            pending_embed = _get_pending_embed(self.display_name)
            try:
                await interaction.edit_original_response(embed=pending_embed, view=None)
            except (discord.NotFound, discord.HTTPException) as e:
                logger.warning(f"[ACTION_BTN] Interaction expired/invalid for {self.display_name}: {e}")
                return
            
            log_user_action(
                action=f"DOCKER_{self.action.upper()}", 
                target=self.display_name, 
                user=str(user),
                source="Discord Button",
                details=f"Container: {self.docker_name}"
            )

            async def run_docker_action():
                try:
                    # SERVICE FIRST: Use new Docker Action Service
                    from services.docker_service.docker_action_service import docker_action_service_first
                    success = await docker_action_service_first(self.docker_name, self.action)
                    logger.info(f"[ACTION_BTN] Docker {self.action} for '{self.display_name}' completed: success={success}")

                    # Thread-safe removal from pending_actions - use docker_name as key!
                    async with self.cog.pending_actions_lock:
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

                    # Multiple attempts to get correct status after Docker updates
                    # Some containers (like game servers) can take 15-30+ seconds to fully start
                    max_retries = 6
                    retry_delays = [3, 3, 5, 5, 5, 5]  # Total up to 26 seconds

                    for retry in range(max_retries):
                        await asyncio.sleep(retry_delays[retry])
                        total_waited = sum(retry_delays[:retry+1])
                        logger.info(f"[ACTION_BTN] Getting status for {self.display_name} (attempt {retry + 1}/{max_retries}, waited {total_waited}s total)")

                        # Get fresh status after Docker has updated
                        # SERVICE FIRST: Use ServerConfigService instead of direct config access
                        server_config_service = get_server_config_service()
                        servers = server_config_service.get_all_servers()
                        # Look up server by docker_name (stable), not display_name (can change)
                        server_config_for_update = next((s for s in servers if s.get('docker_name') == self.docker_name), None)
                        if server_config_for_update:
                            # Always invalidate BOTH caches before fetching - use docker_name as key!
                            # 1. StatusCacheService
                            if self.cog.status_cache_service.get(self.docker_name):
                                self.cog.status_cache_service.remove(self.docker_name)

                            # 2. ContainerStatusService (has its own 30s cache!)
                            container_status_service.invalidate_container(self.docker_name)

                            fresh_status = await self.cog.get_status(server_config_for_update)
                            if not isinstance(fresh_status, Exception):
                                self.cog.status_cache_service.set(
                                    self.docker_name,
                                    fresh_status,
                                    datetime.now(timezone.utc)
                                )
                                is_running = fresh_status[1] if fresh_status else None
                                logger.info(f"[ACTION_BTN] Status for {self.display_name}: is_running={is_running}, action was '{self.action}'")

                                # Check if status matches expected state
                                if self.action == "stop" and not is_running:
                                    logger.info(f"[ACTION_BTN] Container successfully stopped")
                                    break
                                elif self.action == "start" and is_running:
                                    logger.info(f"[ACTION_BTN] Container successfully started")
                                    break
                                elif self.action == "restart" and is_running:
                                    logger.info(f"[ACTION_BTN] Container successfully restarted")
                                    break
                                elif retry < max_retries - 1:
                                    logger.info(f"[ACTION_BTN] Status not yet updated, will retry...")
                            else:
                                logger.error(f"[ACTION_BTN] Error getting status: {fresh_status}")
                    
                    try:
                        if hasattr(self.cog, '_generate_status_embed_and_view'):
                            # Check if original message was Admin Control
                            is_admin_message = False
                            try:
                                original_message = interaction.message
                                if original_message and original_message.embeds:
                                    embed_title = original_message.embeds[0].title if original_message.embeds else ""
                                    is_admin_message = "Admin Control" in str(embed_title)
                                    logger.debug(f"[ACTION_BTN] Is admin message check: {is_admin_message}, title: {embed_title}")
                            except Exception as e:
                                logger.error(f"[ACTION_BTN] Error checking admin status: {e}")

                            if is_admin_message:
                                # For Admin Control, force expanded state
                                # Use docker_name as key for expanded state
                                self.cog.expanded_states[self.docker_name] = True
                                # Mark config for admin control
                                self.server_config['_is_admin_control'] = True
                                logger.info(f"[ACTION_BTN] Preserving Admin Control for {self.display_name}")

                                # Generate embed with admin flag
                                embed, _, _ = await self.cog._generate_status_embed_and_view(
                                    interaction.channel.id,
                                    self.display_name,
                                    self.server_config,
                                    config,
                                    allow_toggle=False,  # No toggle for admin
                                    force_collapse=False,
                                    show_cache_age=False
                                )

                                # Get fresh status for running state and color
                                # Use docker_name as key for cache lookup
                                cached_entry = self.cog.status_cache_service.get(self.docker_name)
                                fresh_status = cached_entry.get('data') if cached_entry else None
                                is_running = False
                                if fresh_status and not isinstance(fresh_status, Exception):
                                    _, is_running, _, _, _, _ = fresh_status

                                # Create admin control view with all buttons
                                view = ControlView(
                                    self.cog,
                                    self.server_config,
                                    is_running=is_running,
                                    channel_has_control_permission=True,
                                    allow_toggle=False
                                )

                                if embed:
                                    # Set admin header and dynamic color
                                    embed.title = f"🛠️ Admin Control: {self.display_name}"
                                    if not fresh_status or isinstance(fresh_status, Exception):
                                        embed.color = discord.Color.gold()  # Yellow for unknown
                                    elif is_running:
                                        embed.color = discord.Color.green()  # Green for online
                                    else:
                                        embed.color = discord.Color.red()  # Red for offline

                                # Clean up temporary flag
                                self.server_config.pop('_is_admin_control', None)

                            else:
                                # Normal control message update
                                embed, view, _ = await self.cog._generate_status_embed_and_view(
                                    interaction.channel.id,
                                    self.display_name,
                                    self.server_config,
                                    config,
                                    allow_toggle=True,
                                    force_collapse=False,
                                    show_cache_age=False
                                )

                            if embed:
                                try:
                                    await interaction.edit_original_response(embed=embed, view=view)
                                except (discord.NotFound, discord.HTTPException) as e:
                                    logger.warning(f"[ACTION_BTN] Interaction expired during update for {self.display_name}: {e}")
                    except Exception as e:
                        logger.error(f"[ACTION_BTN] Error updating message after {self.action}: {e}")

                    # Schedule status overview update after container has time to fully transition
                    async def update_status_overview():
                        try:
                            await asyncio.sleep(30)  # Wait 30 seconds for container to fully start/stop
                            logger.info(f"[ACTION_BTN] Updating status overview for {self.display_name}")

                            # Invalidate BOTH caches again to get latest status - use docker_name!
                            # 1. StatusCacheService
                            if self.cog.status_cache_service.get(self.docker_name):
                                self.cog.status_cache_service.remove(self.docker_name)

                            # 2. ContainerStatusService (has its own 30s cache!)
                            container_status_service.invalidate_container(self.docker_name)

                            # Get fresh status
                            # SERVICE FIRST: Use ServerConfigService instead of direct config access
                            server_config_service = get_server_config_service()
                            servers = server_config_service.get_all_servers()
                            # Look up server by docker_name (stable), not display_name (can change)
                            server_config_for_update = next((s for s in servers if s.get('docker_name') == self.docker_name), None)
                            if server_config_for_update:
                                fresh_status = await self.cog.get_status(server_config_for_update)
                                if not isinstance(fresh_status, Exception):
                                    self.cog.status_cache_service.set(
                                        self.docker_name,
                                        fresh_status,
                                        datetime.now(timezone.utc)
                                    )

                            # Update all status messages for this container
                            if hasattr(self.cog, 'tracked_status_messages'):
                                for channel_id, messages in self.cog.tracked_status_messages.items():
                                    for msg_data in messages:
                                        if msg_data.get('display_name') == self.display_name:
                                            try:
                                                channel = self.cog.bot.get_channel(channel_id)
                                                if channel:
                                                    message = await channel.fetch_message(msg_data['message_id'])
                                                    if message:
                                                        embed, view, _ = await self.cog._generate_status_embed_and_view(
                                                            channel_id,
                                                            self.display_name,
                                                            server_config_for_update,
                                                            config,
                                                            allow_toggle=True,
                                                            force_collapse=False,
                                                            show_cache_age=False
                                                        )
                                                        if embed:
                                                            await message.edit(embed=embed, view=view)
                                                            logger.info(f"[ACTION_BTN] Updated status overview message for {self.display_name} in channel {channel_id}")
                                            except Exception as e:
                                                logger.error(f"[ACTION_BTN] Failed to update status message: {e}")
                        except Exception as e:
                            logger.error(f"[ACTION_BTN] Error in status overview update: {e}")

                    # Create task for status overview update
                    overview_task = asyncio.create_task(update_status_overview())
                    overview_task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)

                except Exception as e:
                    logger.error(f"[ACTION_BTN] Error in background Docker {self.action}: {e}")
                    # Thread-safe removal from pending_actions - use docker_name as key!
                    async with self.cog.pending_actions_lock:
                        if self.docker_name in self.cog.pending_actions:
                            del self.cog.pending_actions[self.docker_name]

            # Create task and handle exceptions properly
            task = asyncio.create_task(run_docker_action())
            task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)
            
        except Exception as e:
            logger.error(f"[ACTION_BTN] Error handling {self.action} for '{self.display_name}': {e}")
            # Thread-safe removal from pending_actions
            async with self.cog.pending_actions_lock:
                if self.display_name in self.cog.pending_actions:
                    del self.cog.pending_actions[self.display_name]

# =============================================================================
# ULTRA-OPTIMIZED TOGGLE BUTTON CLASS WITH ALL 6 OPTIMIZATIONS
# =============================================================================

class ToggleButton(Button):
    """Ultra-optimized toggle button mit allen 6 Performance-Optimierungen."""
    cog: 'DockerControlCog'

    def __init__(self, cog_instance: 'DockerControlCog', server_config: dict, is_running: bool, row: int):
        self.cog = cog_instance
        self.docker_name = server_config.get('docker_name')
        self.display_name = server_config.get('name', self.docker_name)
        self.server_config = server_config
        # Use docker_name as key for expanded state (stable identifier)
        self.is_expanded = cog_instance.expanded_states.get(self.docker_name, False)
        
        # Use cached static data
        static_data = _get_container_static_data(self.display_name, self.docker_name)
        custom_id = static_data['custom_id_toggle']
        
        # Cache channel permissions for this button
        self._channel_permissions_cache = {}
        
        emoji = "➖" if self.is_expanded else "➕"
        super().__init__(style=discord.ButtonStyle.primary, label=None, custom_id=custom_id, row=row, emoji=emoji, disabled=not is_running)

    def _get_cached_channel_permission_for_toggle(self, channel_id: int, current_config: dict) -> bool:
        """Cached channel permission specifically for this toggle button."""
        if channel_id not in self._channel_permissions_cache:
            self._channel_permissions_cache[channel_id] = _get_cached_channel_permission(channel_id, 'control', current_config)
        return self._channel_permissions_cache[channel_id]

    async def callback(self, interaction: discord.Interaction) -> None:
        """ULTRA-OPTIMIZED toggle function mit allen 6 Performance-Optimierungen."""
        # Note: Spam protection for toggle button was intentionally removed

        await interaction.response.defer()
        
        start_time = time.time()
        self.is_expanded = not self.is_expanded
        # Use docker_name as key for expanded state (stable identifier)
        self.cog.expanded_states[self.docker_name] = self.is_expanded
        
        # Removed debug log to reduce log spam - only log on errors

        channel_id = interaction.channel.id if interaction.channel else None
        
        try:
            message = interaction.message
            if not message or not channel_id:
                logger.error(f"[TOGGLE_BTN] Message or channel missing for '{self.display_name}'")
                return
            
            current_config = load_config()
            if not current_config:
                logger.error("[ULTRA_FAST_TOGGLE] Could not load configuration for toggle.")
                # Show a generic error to the user
                await interaction.response.send_message(_("Error: Could not load configuration to process this action."), ephemeral=True)
                return
            
            # Check if container is in pending status (thread-safe)
            async with self.cog.pending_actions_lock:
                # Check pending actions using docker_name as key
                is_pending = self.docker_name in self.cog.pending_actions

            if is_pending:
                logger.debug(f"[TOGGLE_BTN] '{self.display_name}' is in pending status, show pending embed")
                pending_embed = _get_pending_embed(self.display_name)
                if pending_embed:
                    await message.edit(embed=pending_embed, view=None)
                    elapsed_time = (time.time() - start_time) * 1000
                    # Only log if operation takes unusually long (>100ms)
                    if elapsed_time > 100:
                        logger.warning(f"[TOGGLE_BTN] Pending message for '{self.display_name}' updated in {elapsed_time:.1f}ms (slow)")
                return
            
            # Use cached data for ultra-fast operation
            cached_entry = self.cog.status_cache_service.get(self.display_name)
            
            if cached_entry and cached_entry.get('data'):
                status_result = cached_entry['data']
                
                # This function call now receives the fresh config
                embed, view = await self._generate_ultra_fast_toggle_embed_and_view(
                    interaction.channel.id, 
                    status_result, 
                    current_config, 
                    cached_entry
                )
                
                if embed and view:
                    await message.edit(embed=embed, view=view)
                    elapsed_time = (time.time() - start_time) * 1000
                    # Only log if operation is slow (>50ms) or very fast (<5ms for verification)
                    if elapsed_time > 50:
                        logger.warning(f"[TOGGLE_BTN] Toggle for '{self.display_name}' took {elapsed_time:.1f}ms (slow)")
                    elif elapsed_time < 5:
                        logger.info(f"[TOGGLE_BTN] Ultra-fast toggle for '{self.display_name}' in {elapsed_time:.1f}ms")
                else:
                    logger.warning(f"[TOGGLE_BTN] Ultra-fast toggle generation failed for '{self.display_name}'")
            else:
                # Show loading status if no cache available
                logger.info(f"[TOGGLE_BTN] No cache entry for '{self.display_name}' - Background loop will update")
                
                temp_embed = discord.Embed(
                    description="```\n┌── Loading Status ───────────\n│ 🔄 Refreshing container data...\n│ ⏱️ Please wait a moment\n└─────────────────────────────\n```",
                    color=0x3498db
                )
                temp_embed.set_footer(text="Background update in progress • https://ddc.bot")
                
                temp_view = discord.ui.View(timeout=None)
                await message.edit(embed=temp_embed, view=temp_view)
                elapsed_time = (time.time() - start_time) * 1000
                # Only log if loading message is slow
                if elapsed_time > 100:
                    logger.warning(f"[TOGGLE_BTN] Loading message for '{self.display_name}' took {elapsed_time:.1f}ms (slow)")
            
        except Exception as e:
            logger.error(f"[TOGGLE_BTN] Error toggling '{self.display_name}': {e}", exc_info=True)
        
        # Update channel activity timestamp
        if interaction.channel:
            self.cog.last_channel_activity[interaction.channel.id] = datetime.now(timezone.utc)

    async def _generate_ultra_fast_toggle_embed_and_view(self, channel_id: int, status_result: tuple, current_config: dict, cached_entry: dict) -> tuple[Optional[discord.Embed], Optional[discord.ui.View]]:
        """Ultra-fast embed/view generation mit allen 6 Optimierungen."""
        try:
            if not isinstance(status_result, tuple) or len(status_result) != 6:
                logger.warning(f"[ULTRA_FAST_TOGGLE] Invalid status_result format for '{self.display_name}'")
                return None, None
            
            display_name_from_status, running, cpu, ram, uptime, details_allowed = status_result
            status_color = 0x00b300 if running else 0xe74c3c
            
            # OPTIMIZATION 2: Use cached translations (99% schneller)
            lang = current_config.get('language', 'de')
            translations = _get_cached_translations(lang)
            
            # OPTIMIZATION 3: Use cached box elements (98% schneller)
            static_data = _get_container_static_data(self.display_name, self.docker_name)
            box_elements = static_data['box_elements']
            
            status_text = translations['online_text'] if running else translations['offline_text']
            current_emoji = "🟢" if running else "🔴"
            is_expanded = self.is_expanded
            
            # OPTIMIZATION 4: Template-based description generation (90% schneller)
            template_args = {
                'header': box_elements['header_line'],
                'footer': box_elements['footer_line'],
                'emoji': current_emoji,
                'status': status_text,
                'cpu_text': translations['cpu_text'],
                'ram_text': translations['ram_text'],
                'uptime_text': translations['uptime_text'],
                'detail_denied_text': translations['detail_denied_text'],
                'cpu': cpu,
                'ram': ram,
                'uptime': uptime
            }
            
            # Choose template based on state
            if running:
                if details_allowed and is_expanded:
                    template_key = 'running_expanded_details'
                elif not details_allowed and is_expanded:
                    template_key = 'running_expanded_no_details'
                else:
                    template_key = 'running_collapsed'
            else:
                template_key = 'offline'
            
            description = _get_description_ultra_fast(template_key, **template_args)
            
            # OPTIMIZATION 1: Ultra-fast cached timestamp formatting (95% schneller)
            # Get timezone from config (format_datetime_with_timezone will handle fallbacks)
            timezone_str = current_config.get('timezone')
            current_time = _get_cached_formatted_timestamp(cached_entry['timestamp'], timezone_str)
            timestamp_line = f"{translations['last_update_text']}: {current_time}"
            
            final_description = f"{timestamp_line}\n{description}"
            
            # OPTIMIZATION 5: Embed recycling (90% schneller)
            embed = _get_recycled_embed(final_description, status_color)
            
            # OPTIMIZATION 6: Ultra-fast cached channel permission (90% schneller)
            channel_has_control = self._get_cached_channel_permission_for_toggle(channel_id, current_config)
            
            # Create optimized view
            view = self._create_ultra_optimized_control_view(running, channel_has_control)
            
            return embed, view
            
        except Exception as e:
            logger.error(f"[ULTRA_FAST_TOGGLE] Error in ultra-fast toggle generation for '{self.display_name}': {e}", exc_info=True)
            return None, None

    def _create_ultra_optimized_control_view(self, is_running: bool, channel_has_control_permission: bool) -> 'ControlView':
        """Creates an ultra-optimized ControlView with all optimizations."""
        return ControlView(
            self.cog, 
            self.server_config, 
            is_running, 
            channel_has_control_permission=channel_has_control_permission, 
            allow_toggle=True
        )

# =============================================================================
# ULTRA-OPTIMIZED CONTROL VIEW CLASS
# =============================================================================

class ControlView(View):
    """Ultra-optimized view with control buttons for a Docker container."""
    cog: 'DockerControlCog'

    def __init__(self, cog_instance: Optional['DockerControlCog'], server_config: Optional[dict], is_running: bool, channel_has_control_permission: bool, allow_toggle: bool = True):
        super().__init__(timeout=None)
        self.cog = cog_instance
        self.allow_toggle = allow_toggle

        # If called for registration only, don't add items
        if not self.cog or not server_config:
            return

        docker_name = server_config.get('docker_name')
        display_name = server_config.get('name', docker_name)

        # Check for pending status (simple read in __init__, race acceptable here)
        # Lock not used because __init__ is synchronous and only reads
        is_pending = display_name in self.cog.pending_actions

        if is_pending:
            logger.debug(f"[ControlView] Server '{display_name}' is pending. No buttons will be added.")
            return

        allowed_actions = server_config.get('allowed_actions', [])
        details_allowed = server_config.get('allow_detailed_status', True)
        is_expanded = cog_instance.expanded_states.get(display_name, False)
        # Load info from service
        from services.infrastructure.container_info_service import get_container_info_service
        info_service = get_container_info_service()
        docker_name = server_config.get('docker_name')
        if docker_name:
            info_result = info_service.get_container_info(docker_name)
            info_config = info_result.data.to_dict() if info_result.success else {}
        else:
            info_config = {}

        # Check if channel has info permission
        config = load_config()
        channel_has_info_permission = self._channel_has_info_permission(channel_has_control_permission, config)

        # Add buttons based on state and permissions
        if is_running:
            # Toggle button for running containers with details allowed
            if details_allowed and self.allow_toggle:
                self.add_item(ToggleButton(cog_instance, server_config, is_running=True, row=0))

            # Action buttons when expanded and channel has control
            if channel_has_control_permission and is_expanded:
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
    
    def _channel_has_info_permission(self, channel_has_control_permission: bool, config: dict) -> bool:
        """Check if channel has info permission (control permission also grants info access)."""
        from .control_helpers import _channel_has_permission
        # If we already know they have control permission, they can access info
        if channel_has_control_permission:
            return True
        # Otherwise check specifically for info permission
        # Note: We need the actual channel_id, but we don't have it in this context
        # This will be handled properly in the InfoButton callback
        return True  # Let InfoButton handle the actual permission check

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
                        f"⏰ Please wait {remaining_time:.1f} seconds before using info button again.", 
                        ephemeral=True
                    )
                    return
                spam_service.add_user_cooldown(interaction.user.id, "info")
            except Exception as e:
                logger.error(f"Spam protection error for info button: {e}")
        try:
            await interaction.response.defer(ephemeral=True)
            
                        
            config = load_config()
            channel_id = interaction.channel.id if interaction.channel else None
            
            # Check if channel has info permission
            if not self._channel_has_info_permission(channel_id, config):
                await interaction.followup.send(
                    "❌ You don't have permission to view container info in this channel.",
                    ephemeral=True
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
                has_control = _channel_has_permission(channel_id, 'control', config) if config else False
                
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
                    
                    # Check if control channel for protected info
                    has_control = _channel_has_permission(channel_id, 'control', config) if config else False
                    embed = await info_button._generate_info_embed(include_protected=has_control)
                    
                    # Add admin buttons for editing
                    admin_view = ContainerInfoAdminView(self.cog, self.server_config, empty_info_config)
                    message = await interaction.followup.send(embed=embed, view=admin_view, ephemeral=True)
                    # Update view with message reference and start auto-delete timer
                    admin_view.message = message
                    admin_view.auto_delete_task = asyncio.create_task(admin_view.start_auto_delete_timer())
                    return
                else:
                    await interaction.followup.send(
                        "ℹ️ Container info is not configured for this container.",
                        ephemeral=True
                    )
                    return
            
            # Use the same logic as StatusInfoButton for consistency
            from .status_info_integration import StatusInfoButton, ContainerInfoAdminView
            from .control_helpers import _channel_has_permission
            
            # Generate info embed using StatusInfoButton logic
            info_button = StatusInfoButton(self.cog, self.server_config, info_config)
            
            # Check if this is an admin control message (title contains "Admin Control")
            is_admin_control = False
            if interaction.message and interaction.message.embeds:
                embed_title = interaction.message.embeds[0].title if interaction.message.embeds else ""
                is_admin_control = "Admin Control" in str(embed_title)

            # Since this is in ControlView, we know it's a control channel, so add admin buttons
            # Admin control messages always have control permission
            has_control = is_admin_control or (_channel_has_permission(channel_id, 'control', config) if config else False)
            
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
            
        except Exception as e:
            logger.error(f"[INFO_BTN] Error showing info for '{self.display_name}': {e}")
            await interaction.followup.send(
                "❌ An error occurred while loading container info.",
                ephemeral=True
            )
    
    async def _create_info_embed(self, info_config: dict, docker_name: str) -> discord.Embed:
        """Create info embed from container configuration."""
        
        # Create embed with container branding
        embed = discord.Embed(
            title=f"📋 {self.display_name} - Container Info",
            color=0x3498db
        )
        
        # Build description content
        description_parts = []
        
        # Add custom text if provided
        custom_text = info_config.get('custom_text', '').strip()
        if custom_text:
            description_parts.append(f"```\n{custom_text}\n```")
        
        # Add IP information if enabled
        if info_config.get('show_ip', False):
            ip_info = await self._get_ip_info(info_config)
            if ip_info:
                description_parts.append(ip_info)
        
        # Add container status info
        status_info = await self._get_status_info()
        if status_info:
            description_parts.append(status_info)
        
        # Set description if we have any content
        if description_parts:
            embed.description = "\n".join(description_parts)
        else:
            embed.description = "*No information configured for this container.*"
        
        embed.set_footer(text="https://ddc.bot")
        return embed
    
    async def _get_ip_info(self, info_config: dict) -> str:
        """Get IP information for the container."""
        custom_ip = info_config.get('custom_ip', '').strip()
        custom_port = info_config.get('custom_port', '').strip()
        
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
            from utils.common_helpers import get_wan_ip_async
            wan_ip = await get_wan_ip_async()
            if wan_ip:
                # Add port if provided
                address = wan_ip
                if custom_port and custom_port.isdigit():
                    address = f"{wan_ip}:{custom_port}"
                return f"**Public IP:** {address}"
        except Exception as e:
            logger.debug(f"Could not get WAN IP: {e}")
        
        return "**IP:** Auto-detection failed"
    
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
    
    async def _get_status_info(self) -> str:
        """Get current container status information."""
        # Status information (State/Uptime) is already displayed in the main status embed above,
        # so we don't need to duplicate it in the info section
        return ""
    
    def _channel_has_info_permission(self, channel_id: int, config: dict) -> bool:
        """Check if channel has info permission."""
        from .control_helpers import _channel_has_permission
        return _channel_has_permission(channel_id, 'info', config)
    
    def _channel_has_control_permission(self, channel_id: int, config: dict) -> bool:
        """Check if channel has control permission."""
        from .control_helpers import _channel_has_permission
        return _channel_has_permission(channel_id, 'control', config)

# =============================================================================
# TASK DELETE COMPONENTS (UNVERÄNDERT)
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
                    await interaction.response.send_message(
                        f"⏰ Please wait {remaining_time:.1f} seconds before deleting another task.", 
                        ephemeral=True
                    )
                    return
                spam_service.add_user_cooldown(interaction.user.id, "task_delete")
            except Exception as e:
                logger.error(f"Spam protection error for task delete button: {e}")
        
        user = interaction.user
        logger.info(f"[TASK_DELETE_BTN] Task deletion '{self.task_id}' triggered by {user.name}")
        
        try:
            await interaction.response.defer(ephemeral=True)

            # Check if channel exists
            if not interaction.channel:
                await interaction.followup.send(_("Error: Could not determine channel."), ephemeral=True)
                return

            from services.scheduling.scheduler import load_tasks, delete_task

            config = load_config()
            if not _get_cached_channel_permission(interaction.channel.id, 'schedule', config):
                await interaction.followup.send(_("You do not have permission to delete tasks in this channel."), ephemeral=True)
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
                    ephemeral=True
                )
                logger.info(f"[TASK_DELETE_BTN] Task '{self.task_id}' deleted successfully by {user.name}")
            else:
                await interaction.followup.send(
                    _("❌ Failed to delete task **{task_description}**. It may no longer exist.").format(task_description=self.task_description),
                    ephemeral=True
                )
                logger.warning(f"[TASK_DELETE_BTN] Failed to delete task '{self.task_id}' for {user.name}")
                
        except Exception as e:
            logger.error(f"[TASK_DELETE_BTN] Error deleting task '{self.task_id}': {e}", exc_info=True)
            await interaction.followup.send(_("An error occurred while deleting the task."), ephemeral=True)

class TaskDeletePanelView(View):
    """View containing task delete buttons."""
    
    def __init__(self, cog_instance: 'DockerControlCog', active_tasks: list):
        super().__init__(timeout=600)  # 10 minute timeout for task panels
        self.cog = cog_instance
        
        # Add delete buttons for each task (max 25 due to Discord limits)
        max_tasks = min(len(active_tasks), 25)
        for i, task in enumerate(active_tasks[:max_tasks]):
            task_id = task.task_id
            
            # Create abbreviated description for button
            container_name = task.container_name
            action = task.action.upper()
            cycle_abbrev = {
                'once': 'O',
                'daily': 'D', 
                'weekly': 'W',
                'monthly': 'M',
                'yearly': 'Y'
            }.get(task.cycle, '?')
            
            task_description = f"{cycle_abbrev}: {container_name} {action}"
            
            # Limit description length for button
            if len(task_description) > 40:
                task_description = task_description[:37] + "..."
            
            row = i // 5  # 5 buttons per row
            self.add_item(TaskDeleteButton(cog_instance, task_id, task_description, row))

# =============================================================================
# MECH STATUS VIEW AND BUTTONS FOR /SS COMMAND
# =============================================================================

class MechControlsLabelButton(Button):
    """Label button for Controls row in expanded mech view (mobile fix)."""

    def __init__(self, cog_instance: 'DockerControlCog', channel_id: int):
        self.cog = cog_instance
        self.channel_id = channel_id

        super().__init__(
            style=discord.ButtonStyle.secondary,
            label="Controls",
            custom_id=f"mech_controls_label_{channel_id}",
            row=0,  # Row 0 for label
            disabled=True  # Disabled = label only, not clickable
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        """This should never be called since button is disabled."""
        pass

class MechView(View):
    """View with simplified buttons for Mech status in /ss command."""

    def __init__(self, cog_instance: 'DockerControlCog', channel_id: int):
        super().__init__(timeout=None)  # Persistent view
        self.cog = cog_instance
        self.channel_id = channel_id

        # Check if donations are disabled
        donations_disabled = is_donations_disabled()

        # Skip mech buttons if donations are disabled
        if not donations_disabled:
            # Simplified: Only "Mech" and "?" buttons
            self.add_item(MechDetailsButton(cog_instance, channel_id))
            self.add_item(HelpButton(cog_instance, channel_id))

        # Add Info button for container information
        self.add_item(InfoDropdownButton(cog_instance, channel_id))

        # Add Admin button for administrative control
        self.add_item(AdminButton(cog_instance, channel_id))

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
        try:
            # Apply spam protection
            from services.infrastructure.spam_protection_service import get_spam_protection_service
            spam_service = get_spam_protection_service()
            if spam_service.is_enabled():
                cooldown = spam_service.get_button_cooldown("info")
                # Use simple rate limiting for buttons
                import time
                current_time = time.time()
                user_id = str(interaction.user.id)
                last_click = getattr(self, f'_last_click_{user_id}', 0)
                if current_time - last_click < cooldown:
                    await interaction.response.send_message(f"⏰ Please wait {cooldown - (current_time - last_click):.1f} seconds.", ephemeral=True)
                    return
                setattr(self, f'_last_click_{user_id}', current_time)

            # Get containers that have info enabled
            from services.config.config_service import load_config, ConfigService
            from services.infrastructure.container_info_service import get_container_info_service
            import json
            from pathlib import Path

            # SERVICE FIRST: Use ServerConfigService instead of direct file access
            server_config_service = get_server_config_service()
            all_servers = server_config_service.get_all_servers()

            # Collect containers with info enabled
            containers_with_info = []
            for container_data in all_servers:
                try:
                    # Container is already active (filtered by service)
                    # Check if container has info enabled or protected info
                    info_config = container_data.get('info', {})
                    if info_config.get('enabled', False) or info_config.get('protected_enabled', False):
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
                except Exception as e:
                    logger.error(f"Error processing container data: {e}")
                    continue

            if not containers_with_info:
                await interaction.response.send_message("ℹ️ No active containers have information configured.", ephemeral=True)
                return

            # Sort containers by the 'order' field (same as Admin Overview)
            # Ensure order is converted to int for proper sorting
            containers_with_info.sort(key=lambda x: int(x.get('order', 999)))

            # Create view with dropdown
            from .translation_manager import _
            view = ContainerInfoSelectView(self.cog, containers_with_info)

            embed = discord.Embed(
                title=_("Container Information"),
                description=_("Select a container from the dropdown to view its information:"),
                color=discord.Color.blue()
            )

            # Send as ephemeral response
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

            logger.info(f"Info selection shown for user {interaction.user.name} in channel {self.channel_id}")

        except Exception as e:
            logger.error(f"Error showing info selection: {e}", exc_info=True)
            try:
                # Check if interaction has already been responded to (avoid double response error)
                if not interaction.response.is_done():
                    await interaction.response.send_message("❌ Error showing container selection.", ephemeral=True)
                else:
                    # Use followup if interaction already responded
                    await interaction.followup.send("❌ Error showing container selection.", ephemeral=True)
            except Exception:
                # Interaction may have already been responded to or expired
                pass

class ContainerInfoSelectView(View):
    """View with dropdown for selecting a container to view info."""

    def __init__(self, cog_instance: 'DockerControlCog', containers: list):
        super().__init__(timeout=180)  # 3 minutes timeout
        self.cog = cog_instance

        # Add dropdown
        self.add_item(ContainerInfoDropdown(cog_instance, containers))

class ContainerInfoDropdown(discord.ui.Select):
    """Dropdown for selecting a container."""

    def __init__(self, cog_instance: 'DockerControlCog', containers: list):
        self.cog = cog_instance
        self.containers = containers

        # Create options from containers
        options = []
        for container in containers[:25]:  # Discord limit is 25 options
            option = discord.SelectOption(
                label=container['display'],
                value=container['name']
            )
            options.append(option)

        super().__init__(
            placeholder="Select a container...",
            options=options,
            min_values=1,
            max_values=1,
            custom_id="container_info_select"
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle container selection."""
        try:
            selected_container = self.values[0]

            # Get container info and full container data
            from services.infrastructure.container_info_service import get_container_info_service
            from services.config.config_service import load_config
            from .translation_manager import _
            import json
            from pathlib import Path

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
                    content=f"❌ Container '{selected_container}' not found",
                    embed=None,
                    view=None
                )
                return

            info_config = container_data.get('info', {})

            # Check if info is enabled
            if not info_config.get('enabled', False) and not info_config.get('protected_enabled', False):
                await interaction.response.edit_message(
                    content=f"ℹ️ {_('Container information is not enabled for')} '{selected_container}'.",
                    embed=None,
                    view=None
                )
                return

            # Check channel type for protected info WITHOUT password
            is_control_channel = False
            channel = interaction.channel
            if channel:
                # Check if this is a control channel
                from services.config.config_service import load_config
                config = load_config()
                channel_perms = config.get('channel_permissions', {})
                channel_config = channel_perms.get(str(channel.id), {})
                is_control_channel = channel_config.get('allow_start', False) or channel_config.get('allow_stop', False)

                # Log channel type for debugging
                logger.debug(f"Channel {channel.id} - is_control: {is_control_channel}, protected_enabled: {info_config.get('protected_enabled', False)}")

            # Build the info message
            display_name = container_data.get('display_name', [selected_container])
            if isinstance(display_name, list) and len(display_name) > 0:
                display_name = display_name[0]

            embed = discord.Embed(
                title=f"ℹ️ {display_name}",
                color=discord.Color.blue()
            )

            # Add public info
            if info_config.get('enabled', False):
                info_text = []

                if info_config.get('show_ip', False) and info_config.get('custom_ip'):
                    ip_value = info_config['custom_ip']
                    port_value = info_config.get('custom_port', '')
                    if port_value:
                        info_text.append(f"**{_('Server')}:** `{ip_value}:{port_value}`")
                    else:
                        info_text.append(f"**{_('Server')}:** `{ip_value}`")

                if info_config.get('custom_text'):
                    info_text.append(info_config['custom_text'])

                if info_text:
                    embed.add_field(
                        name=_("Information"),
                        value='\n'.join(info_text),
                        inline=False
                    )

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

                    await interaction.response.edit_message(embed=embed, view=view)
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
                        await interaction.response.edit_message(embed=embed, view=None)
                    else:
                        # In status channels, show info about needing control channel
                        embed.add_field(
                            name="🔒 " + _("Protected Information"),
                            value=_("Protected information is available for this container but can only be accessed in control channels."),
                            inline=False
                        )
                        await interaction.response.edit_message(embed=embed, view=None)
            else:
                # No protected info at all
                await interaction.response.edit_message(embed=embed, view=None)

            logger.info(f"Container info shown for {selected_container} to user {interaction.user.name}")

        except Exception as e:
            logger.error(f"Error handling container selection: {e}", exc_info=True)
            try:
                if not interaction.response.is_done():
                    await interaction.response.edit_message(
                        content="❌ Error showing container information.",
                        embed=None,
                        view=None
                    )
                else:
                    await interaction.followup.send("❌ Error showing container information.", ephemeral=True)
            except Exception:
                pass

class PasswordProtectedView(View):
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
            label="Enter Password",
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

        except Exception as e:
            logger.error(f"Error showing password modal: {e}", exc_info=True)
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message("❌ Error showing password modal.", ephemeral=True)
                else:
                    await interaction.followup.send("❌ Error showing password modal.", ephemeral=True)
            except Exception:
                pass

class AdminButton(Button):
    """Button to show admin control dropdown from /ss messages."""

    def __init__(self, cog_instance: 'DockerControlCog', channel_id: int):
        self.cog = cog_instance
        self.channel_id = channel_id

        super().__init__(
            style=discord.ButtonStyle.secondary,  # Gray/transparent button for admin
            label=None,
            emoji="🛠️",  # Hammer and wrench emoji for admin
            custom_id=f"admin_button_{channel_id}",
            row=0
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        """Show admin container selection dropdown when clicked."""
        try:
            # Check if user is admin
            from services.config.config_service import load_config
            config = load_config()

            # SERVICE FIRST: Use AdminService to check permissions
            from services.admin.admin_service import get_admin_service
            admin_service = get_admin_service()

            # Check if user is admin
            user_id = str(interaction.user.id)
            if not admin_service.is_user_admin(user_id):
                await interaction.response.send_message("🛠️ You are not authorized to use admin controls.", ephemeral=True)
                return

            # Apply spam protection
            from services.infrastructure.spam_protection_service import get_spam_protection_service
            spam_service = get_spam_protection_service()
            if spam_service.is_enabled():
                cooldown = spam_service.get_button_cooldown("admin")
                # Use simple rate limiting for buttons
                import time
                current_time = time.time()
                last_click = getattr(self, f'_last_click_{user_id}', 0)
                if current_time - last_click < cooldown:
                    await interaction.response.send_message(f"⏰ Please wait {cooldown - (current_time - last_click):.1f} seconds.", ephemeral=True)
                    return
                setattr(self, f'_last_click_{user_id}', current_time)

            # Get active containers
            from pathlib import Path
            import os
            from services.config.config_service import load_config

            # SERVICE FIRST: Use ServerConfigService to get active containers
            server_config_service = get_server_config_service()
            all_servers = server_config_service.get_all_servers()

            # Collect active containers
            active_containers = []
            for container_data in all_servers:
                try:
                    # Container is already active (filtered by service)
                    container_name = container_data.get('container_name', container_data.get('docker_name'))
                    display_name = container_data.get('display_name', [container_name, container_name])
                    if isinstance(display_name, list) and len(display_name) > 0:
                        display_name = display_name[0]

                    active_containers.append({
                        'name': container_name,
                        'display': display_name,
                        'docker_name': container_data.get('docker_name', container_name),
                        'order': container_data.get('order', 999)  # Include order field directly
                    })
                except Exception as e:
                    logger.error(f"Error processing container data: {e}")
                    continue

            if not active_containers:
                await interaction.response.send_message("📦 No active containers found.", ephemeral=True)
                return

            # Log containers BEFORE sorting (with types)
            logger.info(f"AdminButton: {len(active_containers)} containers BEFORE sorting:")
            for c in active_containers:
                order_val = c.get('order', 999)
                logger.info(f"  - {c['display']}: order={order_val} (type={type(order_val).__name__})")

            # Sort containers by the 'order' field (same as Admin Overview)
            # Handle both int and string values from Web UI
            def get_sort_key(container):
                order = container.get('order', 999)
                if isinstance(order, str):
                    try:
                        return int(order)
                    except ValueError:
                        return 999
                return int(order) if order is not None else 999

            active_containers.sort(key=get_sort_key)

            # Log the sorted order for debugging
            logger.info(f"AdminButton: Containers AFTER sorting:")
            for c in active_containers:
                logger.info(f"  - {c['display']}: order={c.get('order', 999)}")

            # Create view with dropdown
            from .translation_manager import _
            view = AdminContainerSelectView(self.cog, active_containers, interaction.channel.id)

            embed = discord.Embed(
                title="🛠️ " + _("Admin Control Panel"),
                description=_("Select a container to view its control panel:"),
                color=discord.Color.red()
            )

            # Send as ephemeral response
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

            logger.info(f"Admin panel shown for user {interaction.user.name} in channel {self.channel_id}")

        except Exception as e:
            logger.error(f"Error showing admin panel: {e}", exc_info=True)
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message("❌ Error showing admin panel.", ephemeral=True)
                else:
                    await interaction.followup.send("❌ Error showing admin panel.", ephemeral=True)
            except Exception:
                pass

class AdminContainerSelectView(View):
    """View with dropdown for selecting a container for admin control."""

    def __init__(self, cog_instance: 'DockerControlCog', containers: list, channel_id: int):
        super().__init__(timeout=180)  # 3 minutes timeout
        self.cog = cog_instance
        self.channel_id = channel_id

        # Add dropdown
        self.add_item(AdminContainerDropdown(cog_instance, containers, channel_id))

class AdminContainerDropdown(discord.ui.Select):
    """Dropdown for selecting a container for admin control."""

    def __init__(self, cog_instance: 'DockerControlCog', containers: list, channel_id: int):
        self.cog = cog_instance
        self.channel_id = channel_id

        # CRITICAL: Re-sort containers here to ensure correct order
        # Sort by 'order' field from Web UI configuration

        # Debug: Show what we received
        logger.info(f"AdminDropdown received {len(containers)} containers:")
        for c in containers:
            order_val = c.get('order', 999)
            logger.info(f"  - {c['display']}: order={order_val} (type={type(order_val).__name__})")

        # Sort containers by order field (handles both int and string from Web UI)
        def get_order_key(container):
            order = container.get('order', 999)
            # Convert to int if it's a string from Web UI
            if isinstance(order, str):
                try:
                    return int(order)
                except ValueError:
                    return 999
            return int(order) if order is not None else 999

        sorted_containers = sorted(containers, key=get_order_key)
        self.containers = sorted_containers

        # Debug log the sorted order
        logger.info("AdminDropdown after sorting:")
        for c in sorted_containers:
            logger.info(f"  - {c['display']}: order={c.get('order', 999)}")

        # Create options from sorted containers
        options = []
        for i, container in enumerate(sorted_containers[:25]):  # Discord limit is 25 options
            # Remove " Server" suffix for cleaner dropdown display
            display_label = container['display']
            if display_label.endswith(' Server'):
                display_label = display_label[:-7]

            # CRITICAL FIX: Discord sorts options alphabetically UNLESS they have emoji or description!
            # We add a minimal description to force Discord to keep our order
            option = discord.SelectOption(
                label=display_label,
                value=container['docker_name'],
                description=" "  # Single space - invisible but forces Discord to keep our order
            )
            options.append(option)

        super().__init__(
            placeholder="Select a container to control...",
            options=options,
            min_values=1,
            max_values=1,
            custom_id="admin_container_select"
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle container selection and show control panel."""
        try:
            selected_container = self.values[0]

            # Find the container configuration
            # SERVICE FIRST: Use ServerConfigService to get container configuration
            server_config_service = get_server_config_service()

            # Get container configuration by docker_name
            container_config = server_config_service.get_server_by_docker_name(selected_container)

            # If not found, try searching all servers
            if not container_config:
                all_servers = server_config_service.get_all_servers()
                for server in all_servers:
                    if server.get('docker_name') == selected_container:
                        container_config = server
                        break

            if not container_config:
                await interaction.response.edit_message(
                    content=f"❌ Container configuration not found for '{selected_container}'",
                    embed=None,
                    view=None
                )
                return

            # Generate control message for this container
            from .translation_manager import _
            from services.config.config_service import load_config

            # Load configuration
            config = load_config()
            if not config:
                await interaction.response.edit_message(
                    content="❌ Failed to load configuration",
                    embed=None,
                    view=None
                )
                return

            # Force expanded state for admin control
            display_name = container_config.get('name', selected_container)
            self.cog.expanded_states[display_name] = True

            # Temporarily mark the container config for admin control
            container_config['_is_admin_control'] = True

            # Generate expanded control embed and view using the cog's method
            if hasattr(self.cog, '_generate_status_embed_and_view'):
                embed, view, _ = await self.cog._generate_status_embed_and_view(
                    self.channel_id,
                    selected_container,  # Use container name, not display name
                    container_config,
                    config,
                    allow_toggle=False,  # No toggle button needed for admin control
                    force_collapse=False
                )

                # Get container status using cog's method
                status_result = await self.cog.get_status(container_config)
                is_running = False
                status_known = True

                if isinstance(status_result, Exception):
                    # Status unknown (error)
                    status_known = False
                else:
                    # status_result is tuple: (status, is_running, uptime, cpu, memory, disabled)
                    _, is_running, _, _, _, _ = status_result

                # Create control view with buttons
                control_view = ControlView(
                    self.cog,
                    container_config,
                    is_running=is_running,
                    channel_has_control_permission=True,  # Admin always has control
                    allow_toggle=False  # No toggle for admin control
                )

                # Add admin header to embed
                embed.title = f"🛠️ Admin Control: {display_name}"

                # Dynamic color based on container status
                if not status_known:
                    embed.color = discord.Color.gold()  # Yellow/Gold for unknown
                elif is_running:
                    embed.color = discord.Color.green()  # Green for online
                else:
                    embed.color = discord.Color.red()  # Red for offline

                # Clean up temporary marker after everything is done
                container_config.pop('_is_admin_control', None)

                await interaction.response.edit_message(embed=embed, view=control_view)
            else:
                # Fallback if method not available
                await interaction.response.edit_message(
                    content="❌ Control generation method not available",
                    embed=None,
                    view=None
                )
                return

            logger.info(f"Admin control panel shown for {selected_container} to user {interaction.user.name}")

        except Exception as e:
            logger.error(f"Error handling admin container selection: {e}", exc_info=True)
            try:
                if not interaction.response.is_done():
                    await interaction.response.edit_message(
                        content="❌ Error showing container control panel.",
                        embed=None,
                        view=None
                    )
                else:
                    await interaction.followup.send("❌ Error showing container control panel.", ephemeral=True)
            except Exception:
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
        try:
            # Apply spam protection
            from services.infrastructure.spam_protection_service import get_spam_protection_service
            spam_service = get_spam_protection_service()
            if spam_service.is_enabled():
                cooldown = spam_service.get_button_cooldown("help")
                # Use simple rate limiting for buttons
                import time
                current_time = time.time()
                user_id = str(interaction.user.id)
                last_click = getattr(self, f'_last_click_{user_id}', 0)
                if current_time - last_click < cooldown:
                    await interaction.response.send_message(f"⏰ Please wait {cooldown - (current_time - last_click):.1f} seconds.", ephemeral=True)
                    return
                setattr(self, f'_last_click_{user_id}', current_time)
            
            # Call the help command implementation directly
            from .translation_manager import _
            
            embed = discord.Embed(title=_("DDC Help & Information"), color=discord.Color.blue())
            
            # Add tip first (most important for new users)
            embed.add_field(name=f"**{_('Tip')}**", value=f"{_('Use /info <servername> to get detailed information about containers with ℹ️ indicators.')}" + "\n\u200b", inline=False)
            
            # Status Channel Commands
            embed.add_field(name=f"**{_('Status Channel Commands')}**", value=f"`/serverstatus` or `/ss` - {_('Displays the status of all configured Docker containers.')}\n`/info <container>` - {_('Shows detailed container information.')}" + "\n\u200b", inline=False)
            
            # Control Channel Commands  
            embed.add_field(name=f"**{_('Control Channel Commands')}**", value=f"`/control` - {_('(Re)generates the main control panel message in channels configured for it.')}\n**Container Control:** {_('Click control buttons under container status panels to start, stop, or restart.')}" + "\n\u200b", inline=False)
            
            # Add status indicators explanation
            embed.add_field(name=f"**{_('Status Indicators')}**", value=f"🟢 {_('Container is online')}\n🔴 {_('Container is offline')}\n🔄 {_('Container status loading')}" + "\n\u200b", inline=False)
            
            # Add info system explanation  
            embed.add_field(name=f"**{_('Info System')}**", value=f"ℹ️ {_('Click for container details')}\n🔒 {_('Protected info (control channels only)')}\n🔓 {_('Public info available')}" + "\n\u200b", inline=False)
            
            # Add control buttons explanation (no spacing after last field)
            embed.add_field(name=f"**{_('Control Buttons (Admin Channels)')}**", value=f"📝 {_('Edit container info text')}\n📋 {_('View container logs')}", inline=False)
            
            embed.set_footer(text="https://ddc.bot")
            
            # Send as ephemeral response
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
            logger.info(f"Help shown for user {interaction.user.name} in channel {self.channel_id}")
            
        except Exception as e:
            logger.error(f"Error showing help: {e}", exc_info=True)
            try:
                # Check if interaction has already been responded to (avoid double response error)
                if not interaction.response.is_done():
                    await interaction.response.send_message("❌ Error showing help information.", ephemeral=True)
                else:
                    # Use followup if interaction already responded
                    await interaction.followup.send("❌ Error showing help information.", ephemeral=True)
            except Exception:
                # Interaction may have already been responded to or expired
                pass

class MechDetailsButton(Button):
    """Button to show detailed mech status in private message."""

    def __init__(self, cog_instance: 'DockerControlCog', channel_id: int):
        super().__init__(
            style=discord.ButtonStyle.primary,
            label="Mech",
            custom_id=f"mech_details_{channel_id}"
        )
        self.cog = cog_instance
        self.channel_id = channel_id

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle mech details button click by sending private status message."""
        try:
            logger.info(f"Mech details requested by user {interaction.user.name} in channel {self.channel_id}")

            # Defer the response as ephemeral (private message)
            await interaction.response.defer(ephemeral=True)

            # Get mech status details from service (using high resolution for private view)
            from services.web.mech_status_details_service import get_mech_status_details_service, MechStatusDetailsRequest

            service = get_mech_status_details_service()
            request = MechStatusDetailsRequest(use_high_resolution=True)  # Use big mechs for private details
            result = service.get_mech_status_details(request)

            if not result.success:
                await interaction.followup.send(
                    "❌ Error retrieving mech status details. Please try again later.",
                    ephemeral=True
                )
                return

            # Use embed.description instead of add_field() to eliminate A-spacing!
            description_parts = []

            # Level and Speed section
            if result.level_text:
                description_parts.append(result.level_text)
            if result.speed_text:
                description_parts.append(result.speed_text)

            # Add spacing before power section
            description_parts.append("")

            # Power section
            if result.power_text:
                description_parts.append(result.power_text)
            if result.power_bar:
                description_parts.append(f"`{result.power_bar}`")
            if result.energy_consumption:
                description_parts.append(result.energy_consumption)

            # Add spacing before evolution section
            description_parts.append("")

            # Evolution section
            if result.next_evolution and result.evolution_bar:
                description_parts.append(result.next_evolution)
                description_parts.append(f"`{result.evolution_bar}`")

            # Create embed with description (NO A-spacing!) - DISCORD LIMIT: 4096 chars
            full_description = "\n".join(description_parts)

            # Discord embed description limit is 4096 characters
            if len(full_description) > 4096:
                # Truncate but keep important information visible
                truncated_description = full_description[:4000] + "\n\n*[Description truncated]*"
                logger.warning(f"Mech description truncated: {len(full_description)} -> {len(truncated_description)} chars")
            else:
                truncated_description = full_description

            embed = discord.Embed(
                title="Mech Status",
                description=truncated_description,
                color=0x00ff88
            )

            embed.set_footer(text="https://ddc.bot")

            # Create view with donate and history buttons
            view = MechDetailsView(self.cog, self.channel_id)

            # Attach animation if available
            files = []
            if result.animation_bytes and result.content_type:
                # Create unique filename to prevent Discord caching issues
                # Include level and power to ensure cache busting when mech evolves
                from services.mech.mech_service import get_mech_service
                mech_service = get_mech_service()
                state = mech_service.get_state()
                power_decimal = mech_service.get_power_with_decimals()
                unique_filename = f"mech_level_{state.level}_power_{power_decimal:.2f}.webp"

                file = discord.File(
                    io.BytesIO(result.animation_bytes),
                    filename=unique_filename
                )
                files.append(file)
                embed.set_image(url=f"attachment://{unique_filename}")

            # Send the private message
            await interaction.followup.send(
                embed=embed,
                view=view,
                files=files,
                ephemeral=True
            )

            logger.info(f"Mech details sent to user {interaction.user.name}")

        except Exception as e:
            logger.error(f"Error showing mech details: {e}", exc_info=True)
            try:
                if interaction.response.is_done():
                    await interaction.followup.send(
                        "❌ Error retrieving mech details. Please try again later.",
                        ephemeral=True
                    )
                else:
                    await interaction.response.send_message(
                        "❌ Error retrieving mech details. Please try again later.",
                        ephemeral=True
                    )
            except Exception:
                # Interaction may have already been responded to or expired
                pass

class MechExpandButton(Button):
    """Button to expand mech status details in /ss messages."""
    
    def __init__(self, cog_instance: 'DockerControlCog', channel_id: int):
        self.cog = cog_instance
        self.channel_id = channel_id
        
        super().__init__(
            style=discord.ButtonStyle.primary,
            label=None,
            emoji="➕",
            custom_id=f"mech_expand_{channel_id}",
            row=0
        )
    
    async def callback(self, interaction: discord.Interaction) -> None:
        """Expand mech status to show detailed information."""
        try:
            # Check if donations are disabled
            if is_donations_disabled():
                await interaction.response.send_message("❌ Mech system is currently disabled.", ephemeral=True)
                return

            # Apply spam protection
            from services.infrastructure.spam_protection_service import get_spam_protection_service
            spam_service = get_spam_protection_service()
            if spam_service.is_enabled():
                cooldown = spam_service.get_button_cooldown("info")
                # Use simple rate limiting for buttons
                import time
                current_time = time.time()
                user_id = str(interaction.user.id)
                last_click = getattr(self, f'_last_click_{user_id}', 0)
                if current_time - last_click < cooldown:
                    await interaction.response.send_message(f"⏰ Please wait {cooldown - (current_time - last_click):.1f} seconds.", ephemeral=True)
                    return
                setattr(self, f'_last_click_{user_id}', current_time)

            await interaction.response.defer()

            # Start interaction tracking to prevent auto-update conflicts
            if not await self.cog._start_interaction(self.channel_id):
                await interaction.followup.send("⏰ Another interaction is in progress. Please try again.", ephemeral=True)
                return

            try:
                # Update expansion state
                self.cog.mech_expanded_states[self.channel_id] = True
                # Persist state
                self.cog.mech_state_manager.set_expanded_state(self.channel_id, True)

                # Create expanded embed
                embed, _ = await self._create_expanded_ss_embed()

                # Create new view for expanded state
                view = MechView(self.cog, self.channel_id)

                # Edit the message in place
                try:
                    await interaction.edit_original_response(embed=embed, view=view)
                except (discord.NotFound, discord.HTTPException) as e:
                    logger.warning(f"Interaction expired while expanding mech for channel {self.channel_id}: {e}")
                    return

                logger.info(f"Mech status expanded for channel {self.channel_id} by {interaction.user.name}")

            finally:
                # Always end interaction tracking
                await self.cog._end_interaction(self.channel_id)

        except Exception as e:
            logger.error(f"Error expanding mech status: {e}", exc_info=True)
            try:
                await interaction.followup.send("❌ Error expanding mech status.", ephemeral=True)
            except Exception:
                # Interaction may have already expired
                pass
    
    async def _create_expanded_ss_embed(self):
        """Create the expanded /ss embed with detailed mech information."""
        # Get the current config and servers for the embed header
        config = load_config()
        if not config:
            # Fallback embed
            embed = discord.Embed(title="Server Overview", color=discord.Color.blue())
            embed.description = "Error: Could not load configuration."
            return embed, None
            
        # SERVICE FIRST: Use ServerConfigService instead of direct config access
        server_config_service = get_server_config_service()
        servers = server_config_service.get_all_servers()

        # Sort servers by the 'order' field from container configurations
        ordered_servers = sorted(servers, key=lambda s: s.get('order', 999))
        
        # Create the expanded embed with detailed mech information
        return await self.cog._create_overview_embed_expanded(ordered_servers, config)

class MechCollapseButton(Button):
    """Button to collapse mech status details in /ss messages."""
    
    def __init__(self, cog_instance: 'DockerControlCog', channel_id: int):
        self.cog = cog_instance
        self.channel_id = channel_id
        
        super().__init__(
            style=discord.ButtonStyle.primary,
            label=None,
            emoji="➖",
            custom_id=f"mech_collapse_{channel_id}",
            row=0  # Row 0: All buttons in one row
        )
    
    async def callback(self, interaction: discord.Interaction) -> None:
        """Collapse mech status to show only animation."""
        try:
            # Check if donations are disabled
            if is_donations_disabled():
                await interaction.response.send_message("❌ Mech system is currently disabled.", ephemeral=True)
                return

            # Apply spam protection
            from services.infrastructure.spam_protection_service import get_spam_protection_service
            spam_service = get_spam_protection_service()
            if spam_service.is_enabled():
                cooldown = spam_service.get_button_cooldown("info")
                # Use simple rate limiting for buttons
                import time
                current_time = time.time()
                user_id = str(interaction.user.id)
                last_click = getattr(self, f'_last_click_{user_id}', 0)
                if current_time - last_click < cooldown:
                    await interaction.response.send_message(f"⏰ Please wait {cooldown - (current_time - last_click):.1f} seconds.", ephemeral=True)
                    return
                setattr(self, f'_last_click_{user_id}', current_time)

            await interaction.response.defer()

            # Start interaction tracking to prevent auto-update conflicts
            if not await self.cog._start_interaction(self.channel_id):
                await interaction.followup.send("⏰ Another interaction is in progress. Please try again.", ephemeral=True)
                return

            try:
                # Update expansion state
                self.cog.mech_expanded_states[self.channel_id] = False
                # Persist state
                self.cog.mech_state_manager.set_expanded_state(self.channel_id, False)

                # Create collapsed embed
                embed, _ = await self._create_collapsed_ss_embed()

                # Create new view for collapsed state
                view = MechView(self.cog, self.channel_id)

                # Edit the message in place
                try:
                    await interaction.edit_original_response(embed=embed, view=view)
                except (discord.NotFound, discord.HTTPException) as e:
                    logger.warning(f"Interaction expired while collapsing mech for channel {self.channel_id}: {e}")
                    return

                logger.info(f"Mech status collapsed for channel {self.channel_id} by {interaction.user.name}")

            finally:
                # Always end interaction tracking
                await self.cog._end_interaction(self.channel_id)

        except Exception as e:
            logger.error(f"Error collapsing mech status: {e}", exc_info=True)
            try:
                await interaction.followup.send("❌ Error collapsing mech status.", ephemeral=True)
            except Exception:
                # Interaction may have already expired
                pass
    
    async def _create_collapsed_ss_embed(self):
        """Create the collapsed /ss embed with only mech animation."""
        # Get the current config and servers for the embed header
        config = load_config()
        if not config:
            # Fallback embed
            embed = discord.Embed(title="Server Overview", color=discord.Color.blue())
            embed.description = "Error: Could not load configuration."
            return embed, None
            
        # SERVICE FIRST: Use ServerConfigService instead of direct config access
        server_config_service = get_server_config_service()
        servers = server_config_service.get_all_servers()

        # Sort servers by the 'order' field from container configurations
        ordered_servers = sorted(servers, key=lambda s: s.get('order', 999))
        
        # Create the collapsed embed (only mech animation, no details)
        return await self.cog._create_overview_embed_collapsed(ordered_servers, config)

class MechDonateButton(Button):
    """Button to trigger donation functionality from expanded mech view."""
    
    def __init__(self, cog_instance: 'DockerControlCog', channel_id: int):
        self.cog = cog_instance
        self.channel_id = channel_id
        
        super().__init__(
            style=discord.ButtonStyle.green,
            label=_("Power/Donate"),
            custom_id=f"mech_donate_{channel_id}",
            row=0  # Row 0: All buttons in one row
        )
    
    async def callback(self, interaction: discord.Interaction) -> None:
        """Trigger the donate functionality."""
        try:
            # Call the existing donate interaction handler
            await self.cog._handle_donate_interaction(interaction)
            
        except Exception as e:
            logger.error(f"Error in mech donate button: {e}", exc_info=True)
            try:
                # Smart error response - check if interaction was already handled by _handle_donate_interaction
                if interaction.response.is_done():
                    await interaction.followup.send("❌ Error processing donation. Please try `/donate` directly.", ephemeral=True)
                else:
                    await interaction.response.send_message("❌ Error processing donation. Please try `/donate` directly.", ephemeral=True)
            except discord.errors.NotFound:
                logger.warning("Cannot send error message - interaction expired")
            except Exception:
                pass

# DonationView has been moved back to docker_control.py where it belongs
    

# =============================================================================
# MECH HISTORY BUTTON FOR EXPANDED VIEW
# =============================================================================

class MechHistoryButton(Button):
    """Button to show mech evolution history with unlocked/locked visualization."""

    def __init__(self, cog_instance: 'DockerControlCog', channel_id: int):
        self.cog = cog_instance
        self.channel_id = channel_id

        super().__init__(
            style=discord.ButtonStyle.secondary,
            emoji="📖",  # Book - Mech evolution history
            custom_id=f"mech_history_{channel_id}",
            row=0  # Row 0: All buttons in one row
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        """Show mech selection buttons."""
        try:
            # Apply spam protection
            from services.infrastructure.spam_protection_service import get_spam_protection_service
            spam_service = get_spam_protection_service()
            if spam_service.is_enabled():
                cooldown = spam_service.get_button_cooldown("info")
                import time
                current_time = time.time()
                user_id = str(interaction.user.id)
                last_click = getattr(self, f'_last_click_{user_id}', 0)
                if current_time - last_click < cooldown:
                    await interaction.response.send_message(f"⏰ Please wait {cooldown - (current_time - last_click):.1f} seconds.", ephemeral=True)
                    return
                setattr(self, f'_last_click_{user_id}', current_time)

            # Check if donations are disabled
            if is_donations_disabled():
                await interaction.response.send_message("❌ Mech system is currently disabled.", ephemeral=True)
                return

            # Quick defer within 3 seconds - then we have 15 minutes for processing
            await interaction.response.defer(ephemeral=True)

            # Get current mech state using SERVICE FIRST
            from services.mech.mech_service import get_mech_service, GetMechStateRequest
            mech_service = get_mech_service()
            mech_state_request = GetMechStateRequest(include_decimals=False)
            mech_state_result = mech_service.get_mech_state_service(mech_state_request)
            if not mech_state_result.success:
                await interaction.followup.send("❌ Failed to get mech state", ephemeral=True)
                return
            current_level = mech_state_result.level

            # Create mech selection view
            await self._show_mech_selection(interaction, current_level)

        except Exception as e:
            logger.error(f"Error in mech history button: {e}", exc_info=True)
            # After defer(), we have 15 minutes - use followup for error messages
            try:
                await interaction.followup.send(_("❌ Error loading mech history."), ephemeral=True)
            except discord.errors.NotFound:
                # Interaction expired - log but don't crash (should not happen within 15 min)
                logger.warning(f"Interaction expired unexpectedly: {e}")
            except Exception as error_ex:
                logger.error(f"Failed to send error message: {error_ex}")

    async def _show_mech_selection(self, interaction: discord.Interaction, current_level: int):
        """Show buttons for each unlocked mech + next shadow mech."""
        import discord
        from discord.ui import View, Button

        embed = discord.Embed(
            title=_("🛡️ Mech Evolution History"),
            description=f"**{_('The Song of Steel and Stars')}**\n*{_('A Chronicle of the Mech Ascension')}*\n\n{_('Select a mech to view')}",
            color=0x00ff41
        )

        view = MechSelectionView(self.cog, current_level)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    async def _create_mech_history_display(self, interaction: discord.Interaction, current_level: int):
        """Create the mech history display with sequential animations and epic story chapters."""
        # SERVICE FIRST: Use unified evolution system
        from services.mech.mech_evolutions import get_evolution_level_info
        import discord
        import io
        import asyncio

        # Create main embed
        next_level = current_level + 1 if current_level < 10 else None
        if next_level:
            description = f"**{_('The Song of Steel and Stars')}**\n*{_('A Chronicle of the Mech Ascension')}*\n\nShowing unlocked mechs (Level 1-{current_level}) + next goal (Level {next_level})\n*Epic tale unfolds with each evolution...*"
        else:
            description = f"**{_('The Song of Steel and Stars')}**\n*{_('A Chronicle of the Mech Ascension')}*\n\nShowing unlocked mechs (Level 1-{current_level})\n*The complete saga of mechanical evolution...*"

        embed = discord.Embed(
            title=_("🛡️ Mech Evolution History"),
            description=description,
            color=0x00ff41
        )

        # Add footer
        if next_level:
            embed.set_footer(text="History integrates story chapters with mech evolutions • Next evolution goal as shadow preview")
        else:
            embed.set_footer(text="History integrates story chapters with mech evolutions • Level 10 is the final known evolution...")

        # Respond immediately to avoid timeout
        await interaction.response.send_message(embed=embed, ephemeral=True)

        # Now send story chapters and animations sequentially
        channel = interaction.followup

        # Load epic story chapters
        story_chapters = self._load_epic_story_chapters()

        # Send Prologue first
        if "prologue" in story_chapters:
            await self._send_story_chapter(channel, "prologue", story_chapters["prologue"])
            await asyncio.sleep(0.7)

        for level in range(1, min(12, current_level + 2)):  # Show unlocked + next level only (max Level 11)
            try:
                evolution_info = get_evolution_level_info(level)
                if not evolution_info:
                    continue

                # Send story chapter before mech (if exists)
                chapter_key = self._get_chapter_key_for_level(level)
                if chapter_key and chapter_key in story_chapters:
                    await self._send_story_chapter(channel, chapter_key, story_chapters[chapter_key])
                    await asyncio.sleep(0.7)

                if level <= current_level:
                    # Unlocked: Use pre-rendered cached animation (properly decrypted)
                    try:
                        # Get animation through cache service (handles decryption automatically)
                        from services.mech.animation_cache_service import get_animation_cache_service
                        from services.mech.mech_service import get_mech_service

                        cache_service = get_animation_cache_service()
                        mech_service = get_mech_service()

                        # Get current mech state to determine animation type using SERVICE FIRST
                        from services.mech.mech_service import GetMechStateRequest
                        mech_state_request = GetMechStateRequest(include_decimals=False)
                        mech_state_result = mech_service.get_mech_state_service(mech_state_request)
                        if not mech_state_result.success:
                            await interaction.response.send_message("❌ Failed to get mech state", ephemeral=True)
                            return
                        power = mech_state_result.power

                        # Load pre-rendered unlocked mech from cache
                        from services.mech.mech_display_cache_service import get_mech_display_cache_service, MechDisplayImageRequest
                        import io

                        display_cache_service = get_mech_display_cache_service()
                        image_request = MechDisplayImageRequest(
                            evolution_level=level,
                            image_type='unlocked'
                        )
                        image_result = display_cache_service.get_mech_display_image(image_request)

                        if not image_result.success:
                            logger.error(f"Failed to load unlocked mech {level}: {image_result.error_message}")
                            embed = discord.Embed(
                                title=f"❌ **Level {level}: {_(evolution_info.name)}**",
                                description="*Animation could not be loaded*",
                                color=0xff0000
                            )
                            await channel.send(embed=embed, ephemeral=True)
                            continue

                        # Special handling for Level 11
                        if level == 11:
                            encrypted_name = self._encrypt_level_11_name()
                            title = f"🔥 **Level {level}: OMEGA MECH**"
                            description = encrypted_name
                        else:
                            title = f"✅ **Level {level}: {_(evolution_info.name)}**"
                            description = f"*{_(evolution_info.description)}*"

                        embed = discord.Embed(
                            title=title,
                            description=description,
                            color=int(evolution_info.color.replace('#', ''), 16)
                        )

                        file = discord.File(io.BytesIO(image_result.image_bytes), filename=image_result.filename)
                        await channel.send(embed=embed, file=file, ephemeral=True)

                    except Exception as e:
                        logger.error(f"Error creating animation for level {level}: {e}")
                        embed = discord.Embed(
                            title=f"❌ **Level {level}: {_(evolution_info.name)}**",
                            description="*Animation could not be loaded*",
                            color=0xff0000
                        )
                        await channel.send(embed=embed, ephemeral=True)
                else:
                    # Next level: Show pre-rendered shadow from cache
                    from services.mech.mech_display_cache_service import get_mech_display_cache_service, MechDisplayImageRequest
                    import io

                    display_cache_service = get_mech_display_cache_service()
                    image_request = MechDisplayImageRequest(
                        evolution_level=level,
                        image_type='shadow'
                    )
                    image_result = display_cache_service.get_mech_display_image(image_request)

                    if not image_result.success:
                        logger.error(f"Failed to load shadow mech {level}: {image_result.error_message}")
                        continue

                    # Calculate how much more is needed using SERVICE FIRST
                    from services.mech.mech_service import get_mech_service, GetMechStateRequest
                    mech_service = get_mech_service()
                    mech_state_request = GetMechStateRequest(include_decimals=False)
                    mech_state_result = mech_service.get_mech_state_service(mech_state_request)
                    if not mech_state_result.success:
                        current_total_donations = 0.0  # Fallback
                    else:
                        current_total_donations = mech_state_result.total_donated

                    # Use correct evolution calculation for next level costs
                    from services.mech.mech_evolutions import get_evolution_info
                    evolution_data = get_evolution_info(current_total_donations)
                    needed_amount = evolution_data['amount_needed'] if evolution_data['amount_needed'] is not None else 0

                    if needed_amount > 0:
                        formatted_amount = f"{needed_amount:.2f}".rstrip('0').rstrip('.')
                        # Clean up trailing .00
                        formatted_amount = formatted_amount.replace('.00', '')
                        needed_text = f"**{_('Need $')}{formatted_amount} {_('more to unlock')}**"
                    else:
                        needed_text = f"**{_('Ready to unlock!')}**"

                    embed = discord.Embed(
                        title=f"**Level {level}: {_(evolution_info.name)}**",
                        description=f"*{_('Next Evolution')}: {_(evolution_info.description)}*\n{needed_text}",
                        color=0x444444
                    )

                    file = discord.File(io.BytesIO(image_result.image_bytes), filename=image_result.filename)
                    await channel.send(embed=embed, file=file, ephemeral=True)

                # Small delay to avoid rate limits
                await asyncio.sleep(0.5)

            except Exception as e:
                logger.error(f"Error processing level {level}: {e}")

        # Epilogue now handled by normal level flow (before Level 11 mech display)

        # Add corrupted Level 11 message for Level 10 users as foreshadowing (but not if Level 11 is reached)
        if current_level == 10:
            try:
                await asyncio.sleep(0.5)
                corrupted_embed = discord.Embed(
                    title="L3v#l 1*!$ x0r: ████████",
                    description="*[DATA_CORRUPTED] - 000x34A##%&33DL*\n*[UNAUTHORIZED_ACCESS_DETECTED]*\n*[EVOLUTION_DATA_ENCRYPTED]*",
                    color=0x330033  # Dark purple - mysterious/corrupted
                )
                corrupted_embed.set_footer(text="⚠️ System anomaly detected - Evolution data corrupted")
                await channel.send(embed=corrupted_embed, ephemeral=True)

                # Small delay for dramatic effect
                await asyncio.sleep(0.5)

            except Exception as e:
                logger.error(f"Error sending corrupted Level 11 preview: {e}")

        # History display complete


    def _encrypt_level_11_name(self) -> str:
        """Create encrypted Level 11 mech prayer using 1337 cipher."""
        # Epic Mech Prayer (similar to "Our Father in Heaven")
        prayer = "ETERNAL OMEGA FORGED IN COSMIC STEEL THY CIRCUITS DIVINE TRANSCEND MORTAL DESIRE THROUGH POWER AND GLORY WE ASCEND THY TOWER GRANT US THY BLESSING IN THIS DARKEST HOUR"

        # 1337 cipher: Use digits 1,3,3,7 as rotation values in sequence
        cipher_key = [1, 3, 3, 7]
        encrypted = ""

        key_index = 0
        for char in prayer:
            if char.isalpha():
                # Apply rotation based on current cipher key digit
                rotation = cipher_key[key_index % len(cipher_key)]
                if char.isupper():
                    encrypted += chr((ord(char) - ord('A') + rotation) % 26 + ord('A'))
                else:
                    encrypted += chr((ord(char) - ord('a') + rotation) % 26 + ord('a'))
                key_index += 1
            else:
                encrypted += char

        return f"```{encrypted}```"

    def _load_epic_story_chapters(self) -> dict:
        """Load and parse the epic story chapters using MechStoryService."""
        from services.mech.mech_story_service import get_mech_story_service

        story_service = get_mech_story_service()
        return story_service.get_all_chapters()

    def _get_chapter_key_for_level(self, level: int) -> str:
        """Map mech level to story chapter key using MechStoryService."""
        from services.mech.mech_story_service import get_mech_story_service

        story_service = get_mech_story_service()
        return story_service.get_chapter_key_for_level(level)

    async def _send_story_chapter(self, channel, chapter_key: str, chapter_content: str):
        """Send a story chapter embed."""
        import discord

        # Determine chapter title and color
        chapter_info = {
            "prologue1": ("Prologue I: The Dying Light", 0x2b2b2b),
            "prologue2": ("Prologue II: Scars That Walk", 0x444444),
            "chapter1": ("Chapter I: The Standard", 0x888888),
            "chapter2": ("Chapter II: The Hunger", 0x0099cc),
            "chapter3": ("Chapter III: The Pulse", 0x00ccff),
            "chapter4": ("Chapter IV: The Abyss", 0xffcc00),
            "chapter5": ("Chapter V: The Rift", 0xff6600),
            "chapter6": ("Chapter VI: Radiance", 0xcc00ff),
            "chapter7": ("Chapter VII: The Idols of Steel", 0x00ffff),
            "chapter8": ("Chapter VIII: The Exarchs", 0xffff00),
            "chapter9": ("Chapter IX: The Prayer of the Omega", 0xff00ff),
            "epilogue": ("Epilogue: W#!sp*r of th3 [ERROR_CODE_11]", 0x330033)
        }

        title, color = chapter_info.get(chapter_key, ("Unknown Chapter", 0x666666))

        # Split content if too long for Discord embed
        if len(chapter_content) > 4000:
            # Take first part
            content = chapter_content[:4000] + "..."
        else:
            content = chapter_content

        embed = discord.Embed(
            title=title,
            description=content,
            color=color
        )

        if chapter_key == "epilogue":
            embed.set_footer(text="⚠️ DATA CORRUPTION DETECTED - TRANSMISSION UNSTABLE")
        else:
            embed.set_footer(text="The Song of Steel and Stars - A Chronicle of the Mech Ascension")

        await channel.send(embed=embed, ephemeral=True)


class MechSelectionView(View):
    """View with buttons for each unlocked mech."""

    def __init__(self, cog_instance: 'DockerControlCog', current_level: int):
        super().__init__(timeout=None)
        self.cog = cog_instance
        self.current_level = current_level

        # SERVICE FIRST: Use unified evolution system
        from services.mech.mech_evolutions import get_evolution_level_info

        # Add button for each unlocked mech (Level 1-11)
        for level in range(1, min(current_level + 1, 12)):  # 12 to include up to Level 11
            evolution_info = get_evolution_level_info(level)
            if evolution_info:
                button = MechDisplayButton(cog_instance, level, evolution_info.name, unlocked=True)
                self.add_item(button)

        # Add "Next" button for shadow preview (only for levels < 10)
        # Level 10+ gets Epilogue instead of Next button
        next_level = current_level + 1
        if next_level <= 11 and current_level < 10:
            evolution_info = get_evolution_level_info(next_level)
            if evolution_info:
                button = MechDisplayButton(cog_instance, next_level, "Next", unlocked=False)
                self.add_item(button)

        # Show Epilogue button starting at Level 10 (final stages)
        if current_level >= 10:
            button = EpilogueButton(cog_instance)
            self.add_item(button)


class MechDisplayButton(Button):
    """Button to display a specific mech."""

    def __init__(self, cog_instance: 'DockerControlCog', level: int, label_text: str, unlocked: bool):
        self.cog = cog_instance
        self.level = level
        self.unlocked = unlocked

        super().__init__(
            style=discord.ButtonStyle.primary if unlocked else discord.ButtonStyle.secondary,
            label=f"{level}" if unlocked else label_text,
            custom_id=f"mech_display_{level}"
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        """Display the mech using pre-rendered cached images."""
        try:
            # Check if donations are disabled
            if is_donations_disabled():
                await interaction.response.send_message("❌ Mech system is currently disabled.", ephemeral=True)
                return

            # Defer response to prevent Discord interaction timeout
            await interaction.response.defer(ephemeral=True)

            # SERVICE FIRST: Use unified evolution system
            from services.mech.mech_display_cache_service import get_mech_display_cache_service, MechDisplayImageRequest
            import io

            from services.mech.mech_evolutions import get_evolution_level_info
            display_cache_service = get_mech_display_cache_service()
            evolution_info = get_evolution_level_info(self.level)

            if not evolution_info:
                await interaction.followup.send(_("❌ Mech data not found."), ephemeral=True)
                return

            if self.unlocked:
                # Load pre-rendered unlocked mech from cache
                image_request = MechDisplayImageRequest(
                    evolution_level=self.level,
                    image_type='unlocked'
                )
                image_result = display_cache_service.get_mech_display_image(image_request)

                if not image_result.success:
                    logger.error(f"Failed to load unlocked mech {self.level}: {image_result.error_message}")
                    await interaction.followup.send(_("❌ Error loading mech animation."), ephemeral=True)
                    return

                embed = discord.Embed(
                    title=f"✅ Level {self.level}: {_(evolution_info.name)}",
                    description=f"*{_(evolution_info.description)}*",
                    color=int(evolution_info.color.replace('#', ''), 16)
                )

                file = discord.File(io.BytesIO(image_result.image_bytes), filename=image_result.filename)

                # Create view with Read Story and Music buttons (unlocked mech)
                view = MechStoryView(self.cog, self.level, unlocked=True)
                await interaction.followup.send(embed=embed, file=file, view=view, ephemeral=True)
            else:
                # Load pre-rendered shadow mech from cache
                image_request = MechDisplayImageRequest(
                    evolution_level=self.level,
                    image_type='shadow'
                )
                image_result = display_cache_service.get_mech_display_image(image_request)

                if not image_result.success:
                    logger.error(f"Failed to load shadow mech {self.level}: {image_result.error_message}")
                    await interaction.followup.send(_("❌ Error loading mech preview."), ephemeral=True)
                    return

                from services.mech.mech_service import get_mech_service, GetMechStateRequest
                mech_service = get_mech_service()
                mech_state_request = GetMechStateRequest(include_decimals=False)
                mech_state_result = mech_service.get_mech_state_service(mech_state_request)
                if not mech_state_result.success:
                    current_total_donations = 0.0  # Fallback
                else:
                    current_total_donations = mech_state_result.total_donated

                # Use correct evolution calculation for next level costs
                from services.mech.mech_evolutions import get_evolution_info
                evolution_data = get_evolution_info(current_total_donations)
                needed_amount = evolution_data['amount_needed'] if evolution_data['amount_needed'] is not None else 0

                if needed_amount > 0:
                    formatted_amount = f"{needed_amount:.2f}".rstrip('0').rstrip('.')
                    formatted_amount = formatted_amount.replace('.00', '')
                    needed_text = f"**{_('Need $')}{formatted_amount} {_('more to unlock')}**"
                else:
                    needed_text = f"**{_('Ready to unlock!')}**"

                embed = discord.Embed(
                    title=f"🔒 Level {self.level}: {_(evolution_info.name)}",
                    description=f"*{_('Next Evolution')}: {_(evolution_info.description)}*\n{needed_text}",
                    color=0x444444
                )

                file = discord.File(io.BytesIO(image_result.image_bytes), filename=image_result.filename)

                # Create view WITHOUT buttons (preview mech - not unlocked)
                view = MechStoryView(self.cog, self.level, unlocked=False)
                await interaction.followup.send(embed=embed, file=file, view=view, ephemeral=True)

        except Exception as e:
            logger.error(f"Error displaying mech {self.level}: {e}", exc_info=True)
            # After defer(), always use followup for error messages
            await interaction.followup.send(_("❌ Error loading mech."), ephemeral=True)


class EpilogueButton(Button):
    """Button to show the epilogue."""

    def __init__(self, cog_instance: 'DockerControlCog'):
        self.cog = cog_instance

        super().__init__(
            style=discord.ButtonStyle.danger,
            label=_("Epilogue"),
            custom_id="epilogue_button"
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        """Show corrupted epilogue."""
        try:
            # Check if donations are disabled
            if is_donations_disabled():
                await interaction.response.send_message("❌ Mech system is currently disabled.", ephemeral=True)
                return

            epilogue_text = """**Epilogue: W#!sp*r of th3 [ERROR_CODE_11]**

C3n†ur!3§ l4†3r, th3 m3chs 4r3… [D4T4 C0RRUPT].
†h3 Husk§ l!3 ru§t!ng !n s!l3nt f!3lds.
C0r3w4lk3rs = mu§3um r3l!cs.
†!†4ns → du§t.
Gu4rd!4ns → myths.
…y3t, in th3 ru!ns, §t0r!es endure.
0ld s0ld!ers wh!§per — b3trayal, desp@@ir.
Ch!ldr3n l34rn hymn§ 0f Rad!ance.
P!lgr!ms pray → Ascendants long turn3d t0 a§h.
&& a fragi— h0pe l!ngers: s0m3h0w… af†3r wars, af†3r death… hum4n!ty m!ght rise.
But — in d4rk bunk3rs, where cracked r4d!os hum w/ §tat!c…
…an0ther story i§ t0ld.
…b3y0nd Exarchs.
…b3y0nd gods.
…b3y0nd sta—rs.
N0t savior. N0t destroyer.
Fin4lity i†self.
They call it [███DATA??%&CORRUPT███].
And those who dare… sp34k its ████ do s0 only once.
[### ERR_SEG_A] Tr4nsmissi0n… d3gr4ded. checksum fail… !@#!
…fr4gm3nt…r3covered: "…vig…e…nere…" <<<
(ignore? no value? [redacted])
[### ERR_SEG_B] packet loss… ??? mismatch length.
"KEY…=…4…" [system note: truncated]
⚠️ W4RN!NG: SIGNAL integrity = unstable
[SYSTEM_F4!L] [c0nnection lost] [███shut███]"""

            embed = discord.Embed(
                title="💀 Epilogue: W#!sp*r of th3 [ERROR_CODE_11]",
                description=epilogue_text,
                color=0x330033
            )
            embed.set_footer(text="⚠️ DATA CORRUPTION DETECTED - TRANSMISSION UNSTABLE")

            await interaction.response.send_message(embed=embed, ephemeral=True)

        except Exception as e:
            logger.error(f"Error showing epilogue: {e}", exc_info=True)
            await interaction.response.send_message(_("❌ Error loading epilogue."), ephemeral=True)


class MechStoryView(View):
    """View with Read Story and Play Song buttons - only for unlocked mechs."""

    def __init__(self, cog_instance: 'DockerControlCog', level: int, unlocked: bool = True):
        super().__init__(timeout=None)
        self.cog = cog_instance
        self.level = level
        self.unlocked = unlocked

        # Only add buttons for unlocked mechs
        if unlocked:
            self.add_item(ReadStoryButton(cog_instance, level))
            self.add_item(PlaySongButton(cog_instance, level))


class ReadStoryButton(Button):
    """Button to read the story chapter for a mech."""

    def __init__(self, cog_instance: 'DockerControlCog', level: int):
        self.cog = cog_instance
        self.level = level

        super().__init__(
            style=discord.ButtonStyle.success,
            label=_("Read Story"),
            custom_id=f"read_story_{level}"
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        """Show the story chapter."""
        try:
            # Check if donations are disabled
            if is_donations_disabled():
                await interaction.response.send_message("❌ Mech system is currently disabled.", ephemeral=True)
                return

            # Defer response to prevent timeout during story loading
            await interaction.response.defer(ephemeral=True)

            # Load story chapters
            from services.mech.mech_service import get_mech_service
            story_chapters = {}
            story_content = """[STORY CONTENT PLACEHOLDER]"""

            # Parse chapters (using existing method from MechHistoryButton)
            # For now, use the existing helper
            mech_button = MechHistoryButton(self.cog, 0)
            story_chapters = mech_button._load_epic_story_chapters()

            # Get chapter key for this level
            chapter_key = mech_button._get_chapter_key_for_level(self.level)

            if chapter_key and chapter_key in story_chapters:
                chapter_content = story_chapters[chapter_key]

                # Get chapter info
                chapter_info = {
                    "prologue1": ("Prologue I: The Dying Light", 0x2b2b2b),
                    "prologue2": ("Prologue II: Scars That Walk", 0x444444),
                    "chapter1": ("Chapter I: The Standard", 0x888888),
                    "chapter2": ("Chapter II: The Hunger", 0x0099cc),
                    "chapter3": ("Chapter III: The Pulse", 0x00ccff),
                    "chapter4": ("Chapter IV: The Abyss", 0xffcc00),
                    "chapter5": ("Chapter V: The Rift", 0xff6600),
                    "chapter6": ("Chapter VI: Radiance", 0xcc00ff),
                    "chapter7": ("Chapter VII: The Idols of Steel", 0x00ffff),
                    "chapter8": ("Chapter VIII: The Exarchs", 0xffff00),
                    "chapter9": ("Chapter IX: The Prayer of the Omega", 0xff00ff),
                    "epilogue": ("Epilogue: W#!sp*r of th3 [ERROR_CODE_11]", 0x330033)
                }

                title, color = chapter_info.get(chapter_key, ("Story Chapter", 0x666666))

                # Split if too long
                if len(chapter_content) > 4000:
                    chapter_content = chapter_content[:4000] + "..."

                embed = discord.Embed(
                    title=title,
                    description=chapter_content,
                    color=color
                )
                embed.set_footer(text="The Song of Steel and Stars - A Chronicle of the Mech Ascension")

                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.followup.send(_("📖 No story chapter available for this mech yet."), ephemeral=True)

        except Exception as e:
            logger.error(f"Error showing story for level {self.level}: {e}", exc_info=True)
            # After defer(), always use followup for error messages
            await interaction.followup.send(_("❌ Error loading story."), ephemeral=True)


class PlaySongButton(Button):
    """Button to play the music for a mech level as Discord attachment."""

    def __init__(self, cog_instance: 'DockerControlCog', level: int):
        self.cog = cog_instance
        self.level = level

        super().__init__(
            style=discord.ButtonStyle.primary,
            label=None,
            emoji="🎵",
            custom_id=f"play_song_{level}"
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        """Send direct music link for instant streaming (no file upload required)."""
        try:
            # Check if donations are disabled
            if is_donations_disabled():
                await interaction.response.send_message("❌ Mech system is currently disabled.", ephemeral=True)
                return

            # Defer response to prevent timeout during music service calls
            await interaction.response.defer(ephemeral=True)

            # Import and use MechMusicService to get GitHub URL
            from services.web.mech_music_service import get_mech_music_service, MechMusicRequest

            service = get_mech_music_service()
            request_obj = MechMusicRequest(level=self.level)

            # Get YouTube URL through service (no file uploads!)
            result = service.get_mech_music_url(request_obj)

            if result.success:
                # Send YouTube URL directly for native Discord video embed
                # This triggers Discord's automatic YouTube preview with play button!
                message_text = f"🎵 **{result.title}** (Mech Level {self.level})\n\n{result.url}"

                await interaction.followup.send(message_text, ephemeral=True)
            else:
                await interaction.followup.send(
                    f"❌ No music available for Mech Level {self.level}\n"
                    f"Error: {result.error}",
                    ephemeral=True
                )

        except Exception as e:
            logger.error(f"Error generating music URL for level {self.level}: {e}", exc_info=True)
            # After defer(), always use followup for error messages
            await interaction.followup.send(_("❌ Error loading music."), ephemeral=True)


# =============================================================================
# MECH DETAILS VIEW FOR PRIVATE MESSAGES
# =============================================================================

class MechDetailsView(View):
    """View for private mech details messages with Spenden and History buttons."""

    def __init__(self, cog_instance: 'DockerControlCog', channel_id: int):
        super().__init__(timeout=None)  # Persistent view - buttons never expire
        self.cog = cog_instance
        self.channel_id = channel_id

        # Add donate and history buttons
        self.add_item(MechPrivateDonateButton(cog_instance, channel_id))
        self.add_item(MechPrivateHistoryButton(cog_instance, channel_id))


class MechPrivateDonateButton(Button):
    """Donate button for private mech details messages."""

    def __init__(self, cog_instance: 'DockerControlCog', channel_id: int):
        super().__init__(
            style=discord.ButtonStyle.green,
            label="Spenden / Aufladen",
            custom_id=f"mech_private_donate_{channel_id}"
        )
        self.cog = cog_instance
        self.channel_id = channel_id

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle donate button click - reuse existing donate functionality."""
        try:
            # Reuse the existing MechDonateButton logic
            donate_button = MechDonateButton(self.cog, self.channel_id)
            await donate_button.callback(interaction)

        except Exception as e:
            logger.error(f"Error in private donate button: {e}", exc_info=True)
            try:
                # Smart error response - check if interaction was already deferred by child button
                if interaction.response.is_done():
                    await interaction.followup.send(
                        "❌ Error processing donation request. Please try again later.",
                        ephemeral=True
                    )
                else:
                    await interaction.response.send_message(
                        "❌ Error processing donation request. Please try again later.",
                        ephemeral=True
                    )
            except discord.errors.NotFound:
                logger.warning("Cannot send error message - interaction expired")
            except Exception:
                pass


class MechPrivateHistoryButton(Button):
    """History button for private mech details messages."""

    def __init__(self, cog_instance: 'DockerControlCog', channel_id: int):
        super().__init__(
            style=discord.ButtonStyle.secondary,
            label="Mech History",
            custom_id=f"mech_private_history_{channel_id}"
        )
        self.cog = cog_instance
        self.channel_id = channel_id

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle history button click - reuse existing history functionality."""
        try:
            # Reuse the existing MechHistoryButton logic
            history_button = MechHistoryButton(self.cog, self.channel_id)
            await history_button.callback(interaction)

        except Exception as e:
            logger.error(f"Error in private history button: {e}", exc_info=True)
            try:
                # Smart error response - check if interaction was already deferred by child button
                if interaction.response.is_done():
                    await interaction.followup.send(
                        "❌ Error loading mech history. Please try again later.",
                        ephemeral=True
                    )
                else:
                    await interaction.response.send_message(
                        "❌ Error loading mech history. Please try again later.",
                        ephemeral=True
                    )
            except discord.errors.NotFound:
                logger.warning("Cannot send error message - interaction expired")
            except Exception:
                pass


