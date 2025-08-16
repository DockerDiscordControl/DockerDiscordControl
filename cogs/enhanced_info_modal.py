# -*- coding: utf-8 -*-
"""
Enhanced Container Info Modal - Uses separate JSON files per container
"""

import discord
import logging
import re
from typing import Optional
from discord.ui import Modal, View, Button
from discord import InputTextStyle
from utils.logging_utils import get_module_logger
from utils.container_info_manager import get_container_info_manager
from utils.action_logger import log_user_action

logger = get_module_logger('enhanced_info_modal')

# TextInput compatibility will be handled at runtime like the working modal

# Pre-compiled regex for IP validation (performance optimization)  
# Allows: domain.com, domain.com:8080, 192.168.1.1, 192.168.1.1:8080, localhost:3000

class ContainerSettingsView(View):
    """View with checkbox-style buttons for container settings."""
    
    def __init__(self, container_info: dict, timeout: float = 300):
        super().__init__(timeout=timeout)
        self.enabled = container_info.get('enabled', False)
        self.show_ip = container_info.get('show_ip', False)
        
        # Update button styles based on current state
        self.update_buttons()
    
    def update_buttons(self):
        """Update button styles to reflect current state."""
        self.clear_items()
        
        logger.debug(f"Updating buttons: enabled={self.enabled}, show_ip={self.show_ip}")
        
        # Enabled/Disabled button
        enabled_style = discord.ButtonStyle.success if self.enabled else discord.ButtonStyle.secondary
        enabled_emoji = "✅" if self.enabled else "❌"
        enabled_label = "Info Button: Enabled" if self.enabled else "Info Button: Disabled"
        
        self.enabled_button = Button(
            style=enabled_style,
            emoji=enabled_emoji,
            label=enabled_label,
            custom_id="toggle_enabled"
        )
        self.enabled_button.callback = self.toggle_enabled
        self.add_item(self.enabled_button)
        
        # Show IP button
        ip_style = discord.ButtonStyle.primary if self.show_ip else discord.ButtonStyle.secondary
        ip_emoji = "🌐" if self.show_ip else "🔒"
        ip_label = "Show IP: Yes" if self.show_ip else "Show IP: No"
        
        self.ip_button = Button(
            style=ip_style,
            emoji=ip_emoji,
            label=ip_label,
            custom_id="toggle_show_ip"
        )
        self.ip_button.callback = self.toggle_show_ip
        self.add_item(self.ip_button)
        
        # Save button
        self.save_button = Button(
            style=discord.ButtonStyle.success,
            emoji="💾",
            label="Save Settings",
            custom_id="save_settings"
        )
        self.save_button.callback = self.save_settings
        self.add_item(self.save_button)
        
        # Cancel button
        self.cancel_button = Button(
            style=discord.ButtonStyle.danger,
            emoji="❌", 
            label="Cancel",
            custom_id="cancel_settings"
        )
        self.cancel_button.callback = self.cancel_settings
        self.add_item(self.cancel_button)
        
        logger.debug(f"Added {len(self.children)} buttons to view")
    
    async def toggle_enabled(self, interaction: discord.Interaction):
        """Toggle the enabled state."""
        self.enabled = not self.enabled
        self.update_buttons()
        
        status = "enabled" if self.enabled else "disabled"
        # Update the embed instead of just content
        embed = discord.Embed(
            title=f"⚙️ Settings for {self.modal_instance.display_name}",
            description=f"Info button is now **{status}**. Click 'Save Settings' to confirm changes.",
            color=discord.Color.green() if self.enabled else discord.Color.orange()
        )
        await interaction.response.edit_message(embed=embed, view=self)
    
    async def toggle_show_ip(self, interaction: discord.Interaction):
        """Toggle the show IP state."""
        self.show_ip = not self.show_ip
        self.update_buttons()
        
        status = "shown" if self.show_ip else "hidden"
        # Update the embed with better visual feedback
        embed = discord.Embed(
            title=f"⚙️ Settings for {self.modal_instance.display_name}",
            description=f"IP address will be **{status}**. Click 'Save Settings' to confirm changes.",
            color=discord.Color.blue() if self.show_ip else discord.Color.orange()
        )
        await interaction.response.edit_message(embed=embed, view=self)
    
    async def save_settings(self, interaction: discord.Interaction):
        """Save the settings to JSON file."""
        try:
            # Defer the response to avoid timeout
            await interaction.response.defer(ephemeral=True)
            
            modal = self.modal_instance
            
            # Sanitize inputs
            custom_text = re.sub(r'[`@#]', '', modal.temp_custom_text)
            custom_text = re.sub(r'<[^>]*>', '', custom_text)
            
            custom_ip = re.sub(r'[`@#<>]', '', modal.temp_custom_ip)
            
            # Validate IP format if provided
            from utils.common_helpers import validate_ip_format
            if custom_ip and not validate_ip_format(custom_ip):
                await interaction.followup.send(
                    f"⚠️ Custom IP format might be invalid: `{custom_ip[:50]}`\n"
                    "Saving anyway. Accepted formats: domain.com, domain.com:port, IP:port",
                    ephemeral=True
                )
            
            # Prepare data for saving
            updated_info = {
                'enabled': self.enabled,
                'show_ip': self.show_ip,
                'custom_ip': custom_ip,
                'custom_text': custom_text
            }
            
            # Save to JSON file
            success = modal.info_manager.save_container_info(modal.container_name, updated_info)
            
            if success:
                # Log the action
                safe_container_name = re.sub(r'[^\w\-_]', '', modal.container_name)[:50]
                safe_settings = []
                if self.enabled:
                    safe_settings.append('enabled')
                if self.show_ip:
                    safe_settings.append('show_ip')
                    
                log_user_action(
                    action="INFO_EDIT_MODAL",
                    target=modal.display_name,
                    user=str(interaction.user),
                    source="Discord Modal",
                    details=f"Container: {safe_container_name}, Text length: {len(custom_text)} chars, Settings: {', '.join(safe_settings) or 'none'}"
                )
                
                # Create success embed
                embed = discord.Embed(
                    title="✅ Container Info Updated",
                    description=f"Successfully updated information for **{modal.display_name}**",
                    color=discord.Color.green()
                )
                
                # Show what was saved
                if custom_text:
                    safe_text = custom_text.replace('*', '\\*').replace('_', '\\_').replace('~', '\\~')
                    embed.add_field(
                        name="📝 Custom Text",
                        value=f"```\n{safe_text[:100]}{'...' if len(safe_text) > 100 else ''}\n```",
                        inline=False
                    )
                
                if custom_ip:
                    safe_ip = custom_ip.replace('*', '\\*').replace('_', '\\_')[:50]
                    embed.add_field(
                        name="🌐 Custom IP/URL",
                        value=f"`{safe_ip}`",
                        inline=True
                    )
                
                settings_display = []
                if self.enabled:
                    settings_display.append("✅ Info button enabled")
                else:
                    settings_display.append("❌ Info button disabled")
                    
                if self.show_ip:
                    settings_display.append("🌐 Show IP address")
                
                if settings_display:
                    embed.add_field(
                        name="⚙️ Settings",
                        value="\n".join(settings_display),
                        inline=True
                    )
                
                safe_footer_name = re.sub(r'[^\w\-_]', '', modal.container_name)[:30]
                embed.set_footer(text=f"Container: {safe_footer_name}")
                
                await interaction.followup.send(embed=embed, ephemeral=True)
                
                # Log success
                safe_log_name = re.sub(r'[^\w\-_.@]', '', str(modal.container_name))[:50]
                safe_user = re.sub(r'[^\w\-_.@#]', '', str(interaction.user))[:50]
                logger.info(f"Container info updated for {safe_log_name} by {safe_user}")
                
            else:
                await interaction.followup.send(
                    f"❌ Failed to save container info for **{modal.display_name}**. Please try again.",
                    ephemeral=True
                )
                safe_error_name = re.sub(r'[^\w\-_.@]', '', str(modal.container_name))[:50]
                logger.error(f"Failed to save container info for {safe_error_name}")
                
        except Exception as e:
            logger.error(f"Error saving container settings: {e}", exc_info=True)
            await interaction.followup.send(
                "❌ An error occurred while saving. Please try again.",
                ephemeral=True
            )
    
    async def cancel_settings(self, interaction: discord.Interaction):
        """Cancel the settings changes."""
        embed = discord.Embed(
            title="❌ Changes Cancelled",
            description="No changes were saved.",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

class EnhancedContainerInfoModal(Modal):
    """Enhanced modal for editing container information with separate JSON files."""
    
    def __init__(self, cog_instance, container_name: str, display_name: str = None):
        self.cog = cog_instance
        self.container_name = container_name
        self.display_name = display_name or container_name
        
        # Load container info from JSON file
        self.info_manager = get_container_info_manager()
        self.container_info = self.info_manager.load_container_info(container_name)
        
        title = f"📝 Edit Info: {self.display_name}"
        if len(title) > 45:  # Discord modal title limit
            title = f"📝 Info: {self.display_name[:35]}..."
        
        super().__init__(title=title, timeout=300)
        
        # Create form fields directly in __init__
        # Custom Text field
        # Use PyCord InputText directly (since we know we're using py-cord 2.6.1)
        self.custom_text = discord.ui.InputText(
            label="📝 Custom Info Text (250 chars max)",
            style=InputTextStyle.long,
            value=self.container_info.get('custom_text', ''),
            max_length=250,
            required=False,
            placeholder="Example: Password: mypass123\nMax Players: 8\nMods: ModPack1, ModPack2"
        )
        self.add_item(self.custom_text)
        
        # Custom IP field
        self.custom_ip = discord.ui.InputText(
            label="🌐 Custom IP/URL (optional)",  
            style=InputTextStyle.short,
            value=self.container_info.get('custom_ip', ''),
            max_length=100,
            required=False,
            placeholder="mydomain.com:7777 or 192.168.1.100:8080"
        )
        self.add_item(self.custom_ip)
        
        # Remove the text-based settings field - we'll use View with buttons instead
    
    async def on_submit(self, interaction: discord.Interaction):
        """Handle modal submission - show settings view for checkbox selection."""
        try:
            
            # Store the text inputs temporarily in the modal instance
            self.temp_custom_text = self.custom_text.value.strip()
            self.temp_custom_ip = self.custom_ip.value.strip()
            
            # Validate custom text length
            if len(self.temp_custom_text) > 250:
                await interaction.response.send_message(
                    f"❌ Custom text too long ({len(self.temp_custom_text)}/250 characters). Please shorten it.",
                    ephemeral=True
                )
                return
            
            # Show settings view with checkbox-style buttons
            settings_view = ContainerSettingsView(self.container_info)
            settings_view.modal_instance = self  # Pass reference to modal
            
            # Debug: Log the buttons being created
            logger.info(f"Creating settings view with {len(settings_view.children)} buttons")
            
            embed = discord.Embed(
                title=f"⚙️ Settings for {self.display_name}",
                description="Click the buttons below to toggle settings, then click 'Save Settings':",
                color=discord.Color.blue()
            )
            
            # Add current settings status to embed
            current_status = []
            if self.container_info.get('enabled', False):
                current_status.append("✅ Info Button: Currently Enabled")
            else:
                current_status.append("❌ Info Button: Currently Disabled")
                
            if self.container_info.get('show_ip', False):
                current_status.append("🌐 Show IP: Currently Yes")
            else:
                current_status.append("🔒 Show IP: Currently No")
            
            embed.add_field(
                name="Current Settings",
                value="\n".join(current_status),
                inline=False
            )
            
            # Show current text/IP preview with character count
            if self.temp_custom_text:
                char_count = len(self.temp_custom_text)
                char_indicator = f"({char_count}/250 chars)"
                embed.add_field(
                    name=f"📝 Custom Text Preview {char_indicator}", 
                    value=f"```{self.temp_custom_text[:150]}{'...' if len(self.temp_custom_text) > 150 else ''}```",
                    inline=False
                )
            
            if self.temp_custom_ip:
                embed.add_field(
                    name="🌐 Custom IP/URL Preview",
                    value=f"`{self.temp_custom_ip[:50]}`",
                    inline=True
                )
            
            await interaction.response.send_message(
                embed=embed,
                view=settings_view,
                ephemeral=True
            )
        
        except Exception as e:
            logger.error(f"Error in container info modal submission: {e}", exc_info=True)
            await interaction.response.send_message(
                "❌ An error occurred while saving container info. Please try again.",
                ephemeral=True
            )

class ContainerInfoDisplayModal(Modal):
    """Modal for displaying container information (read-only)."""
    
    def __init__(self, container_name: str, display_name: str = None):
        self.container_name = container_name
        self.display_name = display_name or container_name
        
        # Load container info
        self.info_manager = get_container_info_manager()
        self.container_info = self.info_manager.load_container_info(container_name)
        
        title = f"📋 Info: {self.display_name}"
        if len(title) > 45:
            title = f"📋 {self.display_name[:38]}..."
        
        super().__init__(title=title, timeout=300)
        
        # Build display content
        content = self._build_display_content()
        
        # Single read-only text field
        self.display_field = discord.ui.InputText(
            label="Container Information",
            style=InputTextStyle.long,
            value=content,
            max_length=2000,
            required=False
        )
        self.add_item(self.display_field)
    
    def _build_display_content(self) -> str:
        """Build the display content."""
        content_parts = []
        
        # Add IP information if enabled
        if self.container_info.get('show_ip', False):
            custom_ip = self.container_info.get('custom_ip', '').strip()
            if custom_ip:
                content_parts.append(f"🌐 IP: {custom_ip}")
            else:
                content_parts.append("🌐 IP: Auto-detected")
        
        # Add custom text
        custom_text = self.container_info.get('custom_text', '').strip()
        if custom_text:
            if content_parts:
                content_parts.append("")
            content_parts.append("📝 Information:")
            content_parts.append(custom_text)
        
        # Add metadata
        if self.container_info.get('last_updated'):
            content_parts.append("")
            content_parts.append(f"📅 Last updated: {self.container_info['last_updated'][:19].replace('T', ' ')}")
        
        if not content_parts:
            return f"No information configured for {self.display_name}.\n\nUse `/info_edit {self.container_name}` to add information."
        
        return "\n".join(content_parts)
    
    async def on_submit(self, interaction: discord.Interaction):
        """Handle submission (this is read-only, so just acknowledge)."""
        await interaction.response.send_message(
            f"ℹ️ This is display-only. Use `/info_edit {self.container_name}` to edit.",
            ephemeral=True
        )