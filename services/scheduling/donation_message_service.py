# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""
Donation Message Service - Handles the scheduled donation_message task

This service:
1. Checks if the Mech's power level is 0
2. If power is 0, gives a system donation of $1.0 to keep the Mech moving
3. Sends a donation appeal message to all status channels
"""

import logging
from typing import Optional, Dict, Any
import discord

logger = logging.getLogger('ddc.donation_message_service')

_bot_instance: Optional[Any] = None

def set_bot_instance(bot_obj: Any) -> None:
    """Set the global bot instance."""
    global _bot_instance
    _bot_instance = bot_obj

def get_bot_instance() -> Optional[Any]:
    """
    Get the global bot instance.

    Uses the instance registered via set_bot_instance() (bot.py does this) and
    falls back to a module-level ``bot`` attribute of the ``bot`` module.

    Returns:
        Bot instance or None if not available
    """
    if _bot_instance is not None:
        return _bot_instance
    try:
        # Try to import bot from main module
        import bot as bot_module
        if hasattr(bot_module, 'bot') and bot_module.bot:
            return bot_module.bot
        logger.warning("Bot module found but bot instance is None")
        return None
    except ImportError:
        logger.warning("Could not import bot module")
        return None
    except (AttributeError, RuntimeError) as e:
        logger.warning(f"Error accessing bot instance: {e}")
        return None

def _get_level_name(level: int) -> str:
    """Return the mech level name from the evolution config (same lookup as the Web UI)."""
    try:
        from services.mech.mech_evolutions import get_evolution_level_info
        level_info = get_evolution_level_info(level)
        if level_info and getattr(level_info, 'name', None):
            return level_info.name
    except (ImportError, AttributeError, KeyError, ValueError, TypeError, OSError) as e:
        logger.debug(f"Could not resolve mech level name for level {level}: {e}")
    return f"Level {level}"

async def execute_donation_message_task(bot: Optional[Any] = None) -> bool:
    """
    Execute the donation message scheduled task.

    This task:
    - Checks if mech power is 0
    - If power is 0, adds $1.0 system donation to keep mech moving
    - Sends donation appeal message to all status channels

    Args:
        bot: Discord bot instance (optional, for sending messages)

    Returns:
        True if successful, False otherwise
    """
    try:
        # Import services
        from services.mech.progress_service import get_progress_service
        from services.config.config_service import load_config
        from cogs.translation_manager import _

        logger.info("Starting donation_message scheduled task")

        # Get current mech state
        progress_service = get_progress_service()
        current_state = progress_service.get_state()

        current_power = current_state.power_current
        logger.info(f"Current mech power: ${current_power:.2f}")

        # Check if power is 0 and add system donation if needed
        power_boost_given = False
        if current_power <= 0:
            logger.info("Mech power is 0 - adding $1.0 system donation to keep motor running")
            try:
                # Add system donation of $1.0 (power only, no evolution)
                new_state = progress_service.add_system_donation(
                    amount_dollars=1.0,
                    event_name="Monthly Motor Maintenance",
                    description="System donation to keep the Mech moving",
                    idempotency_key=None  # Let it generate unique key
                )
                power_boost_given = True
                current_state = new_state  # Show the boosted state in the message
                logger.info(f"System donation successful. New power: ${new_state.power_current:.2f}")
            except (ValueError, TypeError, RuntimeError) as donation_error:
                logger.error(f"Failed to add system donation: {donation_error}", exc_info=True)
                # Continue anyway to send the message
        else:
            logger.info(f"Mech has power (${current_power:.2f}) - no power boost needed")

        # Prepare message based on whether power boost was given
        if power_boost_given:
            message_title = _("🔋 Mech Motor Maintenance")
            message_description = _(
                "The Mech's power reached 0, but we've given it **$1.00** to keep the motor running! "
                "⚡\n\n"
                "**Help us keep the Mech alive and evolving!**\n"
                "Every donation adds Power (movement) and Evolution Progress (leveling up).\n\n"
                "💝 Support DDC and power the community Mech: https://ddc.bot"
            )
            message_color = 0xFFA500  # Orange - warning/maintenance
        else:
            message_title = _("💝 Support DDC & Power the Mech")
            message_description = _(
                "**The community Mech needs your help to keep evolving!**\n\n"
                "Every donation:\n"
                "• ⚡ Adds **Power** (keeps the Mech moving)\n"
                "• 📊 Increases **Evolution Progress** (levels up)\n"
                "• 💪 Supports DDC development\n\n"
                "Thank you for being part of our community! 🙏\n"
                "💝 Donate: https://ddc.bot"
            )
            message_color = 0x00ff41  # Green - standard donation appeal

        # Send message to all status channels if bot is available
        if bot:
            config = load_config()
            channels_config = config.get('channel_permissions', {})
            level_name = _get_level_name(current_state.level)

            sent_count = 0
            failed_count = 0

            for channel_id_str, channel_info in channels_config.items():
                try:
                    # Status channels only. The loop used to send to every
                    # entry in channel_permissions without looking at what the
                    # channel is for, so a channel configured only for
                    # 'control' - where the operator's start/stop buttons live
                    # - or only for 'download' received the public donation
                    # appeal all the same, against this block's own comment.
                    # Same question as _collect_status_channels in
                    # services/member_count/service.py asks for the identical
                    # loop (review C74).
                    if not isinstance(channel_info, dict):
                        logger.warning(f"Invalid channel config for {channel_id_str}: "
                                       f"{type(channel_info).__name__} - skipped")
                        continue
                    commands = channel_info.get('commands', {})
                    if not isinstance(commands, dict) or not commands.get('serverstatus', False):
                        logger.debug(f"Channel {channel_id_str} is not a status channel - "
                                     f"no donation appeal sent")
                        continue

                    channel_id = int(channel_id_str)
                    channel = bot.get_channel(channel_id)

                    if channel:
                        embed = discord.Embed(
                            title=message_title,
                            description=message_description,
                            color=message_color
                        )

                        # Add current mech stats (ProgressState fields)
                        state_info = (
                            f"🔋 Power: ${current_state.power_current:.2f}\n"
                            f"📊 Level: {current_state.level} - {level_name}\n"
                            f"🎯 Evolution: {current_state.evo_percent}%"
                        )
                        embed.add_field(name=_("Mech Status"), value=state_info, inline=False)

                        embed.set_footer(text=f"https://ddc.bot | {_('Monthly Donation Appeal')}")

                        await channel.send(embed=embed)
                        sent_count += 1
                        logger.debug(f"Sent donation message to channel {channel_id}")
                    else:
                        failed_count += 1
                        logger.warning(f"Channel {channel_id} not found or not accessible")

                except (discord.errors.DiscordException, RuntimeError, ValueError) as channel_error:
                    failed_count += 1
                    logger.error(f"Error sending to channel {channel_id_str}: {channel_error}", exc_info=True)

            logger.info(f"Donation message sent to {sent_count} channels ({failed_count} failed)")
        else:
            logger.warning("Bot instance not available - cannot send messages to channels")

        logger.info("Donation message task completed successfully")
        return True

    except (ImportError, AttributeError) as service_error:
        logger.error(f"Service dependency error in donation_message task: {service_error}", exc_info=True)
        return False
    except (RuntimeError, ValueError, TypeError) as task_error:
        logger.error(f"Error executing donation_message task: {task_error}", exc_info=True)
        return False
