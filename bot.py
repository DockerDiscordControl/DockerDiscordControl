# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #

import os
import sys
import asyncio
import logging
# Fix for audioop module in Python 3.13
try:
    import audioop
except ImportError:
    import audioop_lts as audioop
    sys.modules['audioop'] = audioop
import discord
import json
import random
import traceback
import time
import pytz
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
from pathlib import Path
from discord.ext import commands
import signal

# Set the environment variable for direct token access
if 'DDC_DISCORD_SKIP_TOKEN_LOCK' not in os.environ:
    os.environ['DDC_DISCORD_SKIP_TOKEN_LOCK'] = 'true'

# Import custom modules
from utils.config_loader import load_config, save_config
from utils.logging_utils import setup_logger, refresh_debug_status, setup_all_loggers
from utils.config_cache import init_config_cache, get_cached_config
# Import new features with backwards compatibility
try:
    from utils.dynamic_cooldown_manager import apply_dynamic_cooldowns_to_bot
    dynamic_cooldowns_available = True
except ImportError:
    logger.warning("Dynamic cooldowns not available - using legacy cooldowns")
    dynamic_cooldowns_available = False
    apply_dynamic_cooldowns_to_bot = lambda bot: None

try:
    from utils.update_notifier import get_update_notifier
    update_notifier_available = True
except ImportError:
    logger.warning("Update notifier not available - skipping update notifications")
    update_notifier_available = False

try:
    from utils.donation_manager import get_donation_manager
    donation_manager_available = True
except ImportError:
    logger.warning("Donation manager not available - skipping donation messages")
    donation_manager_available = False
# Import the internal translation system
from cogs.translation_manager import _, get_translations
# Import scheduler service
from utils.scheduler_service import start_scheduler_service, stop_scheduler_service
# Import the centralized action logger (ensures proper logger initialization)
from utils.action_logger import log_user_action, user_action_logger
# Import cogs helper functions
from cogs.control_helpers import container_select
# Import port diagnostics
from app.utils.port_diagnostics import log_port_diagnostics

# Import app_commands using central utility
from utils.app_commands_helper import initialize_app_commands
app_commands, DiscordOption, app_commands_available = initialize_app_commands()

# Preliminary logger for the import phase
_import_logger = logging.getLogger("discord.app_commands_import")

# Direct access to config_manager, if available, for better token decryption
try:
    from utils.config_manager import get_config_manager
    config_manager_available = True
except ImportError:
    config_manager_available = False

# Load configuration ONCE here
loaded_main_config = load_config()

# Initialize config cache for performance optimization
init_config_cache(loaded_main_config)

# Set timezone for logging from configuration
timezone_str = loaded_main_config.get('timezone', 'Europe/Berlin')
try:
    # Use a preliminary print statement because logger is not yet available
    print(f"Attempting to set timezone to: {timezone_str}")
    tz = pytz.timezone(timezone_str)
    print(f"Successfully set timezone to: {tz}")
except pytz.exceptions.UnknownTimeZoneError:
    print(f"WARNING: Unknown timezone '{timezone_str}'. Falling back to UTC for this session.")
    tz = pytz.timezone('UTC')
except Exception as e:
    print(f"ERROR setting timezone '{timezone_str}': {e}. Falling back to UTC for this session.")
    tz = pytz.timezone('UTC')

# Setup logging (NOW the logger is available)
logger = setup_logger('ddc.bot', level=logging.INFO)

# Ensure Web UI log files exist and receive content
def _attach_bot_file_handlers(bot_logger: logging.Logger) -> None:
    try:
        logs_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
        os.makedirs(logs_dir, exist_ok=True)

        # Discord bot combined log (INFO and above)
        discord_log_path = os.path.join(logs_dir, 'discord.log')
        if not any(isinstance(h, logging.FileHandler) and getattr(h, 'baseFilename', '').endswith('discord.log') for h in bot_logger.handlers):
            fh_info = logging.FileHandler(discord_log_path, encoding='utf-8')
            fh_info.setLevel(logging.INFO)
            fh_info.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
            bot_logger.addHandler(fh_info)

        # Bot error-only log (ERROR and above)
        bot_error_log_path = os.path.join(logs_dir, 'bot_error.log')
        if not any(isinstance(h, logging.FileHandler) and getattr(h, 'baseFilename', '').endswith('bot_error.log') for h in bot_logger.handlers):
            fh_err = logging.FileHandler(bot_error_log_path, encoding='utf-8')
            fh_err.setLevel(logging.ERROR)
            fh_err.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
            bot_logger.addHandler(fh_err)

        bot_logger.info("Bot file loggers initialized: discord.log (INFO+), bot_error.log (ERROR+)")
    except Exception as e:
        try:
            print(f"Failed to initialize bot file handlers: {e}")
        except Exception:
            pass

