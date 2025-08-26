# -*- coding: utf-8 -*-
"""
Simplified Container Info Modal - Single modal with dropdown selects
"""

import discord
import logging
import os
import re
from typing import Optional
from discord import InputTextStyle
from utils.logging_utils import get_module_logger
from utils.container_info_manager import get_container_info_manager
from utils.action_logger import log_user_action
from cogs.translation_manager import _
# Channel-based security is already handled in command_handlers.py

logger = get_module_logger('enhanced_info_modal_simple')

# Pre-compiled regex for IP validation

class SimplifiedContainerInfoModal(discord.ui.Modal):
    """Simplified modal with all options in one dialog."""
    
    def __init__(self, cog_instance, container_name: str, display_name: str = None):
        self.cog = cog_instance
        self.container_name = container_name
        self.display_name = display_name or container_name
        
        # Load container info from JSON file
        self.info_manager = get_container_info_manager()
        self.container_info = self.info_manager.load_container_info(container_name)
        
        title = f"📝 Container Info: {self.display_name}"
        if len(title) > 45:  # Discord modal title limit
            title = f"📝 Info: {self.display_name[:35]}..."
        
        super().__init__(title=title, timeout=300)
        
        # Custom Text field
        self.custom_text = discord.ui.InputText(
            label=_("📝 Info Text"),
            style=InputTextStyle.long,
            value=self.container_info.get('custom_text', ''),
            max_length=250,
            required=False,
            placeholder=_("Example: Password: mypass123\nMax Players: 8\nMods: ModPack1, ModPack2")
        )
        self.add_item(self.custom_text)
        
        # Custom IP field
        self.custom_ip = discord.ui.InputText(
            label=_("🌐 IP/URL"),  
            style=InputTextStyle.short,
            value=self.container_info.get('custom_ip', ''),
            max_length=100,
            required=False,
            placeholder=_("mydomain.com or 192.168.1.100")
        )
        self.add_item(self.custom_ip)
        
        # Port field
        self.custom_port = discord.ui.InputText(
            label=_("🔌 Port"),
            style=InputTextStyle.short,
            value=self.container_info.get('custom_port', ''),
            max_length=5,
            required=False,
            placeholder=_("8080")
        )
        self.add_item(self.custom_port)
        
        # Fake Checkbox 1: Info Button Enable/Disable
        enabled = self.container_info.get('enabled', False)
        self.checkbox_enabled = discord.ui.InputText(
            label=_("☑️ Enable Info Button"),
            style=InputTextStyle.short,
            value="X" if enabled else "",
            max_length=1,
            required=False,
            placeholder=_("Type 'X' to enable, leave empty to disable")
        )
        self.add_item(self.checkbox_enabled)
        
        # Fake Checkbox 2: Show IP Address
        show_ip = self.container_info.get('show_ip', False)
        self.checkbox_show_ip = discord.ui.InputText(
            label=_("🌐 Show IP Address"),
            style=InputTextStyle.short,
            value="X" if show_ip else "",
            max_length=1,
            required=False,
            placeholder=_("Type 'X' to show IP, leave empty to hide")
        )
        self.add_item(self.checkbox_show_ip)
    
    async def callback(self, interaction: discord.Interaction):
        """Handle modal submission."""
        logger.info(f"callback called for {self.container_name} by {interaction.user}")
        
        try:
            # Channel-based permissions are already checked in command_handlers.py
            # All users in channels with 'control' permission can edit container info
            logger.info(f"Starting modal submission processing...")
            # Store inputs temporarily
            custom_text = self.custom_text.value.strip()
            custom_ip = self.custom_ip.value.strip()
            custom_port = self.custom_port.value.strip()
            
            # Process fake checkboxes
            checkbox_enabled_value = self.checkbox_enabled.value.strip().lower()
            checkbox_show_ip_value = self.checkbox_show_ip.value.strip().lower()
            
            # Validate custom text length
            if len(custom_text) > 250:
                await interaction.response.send_message(
                    f"❌ Custom text too long ({len(custom_text)}/250 characters). Please shorten it.",
                    ephemeral=True
                )
                return
            
            # Validate port (numbers only, valid range)
            if custom_port:
                if not custom_port.isdigit():
                    await interaction.response.send_message(
                        _("❌ Port must contain only numbers."),
                        ephemeral=True
                    )
                    return
                port_num = int(custom_port)
                if port_num < 1 or port_num > 65535:
                    await interaction.response.send_message(
                        _("❌ Port must be between 1 and 65535."),
                        ephemeral=True
                    )
                    return
            
            # Sanitize inputs
            custom_text = re.sub(r'[`@#]', '', custom_text)
            custom_text = re.sub(r'<[^>]*>', '', custom_text)
            custom_ip = re.sub(r'[`@#<>]', '', custom_ip)
            
            # Parse fake checkboxes (accept 'x', 'X', or any non-empty value as checked)
            enabled = bool(checkbox_enabled_value and checkbox_enabled_value in ['x', 'X', '1', 'yes', 'y', 'true', 't'])
            show_ip = bool(checkbox_show_ip_value and checkbox_show_ip_value in ['x', 'X', '1', 'yes', 'y', 'true', 't'])
            
            # Validate IP format if provided
            ip_warning = ""
            from utils.common_helpers import validate_ip_format
            if custom_ip and not validate_ip_format(custom_ip):
                ip_warning = _("\n⚠️ IP format might be invalid: `{ip}`").format(ip=custom_ip[:50])
            
            # Prepare data for saving
            updated_info = {
                'enabled': enabled,
                'show_ip': show_ip,
                'custom_ip': custom_ip,
                'custom_port': custom_port,
                'custom_text': custom_text
            }
            
            # Save to JSON file
            success = self.info_manager.save_container_info(self.container_name, updated_info)
            
            if success:
                # Log the action
                safe_container_name = re.sub(r'[^\w\-_]', '', self.container_name)[:50]
                settings_summary = []
                if enabled:
                    settings_summary.append('enabled')
                if show_ip:
                    settings_summary.append('show_ip')
                safe_settings = ', '.join(settings_summary) if settings_summary else 'none'
                # Enhanced security logging
                log_user_action(
                    action="INFO_EDIT_MODAL_SIMPLE",
                    target=self.display_name,
                    user=str(interaction.user),
                    source="Discord Modal",
                    details=f"Container: {safe_container_name}, Text length: {len(custom_text)} chars, Settings: {safe_settings}, Guild: {interaction.guild.name if interaction.guild else 'DM'}, Channel: {interaction.channel.name if interaction.channel else 'Unknown'}"
                )
                
                # Create success embed
                embed = discord.Embed(
                    title=_("✅ Container Info Updated"),
                    description=_("Successfully updated information for **{name}**").format(name=self.display_name) + ip_warning,
                    color=discord.Color.green()
                )
                
                # Show what was saved
                if custom_text:
                    safe_text = custom_text.replace('*', '\\*').replace('_', '\\_').replace('~', '\\~')
                    char_count = len(custom_text)
                    embed.add_field(
                        name=_("📝 Custom Text ({count}/250 chars)").format(count=char_count),
                        value=f"```\n{safe_text[:150]}{'...' if len(safe_text) > 150 else ''}\n```",
                        inline=False
                    )
                
                if custom_ip:
                    safe_ip = custom_ip.replace('*', '\\*').replace('_', '\\_')[:50]
                    embed.add_field(
                        name=_("🌐 Custom IP/URL"),
                        value=f"`{safe_ip}`",
                        inline=True
                    )
                
                settings_display = []
                if enabled:
                    settings_display.append(_("✅ Info button enabled"))
                else:
                    settings_display.append(_("❌ Info button disabled"))
                    
                if show_ip:
                    settings_display.append(_("🌐 Show IP address"))
                else:
                    settings_display.append(_("🔒 Hide IP address"))
                
                embed.add_field(
                    name=_("⚙️ Settings"),
                    value="\n".join(settings_display),
                    inline=True
                )
                
                safe_footer_name = re.sub(r'[^\w\-_]', '', self.container_name)[:30]
                embed.set_footer(text=f"Container: {safe_footer_name}")
                
                await interaction.response.send_message(embed=embed, ephemeral=True)
                
                # Log success
                safe_log_name = re.sub(r'[^\w\-_.@]', '', str(self.container_name))[:50]
                safe_user = re.sub(r'[^\w\-_.@#]', '', str(interaction.user))[:50]
                logger.info(f"Container info updated for {safe_log_name} by {safe_user}")
                
            else:
                # More detailed error logging
                logger.error(f"Container info save returned False for {self.container_name}")
                logger.error(f"Attempted to save data: {updated_info}")
                logger.error(f"Config dir exists: {self.info_manager.config_dir.exists()}")
                logger.error(f"Config dir writable: {os.access(self.info_manager.config_dir, os.W_OK)}")
                
                await interaction.response.send_message(
                    _("❌ Failed to save container info for **{name}**. Check permissions on config directory.").format(name=self.display_name),
                    ephemeral=True
                )
                safe_error_name = re.sub(r'[^\w\-_.@]', '', str(self.container_name))[:50]
                logger.error(f"Failed to save container info for {safe_error_name}")
                
        except Exception as e:
            logger.error(f"Error in container info modal submission: {e}", exc_info=True)
            logger.error(f"Container: {self.container_name}, Display: {self.display_name}")
            logger.error(f"Config dir: {self.info_manager.config_dir}")
            
            # Check if interaction already responded
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    _("❌ An error occurred while saving container info: {error}").format(error=str(e)[:100]),
                    ephemeral=True
                )
            else:
                await interaction.followup.send(
                    _("❌ An error occurred while saving container info: {error}").format(error=str(e)[:100]),
                    ephemeral=True
                )
    
