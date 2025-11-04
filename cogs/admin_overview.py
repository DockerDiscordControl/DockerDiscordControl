# =============================================================================
# ADMIN OVERVIEW VIEW FOR CONTROL CHANNELS
# =============================================================================

import discord
from discord.ui import View, Button
import asyncio
import logging
from services.config.config_service import load_config
from datetime import datetime, timezone

logger = logging.getLogger('ddc.admin_overview')

class AdminOverviewView(View):
    """View for admin overview in control channels with bulk container management."""

    def __init__(self, cog_instance, channel_id: int, has_running_containers: bool):
        super().__init__(timeout=None)
        self.cog = cog_instance
        self.channel_id = channel_id
        self.has_running_containers = has_running_containers

        # Add buttons
        self.add_item(AdminOverviewAdminButton(cog_instance, channel_id))
        self.add_item(AdminOverviewRestartAllButton(cog_instance, channel_id, enabled=has_running_containers))
        self.add_item(AdminOverviewStopAllButton(cog_instance, channel_id, enabled=has_running_containers))

class AdminOverviewAdminButton(Button):
    """Admin button for accessing individual container controls."""

    def __init__(self, cog_instance, channel_id: int):
        self.cog = cog_instance
        self.channel_id = channel_id

        super().__init__(
            style=discord.ButtonStyle.secondary,
            label=None,
            emoji="🛠️",
            custom_id=f"admin_overview_admin_{channel_id}",
            row=0
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        """Show container selection dropdown for admin control."""
        try:
            # Check if user is admin
            config = load_config()

            # Load admin users
            import json
            from pathlib import Path
            base_dir = config.get('base_dir', '/app')
            admins_file = Path(base_dir) / 'config' / 'admins.json'

            admin_users = []
            if admins_file.exists():
                try:
                    with open(admins_file, 'r') as f:
                        admin_data = json.load(f)
                        admin_users = admin_data.get('discord_admin_users', [])
                except Exception as e:
                    logger.error(f"Error loading admins.json: {e}")

            # Check if user is admin
            user_id_str = str(interaction.user.id)
            if user_id_str not in admin_users:
                await interaction.response.send_message(
                    "❌ You don't have permission to use admin controls.",
                    ephemeral=True
                )
                return

            # Get containers list for dropdown
            servers = config.get('servers', [])
            containers = []
            for server in servers:
                docker_name = server.get('docker_name')
                display_name = server.get('name', docker_name)
                if docker_name:
                    containers.append({
                        'display': display_name,  # AdminContainerDropdown expects 'display' field
                        'docker_name': docker_name
                    })

            if not containers:
                await interaction.response.send_message(
                    "❌ No containers found in configuration.",
                    ephemeral=True
                )
                return

            # Import AdminContainerSelectView from control_ui
            from .control_ui import AdminContainerSelectView

            # Create dropdown view with containers list
            view = AdminContainerSelectView(self.cog, containers, self.channel_id)
            await interaction.response.send_message(
                "Select a container to control:",
                view=view,
                ephemeral=True
            )

        except Exception as e:
            logger.error(f"Error in admin overview admin button: {e}", exc_info=True)
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        "❌ Error accessing admin controls.",
                        ephemeral=True
                    )
            except Exception:
                pass

class AdminOverviewRestartAllButton(Button):
    """Button to restart all running containers with confirmation."""

    def __init__(self, cog_instance, channel_id: int, enabled: bool):
        self.cog = cog_instance
        self.channel_id = channel_id

        super().__init__(
            style=discord.ButtonStyle.primary,
            label=None,
            emoji="🔄",
            custom_id=f"admin_overview_restart_all_{channel_id}",
            row=0,
            disabled=not enabled
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        """Ask for confirmation before restarting all containers."""
        try:
            # Check admin permission
            config = load_config()
            import json
            from pathlib import Path
            base_dir = config.get('base_dir', '/app')
            admins_file = Path(base_dir) / 'config' / 'admins.json'

            admin_users = []
            if admins_file.exists():
                try:
                    with open(admins_file, 'r') as f:
                        admin_data = json.load(f)
                        admin_users = admin_data.get('discord_admin_users', [])
                except Exception as e:
                    logger.error(f"Error loading admins.json: {e}")

            user_id_str = str(interaction.user.id)
            if user_id_str not in admin_users:
                await interaction.response.send_message(
                    "❌ You don't have permission to restart all containers.",
                    ephemeral=True
                )
                return

            # Create confirmation view
            view = RestartAllConfirmationView(self.cog, self.channel_id)
            embed = discord.Embed(
                title="⚠️ Confirm Restart All",
                description="Are you sure you want to restart ALL running containers?\n\nThis will temporarily disrupt all services.",
                color=discord.Color.orange()
            )
            await interaction.response.send_message(
                embed=embed,
                view=view,
                ephemeral=True
            )

        except Exception as e:
            logger.error(f"Error in restart all button: {e}", exc_info=True)
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        "❌ Error processing restart all request.",
                        ephemeral=True
                    )
            except Exception:
                pass

