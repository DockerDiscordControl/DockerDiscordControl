# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""
Simplified Container Info Modal - Single modal with dropdown selects
"""

import asyncio
import discord
import docker
import re
from typing import Optional
from discord import InputTextStyle
from utils.logging_utils import get_module_logger
from services.infrastructure.container_info_service import get_container_info_service, ContainerInfo
from services.infrastructure.action_logger import log_user_action
from cogs.translation_manager import _
# Channel-based security is handled by the calling UI button

logger = get_module_logger('enhanced_info_modal_simple')

# Pre-compiled regex for IP validation

def _info_summary(info: dict) -> str:
    """What a log line may say about a container's info: names, never values.

    Both modals used to log the whole dict at INFO on every open, including
    protected_password and protected_content in plain text - and the action log is
    downloadable from the web panel (SPEC.md Z9 in spirit, review B7).
    """
    return (f"enabled={bool(info.get('enabled'))}, show_ip={bool(info.get('show_ip'))}, "
            f"text={'yes' if info.get('custom_text') else 'no'}, "
            f"protected={'yes' if info.get('protected_enabled') else 'no'}, "
            f"password={'set' if info.get('protected_password') else 'unset'}")


class SimplifiedContainerInfoModal(discord.ui.Modal):
    """Simplified modal with all options in one dialog."""

    def __init__(self, cog_instance, container_name: str, display_name: str = None):
        self.cog = cog_instance
        self.container_name = container_name
        self.display_name = display_name or container_name

        # SERVICE FIRST: Use ServerConfigService to load container info
        self.info_service = get_container_info_service()
        from services.config.server_config_service import get_server_config_service

        # Get container configuration from service
        server_config_service = get_server_config_service()
        container_data = server_config_service.get_server_by_docker_name(container_name)

        # If not found by name, search all servers
        if not container_data:
            all_servers = server_config_service.get_all_servers()
            for server in all_servers:
                if (server.get('container_name') == container_name or
                    server.get('docker_name') == container_name or
                    server.get('name') == container_name):
                    container_data = server
                    break

        # Extract info section from container data
        self.container_info = {}
        if container_data:
            self.container_info = container_data.get('info', {})
            logger.info(f"Loaded info for {container_name}: {_info_summary(self.container_info)}")
        else:
            logger.warning(f"Container configuration not found for: {container_name}")
            self.container_info = {}

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
            placeholder=_("Empty = auto WAN IP")
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

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle modal submission."""
        logger.info(f"callback called for {self.container_name} by {interaction.user}")

        try:
            # Channel-based permissions are already checked by the calling UI button
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
                    _("❌ Custom text too long ({length}/250 characters). Please shorten it.").format(
                        length=len(custom_text)
                    ),
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

            # Create ContainerInfo object and save via service.
            # Preserve the CURRENT protected info, re-read here: self.container_info is
            # the snapshot from when this modal was opened, and the modal lives 300 s.
            # Writing the snapshot back reverted anything the protected-info modal had
            # changed in between - silently, with a success message (review B6).
            existing_info = self.container_info
            current = self.info_service.get_container_info(self.container_name)
            if current.success and current.data is not None:
                existing_info = current.data.to_dict()
            container_info = ContainerInfo(
                enabled=enabled,
                show_ip=show_ip,
                custom_ip=custom_ip,
                custom_port=custom_port,
                custom_text=custom_text,
                protected_enabled=existing_info.get('protected_enabled', False),
                protected_content=existing_info.get('protected_content', ''),
                protected_password=existing_info.get('protected_password', '')
            )

            result = self.info_service.save_container_info(self.container_name, container_info)
            success = result.success

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
                logger.error(f"Container info save failed for {self.container_name}: {result.error}")
                logger.error(f"Attempted to save container_info object")

                await interaction.response.send_message(
                    _("❌ Failed to save container info for **{name}**. Check permissions on config directory.").format(name=self.display_name),
                    ephemeral=True
                )
                safe_error_name = re.sub(r'[^\w\-_.@]', '', str(self.container_name))[:50]
                logger.error(f"Failed to save container info for {safe_error_name}")

        except (IOError, OSError, PermissionError, RuntimeError, discord.Forbidden, discord.HTTPException, discord.NotFound, docker.errors.APIError, docker.errors.DockerException) as e:
            logger.error(f"Error in container info modal submission: {e}", exc_info=True)
            logger.error(f"Container: {self.container_name}, Display: {self.display_name}")

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


