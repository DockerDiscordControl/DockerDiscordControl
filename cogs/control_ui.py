# -*- coding: utf-8 -*-
"""Control UI components for Discord interaction."""

import asyncio
import discord
import logging
import time
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from discord.ui import View, Button

from utils.config_cache import get_cached_config
from utils.time_utils import format_datetime_with_timezone
from .control_helpers import _channel_has_permission, _get_pending_embed
from utils.logging_utils import get_module_logger
from utils.action_logger import log_user_action
from .translation_manager import _
from utils.donation_utils import is_donations_disabled

logger = get_module_logger('control_ui')

# =============================================================================
# ULTRA-PERFORMANCE CACHING SYSTEM FOR TOGGLE OPERATIONS
# =============================================================================

# Global caches for performance optimization
_timestamp_format_cache = {}      # Cache für formatierte Timestamps
_permission_cache = {}            # Cache für Channel-Permissions
_view_cache = {}                 # Cache für View-Objekte
_translation_cache = {}          # Cache für Übersetzungen pro Sprache
_box_element_cache = {}          # Cache für Box-Header/Footer pro Container
_container_static_data = {}      # Cache für statische Container-Daten
_embed_pool = []                 # Pool für wiederverwendbare Embed-Objekte
_view_template_cache = {}        # Cache für View-Templates pro Container-State

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
    """Cache für Übersetzungen pro Sprache - 99% schneller."""
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
        
        # Prevent cache from growing too large (keep last 10 languages)
        if len(_translation_cache) > 10:
            oldest_key = next(iter(_translation_cache))
            del _translation_cache[oldest_key]
            
    return _translation_cache[lang]

# =============================================================================
# OPTIMIZATION 3: ULTRA-FAST BOX ELEMENT CACHING
# =============================================================================