_attach_bot_file_handlers(logger)

# Now we can safely log the outcome
logger.info(f"Final effective timezone for logging and operations: {tz}")

# Language configuration
# Log config object WITHOUT the token for safety
# Use loaded_main_config
config_log_safe = loaded_main_config.copy()
if 'bot_token_decrypted_for_usage' in config_log_safe: # Use the decrypted key if available
    config_log_safe['bot_token'] = '********' # Mask the token
    del config_log_safe['bot_token_decrypted_for_usage'] # Remove decrypted for logging
else: # Fallback if decrypted key not present yet
    config_log_safe['bot_token'] = '********'

logger.info(f"Attempting to get language from config. Config object (token masked): {config_log_safe}") 
language = loaded_main_config.get('language', 'en') # Read normally from loaded_main_config
logger.info(f"Value read for 'language' from config: '{language}'") 
logger.info(f"Bot language is configured to: {language}")

# RAM-OPTIMIZED Discord Intents: Only essential intents for Docker Control Bot
intents = discord.Intents.none()    # Start with NO intents (minimal RAM usage)
intents.guilds = True               # Required: Access to guild info  
intents.guild_messages = True       # Required: Receive messages in guilds
intents.message_content = True      # Required: Read command content
# EXCLUDED for 70% RAM reduction:
# - guild_members (very memory-intensive for large servers)
# - presences (very memory-intensive for presence updates) 
# - guild_reactions (unnecessary for Docker control)
# - typing (unnecessary for Docker control)
# - voice_states (unnecessary for Docker control)

# Check the Discord module version and try to create an appropriate Bot instance
try:
    # Try with discord.Bot first (PyCord style)
    logger.info("Attempting to create bot with discord.Bot (PyCord style)...")
    bot = discord.Bot(intents=intents)
    logger.info("Successfully created bot with discord.Bot")
except (AttributeError, ImportError) as e:
    print(f"Could not create bot with discord.Bot: {e}")
    try:
        # Fallback to commands.Bot (discord.py style)
        logger.info("Falling back to commands.Bot (discord.py style)...")
        bot = commands.Bot(command_prefix='/', intents=intents)
        logger.info("Successfully created bot with commands.Bot")
    except Exception as e:
        logger.error(f"Failed to create bot instance with either method: {e}")
        raise

# Flag to prevent on_ready from executing code unnecessarily multiple times
_initial_startup_done = False

# Helper function for Autocomplete for the /command command
async def action_select(ctx, current):
    """ Returns a list of possible actions for a container for autocomplete.
    This function handles both discord.py and PyCord autocomplete contexts.
    Always returns a simple list of strings to avoid serialization issues.
    """
    config = get_cached_config()  # Performance optimization: use cache instead of load_config()
    
    # Extract the container name from the context
    container_name = None
    if hasattr(ctx, 'data') and isinstance(ctx.data, dict) and 'options' in ctx.data:
        # discord.py style - Interaction object
        options = ctx.data.get('options', [])
        container_option = next((opt for opt in options if opt.get('name') == 'container_name'), None)
        if container_option and container_option.get('value'):
            container_name = container_option.get('value')
    elif hasattr(ctx, 'options') and hasattr(ctx, 'focused'):
        # PyCord style - AutocompleteContext with options/focused
        try:
            for key, value in ctx.options.items():
                if key == 'container_name' and value:
                    container_name = value
                    break
        except (AttributeError, TypeError):
            pass
    
    # Extract the search text (current) from the context
    search_text = ""
    if isinstance(current, str):
        # discord.py style (for Interaction)
        search_text = current
    else:
        # PyCord style (for AutocompleteContext)
        try:
            # Try to extract the value from the context
            search_text = ctx.value or ""
        except (AttributeError, TypeError):
            # Fallback for other contexts
            _import_logger.debug(f"Unknown autocomplete context type: {type(ctx)}, current type: {type(current)}")
            search_text = ""
    
    # Determine the actions to display
    if not container_name:
        # If no container is selected, show default actions
        actions = ["start", "stop", "restart"]
    else:
        # Container is selected, get allowed actions for this container
        servers = config.get('servers', [])
        server_conf = next((s for s in servers if s.get('docker_name') == container_name), None)
        
        if server_conf:
            actions = server_conf.get('allowed_actions', ["start", "stop", "restart"])
        else:
            # Container not found, show default actions
            actions = ["start", "stop", "restart"]
    
    # Filter based on input (if any)
    if search_text:
        # Safe string matching
        search_text_lower = search_text.lower() if hasattr(search_text, 'lower') else str(search_text).lower()
        actions = [action for action in actions if search_text_lower in action.lower()]
    
    # Return a simple list of strings - NOT dict or Choice objects
    logger.debug(f"action_select: Returning {len(actions)} items as simple strings")
    return actions[:25]