class AdminOverviewStopAllButton(Button):
    """Button to stop all running containers with confirmation."""

    def __init__(self, cog_instance, channel_id: int, enabled: bool):
        self.cog = cog_instance
        self.channel_id = channel_id

        super().__init__(
            style=discord.ButtonStyle.danger,
            label=None,
            emoji="⏹️",
            custom_id=f"admin_overview_stop_all_{channel_id}",
            row=0,
            disabled=not enabled
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        """Ask for confirmation before stopping all containers."""
        try:
            # Check admin permission
            config = load_config()
            import json
            from pathlib import Path
            base_dir = config.get('base_dir', '/app')
            admins_file = Path(base_dir) / 'config' / 'admins.json'

            admin_users = []
            if admins_file.exists():
                try:
                    with open(admins_file, 'r') as f:
                        admin_data = json.load(f)
                        admin_users = admin_data.get('discord_admin_users', [])
                except Exception as e:
                    logger.error(f"Error loading admins.json: {e}")

            user_id_str = str(interaction.user.id)
            if user_id_str not in admin_users:
                await interaction.response.send_message(
                    "❌ You don't have permission to stop all containers.",
                    ephemeral=True
                )
                return

            # Create confirmation view
            view = StopAllConfirmationView(self.cog, self.channel_id)
            embed = discord.Embed(
                title="🚨 Confirm Stop All",
                description="Are you sure you want to STOP ALL running containers?\n\n**WARNING:** This will shut down all services!",
                color=discord.Color.red()
            )
            await interaction.response.send_message(
                embed=embed,
                view=view,
                ephemeral=True
            )

        except Exception as e:
            logger.error(f"Error in stop all button: {e}", exc_info=True)
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        "❌ Error processing stop all request.",
                        ephemeral=True
                    )
            except Exception:
                pass

# =============================================================================
# CONFIRMATION VIEWS FOR BULK ACTIONS
# =============================================================================

class RestartAllConfirmationView(View):
    """Confirmation view for restarting all containers."""

    def __init__(self, cog_instance, channel_id: int):
        super().__init__(timeout=30)
        self.cog = cog_instance
        self.channel_id = channel_id

        # Add confirm and cancel buttons
        self.add_item(ConfirmRestartAllButton(cog_instance, channel_id))
        self.add_item(CancelBulkActionButton())

class StopAllConfirmationView(View):
    """Confirmation view for stopping all containers."""

    def __init__(self, cog_instance, channel_id: int):
        super().__init__(timeout=30)
        self.cog = cog_instance
        self.channel_id = channel_id

        # Add confirm and cancel buttons
        self.add_item(ConfirmStopAllButton(cog_instance, channel_id))
        self.add_item(CancelBulkActionButton())