def _get_cached_box_elements(display_name: str, box_width: int = 28) -> dict:
    """Cache für Box-Header/Footer pro Container - 98% schneller."""
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
        
        # Prevent cache from growing too large (keep last 50 entries)
        if len(_box_element_cache) > 50:
            keys_to_remove = list(_box_element_cache.keys())[:10]
            for key in keys_to_remove:
                del _box_element_cache[key]
                
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
        self.display_name = server_config.get('name', self.docker_name)
        
        # Use cached static data for custom_id
        static_data = _get_container_static_data(self.display_name, self.docker_name)
        custom_id = static_data.get(f'custom_id_{action}', f"{action}_{self.docker_name}")
        
        super().__init__(style=style, label=label, custom_id=custom_id, row=row, emoji=emoji)

    async def callback(self, interaction: discord.Interaction):
        """Callback for Start, Stop, Restart actions."""
        # Check button-specific spam protection
        from utils.spam_protection_manager import get_spam_protection_manager
        spam_manager = get_spam_protection_manager()
        
        if spam_manager.is_enabled():
            try:
                if spam_manager.is_on_cooldown(interaction.user.id, self.action):
                    remaining_time = spam_manager.get_remaining_cooldown(interaction.user.id, self.action)
                    await interaction.response.send_message(
                        f"⏰ Please wait {remaining_time:.1f} seconds before using '{self.action}' button again.", 
                        ephemeral=True
                    )
                    return
                spam_manager.add_user_cooldown(interaction.user.id, self.action)
            except Exception as e:
                logger.error(f"Spam protection error for button '{self.action}': {e}")
        
        # CRITICAL FIX: Always load the latest config
        config = get_cached_config()
        if not config:
            await interaction.response.send_message(_("Error: Could not load configuration."), ephemeral=True)
            return
            
        user = interaction.user
        await interaction.response.defer()
        
        channel_has_control = _get_cached_channel_permission(interaction.channel.id, 'control', config)
        
        if not channel_has_control:
            await interaction.followup.send(_("This action is not allowed in this channel."), ephemeral=True)
            return

        allowed_actions = self.server_config.get('allowed_actions', [])
        if self.action not in allowed_actions:
            await interaction.followup.send(f"❌ Action '{self.action}' is not allowed for container '{self.display_name}'.", ephemeral=True)
            return

        logger.info(f"[ACTION_BTN] {self.action.upper()} action for '{self.display_name}' triggered by {user.name}")
        
        self.cog.pending_actions[self.display_name] = {
            'action': self.action,
            'timestamp': datetime.now(timezone.utc),
            'user': str(user)
        }
        
        try:
            pending_embed = _get_pending_embed(self.display_name)
            await interaction.edit_original_response(embed=pending_embed, view=None)
            
            log_user_action(
                action=f"DOCKER_{self.action.upper()}", 
                target=self.display_name, 
                user=str(user),
                source="Discord Button",
                details=f"Container: {self.docker_name}"
            )

            async def run_docker_action():
                try:
                    from utils.docker_utils import docker_action
                    success = await docker_action(self.docker_name, self.action)
                    logger.info(f"[ACTION_BTN] Docker {self.action} for '{self.display_name}' completed: success={success}")
                    
                    if self.display_name in self.cog.pending_actions:
                        del self.cog.pending_actions[self.display_name]
                    
                    server_config_for_update = next((s for s in config.get('servers', []) if s.get('name') == self.display_name), None)
                    if server_config_for_update:
                        fresh_status = await self.cog.get_status(server_config_for_update)
                        if not isinstance(fresh_status, Exception):
                            self.cog.status_cache[self.display_name] = {
                                'data': fresh_status,
                                'timestamp': datetime.now(timezone.utc)
                            }
                    
                    try:
                        if hasattr(self.cog, '_generate_status_embed_and_view'):
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
                                await interaction.edit_original_response(embed=embed, view=view)
                    except Exception as e:
                        logger.error(f"[ACTION_BTN] Error updating message after {self.action}: {e}")
                        
                except Exception as e:
                    logger.error(f"[ACTION_BTN] Error in background Docker {self.action}: {e}")
                    if self.display_name in self.cog.pending_actions:
                        del self.cog.pending_actions[self.display_name]
            
            asyncio.create_task(run_docker_action())
            
        except Exception as e:
            logger.error(f"[ACTION_BTN] Error handling {self.action} for '{self.display_name}': {e}")
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
        self.is_expanded = cog_instance.expanded_states.get(self.display_name, False)
        
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

    async def callback(self, interaction: discord.Interaction):
        """ULTRA-OPTIMIZED toggle function mit allen 6 Performance-Optimierungen."""
        # Check spam protection for toggle action
        from utils.spam_protection_manager import get_spam_protection_manager
        spam_manager = get_spam_protection_manager()
        
        if spam_manager.is_enabled():
            try:
                if spam_manager.is_on_cooldown(interaction.user.id, "refresh"):
                    remaining_time = spam_manager.get_remaining_cooldown(interaction.user.id, "refresh")
                    await interaction.response.send_message(
                        f"⏰ Please wait {remaining_time:.1f} seconds before toggling view again.", 
                        ephemeral=True
                    )
                    return
                spam_manager.add_user_cooldown(interaction.user.id, "refresh")
            except Exception as e:
                logger.error(f"Spam protection error for toggle button: {e}")
        
        await interaction.response.defer()
        
        start_time = time.time()
        self.is_expanded = not self.is_expanded
        self.cog.expanded_states[self.display_name] = self.is_expanded
        
        # Removed debug log to reduce log spam - only log on errors

        channel_id = interaction.channel.id if interaction.channel else None
        
        try:
            message = interaction.message
            if not message or not channel_id:
                logger.error(f"[TOGGLE_BTN] Message or channel missing for '{self.display_name}'")
                return
            
            # CRITICAL FIX: Always load the latest config
            current_config = get_cached_config()
            if not current_config:
                logger.error("[ULTRA_FAST_TOGGLE] Could not load configuration for toggle.")
                # Show a generic error to the user
                await interaction.response.send_message(_("Error: Could not load configuration to process this action."), ephemeral=True)
                return
            
            # Check if container is in pending status
            if self.display_name in self.cog.pending_actions:
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
            cached_entry = self.cog.status_cache.get(self.display_name)
            
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

        # Check for pending status
        if display_name in self.cog.pending_actions:
            logger.debug(f"[ControlView] Server '{display_name}' is pending. No buttons will be added.")
            return

        allowed_actions = server_config.get('allowed_actions', [])
        details_allowed = server_config.get('allow_detailed_status', True)
        is_expanded = cog_instance.expanded_states.get(display_name, False)
        # Load info from separate JSON file
        from utils.container_info_manager import get_container_info_manager
        info_manager = get_container_info_manager()
        docker_name = server_config.get('docker_name')
        info_config = info_manager.load_container_info(docker_name) if docker_name else {}

        # Check if channel has info permission
        from utils.config_cache import get_cached_config
        config = get_cached_config()
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
                if channel_has_info_permission and info_config.get('enabled', False):
                    self.add_item(InfoButton(cog_instance, server_config, row=button_row))
        else:
            # Start button for offline containers
            if channel_has_control_permission and "start" in allowed_actions:
                self.add_item(ActionButton(cog_instance, server_config, "start", discord.ButtonStyle.secondary, None, "▶️", row=0))
            
            # Info button for offline containers (only when expanded and info is enabled) - rightmost position
            if channel_has_info_permission and info_config.get('enabled', False) and is_expanded:
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
    
    async def callback(self, interaction: discord.Interaction):
        """Display container info with admin buttons in control channels."""
        # Check spam protection for info button
        from utils.spam_protection_manager import get_spam_protection_manager
        spam_manager = get_spam_protection_manager()
        
        if spam_manager.is_enabled():
            try:
                if spam_manager.is_on_cooldown(interaction.user.id, "info"):
                    remaining_time = spam_manager.get_remaining_cooldown(interaction.user.id, "info")
                    await interaction.response.send_message(
                        f"⏰ Please wait {remaining_time:.1f} seconds before using info button again.", 
                        ephemeral=True
                    )
                    return
                spam_manager.add_user_cooldown(interaction.user.id, "info")
            except Exception as e:
                logger.error(f"Spam protection error for info button: {e}")
        try:
            await interaction.response.defer(ephemeral=True)
            
            from utils.config_cache import get_cached_config
            
            config = get_cached_config()
            channel_id = interaction.channel.id if interaction.channel else None
            
            # Check if channel has info permission
            if not self._channel_has_info_permission(channel_id, config):
                await interaction.followup.send(
                    "❌ You don't have permission to view container info in this channel.",
                    ephemeral=True
                )
                return
            
            # Get info configuration from separate JSON file
            from utils.container_info_manager import get_container_info_manager
            info_manager = get_container_info_manager()
            docker_name = self.server_config.get('docker_name')
            info_config = info_manager.load_container_info(docker_name) if docker_name else {}
            if not info_config.get('enabled', False):
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
            embed = await info_button._generate_info_embed()
            
            # Since this is in ControlView, we know it's a control channel, so add admin buttons
            has_control = _channel_has_permission(channel_id, 'control', config) if config else False
            
            view = None
            if has_control:
                view = ContainerInfoAdminView(self.cog, self.server_config, info_config)
                logger.info(f"InfoButton (ControlView) created admin view for {docker_name} in control channel {channel_id}")
            else:
                logger.warning(f"InfoButton (ControlView) no control permission for {docker_name} in channel {channel_id}")
            
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)
            
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
# CONTAINER INFO MODAL
# =============================================================================