# Function to set up application commands with slash command choices and autocomplete
def setup_app_commands():
    try:
        logger.info("Setting up application commands with choices and autocomplete...")
        
        # Check if we're using discord.py style
        if hasattr(bot, 'tree'):
            # discord.py style - use command tree
            command = app_commands.Command(
                name="command",
                description="Controls a Docker container",
                callback=lambda interaction, container_name, action: 
                    bot.get_cog('DockerControlCog').command_interaction_handler(interaction, container_name, action)
            )
            
            # Add container_name parameter with autocomplete
            container_param = app_commands.describe(container_name="The Docker container to control")(
                app_commands.Parameter(
                    name="container_name",
                    description="The Docker container to control",
                    type=app_commands.AppCommandOptionType.string,
                    required=True,
                    autocomplete=container_select
                )
            )
            
            # Add action parameter with autocomplete
            action_param = app_commands.describe(action="The action to perform")(
                app_commands.Parameter(
                    name="action",
                    description="The action to perform",
                    type=app_commands.AppCommandOptionType.string,
                    required=True,
                    autocomplete=action_select
                )
            )
            
            # Add parameters to command
            command.parameters = [container_param, action_param]
            
            # Add command to the bot's command tree
            bot.tree.add_command(command)
            logger.info("Added /command to bot's command tree with autocomplete (discord.py style)")
            
        elif hasattr(bot, 'create_group'):
            # PyCord style
            try:
                # Use the Autocomplete-Decorator explicitly for PyCord
                from discord.commands import Option
                
                @bot.slash_command(name="command", description="Controls a Docker container")
                async def command(
                    ctx,
                    container_name: Option(str, "The Docker container to control", autocomplete=container_select),
                    action: Option(str, "The action to perform", autocomplete=action_select)
                ):
                    await bot.get_cog('DockerControlCog').command(ctx, container_name, action)
                
                # Create command group for DDC subcommands
                ddc_group = bot.create_group("ddc", "DDC management commands")
                info_group = ddc_group.create_subgroup("info", "Container info commands")
                
                @info_group.command(name="edit", description="Edit container information")
                async def ddc_info_edit(
                    ctx,
                    container: Option(str, "The Docker container to edit info for", autocomplete=container_select)
                ):
                    """Edit container information."""
                    await bot.get_cog('DockerControlCog').info_edit(ctx, container)
                    
                logger.info("Added /command and /ddc info edit to bot with autocomplete (PyCord style)")
            except ImportError:
                # Fallback to normal registration without Option
                @bot.slash_command(name="command", description="Controls a Docker container")
                async def command(
                    ctx,
                    container_name: discord.Option(str, "The Docker container to control", autocomplete=container_select),
                    action: discord.Option(str, "The action to perform", autocomplete=action_select)
                ):
                    await bot.get_cog('DockerControlCog').command(ctx, container_name, action)
                
                # Create command group for DDC subcommands (fallback)
                ddc_group_fallback = bot.create_group("ddc", "DDC management commands")
                info_group_fallback = ddc_group_fallback.create_subgroup("info", "Container info commands")
                
                @info_group_fallback.command(name="edit", description="Edit container information")
                async def ddc_info_edit_fallback(
                    ctx,
                    container: discord.Option(str, "The Docker container to edit info for", autocomplete=container_select)
                ):
                    """Edit container information."""
                    await bot.get_cog('DockerControlCog').info_edit(ctx, container)
                    
                logger.info("Added /command and /ddc info edit to bot with autocomplete (PyCord fallback style)")
        
        else:
            logger.error("Could not set up application commands: Bot instance lacks expected attributes")
    
    except Exception as e:
        logger.error(f"Error setting up application commands: {e}", exc_info=True)

