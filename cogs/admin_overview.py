# =============================================================================
# ADMIN OVERVIEW VIEW FOR CONTROL CHANNELS - SERVICE FIRST IMPLEMENTATION
# =============================================================================

import discord
from discord.ui import View, Button
import asyncio
import logging
from datetime import datetime, timezone

# SERVICE FIRST: Import all required services
from services.admin.admin_service import get_admin_service
from services.status.status_cache_service import get_status_cache_service
from services.config.server_config_service import get_server_config_service
from services.config.config_service import load_config  # Keep for backward compatibility

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
        self.add_item(AdminOverviewDonateButton(cog_instance, channel_id))

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
        # Edge case: Immediately defer to avoid timeout
        try:
            await interaction.response.defer(ephemeral=True)
            deferred = True
        except discord.errors.NotFound:
            logger.warning(f"Admin button interaction expired for channel {self.channel_id}")
            return
        except (discord.errors.HTTPException, discord.errors.DiscordException) as e:
            logger.error(f"Error deferring admin button interaction: {e}", exc_info=True)
            return

        try:
            # SERVICE FIRST: Use AdminService to check permissions
            admin_service = get_admin_service()
            user_id = str(interaction.user.id)

            # Check if user is admin using service
            is_admin = await admin_service.is_user_admin_async(user_id)
            if not is_admin:
                await interaction.followup.send(
                    "❌ You don't have permission to use admin controls.",
                    ephemeral=True
                )
                return

            # SERVICE FIRST: Use ServerConfigService to get containers
            server_config_service = get_server_config_service()
            # Use get_all_servers() to get full container data including 'order' field
            all_servers = server_config_service.get_all_servers()

            if not all_servers:
                await interaction.followup.send(
                    "❌ No containers found in configuration.",
                    ephemeral=True
                )
                return

            # Sort containers by order field (from Web UI configuration)
            containers = sorted(all_servers, key=lambda s: s.get('order', 999))

            # Transform to the format expected by AdminContainerSelectView
            formatted_containers = []
            for server in containers:
                docker_name = server.get('docker_name')
                if docker_name:
                    # Get display name from server config
                    display_name = server.get('display_name', [docker_name, docker_name])
                    if isinstance(display_name, list) and len(display_name) > 0:
                        display_name = display_name[0]

                    formatted_containers.append({
                        'display': display_name,
                        'docker_name': docker_name,
                        'order': server.get('order', 999)  # Include order for dropdown sorting
                    })

            containers = formatted_containers

            if not containers:
                await interaction.followup.send(
                    "❌ No valid containers found in configuration.",
                    ephemeral=True
                )
                return

            # Import AdminContainerSelectView from control_ui
            try:
                from .control_ui import AdminContainerSelectView
            except ImportError as e:
                logger.error(f"Failed to import AdminContainerSelectView: {e}")
                await interaction.followup.send(
                    "❌ Internal error. Please try again later.",
                    ephemeral=True
                )
                return

            # Create dropdown view with containers list
            view = AdminContainerSelectView(self.cog, containers, self.channel_id)
            await interaction.followup.send(
                "Select a container to control:",
                view=view,
                ephemeral=True
            )

        except (discord.errors.DiscordException, ImportError, AttributeError, KeyError) as e:
            logger.error(f"Error in admin overview admin button: {e}", exc_info=True)
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        "❌ Error accessing admin controls.",
                        ephemeral=True
                    )
            except (discord.errors.NotFound, discord.errors.HTTPException):
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
        # Edge case: Immediately defer to avoid timeout
        try:
            await interaction.response.defer(ephemeral=True)
        except discord.errors.NotFound:
            logger.warning(f"Restart all interaction expired for channel {self.channel_id}")
            return
        except (discord.errors.HTTPException, discord.errors.DiscordException) as e:
            logger.error(f"Error deferring restart all interaction: {e}", exc_info=True)
            return

        try:
            # SERVICE FIRST: Use AdminService to check permissions
            admin_service = get_admin_service()
            user_id = str(interaction.user.id)

            # Check if user is admin using service
            is_admin = await admin_service.is_user_admin_async(user_id)
            if not is_admin:
                await interaction.followup.send(
                    "❌ You don't have permission to restart all containers.",
                    ephemeral=True
                )
                return

            # Edge case: Check if button is already disabled
            if self.disabled:
                await interaction.followup.send(
                    "❌ No running containers to restart.",
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
            await interaction.followup.send(
                embed=embed,
                view=view,
                ephemeral=True
            )

        except (discord.errors.DiscordException, ImportError, KeyError, RuntimeError) as e:
            logger.error(f"Error in restart all button: {e}", exc_info=True)
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        "❌ Error processing restart all request.",
                        ephemeral=True
                    )
            except (discord.errors.NotFound, discord.errors.HTTPException):
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
        # Edge case: Immediately defer to avoid timeout
        try:
            await interaction.response.defer(ephemeral=True)
        except discord.errors.NotFound:
            logger.warning(f"Stop all interaction expired for channel {self.channel_id}")
            return
        except (discord.errors.HTTPException, discord.errors.DiscordException) as e:
            logger.error(f"Error deferring stop all interaction: {e}", exc_info=True)
            return

        try:
            # SERVICE FIRST: Use AdminService to check permissions
            admin_service = get_admin_service()
            user_id = str(interaction.user.id)

            # Check if user is admin using service
            is_admin = await admin_service.is_user_admin_async(user_id)
            if not is_admin:
                await interaction.followup.send(
                    "❌ You don't have permission to stop all containers.",
                    ephemeral=True
                )
                return

            # Edge case: Check if button is already disabled
            if self.disabled:
                await interaction.followup.send(
                    "❌ No running containers to stop.",
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
            await interaction.followup.send(
                embed=embed,
                view=view,
                ephemeral=True
            )

        except (discord.errors.DiscordException, ImportError, KeyError, RuntimeError) as e:
            logger.error(f"Error in stop all button: {e}", exc_info=True)
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        "❌ Error processing stop all request.",
                        ephemeral=True
                    )
            except (discord.errors.NotFound, discord.errors.HTTPException):
                pass