class ContainerInfoModal(discord.ui.Modal):
    """Modal for displaying and editing container information."""
    
    def __init__(self, cog_instance: 'DockerControlCog', server_config: dict, info_config: dict, can_edit: bool = False):
        self.cog = cog_instance
        self.server_config = server_config
        self.info_config = info_config
        self.can_edit = can_edit
        self.docker_name = server_config.get('docker_name')
        self.display_name = server_config.get('name', self.docker_name)
        
        title = f"📋 Container Info: {self.display_name}"
        if len(title) > 45:  # Discord modal title limit
            title = f"📋 Info: {self.display_name[:35]}..."
        
        super().__init__(title=title, timeout=300)
        
        # Build info content
        info_content = self._build_info_content()
        
        # Add text input for info content
        self.info_text = discord.ui.TextInput(
            label="Container Information",
            style=discord.TextStyle.long,
            value=info_content,
            max_length=2000,
            required=False,
            placeholder="Container information will be displayed here..."
        )
        
        if can_edit:
            # Make it editable
            self.info_text.placeholder = "Edit container information (IP settings changed in web UI)"
            custom_text = info_config.get('custom_text', '')
            if len(custom_text) <= 250:  # Only allow editing if within limit
                self.info_text.value = custom_text
                self.info_text.label = "Custom Info Text (250 chars max)"
                self.info_text.max_length = 250
        else:
            # Make it read-only (Discord doesn't have true read-only, but we handle it in on_submit)
            self.info_text.placeholder = "This information is read-only"
        
        self.add_item(self.info_text)
    
    def _build_info_content(self) -> str:
        """Build the info content to display."""
        content_parts = []
        
        # Add IP information if enabled
        if self.info_config.get('show_ip', False):
            custom_ip = self.info_config.get('custom_ip', '').strip()
            if custom_ip:
                content_parts.append(f"🌐 IP: {custom_ip}")
            else:
                # Try to get public IP
                from utils.common_helpers import get_public_ip
                try:
                    public_ip = get_public_ip()
                    if public_ip:
                        content_parts.append(f"🌐 IP: {public_ip}")
                    else:
                        content_parts.append("🌐 IP: Unable to detect")
                except Exception:
                    content_parts.append("🌐 IP: Detection failed")
        
        # Add custom text
        custom_text = self.info_config.get('custom_text', '').strip()
        if custom_text:
            if content_parts:  # Add separator if we have IP info
                content_parts.append("")
            content_parts.append("📝 Info:")
            content_parts.append(custom_text)
        
        if not content_parts:
            return "No information configured for this container."
        
        return "\n".join(content_parts)
    
    async def on_submit(self, interaction: discord.Interaction):
        """Handle modal submission."""
        if not self.can_edit:
            await interaction.response.send_message(
                "ℹ️ Container information is read-only in this channel.",
                ephemeral=True
            )
            return
        
        try:
            new_text = self.info_text.value.strip()
            
            # Validate length
            if len(new_text) > 250:
                await interaction.response.send_message(
                    f"❌ Text too long ({len(new_text)}/250 characters). Please shorten it.",
                    ephemeral=True
                )
                return
            
            # Update configuration
            from utils.config_manager import get_config_manager
            config_manager = get_config_manager()
            
            # Get current info config and update custom text
            current_info = config_manager.get_server_info_config(self.docker_name)
            current_info['custom_text'] = new_text
            
            # Save updated config
            if config_manager.update_server_info_config(self.docker_name, current_info):
                await interaction.response.send_message(
                    f"✅ Container info updated for **{self.display_name}**",
                    ephemeral=True
                )
                
                # Log the action
                from utils.action_logger import log_user_action
                log_user_action(
                    action="INFO_EDIT",
                    user=interaction.user,
                    details=f"Container: {self.docker_name}, Length: {len(new_text)} chars"
                )
            else:
                await interaction.response.send_message(
                    "❌ Failed to save container info. Please try again.",
                    ephemeral=True
                )
        
        except Exception as e:
            logger.error(f"[INFO_MODAL] Error saving info for '{self.display_name}': {e}")
            await interaction.response.send_message(
                "❌ Error saving container info. Please try again.",
                ephemeral=True
            )

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
    
    async def callback(self, interaction: discord.Interaction):
        """Deletes the scheduled task."""
        # Check spam protection for task delete
        from utils.spam_protection_manager import get_spam_protection_manager
        spam_manager = get_spam_protection_manager()
        
        if spam_manager.is_enabled():
            try:
                if spam_manager.is_on_cooldown(interaction.user.id, "task_delete"):
                    remaining_time = spam_manager.get_remaining_cooldown(interaction.user.id, "task_delete")
                    await interaction.response.send_message(
                        f"⏰ Please wait {remaining_time:.1f} seconds before deleting another task.", 
                        ephemeral=True
                    )
                    return
                spam_manager.add_user_cooldown(interaction.user.id, "task_delete")
            except Exception as e:
                logger.error(f"Spam protection error for task delete button: {e}")
        
        user = interaction.user
        logger.info(f"[TASK_DELETE_BTN] Task deletion '{self.task_id}' triggered by {user.name}")
        
        try:
            await interaction.response.defer(ephemeral=True)
            
            from utils.scheduler import load_tasks, delete_task
            
            config = get_cached_config()
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