# Add the improved setup_schedule_commands function after the setup_app_commands function
def setup_schedule_commands():
    """Register schedule commands directly from the DockerControlCog.
    This improved implementation avoids duplicate command registration.
    """
    try:
        logger.info("Setting up schedule commands with improved implementation...")
        cog = bot.get_cog('DockerControlCog')
        if not cog:
            logger.error("Could not retrieve DockerControlCog instance for setting up schedule commands")
            return False

        # Get already registered command names
        registered_commands = []
        if hasattr(bot, 'application_commands'):
            registered_commands = [cmd.name for cmd in bot.application_commands]
        elif hasattr(bot.tree, '_global_commands') and bot.tree._global_commands:
            registered_commands = [cmd.name for cmd in bot.tree._global_commands.values()]
        
        logger.info(f"Currently registered commands: {registered_commands}")
        
        logger.info("MANUAL REGISTRATION IN setup_schedule_commands IS CURRENTLY DISABLED FOR TESTING.")
        logger.info("Relying on Cog registration and on_ready autocomplete assignment.")
        return True # Assume success as we are not doing anything here for now
        
    except Exception as e:
        logger.error(f"Error setting up schedule commands: {e}", exc_info=True)
        return False

@bot.event
async def on_ready():
    global _initial_startup_done
    print("-" * 50)
    logger.info(f'Logged in as {bot.user.name} (ID: {bot.user.id})')
    logger.info(f'discord.py Version: {discord.__version__}')
    print("-" * 50)

    if not _initial_startup_done:
        logger.info("First initialization after start...")
        
        # Run port diagnostics at Discord bot startup
        try:
            logger.info("Running port diagnostics at Discord bot startup...")
            log_port_diagnostics()
        except Exception as e:
            logger.error(f"Error running port diagnostics at startup: {e}")
        
        try:
            # Load extensions (CRITICAL: Required for slash commands to work)
            logger.info("Loading extensions...")
            
            # Load DockerControl extension with proper PyCord handling
            if 'cogs.docker_control' not in bot.extensions:
                try:
                    # Check if we're using PyCord (sync) or discord.py (async)
                    import inspect
                    if inspect.iscoroutinefunction(bot.load_extension):
                        # discord.py (async)
                        await bot.load_extension('cogs.docker_control')
                        logger.info("Successfully loaded extension: cogs.docker_control (discord.py async)")
                    else:
                        # PyCord (sync)
                        bot.load_extension('cogs.docker_control')
                        logger.info("Successfully loaded extension: cogs.docker_control (PyCord sync)")
                except Exception as e:
                    logger.error(f"Failed to load extension 'cogs.docker_control': {e}", exc_info=True)
                    raise
            else:
                logger.info("Extension cogs.docker_control already loaded, skipping")
            
            # Load InfoCommand extension with proper PyCord handling
            if 'cogs.info_command' not in bot.extensions:
                try:
                    # Check if we're using PyCord (sync) or discord.py (async)
                    if inspect.iscoroutinefunction(bot.load_extension):
                        # discord.py (async)
                        await bot.load_extension('cogs.info_command')
                        logger.info("Successfully loaded extension: cogs.info_command (discord.py async)")
                    else:
                        # PyCord (sync)
                        bot.load_extension('cogs.info_command')
                        logger.info("Successfully loaded extension: cogs.info_command (PyCord sync)")
                except Exception as e:
                    logger.error(f"Failed to load extension 'cogs.info_command': {e}", exc_info=True)
                    # Don't raise here - this is optional
            else:
                logger.info("Extension cogs.info_command already loaded, skipping")

            # --- Checkpoint and Cog initialization --- 
            logger.info("Checkpoint: Attempting to get DockerControlCog instance...")
            cog = bot.get_cog('DockerControlCog') # Fetch the manually added instance
            if cog:
                logger.info("Executing initialization of DockerControlCog (loop checks & initial send)...")

                # --- IMPORTANT: Start loops BEFORE send_initial_status ---
                # Start loops manually if they exist and are not running
                # if hasattr(cog, 'heartbeat_send_loop') and not cog.heartbeat_send_loop.is_running():
                #     cog.heartbeat_send_loop.start()
                #     logger.info("Heartbeat loop in Cog started manually.")
                # # Start the cache loop HERE
                # if hasattr(cog, 'status_update_loop') and not cog.status_update_loop.is_running():
                #     cog.status_update_loop.start()
                #     logger.info("Status update loop in Cog started manually.")
                #  # Start the edit loop HERE (or after send_initial_status? Better here)
                # if hasattr(cog, 'periodic_message_edit_loop') and not cog.periodic_message_edit_loop.is_running():
                #     cog.periodic_message_edit_loop.start()
                #     logger.info("Periodic message edit loop in Cog started manually.")
                # # Start inactivity loop
                # if hasattr(cog, 'inactivity_check_loop') and not cog.inactivity_check_loop.is_running():
                #     cog.inactivity_check_loop.start()
                #     logger.info("Inactivity check loop in Cog started manually.")

                # Call send_initial_status only AFTER starting the loops
                # await cog.send_initial_status() # This call is now handled by the Cog itself in __init__ via create_task

                # --- End of loop start logic ---

            else:
                logger.error("Could not retrieve DockerControlCog instance!")

        except Exception as e:
            logger.error(f"Error loading extension 'cogs.docker_control': {e}", exc_info=True)
            
        # Setup command and autocomplete
        setup_app_commands()
        
        # Improve the direct registration of schedule commands with autocomplete support
        logger.info("Attempting direct registration of schedule commands...")
        try:
            cog = bot.get_cog('DockerControlCog')
            if cog:
                # The commands are now defined in DockerControlCog and should have their autocomplete handlers
                # directly in the parameter definition using discord.commands.Option.
                # The following block for manual assignment is therefore no longer necessary and potentially problematic.
                logger.info("Autocomplete for schedule commands should now be handled directly in Cog command definitions.")
                logger.info("Skipping manual assignment of autocomplete handlers in on_ready.")

            else:
                logger.error("Could not retrieve DockerControlCog for schedule command setup in on_ready.")
        except Exception as e:
            logger.error(f"Error during schedule command processing in on_ready: {e}", exc_info=True)
        
        # Wait a moment for commands to be fully registered
        logger.info("Waiting 2 seconds for all commands to be fully registered...")
        await asyncio.sleep(2)
        
        # COMMAND SYNCHRONIZATION (important for Discord to recognize the changes)
        logger.info("Synchronizing App Commands after potential Cog registrations...")

        # ENABLE SYNCHRONIZATION AGAIN, BUT WITH A CAREFUL APPROACH
        logger.info("Synchronizing App Commands with improved approach...")
        try:
            guild_id_str = loaded_main_config.get('guild_id')
            if guild_id_str and guild_id_str.isdigit():
                guild_id = int(guild_id_str)
                logger.info(f"Synchronizing commands for Guild ID: {guild_id}")
                
                # Only for PyCord (discord.Bot)
                if hasattr(bot, 'sync_commands'):
                    # Show all commands to be synchronized
                    if hasattr(bot, 'application_commands'):
                        app_cmds = bot.application_commands
                        cmd_names = [cmd.name for cmd in app_cmds]
                        logger.info(f"Found {len(cmd_names)} commands to sync: {cmd_names}")
                        
                        # Debug: Show all command details
                        for cmd in app_cmds:
                            logger.info(f"Command details: {cmd.name} - Type: {type(cmd)} - Module: {getattr(cmd, '__module__', 'Unknown')}")
                        
                        # Check if schedule_* commands are included
                        schedule_cmd_names = [name for name in cmd_names if name.startswith('schedule_')]
                        if schedule_cmd_names:
                            logger.info(f"Schedule commands to sync: {schedule_cmd_names}")
                        else:
                            logger.info("Schedule commands not yet visible in application_commands list.")
                            logger.info("This is normal - commands are registered by the Cog and will be available after sync.")
                            # Do NOT manually add commands here - they are auto-registered by the Cog
                            # Manual addition causes duplicate command errors
                    
                    # Perform synchronization with Try/Except
                    try:
                        logger.info("Attempting to sync commands...")
                        await bot.sync_commands(guild_ids=[guild_id])
                        logger.info("Commands synchronized successfully")
                    except Exception as sync_error:
                        logger.error(f"Error syncing commands: {sync_error}")
                        # Try as fallback to register commands individually
                        logger.info("Attempting fallback: registering commands individually")
                        try:
                            for cmd in bot.application_commands:
                                try:
                                    await bot.register_commands(guild_id=guild_id, commands=[cmd])
                                    logger.info(f"Successfully registered command: {cmd.name}")
                                except Exception as cmd_error:
                                    logger.error(f"Error registering command {cmd.name}: {cmd_error}")
                        except Exception as fallback_error:
                            logger.error(f"Fallback registration failed: {fallback_error}")
            else:
                print("No guild ID configured, skipping command synchronization")
                        
            logger.info("App Commands synchronization process completed")
            
            # Apply dynamic cooldowns to all commands (if available)
            if dynamic_cooldowns_available:
                try:
                    logger.info("Applying dynamic cooldowns from spam protection settings...")
                    apply_dynamic_cooldowns_to_bot(bot)
                    logger.info("Dynamic cooldowns applied successfully")
                except Exception as cooldown_error:
                    logger.error(f"Error applying dynamic cooldowns: {cooldown_error}", exc_info=True)
            else:
                logger.info("Dynamic cooldowns not available - using legacy hardcoded cooldowns")
                
        except Exception as e:
            logger.error(f"Error in command synchronization process: {e}", exc_info=True)
            
        # Start scheduler service
        try:
            logger.info("Starting Scheduler Service...")
            if start_scheduler_service():
                logger.info("Scheduler Service started successfully.")
            else:
                print("Scheduler Service could not be started or was already running.")
        except Exception as e:
            logger.error(f"Error starting Scheduler Service: {e}", exc_info=True)

        # Send update notification if needed (after everything is initialized)
        if update_notifier_available:
            try:
                logger.info("Checking for update notifications...")
                update_notifier = get_update_notifier()
                if await update_notifier.send_update_notification(bot):
                    logger.info("Update notification sent successfully")
                else:
                    logger.debug("No update notification needed")
            except Exception as e:
                logger.error(f"Error sending update notification: {e}", exc_info=True)
        else:
            logger.debug("Update notifier not available - skipping update notifications")

        # Donation message scheduling: check at startup and then periodically (e.g., every 6 hours)
        if donation_manager_available:
            try:
                logger.info("Checking for donation message...")
                donation_manager = get_donation_manager()
                result = await donation_manager.send_donation_message(bot)
                if result["success"]:
                    logger.info(f"Donation message sent: {result['message']}")
                else:
                    logger.debug(f"No donation message sent: {result['message']}")

                async def periodic_donation_check():
                    while True:
                        try:
                            await asyncio.sleep(6 * 60 * 60)  # 6 hours
                            logger.info("Periodic donation check...")
                            res = await donation_manager.send_donation_message(bot)
                            if res["success"]:
                                logger.info(f"Donation message sent: {res['message']}")
                            else:
                                logger.debug(f"No donation message sent: {res['message']}")
                        except asyncio.CancelledError:
                            break
                        except Exception as e:
                            logger.error(f"Error in periodic donation check: {e}", exc_info=True)

                # Fire-and-forget periodic task
                bot.loop.create_task(periodic_donation_check())
            except Exception as e:
                logger.error(f"Error sending donation message: {e}", exc_info=True)
        else:
            logger.debug("Donation manager not available - skipping donation messages")

        _initial_startup_done = True # Prevents re-execution
        logger.info("Initialization complete.")

    logger.info(f"{bot.user.name} is ready.")

