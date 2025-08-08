# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Info Command                                   #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #

"""
Info command for displaying container information in channels with appropriate permissions.
Works in both status channels (/ss + info permission) and control channels (/control + info permission).
"""

import discord
from discord.ext import commands
from typing import Dict, Any, Optional
from utils.logging_utils import get_module_logger
from utils.config_cache import get_cached_config, get_cached_servers

# Import with backwards compatibility
try:
    from utils.container_info_manager import get_container_info_manager
    container_info_available = True
except ImportError:
    container_info_available = False
    get_container_info_manager = lambda: None

try:
    from utils.spam_protection_manager import get_spam_protection_manager
    spam_protection_available = True
except ImportError:
    spam_protection_available = False
    get_spam_protection_manager = lambda: None
from .control_helpers import _channel_has_permission, container_select, get_guild_id
from .translation_manager import _
import aiohttp
import asyncio

logger = get_module_logger('info_command')

class InfoCommandCog(commands.Cog):
    """Cog for container info command functionality."""
    
    def __init__(self, bot):
        self.bot = bot
        
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
    
            
    def _get_server_config(self, container_name: str) -> Optional[Dict[str, Any]]:
        """Get server config for a container name."""
        servers = get_cached_servers()
        
        # Try exact match first (docker_name)
        for server in servers:
            if server.get('docker_name') == container_name:
                return server
                
        # Try display name match
        for server in servers:
            if server.get('name') == container_name:
                return server
                
        return None
        
    async def _generate_info_embed(self, container_name: str, server_config: Dict[str, Any], info_config: Dict[str, Any]) -> discord.Embed:
        """Generate the container info embed."""
        display_name = server_config.get('name', container_name)
        
        # Create embed with container branding
        embed = discord.Embed(
            title=f"📋 {display_name} - Container Info",
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
        status_info = await self._get_status_info(server_config)
        if status_info:
            description_parts.append(status_info)
        
        # Set description if we have any content
        if description_parts:
            embed.description = "\n".join(description_parts)
        
        embed.set_footer(text="Container Info • https://ddc.bot")
        return embed
    
    async def _get_ip_info(self, info_config: Dict[str, Any]) -> Optional[str]:
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
            wan_ip = await self._get_wan_ip_async()
            if wan_ip:
                # Add port if provided
                address = wan_ip
                if custom_port and custom_port.isdigit():
                    address = f"{wan_ip}:{custom_port}"
                return f"🌍 **Public IP:** {address}"
        except Exception as e:
            logger.debug(f"Could not get WAN IP: {e}")
        
        return "🔍 **IP:** Auto-detection failed"
    
    async def _get_status_info(self, server_config: Dict[str, Any]) -> Optional[str]:
        """Get current container status information."""
        try:
            # Import here to avoid circular imports
            from .docker_control import DockerControlCog
            
            # Try to get the DockerControlCog instance
            docker_cog = None
            for cog_name, cog_instance in self.bot.cogs.items():
                if isinstance(cog_instance, DockerControlCog):
                    docker_cog = cog_instance
                    break
            
            if not docker_cog:
                return "**State:** 🔄 Loading..."
            
            # Get status from cache if available
            status_cache = getattr(docker_cog, 'status_cache', {})
            display_name = server_config.get('name', server_config.get('docker_name'))
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
            logger.debug(f"Error getting status info for {server_config.get('docker_name')}: {e}")
            return None

    @commands.slash_command(
        name="info",
        description="Display detailed information about a container",
        guild_ids=get_guild_id()
    )
    async def info_command(
        self,
        ctx: discord.ApplicationContext,
        container: discord.Option(
            str,
            description="Container name to show info for",
            autocomplete=container_select,
            required=True
        )
    ):
        """Display container information."""
        try:
            # Check dynamic cooldown (if available)
            if spam_protection_available:
                spam_manager = get_spam_protection_manager()
                if spam_manager and spam_manager.is_enabled():
                    cooldown_seconds = spam_manager.get_command_cooldown('info')
                    # Apply cooldown logic here (simplified - in production you'd track per user)
                    # For now, we'll rely on the dynamic cooldown system at bot level
            
            await ctx.defer(ephemeral=True)  # Always ephemeral for info display
            
            # Check permissions
            config = get_cached_config()
            channel_id = ctx.channel.id
            
            # Check if channel has status OR control permission AND info permission
            has_status = _channel_has_permission(channel_id, 'serverstatus', config)
            has_control = _channel_has_permission(channel_id, 'control', config) 
            has_info_permission = _channel_has_permission(channel_id, 'info', config)
            
            if not has_info_permission:
                embed = discord.Embed(
                    title="❌ Permission Denied",
                    description=_("This channel doesn't have permission to use the info command."),
                    color=discord.Color.red()
                )
                await ctx.followup.send(embed=embed, ephemeral=True)
                return
                
            if not (has_status or has_control):
                embed = discord.Embed(
                    title="❌ Permission Denied", 
                    description=_("This channel needs either status or control permissions to use the info command."),
                    color=discord.Color.red()
                )
                await ctx.followup.send(embed=embed, ephemeral=True)
                return
            
            # Find server config
            server_config = self._get_server_config(container)
            if not server_config:
                embed = discord.Embed(
                    title="❌ Container Not Found",
                    description=_("Container '{}' not found in configuration.").format(container),
                    color=discord.Color.red()
                )
                await ctx.followup.send(embed=embed, ephemeral=True)
                return
            
            # Load container info (if available)
            if container_info_available:
                info_manager = get_container_info_manager()
                docker_name = server_config.get('docker_name')
                info_config = info_manager.load_container_info(docker_name)
                
                # Check if info is enabled for this container
                if not info_config.get('enabled', False):
                    embed = discord.Embed(
                        title="ℹ️ No Info Available",
                        description=_("No additional information is configured for container '{}'.").format(server_config.get('name', container)),
                        color=discord.Color.blue()
                    )
                    await ctx.followup.send(embed=embed, ephemeral=True)
                    return
            else:
                # Fallback: Basic info without container_info_manager
                embed = discord.Embed(
                    title="ℹ️ Container Info (Legacy)",
                    description=f"Container info system not available. Use `/control` for basic container management.",
                    color=discord.Color.blue()
                )
                embed.set_footer(text="Container Info • https://ddc.bot")
                await ctx.followup.send(embed=embed, ephemeral=True)
                return
            
            # Generate and send info embed
            embed = await self._generate_info_embed(docker_name, server_config, info_config)
            await ctx.followup.send(embed=embed, ephemeral=True)
            
            logger.info(f"Info command used for {container} by user {ctx.user.id} in channel {channel_id}")
            
        except Exception as e:
            logger.error(f"Error in info command for {container}: {e}", exc_info=True)
            try:
                error_embed = discord.Embed(
                    title="❌ Error",
                    description=_("An error occurred while retrieving container information. Please try again later."),
                    color=discord.Color.red()
                )
                await ctx.followup.send(embed=error_embed, ephemeral=True)
            except:
                pass  # Ignore errors in error handling

def setup(bot):
    """Setup function for the cog."""
    bot.add_cog(InfoCommandCog(bot))