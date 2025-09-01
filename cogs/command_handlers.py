# -*- coding: utf-8 -*-
"""
Module containing command handlers for Docker container actions.
These are implemented as a mixin class to be used with the main DockerControlCog.
"""
import logging
import asyncio
from datetime import datetime, timezone
import discord
from discord.ext import commands
from typing import Dict, Any, Optional

# Import necessary utilities
from utils.logging_utils import setup_logger
from services.docker_service.docker_utils import docker_action
from services.infrastructure.action_logger import log_user_action

# Import helper functions
from .control_helpers import _channel_has_permission
from .translation_manager import _

# Configure logger for this module
logger = setup_logger('ddc.command_handlers', level=logging.DEBUG)

class CommandHandlersMixin:
    """
    Mixin class containing command handler functionality for DockerControlCog.
    Handles Docker container action commands like start, stop, restart.
    """
    
    async def _impl_command(self, ctx: discord.ApplicationContext, container_name: str, action: str):
        """
        Implementation of the Docker container action command.
        Executes a Docker action (start, stop, restart) on a specified container.
        
        Parameters:
        - ctx: Discord ApplicationContext
        - container_name: The name of the Docker container to control
        - action: The action to perform (start, stop, restart)
        """
        # Check action-specific spam protection for start/stop/restart
        if action.lower() in ['start', 'stop', 'restart']:
            from services.infrastructure.spam_protection_service import get_spam_protection_service
            spam_manager = get_spam_protection_service()
            if spam_manager.is_enabled():
                try:
                    if spam_manager.is_on_cooldown(ctx.author.id, action.lower()):
                        remaining_time = spam_manager.get_remaining_cooldown(ctx.author.id, action.lower())
                        await ctx.respond(f"⏰ Please wait {remaining_time:.1f} seconds before using '{action}' again.", ephemeral=True)
                        return
                    spam_manager.add_user_cooldown(ctx.author.id, action.lower())
                except Exception as e:
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.error(f"Spam protection error for action '{action}': {e}")

        # Validate channel
        if not ctx.channel or not isinstance(ctx.channel, discord.TextChannel):
            await ctx.respond(_("This command can only be used in server channels."), ephemeral=True)
            return

        # Check permissions
        config = self.config
        if not _channel_has_permission(ctx.channel.id, 'command', config):
            await ctx.respond(_("You do not have permission to use this command in this channel."), ephemeral=True)
            return
        if not _channel_has_permission(ctx.channel.id, 'control', config):
            await ctx.respond(_("Container control actions are generally disabled in this channel."), ephemeral=True)
            return

        # Find server configuration
        docker_name = container_name
        server_conf = next((s for s in config.get('servers', []) if s.get('docker_name') == docker_name), None)

        if not server_conf:
            await ctx.respond(_("Error: Server configuration for '{docker_name}' not found.").format(docker_name=docker_name), ephemeral=True)
            return

        display_name = server_conf.get('name', docker_name)
        internal_action = action

        if not internal_action:
            await ctx.respond(_("Invalid action specified."), ephemeral=True)
            return

        # Check if action is allowed for this container
        allowed_actions = server_conf.get('allowed_actions', [])
        if internal_action not in allowed_actions:
            await ctx.respond(_("Error: Action '{action}' is not allowed for {server_name}.").format(
                action=action, 
                server_name=display_name
            ), ephemeral=True)
            return

        # Mark container as pending action
        now = datetime.now(timezone.utc)
        self.pending_actions[display_name] = {'timestamp': now, 'action': internal_action}
        logger.debug(f"[COMMAND] Set pending state for '{display_name}' at {now} with action '{internal_action}'")

        # Defer reply
        await ctx.defer(ephemeral=False)
        
        # Log the action
        logger.info(f"Docker action '{internal_action}' for {display_name} requested by {ctx.author} in {ctx.channel.name}")
        log_user_action(
            action="COMMAND", 
            target=f"{display_name} ({internal_action})", 
            user=str(ctx.author), 
            source="Discord Command", 
            details=f"Channel: {ctx.channel.name}"
        )

        # Execute Docker action
        success = await docker_action(docker_name, internal_action)

        # Process result and respond
        action_process_keys = {
            "start": "started_process",
            "stop": "stopped_process",
            "restart": "restarted_process"
        }
        action_process_text = _(action_process_keys.get(internal_action, internal_action))

        if success:
            # Success response
            embed = discord.Embed(
                title=_("✅ Server Action Initiated"),
                description=_("Server **{server_name}** is being processed {action_process_text}.").format(
                    server_name=display_name, 
                    action_process_text=action_process_text
                ),
                color=discord.Color.green()
            )
            embed.add_field(name=_("Action"), value=f"`{internal_action.upper()}`", inline=True)
            embed.add_field(name=_("Executed by"), value=ctx.author.mention, inline=True)
            embed.set_footer(text=_("Docker container: {docker_name}").format(docker_name=docker_name))
            await ctx.followup.send(embed=embed)

            # Update status message
            await asyncio.sleep(1)
            logger.debug(f"[COMMAND] Triggering main status message update for {display_name} in {ctx.channel.name} after action.")
            await self.send_server_status(ctx.channel, server_conf, self.config)

        else:
            # Failed action response
            if display_name in self.pending_actions:
                del self.pending_actions[display_name]
                logger.debug(f"[COMMAND] Removed pending state for '{display_name}' due to action failure.")

            embed = discord.Embed(
                title=_("❌ Server Action Failed"),
                description=_("Server **{server_name}** could not be processed {action_process_text}.").format(
                    server_name=display_name, 
                    action_process_text=action_process_text
                ),
                color=discord.Color.red()
            )
            embed.add_field(name=_("Action"), value=f"`{internal_action.upper()}`", inline=True)
            embed.add_field(name=_("Error"), value=_("Docker command failed or timed out"), inline=True)
            embed.set_footer(text=_("Docker container: {docker_name}").format(docker_name=docker_name))
            await ctx.followup.send(embed=embed)

            # Update status message
            await asyncio.sleep(1)
            logger.debug(f"[COMMAND] Triggering main status message update for {display_name} in {ctx.channel.name} after failed action.")
            await self.send_server_status(ctx.channel, server_conf, self.config)
    
    async def _impl_info_edit(self, ctx: discord.ApplicationContext, container_name: str):
        """
        LEGACY: Implementation of the old info edit command.
        This is kept for backward compatibility with /ddc info edit command.
        For new functionality, use _impl_info_edit_new instead.
        """
        # Delegate to the new implementation
        await self._impl_info_edit_new(ctx, container_name)
    
    async def _impl_info_edit_new(self, ctx: discord.ApplicationContext, container_name: str):
        """
        Enhanced implementation of the info edit command using separate JSON files.
        Opens a modal to edit container information stored in individual JSON files.
        
        Parameters:
        - ctx: Discord ApplicationContext
        - container_name: The name of the Docker container to edit info for
        """
        # Validate channel
        if not ctx.channel or not isinstance(ctx.channel, discord.TextChannel):
            await ctx.respond(_("This command can only be used in server channels."), ephemeral=True)
            return

        # Check permissions - info edit requires control permission
        config = self.config
        if not _channel_has_permission(ctx.channel.id, 'control', config):
            await ctx.respond(_("You do not have permission to edit container info in this channel."), ephemeral=True)
            return

        # Find server configuration to get display name
        docker_name = container_name
        server_conf = next((s for s in config.get('servers', []) if s.get('docker_name') == docker_name), None)
        
        display_name = server_conf.get('name', docker_name) if server_conf else docker_name

        # Log the action
        logger.info(f"Enhanced info edit for {display_name} requested by {ctx.author} in {ctx.channel.name}")
        log_user_action(
            action="INFO_EDIT_CMD_NEW", 
            target=display_name, 
            user=str(ctx.author), 
            source="Discord Command", 
            details=f"Channel: {ctx.channel.name}, Container: {docker_name}"
        )

        # Create and show simplified modal (single dialog with all options)
        try:
            logger.info(f"Attempting to import SimplifiedContainerInfoModal...")
            from .enhanced_info_modal_simple import SimplifiedContainerInfoModal
            logger.info(f"Import successful")
            
            logger.info(f"Creating modal instance for {docker_name}...")
            modal = SimplifiedContainerInfoModal(
                self,
                container_name=docker_name,
                display_name=display_name
            )
            logger.info(f"Modal created successfully: {modal}")
            logger.info(f"Modal title: {modal.title}")
            logger.info(f"Modal children count: {len(modal.children)}")
            
            logger.info(f"Attempting to send modal...")
            await ctx.response.send_modal(modal)
            logger.info(f"Modal sent successfully")
            
        except ImportError as e:
            logger.error(f"Import error: {e}", exc_info=True)
            await ctx.respond(f"Error loading modal module: {str(e)}", ephemeral=True)
        except Exception as e:
            logger.error(f"Error creating/sending modal: {e}", exc_info=True)
            logger.error(f"Exception type: {type(e).__name__}")
            logger.error(f"Container: {docker_name}, Display: {display_name}")
            await ctx.respond(f"Error: {str(e)[:100]}", ephemeral=True) 
    
    async def _impl_info_debug(self, ctx: discord.ApplicationContext, container_name: str):
        """Debug version of the info edit command without translations."""
        # Validate channel
        if not ctx.channel or not isinstance(ctx.channel, discord.TextChannel):
            await ctx.respond("This command can only be used in server channels.", ephemeral=True)
            return

        # Check permissions - info edit requires control permission
        config = self.config
        if not _channel_has_permission(ctx.channel.id, 'control', config):
            await ctx.respond("You do not have permission to edit container info in this channel.", ephemeral=True)
            return

        # Find server configuration to get display name
        docker_name = container_name
        server_conf = next((s for s in config.get('servers', []) if s.get('docker_name') == docker_name), None)
        
        display_name = server_conf.get('name', docker_name) if server_conf else docker_name

        # Log the action
        logger.info(f"Debug info edit for {display_name} requested by {ctx.author} in {ctx.channel.name}")

        # Create and show debug modal
        try:
            logger.info(f"Debug: Attempting to import DebugContainerInfoModal...")
            from .debug_modal_simple import DebugContainerInfoModal
            logger.info(f"Debug: Import successful")
            
            logger.info(f"Debug: Creating modal instance...")
            modal = DebugContainerInfoModal(
                self,
                container_name=docker_name,
                display_name=display_name
            )
            logger.info(f"Debug: Modal created: {modal}")
            
            logger.info(f"Debug: Sending modal...")
            await ctx.response.send_modal(modal)
            logger.info(f"Debug: Modal sent")
            
        except Exception as e:
            logger.error(f"Debug modal error: {e}", exc_info=True)
            await ctx.respond(f"Debug error: {str(e)}", ephemeral=True)
    
    async def _impl_minimal_test(self, ctx: discord.ApplicationContext):
        """Ultra-minimal modal test."""
        try:
            logger.info("Minimal test: Starting...")
            from .minimal_test_modal import MinimalTestModal
            logger.info("Minimal test: Import successful")
            
            modal = MinimalTestModal()
            logger.info(f"Minimal test: Modal created: {modal}")
            
            await ctx.response.send_modal(modal)
            logger.info("Minimal test: Modal sent")
            
        except Exception as e:
            logger.error(f"Minimal test error: {e}", exc_info=True)
            await ctx.respond(f"Minimal test error: {str(e)}", ephemeral=True)