@bot.event
async def on_error(event, *args, **kwargs):
    """Handles unexpected errors in the bot"""
    logger.error(f"Error in event {event}: {traceback.format_exc()}")

@bot.event
async def on_command_error(ctx, error):
    """Centralized error handling for all slash commands"""
    # Handle cooldown errors
    if isinstance(error, commands.CommandOnCooldown):
        seconds = error.retry_after
        minutes, seconds = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        time_str = ""
        if hours > 0:
            time_str += f"{int(hours)}h "
        if minutes > 0:
            time_str += f"{int(minutes)}m "
        if seconds > 0 or not time_str:
             time_str += f"{seconds:.2f}s"
        
        message = _("This command is on cooldown. Please try again in {duration}.").format(duration=time_str.strip())
        try:
            await ctx.respond(message, ephemeral=True)
        except discord.HTTPException:
            pass # Failed to send cooldown message
        return # Stop further processing for cooldown errors

    # Handle other application command errors
    if isinstance(error, discord.ApplicationCommandError):
        logger.error(f"Command Error in '{ctx.command}': {error}")
        try:
            await ctx.respond(_("Error during execution: {error}").format(error=error), ephemeral=True)
        except discord.HTTPException:
            pass  # Error sending the error response
    else:
        logger.error(f"Unexpected Command Error in '{ctx.command}': {error}")
        traceback.print_exc()