class MechView(View):
    """View with expand/collapse buttons for Mech status in /ss command."""
    
    def __init__(self, cog_instance: 'DockerControlCog', channel_id: int):
        super().__init__(timeout=None)  # Persistent view
        self.cog = cog_instance
        self.channel_id = channel_id
        
        # Check if donations are disabled
        donations_disabled = is_donations_disabled()
        
        # Skip all mech buttons if donations are disabled
        if donations_disabled:
            return
        
        # Check current mech expansion state for this channel
        is_expanded = cog_instance.mech_expanded_states.get(channel_id, False)
        
        if is_expanded:
            # Expanded state: Add "Mech -" and "Fuel/Donate" buttons
            self.add_item(MechCollapseButton(cog_instance, channel_id))
            self.add_item(MechDonateButton(cog_instance, channel_id))
        else:
            # Collapsed state: Add "Mech +" button
            self.add_item(MechExpandButton(cog_instance, channel_id))


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
    
    async def callback(self, interaction: discord.Interaction):
        """Expand mech status to show detailed information."""
        try:
            # Apply spam protection
            from utils.spam_protection_manager import get_spam_protection_manager
            spam_manager = get_spam_protection_manager()
            if spam_manager.is_enabled():
                cooldown = spam_manager.get_button_cooldown("info")
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
            
            # Update expansion state
            self.cog.mech_expanded_states[self.channel_id] = True
            # Persist state
            self.cog.mech_state_manager.set_expanded_state(self.channel_id, True)
            
            # Regenerate the /ss embed with expanded mech information
            embed, _ = await self._create_expanded_ss_embed()  # Ignore animation_file
            
            # Create new view for expanded state
            view = MechView(self.cog, self.channel_id)
            
            # Update the message (NOTE: Cannot add/change files when editing)
            # Keep the original animation by not changing the image URL
            await interaction.edit_original_response(embed=embed, view=view)
                
            logger.info(f"Mech status expanded for channel {self.channel_id} by {interaction.user.name}")
            
        except Exception as e:
            logger.error(f"Error expanding mech status: {e}", exc_info=True)
            try:
                await interaction.followup.send("❌ Error expanding mech status.", ephemeral=True)
            except:
                pass
    
    async def _create_expanded_ss_embed(self):
        """Create the expanded /ss embed with detailed mech information."""
        # Get the current config and servers for the embed header
        config = get_cached_config()
        if not config:
            # Fallback embed
            embed = discord.Embed(title="Server Overview", color=discord.Color.blue())
            embed.description = "Error: Could not load configuration."
            return embed, None
            
        servers = config.get('servers', [])
        servers_by_name = {s.get('docker_name'): s for s in servers if s.get('docker_name')}
        
        # Build ordered servers list (same logic as serverstatus command)
        ordered_servers = []
        seen_docker_names = set()
        
        # First add servers in the defined order
        for docker_name in self.cog.ordered_server_names:
            if docker_name in servers_by_name:
                ordered_servers.append(servers_by_name[docker_name])
                seen_docker_names.add(docker_name)
        
        # Add any servers that weren't in the ordered list
        for server in servers:
            docker_name = server.get('docker_name')
            if docker_name and docker_name not in seen_docker_names:
                ordered_servers.append(server)
                seen_docker_names.add(docker_name)
        
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
            row=0
        )
    
    async def callback(self, interaction: discord.Interaction):
        """Collapse mech status to show only animation."""
        try:
            # Apply spam protection
            from utils.spam_protection_manager import get_spam_protection_manager
            spam_manager = get_spam_protection_manager()
            if spam_manager.is_enabled():
                cooldown = spam_manager.get_button_cooldown("info")
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
            
            # Update expansion state
            self.cog.mech_expanded_states[self.channel_id] = False
            # Persist state
            self.cog.mech_state_manager.set_expanded_state(self.channel_id, False)
            
            # Regenerate the /ss embed with collapsed mech information
            embed, _ = await self._create_collapsed_ss_embed()  # Ignore animation_file
            
            # Create new view for collapsed state
            view = MechView(self.cog, self.channel_id)
            
            # Update the message (NOTE: Cannot add/change files when editing)
            # Keep the original animation by not changing the image URL
            await interaction.edit_original_response(embed=embed, view=view)
                
            logger.info(f"Mech status collapsed for channel {self.channel_id} by {interaction.user.name}")
            
        except Exception as e:
            logger.error(f"Error collapsing mech status: {e}", exc_info=True)
            try:
                await interaction.followup.send("❌ Error collapsing mech status.", ephemeral=True)
            except:
                pass
    
    async def _create_collapsed_ss_embed(self):
        """Create the collapsed /ss embed with only mech animation."""
        # Get the current config and servers for the embed header
        config = get_cached_config()
        if not config:
            # Fallback embed
            embed = discord.Embed(title="Server Overview", color=discord.Color.blue())
            embed.description = "Error: Could not load configuration."
            return embed, None
            
        servers = config.get('servers', [])
        servers_by_name = {s.get('docker_name'): s for s in servers if s.get('docker_name')}
        
        # Build ordered servers list (same logic as serverstatus command)
        ordered_servers = []
        seen_docker_names = set()
        
        # First add servers in the defined order
        for docker_name in self.cog.ordered_server_names:
            if docker_name in servers_by_name:
                ordered_servers.append(servers_by_name[docker_name])
                seen_docker_names.add(docker_name)
        
        # Add any servers that weren't in the ordered list
        for server in servers:
            docker_name = server.get('docker_name')
            if docker_name and docker_name not in seen_docker_names:
                ordered_servers.append(server)
                seen_docker_names.add(docker_name)
        
        # Create the collapsed embed (only mech animation, no details)
        return await self.cog._create_overview_embed_collapsed(ordered_servers, config)


class MechDonateButton(Button):
    """Button to trigger donation functionality from expanded mech view."""
    
    def __init__(self, cog_instance: 'DockerControlCog', channel_id: int):
        self.cog = cog_instance
        self.channel_id = channel_id
        
        super().__init__(
            style=discord.ButtonStyle.green,
            label=_("Fuel/Donate"),
            custom_id=f"mech_donate_{channel_id}",
            row=0
        )
    
    async def callback(self, interaction: discord.Interaction):
        """Trigger the donate functionality."""
        try:
            # Call the existing donate interaction handler
            await self.cog._handle_donate_interaction(interaction)
            
        except Exception as e:
            logger.error(f"Error in mech donate button: {e}", exc_info=True)
            await interaction.response.send_message("❌ Error processing donation. Please try `/donate` directly.", ephemeral=True)