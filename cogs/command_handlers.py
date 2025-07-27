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
from utils.docker_utils import docker_action
from utils.action_logger import log_user_action

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
        Implementation of the info edit command.
        Opens a modal to edit container information.
        
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

        # Find server configuration
        docker_name = container_name
        server_conf = next((s for s in config.get('servers', []) if s.get('docker_name') == docker_name), None)

        if not server_conf:
            await ctx.respond(_("Error: Server configuration for '{docker_name}' not found.").format(docker_name=docker_name), ephemeral=True)
            return

        display_name = server_conf.get('name', docker_name)
        info_config = server_conf.get('info', {})

        # Check if info is enabled
        if not info_config.get('enabled', False):
            await ctx.respond(_("Container info is not enabled for **{display_name}**. Enable it in the web UI first.").format(display_name=display_name), ephemeral=True)
            return

        # Log the action
        logger.info(f"Info edit for {display_name} requested by {ctx.author} in {ctx.channel.name}")
        log_user_action(
            action="INFO_EDIT_CMD", 
            target=display_name, 
            user=str(ctx.author), 
            source="Discord Command", 
            details=f"Channel: {ctx.channel.name}"
        )

        # Create and show modal
        from .control_ui import ContainerInfoModal
        modal = ContainerInfoModal(
            self,
            server_conf,
            info_config,
            can_edit=True
        )
        
        await ctx.response.send_modal(modal) 