# Helper function to mask sensitive data in config for logging
def _mask_token_in_config(config):
    """Masks sensitive data in config for safe logging."""
    if not config:
        return {}
    
    masked_config = config.copy()
    
    # Mask bot token
    if 'bot_token' in masked_config:
        masked_config['bot_token'] = '********'
    if 'bot_token_decrypted_for_usage' in masked_config:
        masked_config['bot_token_decrypted_for_usage'] = '********'
        
    # Mask web UI password hash if present
    if 'web_ui_password_hash' in masked_config:
        masked_config['web_ui_password_hash'] = '********'
        
    return masked_config

# Improved function to decrypt the bot token with multiple fallback methods
def get_decrypted_bot_token():
    """Attempts to decrypt the bot token in various ways for DockerDiscordControl."""
    
    # 0. First method: Try direct plaintext token from bot_config.json
    try:
        config_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config")
        bot_config_file = os.path.join(config_dir, "bot_config.json")
        
        if os.path.exists(bot_config_file):
            with open(bot_config_file, 'r') as f:
                bot_config = json.load(f)
            
            plaintext_token = bot_config.get('bot_token')
            if plaintext_token and not plaintext_token.startswith('gAAAAA'):  # Not encrypted
                logger.info("Using plaintext bot token from bot_config.json")
                return plaintext_token
    except Exception as e:
        logger.debug(f"Could not read plaintext token: {e}")
    
    # 1. Second method: Directly from loaded configuration
    token = loaded_main_config.get('bot_token_decrypted_for_usage')
    if token:
        logger.info(f"Using bot token from initial config loading")
        return token
        
    # 2. Third method: Use ConfigManager directly (use global instance to preserve cache)
    if config_manager_available:
        try:
            logger.info("Attempting to use ConfigManager for token decryption")
            # Use global config_manager instance to preserve _failed_decrypt_cache
            global config_manager_instance
            if 'config_manager_instance' not in globals():
                config_manager_instance = get_config_manager()
            config = config_manager_instance.get_config(force_reload=True)
            token = config.get('bot_token_decrypted_for_usage')
            if token:
                logger.info("Successfully decrypted token using ConfigManager")
                return token
        except Exception as e:
            logger.warning(f"Error using ConfigManager: {e}")
    
    # 3. Fourth method: Try direct decryption
    try:
        logger.info("Attempting manual token decryption")
        # Load bot configuration and web configuration
        config_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config")
        bot_config_file = os.path.join(config_dir, "bot_config.json")
        web_config_file = os.path.join(config_dir, "web_config.json")
        
        if os.path.exists(bot_config_file) and os.path.exists(web_config_file):
            with open(bot_config_file, 'r') as f:
                bot_config = json.load(f)
            with open(web_config_file, 'r') as f:
                web_config = json.load(f)
                
            encrypted_token = bot_config.get('bot_token')
            password_hash = web_config.get('web_ui_password_hash')
            
            if encrypted_token and password_hash and config_manager_available:
                # Try direct decryption
                config_manager = get_config_manager()
                decrypted = config_manager._decrypt_token(encrypted_token, password_hash)
                if decrypted:
                    logger.info("Successfully performed direct token decryption")
                    return decrypted
    except Exception as e:
        logger.error(f"Manual token decryption failed: {e}")
    
    # No method successful
    logger.error("All token decryption methods failed")
    return None

