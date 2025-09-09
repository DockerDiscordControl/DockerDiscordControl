# -*- coding: utf-8 -*-
"""
Update Notification System - Shows new features after updates
"""

import json
from services.config.config_service import load_config
import logging
import discord
from pathlib import Path
from typing import Dict, Any, Optional
from utils.logging_utils import get_module_logger
# Translation import moved to function level to avoid circular import

logger = get_module_logger('update_notifier')

class UpdateNotifier:
    """Manages update notifications for new features."""
    
    def __init__(self, config_dir: str = "config"):
        """Initialize the update notifier.
        
        Args:
            config_dir: Directory where update_status.json will be stored
        """
        self.config_dir = Path(config_dir)
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.status_file = self.config_dir / "update_status.json"
        self.current_version = "2025.01.07"  # Update this with each release
        
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
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Error loading update status: {e}")
            return default_status
    
    def save_update_status(self, status: Dict[str, Any]) -> bool:
        """Save update notification status."""
        try:
            with open(self.status_file, 'w', encoding='utf-8') as f:
                json.dump(status, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            logger.error(f"Error saving update status: {e}")
            return False
    
    def should_show_update_notification(self) -> bool:
        """Check if update notification should be shown."""
        status = self.get_update_status()
        last_version = status.get("last_notified_version")
        
        # Show notification if this is a new version
        return last_version != self.current_version
    
    def mark_notification_shown(self):
        """Mark update notification as shown."""
        status = self.get_update_status()
        status["last_notified_version"] = self.current_version
        if self.current_version not in status["notifications_shown"]:
            status["notifications_shown"].append(self.current_version)
        self.save_update_status(status)
    
    def create_update_embed(self) -> discord.Embed:
        """Create the update notification embed."""
        embed = discord.Embed(
            title="🎉 DockerDiscordControl Update",
            description=f"**Version {self.current_version}** - Neue Features verfügbar!",
            color=0x00ff00
        )
        
        # New features in this update
        embed.add_field(
            name="🔒 Spam Protection System",
            value="• Dynamisch konfigurierbare Cooldowns für alle Commands\n"
                  "• Web UI Modal unter 'Web UI Authentication'\n"
                  "• Individuelle Einstellungen pro Command und Button\n"
                  "• Schutz vor Rate-Limiting und Missbrauch",
            inline=False
        )
        
        embed.add_field(
            name="📋 Container Info System",
            value="• Neuer `/info` Command für detaillierte Container-Infos\n"
                  "• Port-Feld im Info-Editor Modal\n"
                  "• Live WAN IP Detection oder Custom Address\n"
                  "• Einheitliche Darstellung in allen Info-Anzeigen",
            inline=False
        )
        
        embed.add_field(
            name="🌍 Dynamisches Timezone System",
            value="• Automatische Timezone-Erkennung aus Web UI Config\n"
                  "• Keine hardcodierten Timezones mehr\n"
                  "• Bessere Token-Entschlüsselung",
            inline=False
        )
        
        embed.add_field(
            name="⚙️ Konfiguration",
            value="**Spam Protection:** Web UI → Konfiguration → 'Spam Protection Settings'\n"
                  "**Container Info:** Info-Buttons in Status-Nachrichten verwenden",
            inline=False
        )
        
        embed.set_footer(text="Diese Nachricht wird nur einmal angezeigt • https://ddc.bot")
        return embed
    
    async def send_update_notification(self, bot) -> bool:
        """Send update notification to control channels."""
        if not self.should_show_update_notification():
            logger.debug("Update notification already shown for this version")
            return False
            
        try:
            config = load_config()
            control_channels = []
            
            # Find control channels - check both old and new config formats
            # New format: channel_permissions
            channel_permissions = config.get('channel_permissions', {})
            for channel_id, perms in channel_permissions.items():
                if perms.get('commands', {}).get('control', False):
                    try:
                        control_channels.append(int(channel_id))
                    except ValueError:
                        logger.debug(f"Invalid channel ID: {channel_id}")
            
            # Old format fallback: channels array
            if not control_channels:
                for channel_config in config.get('channels', []):
                    if 'control' in channel_config.get('permissions', []):
                        try:
                            control_channels.append(int(channel_config['channel_id']))
                        except (ValueError, KeyError):
                            pass
            
            if not control_channels:
                logger.info("No control channels configured - skipping update notification")
                # Mark as shown anyway to avoid repeated attempts
                self.mark_update_notification_shown()
                return False
            
            embed = self.create_update_embed()
            sent_count = 0
            
            # Send to all control channels
            for channel_id in control_channels:
                try:
                    channel = bot.get_channel(channel_id)
                    if channel:
                        await channel.send(embed=embed)
                        sent_count += 1
                        logger.info(f"Update notification sent to channel {channel_id}")
                    else:
                        logger.warning(f"Could not find channel {channel_id}")
                except Exception as e:
                    logger.error(f"Error sending update notification to channel {channel_id}: {e}")
            
            if sent_count > 0:
                # Mark as shown only if at least one message was sent
                self.mark_notification_shown()
                logger.info(f"Update notification sent to {sent_count} control channels")
                return True
            else:
                logger.error("Failed to send update notification to any channel")
                return False
                
        except Exception as e:
            logger.error(f"Error in send_update_notification: {e}")
            return False

# Global instance
_update_notifier = None

def get_update_notifier() -> UpdateNotifier:
    """Get the global update notifier instance."""
    global _update_notifier
    if _update_notifier is None:
        _update_notifier = UpdateNotifier()
    return _update_notifier