class ProtectedInfoModal(discord.ui.Modal):
    """Modal for managing protected container information."""

    def __init__(self, cog_instance, container_name: str, display_name: str = None):
        self.cog = cog_instance
        self.container_name = container_name
        self.display_name = display_name or container_name

        # SERVICE FIRST: Use ServerConfigService to load container info
        self.info_service = get_container_info_service()
        from services.config.server_config_service import get_server_config_service

        # Get container configuration from service
        server_config_service = get_server_config_service()
        container_data = server_config_service.get_server_by_docker_name(container_name)

        # If not found by name, search all servers
        if not container_data:
            all_servers = server_config_service.get_all_servers()
            for server in all_servers:
                if (server.get('container_name') == container_name or
                    server.get('docker_name') == container_name or
                    server.get('name') == container_name):
                    container_data = server
                    break

        # Extract info section from container data
        self.container_info = {}
        if container_data:
            self.container_info = container_data.get('info', {})
            logger.info(f"Loaded protected info for {container_name}: {_info_summary(self.container_info)}")
        else:
            logger.warning(f"Container configuration not found for: {container_name}")
            self.container_info = {}

        title = f"🔒 Protected Info: {self.display_name}"
        if len(title) > 45:  # Discord modal title limit
            title = f"🔒 Protected: {self.display_name[:30]}..."

        super().__init__(title=title, timeout=300)

        # Protected Info Enable field
        protected_enabled = self.container_info.get('protected_enabled', False)
        self.protected_enabled = discord.ui.InputText(
            label=_("🔐 Enable Protected Information"),
            style=InputTextStyle.short,
            value="X" if protected_enabled else "",
            max_length=1,
            required=False,
            placeholder=_("Type 'X' to enable, leave empty to disable")
        )
        self.add_item(self.protected_enabled)

        # Protected Content field
        self.protected_content = discord.ui.InputText(
            label=_("🔒 Protected Information"),
            style=InputTextStyle.long,
            value=self.container_info.get('protected_content', ''),
            max_length=250,
            required=False,
            placeholder=_("Secret server details, admin passwords, etc. (max 250 characters)")
        )
        self.add_item(self.protected_content)

        # Protected Password field
        self.protected_password = discord.ui.InputText(
            label=_("🗝️ Password for Protected Information"),
            style=InputTextStyle.short,
            value=self.container_info.get('protected_password', ''),
            max_length=60,
            required=False,
            placeholder=_("Password to protect secret information (max 60 characters)")
        )
        self.add_item(self.protected_password)

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle protected info modal submission."""
        logger.info(f"Protected info callback called for {self.container_name} by {interaction.user}")

        try:
            # Process inputs
            protected_enabled_value = self.protected_enabled.value.strip().lower()
            protected_content = self.protected_content.value.strip()
            protected_password = self.protected_password.value.strip()

            # Parse protected enabled checkbox
            protected_enabled = bool(protected_enabled_value and protected_enabled_value in ['x', 'X', '1', 'yes', 'y', 'true', 't'])

            # Validate inputs
            if protected_enabled and not protected_content:
                await interaction.response.send_message(
                    _("❌ Protected information is enabled but no content provided."),
                    ephemeral=True
                )
                return

            if protected_enabled and not protected_password:
                await interaction.response.send_message(
                    _("❌ Protected information is enabled but no password provided."),
                    ephemeral=True
                )
                return

            # Sanitize inputs
            protected_content = re.sub(r'[`@#]', '', protected_content)
            protected_content = re.sub(r'<[^>]*>', '', protected_content)

            # Load existing container info and update protected fields
            existing_result = self.info_service.get_container_info(self.container_name)
            if existing_result.success:
                existing_info = existing_result.data.to_dict()
            else:
                # Create default info if none exists
                existing_info = {
                    'enabled': False,
                    'show_ip': False,
                    'custom_ip': '',
                    'custom_port': '',
                    'custom_text': ''
                }

            # Create updated ContainerInfo with protected info
            container_info = ContainerInfo(
                enabled=existing_info['enabled'],
                show_ip=existing_info['show_ip'],
                custom_ip=existing_info['custom_ip'],
                custom_port=existing_info['custom_port'],
                custom_text=existing_info['custom_text'],
                protected_enabled=protected_enabled,
                protected_content=protected_content,
                protected_password=protected_password
            )

            result = self.info_service.save_container_info(self.container_name, container_info)

            if result.success:
                # Log the action
                log_user_action(
                    action="PROTECTED_INFO_EDIT",
                    target=self.display_name,
                    user=str(interaction.user),
                    source="Discord Modal",
                    details=f"Container: {self.container_name}, Protected enabled: {protected_enabled}, Content length: {len(protected_content)}, Guild: {interaction.guild.name if interaction.guild else 'DM'}"
                )

                # Create success embed
                embed = discord.Embed(
                    title=_("🔒 Protected Information Updated"),
                    description=_("Protected information for **{name}** successfully saved").format(name=self.display_name),
                    color=discord.Color.green()
                )

                if protected_enabled:
                    embed.add_field(
                        name=_("✅ Status"),
                        value=_("🔐 Protected information enabled\n🗝️ Password set\n📄 {content_length} characters of content").format(content_length=len(protected_content)),
                        inline=False
                    )
                else:
                    embed.add_field(
                        name=_("❌ Status"),
                        value=_("🔓 Protected information disabled"),
                        inline=False
                    )

                await interaction.response.send_message(embed=embed, ephemeral=True)
                logger.info(f"Protected info updated for {self.container_name} by {interaction.user}")

            else:
                logger.error(f"Protected info save failed for {self.container_name}: {result.error}")
                await interaction.response.send_message(
                    _("❌ Error saving protected information for **{name}**").format(name=self.display_name),
                    ephemeral=True
                )

        except (RuntimeError, asyncio.CancelledError, asyncio.TimeoutError, discord.Forbidden, discord.HTTPException, discord.NotFound) as e:
            logger.error(f"Error in protected info modal submission: {e}", exc_info=True)

            if not interaction.response.is_done():
                await interaction.response.send_message(
                    _("❌ An error occurred: {error}").format(error=str(e)[:100]),
                    ephemeral=True
                )
            else:
                await interaction.followup.send(
                    _("❌ An error occurred: {error}").format(error=str(e)[:100]),
                    ephemeral=True
                )


class PasswordValidationModal(discord.ui.Modal):
    """Modal for validating password to access protected information."""

    def __init__(self, cog_instance, container_name: str, display_name: str, container_info: dict):
        self.cog = cog_instance
        self.container_name = container_name
        self.display_name = display_name or container_name
        self.container_info = container_info

        title = f"🔐 Password: {self.display_name}"
        if len(title) > 45:  # Discord modal title limit
            title = f"🔐 Password: {self.display_name[:30]}..."

        super().__init__(title=title, timeout=300)

        # Password field
        self.password_input = discord.ui.InputText(
            label=_("🗝️ Password"),
            style=InputTextStyle.short,
            max_length=60,
            required=True,
            placeholder=_("Enter password to access protected information")
        )
        self.add_item(self.password_input)

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle password validation."""
        logger.info(f"Password validation attempt for {self.container_name} by {interaction.user}")

        try:
            entered_password = self.password_input.value.strip()
            stored_password = self.container_info.get('protected_password', '')

            if not stored_password:
                await interaction.response.send_message(
                    _("❌ No password is set for this container's protected information."),
                    ephemeral=True
                )
                return

            if entered_password != stored_password:
                # Log failed attempt
                log_user_action(
                    action="PROTECTED_INFO_FAILED",
                    target=self.display_name,
                    user=str(interaction.user),
                    source="Discord Modal",
                    details=f"Container: {self.container_name}, Failed password attempt, Guild: {interaction.guild.name if interaction.guild else 'DM'}"
                )

                await interaction.response.send_message(
                    _("❌ Incorrect password. Access denied."),
                    ephemeral=True
                )
                return

            # Password correct - show protected info
            protected_content = self.container_info.get('protected_content', '')

            if not protected_content:
                await interaction.response.send_message(
                    _("❌ No protected information available for this container."),
                    ephemeral=True
                )
                return

            # Log successful access
            log_user_action(
                action="PROTECTED_INFO_ACCESS",
                target=self.display_name,
                user=str(interaction.user),
                source="Discord Modal",
                details=f"Container: {self.container_name}, Successful access, Guild: {interaction.guild.name if interaction.guild else 'DM'}"
            )

            # Create protected info embed
            embed = discord.Embed(
                title=f"🔐 {self.display_name} - {_('Protected Information')}",
                description=protected_content,
                color=discord.Color.orange()
            )

            embed.add_field(
                name=_("⚠️ Security Notice"),
                value=_("This information is confidential. Do not share it publicly."),
                inline=False
            )

            embed.set_footer(text=f"Accessed by {interaction.user.display_name} • Container: {self.container_name}")

            await interaction.response.send_message(embed=embed, ephemeral=True)
            logger.info(f"Protected info accessed for {self.container_name} by {interaction.user}")

        except (RuntimeError, asyncio.CancelledError, asyncio.TimeoutError, discord.Forbidden, discord.HTTPException, discord.NotFound, docker.errors.APIError, docker.errors.DockerException) as e:
            logger.error(f"Error in password validation modal: {e}", exc_info=True)

            if not interaction.response.is_done():
                await interaction.response.send_message(
                    _("❌ An error occurred during password validation: {error}").format(error=str(e)[:100]),
                    ephemeral=True
                )
            else:
                await interaction.followup.send(
                    _("❌ An error occurred during password validation: {error}").format(error=str(e)[:100]),
                    ephemeral=True
                )

