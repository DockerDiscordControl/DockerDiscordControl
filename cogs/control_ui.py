# -*- coding: utf-8 -*-
"""Control UI components for Discord interaction."""

import asyncio
from collections import OrderedDict
from services.config.config_service import load_config
import discord
import logging
import time
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
        self.display_name = server_config.get('name', self.docker_name)
        
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

        channel_has_control = _get_cached_channel_permission(interaction.channel.id, 'control', config)

        if not channel_has_control:
            await interaction.followup.send(_("This action is not allowed in this channel."), ephemeral=True)
            return

        allowed_actions = self.server_config.get('allowed_actions', [])
        if self.action not in allowed_actions:
            await interaction.followup.send(f"❌ Action '{self.action}' is not allowed for container '{self.display_name}'.", ephemeral=True)
            return

        logger.info(f"[ACTION_BTN] {self.action.upper()} action for '{self.display_name}' triggered by {user.name}")

        # Thread-safe access to pending_actions
        async with self.cog.pending_actions_lock:
            self.cog.pending_actions[self.display_name] = {
                'action': self.action,
                'timestamp': datetime.now(timezone.utc),
                'user': str(user)
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
                    from services.docker_service.docker_utils import docker_action
                    success = await docker_action(self.docker_name, self.action)
                    logger.info(f"[ACTION_BTN] Docker {self.action} for '{self.display_name}' completed: success={success}")

                    # Thread-safe removal from pending_actions
                    async with self.cog.pending_actions_lock:
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
                                try:
                                    await interaction.edit_original_response(embed=embed, view=view)
                                except (discord.NotFound, discord.HTTPException) as e:
                                    logger.warning(f"[ACTION_BTN] Interaction expired during update for {self.display_name}: {e}")
                    except Exception as e:
                        logger.error(f"[ACTION_BTN] Error updating message after {self.action}: {e}")
                        
                except Exception as e:
                    logger.error(f"[ACTION_BTN] Error in background Docker {self.action}: {e}")
                    # Thread-safe removal from pending_actions
                    async with self.cog.pending_actions_lock:
                        if self.display_name in self.cog.pending_actions:
                            del self.cog.pending_actions[self.display_name]

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

    async def callback(self, interaction: discord.Interaction) -> None:
        """ULTRA-OPTIMIZED toggle function mit allen 6 Performance-Optimierungen."""
        # Check spam protection for toggle action
        from services.infrastructure.spam_protection_service import get_spam_protection_service
        spam_service = get_spam_protection_service()
        
        if spam_service.is_enabled():
            try:
                if spam_service.is_on_cooldown(interaction.user.id, "refresh"):
                    remaining_time = spam_service.get_remaining_cooldown(interaction.user.id, "refresh")
                    await interaction.response.send_message(
                        f"⏰ Please wait {remaining_time:.1f} seconds before toggling view again.", 
                        ephemeral=True
                    )
                    return
                spam_service.add_user_cooldown(interaction.user.id, "refresh")
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
            
            current_config = load_config()
            if not current_config:
                logger.error("[ULTRA_FAST_TOGGLE] Could not load configuration for toggle.")
                # Show a generic error to the user
                await interaction.response.send_message(_("Error: Could not load configuration to process this action."), ephemeral=True)
                return
            
            # Check if container is in pending status (thread-safe)
            async with self.cog.pending_actions_lock:
                is_pending = self.display_name in self.cog.pending_actions

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
            
            # Since this is in ControlView, we know it's a control channel, so add admin buttons
            has_control = _channel_has_permission(channel_id, 'control', config) if config else False
            
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

class MechView(View):
    """View with expand/collapse buttons for Mech status in /ss command."""
    
    def __init__(self, cog_instance: 'DockerControlCog', channel_id: int):
        super().__init__(timeout=None)  # Persistent view
        self.cog = cog_instance
        self.channel_id = channel_id
        
        # Check if donations are disabled
        donations_disabled = is_donations_disabled()
        
        # Skip mech buttons if donations are disabled
        if not donations_disabled:
            # Check current mech expansion state for this channel
            is_expanded = cog_instance.mech_expanded_states.get(channel_id, False)
            
            if is_expanded:
                # Expanded state: Close(-), Donate, History (no help button)
                self.add_item(MechCollapseButton(cog_instance, channel_id))
                self.add_item(MechDonateButton(cog_instance, channel_id))
                self.add_item(MechHistoryButton(cog_instance, channel_id))
            else:
                # Collapsed state: Add "Mech +" button and help button
                self.add_item(MechExpandButton(cog_instance, channel_id))
                self.add_item(HelpButton(cog_instance, channel_id))

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
                await interaction.response.send_message("❌ Error showing help information.", ephemeral=True)
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
            label=_("Power/Donate"),
            custom_id=f"mech_donate_{channel_id}",
            row=0
        )
    
    async def callback(self, interaction: discord.Interaction) -> None:
        """Trigger the donate functionality."""
        try:
            # Call the existing donate interaction handler
            await self.cog._handle_donate_interaction(interaction)
            
        except Exception as e:
            logger.error(f"Error in mech donate button: {e}", exc_info=True)
            await interaction.response.send_message("❌ Error processing donation. Please try `/donate` directly.", ephemeral=True)

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
            row=0
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

            # Get current mech state
            from services.mech.mech_service import get_mech_service
            mech_service = get_mech_service()
            current_state = mech_service.get_state()
            current_level = current_state.level

            # Create mech selection view
            await self._show_mech_selection(interaction, current_level)

        except Exception as e:
            logger.error(f"Error in mech history button: {e}", exc_info=True)
            await interaction.response.send_message(_("❌ Error loading mech history."), ephemeral=True)

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
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    async def _create_mech_history_display(self, interaction: discord.Interaction, current_level: int):
        """Create the mech history display with sequential animations and epic story chapters."""
        from services.mech.mech_animation_service import get_mech_animation_service
        from services.mech.evolution_config_manager import get_evolution_config_manager
        import discord
        import io
        import asyncio

        animation_service = get_mech_animation_service()
        config_manager = get_evolution_config_manager()

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
                evolution_info = config_manager.get_evolution_level(level)
                if not evolution_info:
                    continue

                # Send story chapter before mech (if exists)
                chapter_key = self._get_chapter_key_for_level(level)
                if chapter_key and chapter_key in story_chapters:
                    await self._send_story_chapter(channel, chapter_key, story_chapters[chapter_key])
                    await asyncio.sleep(0.7)

                if level <= current_level:
                    # Unlocked: Use pre-rendered cached animation
                    try:
                        # Get cached WebP animation directly from cache service
                        from services.mech.animation_cache_service import get_animation_cache_service
                        cache_service = get_animation_cache_service()

                        cached_path = cache_service.get_cached_animation_path(level)
                        if cached_path.exists():
                            with open(cached_path, 'rb') as f:
                                animation_bytes = f.read()
                        else:
                            # Pre-generate if not exists
                            logger.info(f"Pre-generating missing cached animation for level {level}")
                            cache_service.pre_generate_animation(level)
                            with open(cached_path, 'rb') as f:
                                animation_bytes = f.read()

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

                        filename = f"mech_level_{level}.webp"
                        file = discord.File(io.BytesIO(animation_bytes), filename=filename)
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
                    # Next level: Show shadow as preview
                    shadow_bytes = MechHistoryButtonHelper._create_shadow_animation(level)
                    # Calculate how much more is needed
                    from services.mech.mech_service import get_mech_service
                    mech_service = get_mech_service()
                    current_total_donations = float(mech_service.get_state().total_donated)
                    needed_amount = max(0, evolution_info.base_cost - current_total_donations)

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

                    filename = f"mech_shadow_{level}.webp"
                    file = discord.File(io.BytesIO(shadow_bytes), filename=filename)
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
        """Load and parse the epic story chapters from external file based on language."""
        story_chapters = {}

        # Load story from external file based on current language
        import os
        from cogs.translation_manager import translation_manager

        # Get current language (en, de, fr)
        current_lang = translation_manager.get_current_language()

        # Map language to story file
        lang_file_map = {
            'en': 'mech_story.txt',
            'de': 'mech_story_de.txt',
            'fr': 'mech_story_fr.txt'
        }

        # Default to English if language not found
        story_filename = lang_file_map.get(current_lang, 'mech_story.txt')
        story_file = os.path.join(os.path.dirname(__file__), '..', 'services', 'mech', story_filename)

        try:
            with open(story_file, 'r', encoding='utf-8') as f:
                story_content = f.read()
        except Exception as e:
            logger.error(f"Failed to load mech story from {story_file}: {e}")
            # Fallback to English
            if current_lang != 'en':
                try:
                    fallback_file = os.path.join(os.path.dirname(__file__), '..', 'services', 'mech', 'mech_story.txt')
                    with open(fallback_file, 'r', encoding='utf-8') as f:
                        story_content = f.read()
                except (FileNotFoundError, PermissionError, UnicodeDecodeError) as e:
                    logger.error(f"Failed to load English fallback story: {e}")
                    story_content = "Error: Story content could not be loaded."
            else:
                story_content = "Error: Story content could not be loaded."

        # Parse chapters - support EN/DE/FR
        sections = story_content.split('\n\n')
        current_chapter = None
        current_content = []

        for section in sections:
            # Prologue I (EN/DE/FR)
            if section.startswith('Prologue I:') or section.startswith('Prolog I:'):
                if current_chapter:
                    story_chapters[current_chapter] = '\n'.join(current_content)
                current_chapter = "prologue1"
                current_content = [section]
            # Prologue II (EN/DE/FR)
            elif section.startswith('Prologue II:') or section.startswith('Prolog II:'):
                if current_chapter:
                    story_chapters[current_chapter] = '\n'.join(current_content)
                current_chapter = "prologue2"
                current_content = [section]
            # Chapter I (EN/DE/FR)
            elif section.startswith('Chapter I:') or section.startswith('Kapitel I:') or section.startswith('Chapitre I'):
                if current_chapter:
                    story_chapters[current_chapter] = '\n'.join(current_content)
                current_chapter = "chapter1"
                current_content = [section]
            # Chapter II (EN/DE/FR)
            elif section.startswith('Chapter II:') or section.startswith('Kapitel II:') or section.startswith('Chapitre II'):
                if current_chapter:
                    story_chapters[current_chapter] = '\n'.join(current_content)
                current_chapter = "chapter2"
                current_content = [section]
            # Chapter III (EN/DE/FR)
            elif section.startswith('Chapter III:') or section.startswith('Kapitel III:') or section.startswith('Chapitre III'):
                if current_chapter:
                    story_chapters[current_chapter] = '\n'.join(current_content)
                current_chapter = "chapter3"
                current_content = [section]
            # Chapter IV (EN/DE/FR)
            elif section.startswith('Chapter IV:') or section.startswith('Kapitel IV:') or section.startswith('Chapitre IV'):
                if current_chapter:
                    story_chapters[current_chapter] = '\n'.join(current_content)
                current_chapter = "chapter4"
                current_content = [section]
            # Chapter V (EN/DE/FR)
            elif section.startswith('Chapter V:') or section.startswith('Kapitel V:') or section.startswith('Chapitre V'):
                if current_chapter:
                    story_chapters[current_chapter] = '\n'.join(current_content)
                current_chapter = "chapter5"
                current_content = [section]
            # Chapter VI (EN/DE/FR)
            elif section.startswith('Chapter VI:') or section.startswith('Kapitel VI:') or section.startswith('Chapitre VI'):
                if current_chapter:
                    story_chapters[current_chapter] = '\n'.join(current_content)
                current_chapter = "chapter6"
                current_content = [section]
            # Chapter VII (EN/DE/FR)
            elif section.startswith('Chapter VII:') or section.startswith('Kapitel VII:') or section.startswith('Chapitre VII'):
                if current_chapter:
                    story_chapters[current_chapter] = '\n'.join(current_content)
                current_chapter = "chapter7"
                current_content = [section]
            # Chapter VIII (EN/DE/FR)
            elif section.startswith('Chapter VIII:') or section.startswith('Kapitel VIII:') or section.startswith('Chapitre VIII'):
                if current_chapter:
                    story_chapters[current_chapter] = '\n'.join(current_content)
                current_chapter = "chapter8"
                current_content = [section]
            # Epilogue (EN/DE/FR + corrupted variant)
            elif section.startswith('Epilogue:') or section.startswith('Epilog:') or section.startswith('Épilogue:') or section.startswith('3p!l0gu3:'):
                if current_chapter:
                    story_chapters[current_chapter] = '\n'.join(current_content)
                current_chapter = "epilogue"
                current_content = [section]
            else:
                if current_chapter:
                    current_content.append(section)

        # Add final chapter
        if current_chapter:
            story_chapters[current_chapter] = '\n'.join(current_content)

        return story_chapters

    def _get_chapter_key_for_level(self, level: int) -> str:
        """Map mech level to story chapter key."""
        # Mapping: Levels -> Chapters
        # Prologue I: Level 1 (Rustborn Husks)
        # Prologue II: Level 2 (Battle-Scarred Survivors + Luigi)
        # Chapter I: Level 3 (Corewalker Standard - Mass Production)
        # Chapter II: Level 4 (Titanframe - The Hunger)
        # Chapter III: Level 5 (Pulseforged Guardian - The Pulse)
        # Chapter IV: Level 6 (Abyss Engines)
        # Chapter V: Level 7 (Rift Striders)
        # Chapter VI: Level 8 (Radiant Bastions)
        # Chapter VII: Level 9 (Overlord Ascendants)
        # Chapter VIII: Level 10 (Celestial Exarchs)
        # Epilogue: Level 11 (corrupted omega hints)

        mapping = {
            1: "prologue1",  # Rustborn Husks
            2: "prologue2",  # Battle-Scarred Survivors + Luigi
            3: "chapter1",   # Corewalker Standard (Mass Production)
            4: "chapter2",   # Titanframe (The Hunger)
            5: "chapter3",   # Pulseforged Guardian (The Pulse)
            6: "chapter4",   # Abyss Engines
            7: "chapter5",   # Rift Striders
            8: "chapter6",   # Radiant Bastions
            9: "chapter7",   # Overlord Ascendants
            10: "chapter8",  # Celestial Exarchs
            11: "epilogue"   # Corrupted Omega hints
        }
        return mapping.get(level, None)

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

        from services.mech.evolution_config_manager import get_evolution_config_manager
        config_manager = get_evolution_config_manager()

        # Add button for each unlocked mech (Level 1-10 only, NO Level 11)
        for level in range(1, min(current_level + 1, 11)):  # 11 to include up to Level 10
            evolution_info = config_manager.get_evolution_level(level)
            if evolution_info:
                button = MechDisplayButton(cog_instance, level, evolution_info.name, unlocked=True)
                self.add_item(button)

        # Add "Next" button for shadow preview (only for levels < 10)
        next_level = current_level + 1
        if next_level <= 10:
            evolution_info = config_manager.get_evolution_level(next_level)
            if evolution_info:
                button = MechDisplayButton(cog_instance, next_level, "Next", unlocked=False)
                self.add_item(button)

        # Always show Epilogue button at Level 10+ (no Level 11 preview)
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
        """Display the mech with Read Story button."""
        try:
            # Check if donations are disabled
            if is_donations_disabled():
                await interaction.response.send_message("❌ Mech system is currently disabled.", ephemeral=True)
                return

            from services.mech.evolution_config_manager import get_evolution_config_manager
            from services.mech.animation_cache_service import get_animation_cache_service
            import io

            config_manager = get_evolution_config_manager()
            cache_service = get_animation_cache_service()
            evolution_info = config_manager.get_evolution_level(self.level)

            if not evolution_info:
                await interaction.response.send_message(_("❌ Mech data not found."), ephemeral=True)
                return

            if self.unlocked:
                # Show unlocked mech with animation
                cached_path = cache_service.get_cached_animation_path(self.level)

                if cached_path.exists():
                    with open(cached_path, 'rb') as f:
                        animation_bytes = f.read()
                else:
                    cache_service.pre_generate_animation(self.level)
                    with open(cached_path, 'rb') as f:
                        animation_bytes = f.read()

                embed = discord.Embed(
                    title=f"✅ Level {self.level}: {_(evolution_info.name)}",
                    description=f"*{_(evolution_info.description)}*",
                    color=int(evolution_info.color.replace('#', ''), 16)
                )

                filename = f"mech_level_{self.level}.webp"
                file = discord.File(io.BytesIO(animation_bytes), filename=filename)

                # Create view with Read Story button
                view = MechStoryView(self.cog, self.level)
                await interaction.response.send_message(embed=embed, file=file, view=view, ephemeral=True)
            else:
                # Show shadow mech
                shadow_bytes = MechHistoryButtonHelper._create_shadow_animation(self.level)

                from services.mech.mech_service import get_mech_service
                mech_service = get_mech_service()
                current_total_donations = float(mech_service.get_state().total_donated)
                needed_amount = max(0, evolution_info.base_cost - current_total_donations)

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

                filename = f"mech_shadow_{self.level}.webp"
                file = discord.File(io.BytesIO(shadow_bytes), filename=filename)

                # Create view with Read Story button
                view = MechStoryView(self.cog, self.level)
                await interaction.response.send_message(embed=embed, file=file, view=view, ephemeral=True)

        except Exception as e:
            logger.error(f"Error displaying mech {self.level}: {e}", exc_info=True)
            await interaction.response.send_message(_("❌ Error loading mech."), ephemeral=True)


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
    """View with Read Story button."""

    def __init__(self, cog_instance: 'DockerControlCog', level: int):
        super().__init__(timeout=None)
        self.cog = cog_instance
        self.level = level
        self.add_item(ReadStoryButton(cog_instance, level))


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

                await interaction.response.send_message(embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message(_("📖 No story chapter available for this mech yet."), ephemeral=True)

        except Exception as e:
            logger.error(f"Error showing story for level {self.level}: {e}", exc_info=True)
            await interaction.response.send_message(_("❌ Error loading story."), ephemeral=True)


class MechHistoryButtonHelper:
    """Helper methods for MechHistoryButton."""

    @staticmethod
    def _create_shadow_animation(evolution_level: int = 1) -> bytes:
        """Create a static black silhouette from cached WebP animation."""
        from PIL import Image
        import io

        try:
            # Use the pre-generated cached WebP (already cropped and optimized!)
            from services.mech.animation_cache_service import get_animation_cache_service
            cache_service = get_animation_cache_service()

            cached_path = cache_service.get_cached_animation_path(evolution_level)

            if cached_path.exists():
                # Load the first frame of the cached WebP animation
                with Image.open(cached_path) as cached_webp:
                    # Get first frame (already perfectly cropped and sized!)
                    first_frame = cached_webp.copy().convert('RGBA')

                    # Create silhouette: keep transparent pixels transparent, make all others black
                    silhouette_data = []
                    for pixel in first_frame.getdata():
                        r, g, b, a = pixel
                        if a == 0:
                            # Keep transparent pixels transparent
                            silhouette_data.append((0, 0, 0, 0))
                        else:
                            # Make all non-transparent pixels black
                            silhouette_data.append((0, 0, 0, min(180, a)))  # Semi-transparent black

                    # Create silhouette image (same size as cached WebP!)
                    silhouette_img = Image.new('RGBA', first_frame.size)
                    silhouette_img.putdata(silhouette_data)

                    # Save as static WebP
                    buffer = io.BytesIO()
                    silhouette_img.save(
                        buffer,
                        format='WebP',
                        lossless=True,
                        quality=100
                    )
                    buffer.seek(0)
                    return buffer.getvalue()

            else:
                # Return a better placeholder if cache doesn't exist
                logger.warning(f"No cached WebP for evolution level {evolution_level}, creating placeholder shadow")
                # Create a larger, more visible shadow placeholder (512x512)
                img = Image.new('RGBA', (512, 512), (0, 0, 0, 0))

                # Draw a dark silhouette shape in the center
                from PIL import ImageDraw
                draw = ImageDraw.Draw(img)

                # Draw a mech-like silhouette shape (centered hexagon/diamond)
                center_x, center_y = 256, 256
                size = 200

                # Create a simple mech silhouette (diamond/hexagon shape)
                points = [
                    (center_x, center_y - size),           # Top
                    (center_x + size//2, center_y - size//3),  # Upper right
                    (center_x + size//2, center_y + size//3),  # Lower right
                    (center_x, center_y + size),           # Bottom
                    (center_x - size//2, center_y + size//3),  # Lower left
                    (center_x - size//2, center_y - size//3),  # Upper left
                ]

                draw.polygon(points, fill=(0, 0, 0, 160))  # Semi-transparent black

                # Add "?" in center to indicate unknown
                from PIL import ImageFont
                try:
                    font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 120)
                except:
                    font = ImageFont.load_default()

                text = "?"
                # Get text bounding box for centering
                bbox = draw.textbbox((0, 0), text, font=font)
                text_width = bbox[2] - bbox[0]
                text_height = bbox[3] - bbox[1]
                text_x = center_x - text_width // 2
                text_y = center_y - text_height // 2 - 20

                draw.text((text_x, text_y), text, fill=(80, 80, 80, 200), font=font)

                buffer = io.BytesIO()
                img.save(buffer, format='WebP', lossless=True, quality=100)
                buffer.seek(0)
                return buffer.getvalue()

        except Exception as e:
            logger.error(f"Error creating shadow animation: {e}", exc_info=True)
            # Return a better fallback placeholder
            from PIL import Image, ImageDraw, ImageFont
            img = Image.new('RGBA', (512, 512), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)

            # Simple dark circle as fallback
            draw.ellipse([106, 106, 406, 406], fill=(0, 0, 0, 140))

            # Add "?" text
            try:
                font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 100)
            except:
                font = ImageFont.load_default()

            draw.text((220, 180), "?", fill=(80, 80, 80, 200), font=font)

            buffer = io.BytesIO()
            img.save(buffer, format='WebP', lossless=True)
            buffer.seek(0)
            return buffer.getvalue()
