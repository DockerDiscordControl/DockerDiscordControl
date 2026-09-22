# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""
Update Notification System - Shows new features after updates
"""

import asyncio
import json
import os
from services.config.config_service import load_config
import logging
import discord
from pathlib import Path
from typing import Dict, Any, Optional
from utils.atomic_io import atomic_write_json
from utils.logging_utils import get_module_logger
from cogs.translation_manager import _

logger = get_module_logger('update_notifier')

class UpdateNotifier:
    """Manages update notifications for new features."""

    def __init__(self, config_dir: str = None):
        """Initialize the update notifier.

        Args:
            config_dir: Directory where update_status.json will be stored
        """
        if config_dir:
            self.config_dir = Path(config_dir)
        else:
            # Via utils/config_paths.py (DDC_CONFIG_DIR) - derived from
            # __file__ before, blind to the variable.
            from utils.config_paths import get_config_dir
            self.config_dir = get_config_dir()
            
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.status_file = self.config_dir / "update_status.json"
        # The running version, from the one source the image sets (Dockerfile ENV
        # DDC_VERSION, also read by /health and the panel footer). A literal here
        # meant the marker on disk equalled it after the first install, so the
        # notice never fired again - while its text advertised that old release.
        self.current_version = (os.environ.get("DDC_VERSION") or "").strip().lstrip("vV")

    def get_update_status(self) -> Dict[str, Any]:
        """Get current update notification status."""
        default_status = {
            "last_notified_version": None,
            "notifications_shown": []
        }

        if not self.status_file.exists():
            return default_status

        try:
            with open(self.status_file, 'r', encoding='utf-8') as f:
                stored = json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Error loading update status: {e}")
            return default_status

        # What this method promises is the shape above, not whatever happens to
        # be in the file. A file that parses used to come back untouched, so the
        # two keys were only guaranteed on the error paths - and
        # mark_notification_shown indexes status["notifications_shown"]
        # directly. A hand-edited file, or one from another schema, raised
        # KeyError there, inside send_update_notification, whose clause names
        # RuntimeError and three discord exceptions: it left that method
        # uncaught (review C65).
        if not isinstance(stored, dict):
            logger.error(f"{self.status_file.name} does not hold an object "
                         f"({type(stored).__name__}) - starting from the defaults")
            return default_status

        # Fill the gaps, keep everything else: save_update_status writes the
        # whole record back, so a key this version does not know must survive.
        status = {**default_status, **stored}
        if not isinstance(status.get("notifications_shown"), list):
            logger.error(f"notifications_shown in {self.status_file.name} is not a list "
                         f"({status.get('notifications_shown')!r}) - starting it empty")
            status["notifications_shown"] = []
        return status

    def save_update_status(self, status: Dict[str, Any]) -> bool:
        """Save update notification status."""
        try:
            # Write atomically instead of open(..., "w"): the latter truncates the
            # file on open, and json.dump writes as a stream. Measured: on a
            # serialisation error a HALF record was left behind
            # ('{\n  "last_notified_version": "2.0",\n  "notifications_shown": '),
            # and get_update_status:56-58 then falls back to the defaults - a
            # long-dismissed update notice appears again.
            # atomic_write_json serialises BEFORE opening (utils/atomic_io.py:66-69)
            # and writes with the same parameters (indent=2, ensure_ascii=False).
            atomic_write_json(self.status_file, status)
            return True
        except (IOError, OSError, PermissionError, RuntimeError, json.JSONDecodeError) as e:
            logger.error(f"Error saving update status: {e}", exc_info=True)
            return False

    def should_show_update_notification(self) -> bool:
        """Check if update notification should be shown."""
        if not self.current_version:
            # Without a version there is nothing to announce - and nothing to
            # compare against either
            return False
        status = self.get_update_status()
        return status.get("last_notified_version") != self.current_version

    def channels_still_to_tell(self, channel_ids) -> list:
        """The channels that have not had THIS version's notice yet.

        One successful channel used to mark the whole version done, so a channel
        that was unreachable at that moment never got it - and a crash before the
        mark sent it to everybody a second time.
        """
        told = set(self.get_update_status().get("channels_notified", {}).get(self.current_version, []))
        return [channel_id for channel_id in channel_ids if channel_id not in told]

    def mark_notification_shown(self, channel_ids=None) -> bool:
        """Write down that this version's notice went out; True when that WORKED.

        A status file that cannot be written (the classic root-owned file) used
        to be ignored, so the notice counted as shown and was posted again on
        every start, into every channel, for ever.
        """
        status = self.get_update_status()
        status["last_notified_version"] = self.current_version
        if self.current_version not in status["notifications_shown"]:
            status["notifications_shown"].append(self.current_version)
        if channel_ids:
            told = status.setdefault("channels_notified", {}).setdefault(self.current_version, [])
            told.extend(channel_id for channel_id in channel_ids if channel_id not in told)
        if self.save_update_status(status):
            return True
        logger.error("Update notice could not be written down (%s) - it is NOT counted as shown",
                     self.status_file)
        return False

    def create_update_embed(self) -> discord.Embed:
        """Create the update notification embed."""
        embed = discord.Embed(
            title=_("🎉 DockerDiscordControl Update"),
            description=_("**Version {version}** - New features available!").format(version=self.current_version),
            color=0x00ff00
        )

        # New features in this update
        embed.add_field(
            name=_("🔒 Spam Protection System"),
            value=_("• Dynamically configurable cooldowns for all commands\n"
                    "• Web UI Modal under 'Web UI Authentication'\n"
                    "• Individual settings per command and button\n"
                    "• Protection against rate-limiting and abuse"),
            inline=False
        )

        embed.add_field(
            name=_("📋 Container Info System"),
            value=_("• New /info command for detailed container information\n"
                    "• Port field in info editor modal\n"
                    "• Live WAN IP detection or custom address\n"
                    "• Consistent display in all info views"),
            inline=False
        )

        embed.add_field(
            name=_("🌍 Dynamic Timezone System"),
            value=_("• Automatic timezone detection from Web UI config\n"
                    "• No more hardcoded timezones\n"
                    "• Better token decryption"),
            inline=False
        )

        embed.add_field(
            name=_("⚙️ Configuration"),
            value=_("**Spam Protection:** Web UI → Configuration → 'Spam Protection Settings'\n"
                    "**Container Info:** Use info buttons in status messages"),
            inline=False
        )

        embed.set_footer(text=_("This message is only shown once • https://ddc.bot"))
        return embed

    async def send_update_notification(self, bot) -> bool:
        """Send update notification to control channels."""
        if not self.should_show_update_notification():
            logger.debug("Update notification already shown for this version")
            return False

        try:
            config = load_config()
            from services.config.channel_roles import control_channel_ids
            control_channels = control_channel_ids(config)

            if not control_channels:
                logger.info("No control channels configured - skipping update notification")
                # Mark as shown anyway to avoid repeated attempts
                self.mark_notification_shown()
                return False

            embed = self.create_update_embed()
            sent_count = 0
            told = []

            # Send to the control channels that have not had it yet
            for channel_id in self.channels_still_to_tell(control_channels):
                try:
                    channel = bot.get_channel(channel_id)
                    if channel:
                        await channel.send(embed=embed)
                        sent_count += 1
                        told.append(channel_id)
                        logger.info(f"Update notification sent to channel {channel_id}")
                    else:
                        logger.warning(f"Could not find channel {channel_id}")
                except (RuntimeError, asyncio.TimeoutError, discord.Forbidden, discord.HTTPException, discord.NotFound) as e:
                    logger.error(f"Error sending update notification to channel {channel_id}: {e}", exc_info=True)

            if sent_count > 0:
                # Per channel, so one that was unreachable gets it next time
                self.mark_notification_shown(channel_ids=told)
                logger.info(f"Update notification sent to {sent_count} control channels")
                return True
            else:
                logger.error("Failed to send update notification to any channel")
                return False

        except (RuntimeError, discord.Forbidden, discord.HTTPException, discord.NotFound) as e:
            logger.error(f"Error in send_update_notification: {e}", exc_info=True)
            return False

# Global instance
_update_notifier = None

def get_update_notifier() -> UpdateNotifier:
    """Get the global update notifier instance."""
    global _update_notifier
    if _update_notifier is None:
        _update_notifier = UpdateNotifier()
    return _update_notifier