# --- Main execution / Start ---
def main():
    """Main entry point for the Discord bot."""
    try:
        # Initialize timezone from environment or config
        timezone_name = os.environ.get('TZ', 'Europe/Berlin')
        logger.info(f"Attempting to set timezone to: {timezone_name}")
        
        try:
            # Try to use tzdata directly instead of pytz
            import zoneinfo
            tz = zoneinfo.ZoneInfo(timezone_name)
            logger.info(f"Successfully set timezone to {timezone_name} using zoneinfo")
        except ImportError:
            try:
                # Fallback to pytz
                tz = pytz.timezone(timezone_name)
                logger.info(f"Successfully set timezone to {timezone_name} using pytz")
            except Exception as e:
                logger.warning(f"Could not set timezone {timezone_name}: {e}")
                logger.info("Using UTC as fallback")
                tz = timezone.utc

        # Set for all datetime operations
        datetime.now().astimezone(tz)
        
        # Try to get language from config
        config = get_cached_config()
        logger.info(f"Attempting to get language from config. Config object (token masked): {_mask_token_in_config(config)}")
        
        # Use proper token decryption method
        bot_token = get_decrypted_bot_token()

        if not bot_token:
            logger.error("FATAL: Bot token not found or could not be decrypted.")
            logger.error("Please configure the bot token in the Web UI or check the configuration files.")
            sys.exit(1)

        logger.info(f"Starting bot with token ending in: ...{bot_token[-4:]}")
        # Run the bot - this blocks until the bot stops
        bot.run(bot_token)
        logger.info("Bot has stopped gracefully.")
    except discord.LoginFailure:
        logger.error("FATAL: Invalid Discord Bot Token provided.")
        logger.error("Please verify the token in the configuration.")
        sys.exit(1) # Exit - supervisord will restart
    except discord.PrivilegedIntentsRequired:
        logger.error("FATAL: Necessary Privileged Intents are missing in the Discord Developer Portal!")
        sys.exit(1) # Exit - supervisord will restart
    except Exception as e:
        logger.error(f"FATAL: An unexpected error occurred during bot execution: {e}", exc_info=True)
        sys.exit(1) # Exit on other fatal errors - supervisord will restart
    finally:
        # Stop scheduler service when bot stops
        try:
            logger.info("Stopping Scheduler Service...")
            if stop_scheduler_service():
                logger.info("Scheduler Service stopped successfully.")
            else:
                logger.warning("Scheduler Service could not be stopped or was not running.")
        except Exception as e:
            logger.error(f"Error stopping Scheduler Service: {e}", exc_info=True)

if __name__ == "__main__":
    try:
        # Ensure we're not in an event loop already
        try:
            loop = asyncio.get_running_loop()
            logger.error("Event loop already running - this should not happen!")
            sys.exit(1)
        except RuntimeError:
            # No running loop - this is what we want
            pass
            
        # Create a new event loop with proper policy
        if sys.platform == 'win32':
            # Windows needs a different event loop policy
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        else:
            # Try to use uvloop on Unix systems if available
            try:
                import uvloop
                asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
                logger.info("Using uvloop for better performance")
            except ImportError:
                # Fallback to default policy
                pass
        
        # Create and set the event loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            # Run the main function
            main()
        except KeyboardInterrupt:
            logger.info("Received keyboard interrupt - shutting down gracefully")
        except Exception as e:
            logger.error(f"Error in main event loop: {e}", exc_info=True)
        finally:
            # Clean up tasks
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            
            # Wait for tasks to finish
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            
            # Close the loop
            loop.close()
            asyncio.set_event_loop(None)
            
    except Exception as e:
        logger.error(f"Critical error in event loop setup: {e}", exc_info=True)
        sys.exit(1)
