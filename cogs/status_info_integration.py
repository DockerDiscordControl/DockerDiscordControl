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
from typing import Dict, Any, Optional, List
from utils.logging_utils import get_module_logger
from utils.container_info_manager import get_container_info_manager
from utils.common_helpers import get_public_ip
from .translation_manager import _
import asyncio
import aiohttp

logger = get_module_logger('status_info_integration')

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
            
            await interaction.followup.send(embed=embed, ephemeral=True)
            logger.info(f"Displayed container info for {self.container_name} to user {interaction.user.id}")
            
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
        
        embed.set_footer(text="Container Info • https://ddc.bot")
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
                return f"🌍 **Public IP:** {address}"
        except Exception as e:
            logger.debug(f"Could not get WAN IP for {self.container_name}: {e}")
        
        return "🔍 **IP:** Auto-detection failed"
    
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
        try:
            # Get status from cache if available
            status_cache = getattr(self.cog, 'status_cache', {})
            display_name = self.server_config.get('name', self.container_name)
            cached_entry = status_cache.get(display_name)
            
            if cached_entry and cached_entry.get('data'):
                status_data = cached_entry['data']
                if isinstance(status_data, tuple) and len(status_data) >= 5:
                    _, is_running, cpu, ram, uptime, _ = status_data
                    
                    status_parts = []
                    status_parts.append(f"**State:** {'🟢 Online' if is_running else '🔴 Offline'}")
                    
                    if is_running and uptime != 'N/A':
                        status_parts.append(f"**Uptime:** {uptime}")
                    
                    return "\n".join(status_parts)
            
            return "**State:** 🔄 Loading..."
            
        except Exception as e:
            logger.debug(f"Error getting status info for {self.container_name}: {e}")
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