class ConfirmRestartAllButton(Button):
    """Button to confirm restart all action."""

    def __init__(self, cog_instance, channel_id: int):
        self.cog = cog_instance
        self.channel_id = channel_id

        super().__init__(
            style=discord.ButtonStyle.danger,
            label="Yes, Restart All",
            custom_id="confirm_restart_all"
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        """Execute restart all containers."""
        try:
            await interaction.response.defer()

            # Get all running containers
            config = load_config()
            servers = config.get('servers', [])

            restarted_count = 0
            failed_count = 0

            for server in servers:
                docker_name = server.get('docker_name')
                if not docker_name:
                    continue

                # Check if container is running
                cached_entry = self.cog.status_cache.get(server.get('name', docker_name))
                if cached_entry and cached_entry.get('data'):
                    _, is_running, _, _, _, _ = cached_entry['data']
                    if is_running:
                        # Restart container
                        try:
                            from services.docker.docker_action_service import docker_action_service_first
                            success = await docker_action_service_first(docker_name, "restart")
                            if success:
                                restarted_count += 1
                            else:
                                failed_count += 1
                        except Exception as e:
                            logger.error(f"Error restarting {docker_name}: {e}")
                            failed_count += 1

            # Send result message
            embed = discord.Embed(
                title="🔄 Restart All Complete",
                description=f"Successfully restarted: **{restarted_count}** containers\nFailed: **{failed_count}** containers",
                color=discord.Color.green() if failed_count == 0 else discord.Color.orange()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)

            # Update admin overview after a delay
            await asyncio.sleep(5)
            await self._update_admin_overview()

        except Exception as e:
            logger.error(f"Error executing restart all: {e}", exc_info=True)
            await interaction.followup.send("❌ Error restarting containers.", ephemeral=True)

    async def _update_admin_overview(self):
        """Update admin overview message after bulk action."""
        try:
            # Find and update admin overview messages in channel
            channel = self.cog.bot.get_channel(self.channel_id)
            if channel:
                async for message in channel.history(limit=50):
                    if message.author == self.cog.bot.user and message.embeds:
                        embed = message.embeds[0]
                        if embed.title == "Admin Overview":
                            # Recreate admin overview
                            config = load_config()
                            servers = config.get('servers', [])
                            ordered_servers = sorted(servers, key=lambda s: s.get('order', 999))

                            new_embed, _, has_running = await self.cog._create_admin_overview_embed(ordered_servers, config)
                            new_view = AdminOverviewView(self.cog, self.channel_id, has_running)

                            await message.edit(embed=new_embed, view=new_view)
                            break
        except Exception as e:
            logger.error(f"Error updating admin overview: {e}")

class ConfirmStopAllButton(Button):
    """Button to confirm stop all action."""

    def __init__(self, cog_instance, channel_id: int):
        self.cog = cog_instance
        self.channel_id = channel_id

        super().__init__(
            style=discord.ButtonStyle.danger,
            label="Yes, Stop All",
            custom_id="confirm_stop_all"
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        """Execute stop all containers."""
        try:
            await interaction.response.defer()

            # Get all running containers
            config = load_config()
            servers = config.get('servers', [])

            stopped_count = 0
            failed_count = 0

            for server in servers:
                docker_name = server.get('docker_name')
                if not docker_name:
                    continue

                # Check if container is running
                cached_entry = self.cog.status_cache.get(server.get('name', docker_name))
                if cached_entry and cached_entry.get('data'):
                    _, is_running, _, _, _, _ = cached_entry['data']
                    if is_running:
                        # Stop container
                        try:
                            from services.docker.docker_action_service import docker_action_service_first
                            success = await docker_action_service_first(docker_name, "stop")
                            if success:
                                stopped_count += 1
                            else:
                                failed_count += 1
                        except Exception as e:
                            logger.error(f"Error stopping {docker_name}: {e}")
                            failed_count += 1

            # Send result message
            embed = discord.Embed(
                title="⏹️ Stop All Complete",
                description=f"Successfully stopped: **{stopped_count}** containers\nFailed: **{failed_count}** containers",
                color=discord.Color.green() if failed_count == 0 else discord.Color.orange()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)

            # Update admin overview after a delay
            await asyncio.sleep(5)
            await self._update_admin_overview()

        except Exception as e:
            logger.error(f"Error executing stop all: {e}", exc_info=True)
            await interaction.followup.send("❌ Error stopping containers.", ephemeral=True)

    async def _update_admin_overview(self):
        """Update admin overview message after bulk action."""
        try:
            # Find and update admin overview messages in channel
            channel = self.cog.bot.get_channel(self.channel_id)
            if channel:
                async for message in channel.history(limit=50):
                    if message.author == self.cog.bot.user and message.embeds:
                        embed = message.embeds[0]
                        if embed.title == "Admin Overview":
                            # Recreate admin overview
                            config = load_config()
                            servers = config.get('servers', [])
                            ordered_servers = sorted(servers, key=lambda s: s.get('order', 999))

                            new_embed, _, has_running = await self.cog._create_admin_overview_embed(ordered_servers, config)
                            new_view = AdminOverviewView(self.cog, self.channel_id, has_running)

                            await message.edit(embed=new_embed, view=new_view)
                            break
        except Exception as e:
            logger.error(f"Error updating admin overview: {e}")

class CancelBulkActionButton(Button):
    """Button to cancel bulk action."""

    def __init__(self):
        super().__init__(
            style=discord.ButtonStyle.secondary,
            label="Cancel",
            custom_id="cancel_bulk_action"
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        """Cancel the bulk action."""
        await interaction.response.edit_message(
            content="✅ Action cancelled.",
            embed=None,
            view=None
        )