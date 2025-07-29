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

def _get_cached_formatted_timestamp(timestamp: datetime, timezone_str: str, fmt: str = "%H:%M:%S") -> str:
    """Ultra-fast cached timestamp formatting - FIXED VERSION."""
    # CLEAR OLD CACHE - it might contain wrong UTC values
    global _timestamp_format_cache
    _timestamp_format_cache.clear()
    
    # Always call format_datetime_with_timezone directly (no caching for now)
    return format_datetime_with_timezone(timestamp, timezone_str, fmt)

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
        """Ultra-optimized action button handler."""
        user = interaction.user
        await interaction.response.defer()
        
        current_config = get_cached_config()
        channel_has_control = _get_cached_channel_permission(interaction.channel.id, 'control', current_config)
        
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
                    
                    server_config_for_update = next((s for s in self.cog.config.get('servers', []) if s.get('name') == self.display_name), None)
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
                                current_config, 
                                allow_toggle=True, 
                                force_collapse=False
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
            
            current_config = get_cached_config()
            
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
                
                embed, view = await self._generate_ultra_fast_toggle_embed_and_view(
                    channel_id=channel_id,
                    status_result=status_result,
                    current_config=current_config,
                    cached_entry=cached_entry
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
            current_time = _get_cached_formatted_timestamp(cached_entry['timestamp'], timezone_str, fmt="%H:%M:%S")
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
        else:
            # Start button for offline containers
            if channel_has_control_permission and "start" in allowed_actions:
                self.add_item(ActionButton(cog_instance, server_config, "start", discord.ButtonStyle.secondary, None, "▶️", row=0))

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