class AdminOverviewDonateButton(Button):
    """Donate button for supporting the project."""

    def __init__(self, cog_instance, channel_id: int):
        self.cog = cog_instance
        self.channel_id = channel_id

        super().__init__(
            style=discord.ButtonStyle.success,  # Green button
            label=None,  # No text, only icon
            emoji="💖",  # Heart icon for donations
            custom_id=f"admin_overview_donate_{channel_id}",
            row=0
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        """Execute /donate command when clicked."""
        # Edge case: Immediately defer to avoid timeout
        try:
            await interaction.response.defer(ephemeral=True)
        except discord.errors.NotFound:
            logger.warning(f"Donate button interaction expired for channel {self.channel_id}")
            return
        except (discord.errors.HTTPException, discord.errors.DiscordException) as e:
            logger.error(f"Error deferring donate button interaction: {e}", exc_info=True)
            return

        try:
            # Check if donations are disabled
            try:
                from services.donation.donation_utils import is_donations_disabled
                if is_donations_disabled():
                    # Donations disabled, send minimal response
                    try:
                        await interaction.followup.send(".", delete_after=0.1)
                    except (discord.errors.HTTPException, discord.errors.NotFound) as e:
                        logger.debug(f"Failed to send donation disabled response: {e}")
                    return
            except ImportError as e:
                logger.warning(f"Donation utils not available: {e}")
            except (AttributeError, RuntimeError) as e:
                logger.debug(f"Donation check failed: {e}")

            # Create donation embed (matching the /donate command)
            from .translation_manager import _ as translate

            embed = discord.Embed(
                title=translate('Support DockerDiscordControl'),
                description=translate(
                    'If DDC helps you, please consider supporting ongoing development. '
                    'Donations help cover hosting, CI, maintenance, and feature work.'
                ),
                color=0x00ff41  # Green color
            )
            embed.add_field(
                name=translate('Choose your preferred method:'),
                value=translate('Click one of the buttons below to support DDC development'),
                inline=False
            )

            # Create donation view with buttons
            # Check MechService availability (same as /donate command)
            mech_service_available = False
            try:
                from services.mech.mech_service import get_mech_service
                mech_service = get_mech_service()
                mech_service_available = True
            except:
                pass

            # Import DonationView from docker_control
            from .docker_control import DonationView
            view = DonationView(mech_service_available, bot=self.cog.bot)

            # Send the donation embed with buttons
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)

        except (discord.errors.DiscordException, ImportError, AttributeError) as e:
            logger.error(f"Error in donate button: {e}", exc_info=True)
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        "❌ Error processing donate request.",
                        ephemeral=True
                    )
            except (discord.errors.NotFound, discord.errors.HTTPException):
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
        # Edge case: Defer immediately
        try:
            await interaction.response.defer()
        except discord.errors.NotFound:
            logger.warning("Restart all confirmation interaction expired")
            return
        except (discord.errors.HTTPException, discord.errors.DiscordException) as e:
            logger.error(f"Error deferring restart all confirmation: {e}", exc_info=True)
            return

        # Edge case: Prevent concurrent bulk operations
        if hasattr(self.cog, '_bulk_operation_in_progress'):
            if self.cog._bulk_operation_in_progress:
                await interaction.followup.send(
                    "⏳ Another bulk operation is in progress. Please wait.",
                    ephemeral=True
                )
                return

        # Set operation lock
        self.cog._bulk_operation_in_progress = True

        try:
            # SERVICE FIRST: Use ServerConfigService to get server configurations
            server_config_service = get_server_config_service()
            all_servers = server_config_service.get_all_servers()

            # CRITICAL: Filter to only ACTIVE containers (as shown in Admin Overview)
            servers = [s for s in all_servers if s.get('active', False)]

            if not servers:
                await interaction.followup.send(
                    "❌ No active servers configured.",
                    ephemeral=True
                )
                return

            logger.info(f"Restart All: Processing {len(servers)} active containers (filtered from {len(all_servers)} total)")

            restarted_count = 0
            failed_count = 0
            skipped_count = 0

            # Import docker service with error handling
            try:
                from services.docker_service.docker_action_service import docker_action_service_first
            except ImportError as e:
                logger.error(f"Failed to import docker action service: {e}")
                await interaction.followup.send(
                    "❌ Docker service unavailable. Operation cancelled.",
                    ephemeral=True
                )
                return

            # Process containers with rate limiting
            for server in servers:
                if not isinstance(server, dict):
                    continue

                docker_name = server.get('docker_name')
                if not docker_name or not isinstance(docker_name, str):
                    continue

                # SERVICE FIRST: Use StatusCacheService to check if container is running
                # IMPORTANT: Always use docker_name for cache lookups (stable identifier)
                status_cache_service = get_status_cache_service()
                cached_entry = status_cache_service.get(docker_name)

                # Extract is_running from cache data (ContainerStatusResult object)
                is_running = False
                if cached_entry and cached_entry.get('data'):
                    status_result = cached_entry['data']
                    # Modern format: ContainerStatusResult dataclass
                    from services.docker_status.models import ContainerStatusResult
                    if isinstance(status_result, ContainerStatusResult):
                        is_running = status_result.is_running
                    # Backwards compatibility: old tuple format
                    elif isinstance(status_result, tuple) and len(status_result) >= 2:
                        is_running = status_result[1]

                if is_running:
                                # Restart container with timeout protection
                                try:
                                    # Add small delay between operations to avoid overloading
                                    if restarted_count > 0:
                                        await asyncio.sleep(0.5)

                                    # Set timeout for docker operation
                                    success = await asyncio.wait_for(
                                        docker_action_service_first(docker_name, "restart"),
                                        timeout=30.0  # 30 second timeout per container
                                    )
                                    if success:
                                        restarted_count += 1
                                        logger.info(f"Successfully restarted {docker_name}")
                                    else:
                                        failed_count += 1
                                        logger.warning(f"Failed to restart {docker_name}")
                                except asyncio.TimeoutError:
                                    logger.error(f"Timeout restarting {docker_name}")
                                    failed_count += 1
                                except (RuntimeError, OSError) as e:
                                    logger.error(f"Error restarting {docker_name}: {e}", exc_info=True)
                                    failed_count += 1
                else:
                    skipped_count += 1

            # Send result message
            description = f"Successfully restarted: **{restarted_count}** containers"
            if failed_count > 0:
                description += f"\nFailed: **{failed_count}** containers"
            if skipped_count > 0:
                description += f"\nSkipped (not running): **{skipped_count}** containers"

            embed = discord.Embed(
                title="🔄 Restart All Complete",
                description=description,
                color=discord.Color.green() if failed_count == 0 else discord.Color.orange()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)

            # Update admin overview after a delay (but don't wait for it)
            asyncio.create_task(self._delayed_overview_update())

        except (ImportError, KeyError, RuntimeError, asyncio.TimeoutError) as e:
            logger.error(f"Critical error in restart all: {e}", exc_info=True)
            try:
                await interaction.followup.send(
                    "❌ An error occurred during the restart operation.",
                    ephemeral=True
                )
            except (discord.errors.NotFound, discord.errors.HTTPException):
                pass
        finally:
            # Always release the lock
            self.cog._bulk_operation_in_progress = False

    async def _delayed_overview_update(self):
        """Update admin overview after a delay."""
        try:
            await asyncio.sleep(5)
            await self._update_admin_overview()
        except (asyncio.CancelledError, RuntimeError) as e:
            logger.error(f"Error updating admin overview after restart: {e}", exc_info=True)

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
                            # SERVICE FIRST: Recreate admin overview using service
                            server_config_service = get_server_config_service()
                            ordered_servers = server_config_service.get_ordered_servers()
                            config = load_config()  # Still need config for embed creation

                            new_embed, _, has_running = await self.cog._create_admin_overview_embed(ordered_servers, config)
                            new_view = AdminOverviewView(self.cog, self.channel_id, has_running)

                            await message.edit(embed=new_embed, view=new_view)
                            break
        except (discord.errors.DiscordException, ImportError, AttributeError) as e:
            logger.error(f"Error updating admin overview: {e}", exc_info=True)

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
        # Edge case: Defer immediately
        try:
            await interaction.response.defer()
        except discord.errors.NotFound:
            logger.warning("Stop all confirmation interaction expired")
            return
        except (discord.errors.HTTPException, discord.errors.DiscordException) as e:
            logger.error(f"Error deferring stop all confirmation: {e}", exc_info=True)
            return

        # Edge case: Prevent concurrent bulk operations
        if hasattr(self.cog, '_bulk_operation_in_progress'):
            if self.cog._bulk_operation_in_progress:
                await interaction.followup.send(
                    "⏳ Another bulk operation is in progress. Please wait.",
                    ephemeral=True
                )
                return

        # Set operation lock
        self.cog._bulk_operation_in_progress = True

        try:
            # SERVICE FIRST: Use ServerConfigService to get server configurations
            server_config_service = get_server_config_service()
            all_servers = server_config_service.get_all_servers()

            # CRITICAL: Filter to only ACTIVE containers (as shown in Admin Overview)
            servers = [s for s in all_servers if s.get('active', False)]

            if not servers:
                await interaction.followup.send(
                    "❌ No active servers configured.",
                    ephemeral=True
                )
                return

            logger.info(f"Stop All: Processing {len(servers)} active containers (filtered from {len(all_servers)} total)")

            stopped_count = 0
            failed_count = 0
            skipped_count = 0

            # Import docker service with error handling
            try:
                from services.docker_service.docker_action_service import docker_action_service_first
            except ImportError as e:
                logger.error(f"Failed to import docker action service: {e}")
                await interaction.followup.send(
                    "❌ Docker service unavailable. Operation cancelled.",
                    ephemeral=True
                )
                return

            # Process containers with rate limiting
            for server in servers:
                if not isinstance(server, dict):
                    continue

                docker_name = server.get('docker_name')
                if not docker_name or not isinstance(docker_name, str):
                    continue

                # SERVICE FIRST: Use StatusCacheService to check if container is running
                # IMPORTANT: Always use docker_name for cache lookups (stable identifier)
                status_cache_service = get_status_cache_service()
                cached_entry = status_cache_service.get(docker_name)

                # Extract is_running from cache data (ContainerStatusResult object)
                is_running = False
                if cached_entry and cached_entry.get('data'):
                    status_result = cached_entry['data']
                    # Modern format: ContainerStatusResult dataclass
                    from services.docker_status.models import ContainerStatusResult
                    if isinstance(status_result, ContainerStatusResult):
                        is_running = status_result.is_running
                    # Backwards compatibility: old tuple format
                    elif isinstance(status_result, tuple) and len(status_result) >= 2:
                        is_running = status_result[1]

                if is_running:
                                # Stop container with timeout protection
                                try:
                                    # Add small delay between operations to avoid overloading
                                    if stopped_count > 0:
                                        await asyncio.sleep(0.5)

                                    # Set timeout for docker operation
                                    success = await asyncio.wait_for(
                                        docker_action_service_first(docker_name, "stop"),
                                        timeout=30.0  # 30 second timeout per container
                                    )
                                    if success:
                                        stopped_count += 1
                                        logger.info(f"Successfully stopped {docker_name}")
                                    else:
                                        failed_count += 1
                                        logger.warning(f"Failed to stop {docker_name}")
                                except asyncio.TimeoutError:
                                    logger.error(f"Timeout stopping {docker_name}")
                                    failed_count += 1
                                except (RuntimeError, OSError) as e:
                                    logger.error(f"Error stopping {docker_name}: {e}", exc_info=True)
                                    failed_count += 1
                else:
                    skipped_count += 1

            # Send result message
            description = f"Successfully stopped: **{stopped_count}** containers"
            if failed_count > 0:
                description += f"\nFailed: **{failed_count}** containers"
            if skipped_count > 0:
                description += f"\nSkipped (not running): **{skipped_count}** containers"

            embed = discord.Embed(
                title="⏹️ Stop All Complete",
                description=description,
                color=discord.Color.green() if failed_count == 0 else discord.Color.orange()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)

            # Update admin overview after a delay (but don't wait for it)
            asyncio.create_task(self._delayed_overview_update())

        except (ImportError, KeyError, RuntimeError, asyncio.TimeoutError) as e:
            logger.error(f"Critical error in stop all: {e}", exc_info=True)
            try:
                await interaction.followup.send(
                    "❌ An error occurred during the stop operation.",
                    ephemeral=True
                )
            except (discord.errors.NotFound, discord.errors.HTTPException):
                pass
        finally:
            # Always release the lock
            self.cog._bulk_operation_in_progress = False

    async def _delayed_overview_update(self):
        """Update admin overview after a delay."""
        try:
            await asyncio.sleep(5)
            await self._update_admin_overview()
        except (asyncio.CancelledError, RuntimeError) as e:
            logger.error(f"Error updating admin overview after stop: {e}", exc_info=True)

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
                            # SERVICE FIRST: Recreate admin overview using service
                            server_config_service = get_server_config_service()
                            ordered_servers = server_config_service.get_ordered_servers()
                            config = load_config()  # Still need config for embed creation

                            new_embed, _, has_running = await self.cog._create_admin_overview_embed(ordered_servers, config)
                            new_view = AdminOverviewView(self.cog, self.channel_id, has_running)

                            await message.edit(embed=new_embed, view=new_view)
                            break
        except (discord.errors.DiscordException, ImportError, AttributeError) as e:
            logger.error(f"Error updating admin overview: {e}", exc_info=True)

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
        try:
            await interaction.response.edit_message(
                content="✅ Action cancelled.",
                embed=None,
                view=None
            )
        except discord.errors.NotFound:
            logger.warning("Cancel button interaction expired")
        except (discord.errors.HTTPException, discord.errors.DiscordException) as e:
            logger.error(f"Error in cancel button: {e}", exc_info=True)