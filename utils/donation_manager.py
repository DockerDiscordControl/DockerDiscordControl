# -*- coding: utf-8 -*-
"""
Donation Manager - Handles donation messages and scheduling
"""

import json
import logging
import discord
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from utils.logging_utils import get_module_logger
from utils.config_cache import get_cached_config
from cogs.translation_manager import _

logger = get_module_logger('donation_manager')

class DonationManager:
    """Manages donation reminders and messages."""
    
    def __init__(self, config_dir: str = "config"):
        """Initialize the donation manager.
        
        Args:
            config_dir: Directory where donation_status.json will be stored
        """
        self.config_dir = Path(config_dir)
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.status_file = self.config_dir / "donation_status.json"
        
        # Donation links
        self.buymeacoffee_link = "https://buymeacoffee.com/dockerdiscordcontrol"
        self.paypal_link = "https://www.paypal.com/donate/?hosted_button_id=XKVC6SFXU2GW4"
        
    def get_donation_status(self) -> Dict[str, Any]:
        """Get current donation status."""
        default_status = {
            "last_donation_message": None,
            "donation_messages_sent": []
        }
        
        if not self.status_file.exists():
            return default_status
            
        try:
            with open(self.status_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Error loading donation status: {e}")
            return default_status
    
    def save_donation_status(self, status: Dict[str, Any]) -> bool:
        """Save donation status."""
        try:
            with open(self.status_file, 'w', encoding='utf-8') as f:
                json.dump(status, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            logger.error(f"Error saving donation status: {e}")
            return False
    
    def should_send_donation_message(self) -> bool:
        """Check if donation message should be sent (every 2nd Sunday of the month)."""
        status = self.get_donation_status()
        last_message_date = status.get("last_donation_message")
        
        now = datetime.now()
        
        # Check if today is Sunday
        if now.weekday() != 6:  # Sunday = 6
            return False
        
        # Check if today is the 2nd Sunday of the month
        if not self._is_second_sunday_of_month(now):
            return False
        
        # If never sent before, send it
        if not last_message_date:
            return True
        
        try:
            last_date = datetime.fromisoformat(last_message_date)
            # Don't send if already sent this month
            if last_date.year == now.year and last_date.month == now.month:
                return False
            
            return True
                
        except Exception as e:
            logger.error(f"Error parsing last donation message date: {e}")
            return True
    
    def _is_second_sunday_of_month(self, date: datetime) -> bool:
        """Check if the given date is the 2nd Sunday of its month."""
        # Find the first day of the month
        first_day = date.replace(day=1)
        
        # Find the first Sunday of the month
        days_to_first_sunday = (6 - first_day.weekday()) % 7
        if first_day.weekday() == 6:  # First day is Sunday
            days_to_first_sunday = 0
        first_sunday = first_day + timedelta(days=days_to_first_sunday)
        
        # The second Sunday is 7 days later
        second_sunday = first_sunday + timedelta(days=7)
        
        return date.date() == second_sunday.date()
    
    def get_next_donation_date(self) -> Optional[datetime]:
        """Get the next scheduled donation message date (next 2nd Sunday of month)."""
        now = datetime.now()
        
        # Check if this month's 2nd Sunday hasn't passed yet
        current_month_second_sunday = self._get_second_sunday_of_month(now.year, now.month)
        if now.date() <= current_month_second_sunday.date():
            return current_month_second_sunday
        
        # Otherwise, get next month's 2nd Sunday
        next_month = now.month + 1
        next_year = now.year
        if next_month > 12:
            next_month = 1
            next_year += 1
            
        return self._get_second_sunday_of_month(next_year, next_month)
    
    def _get_second_sunday_of_month(self, year: int, month: int) -> datetime:
        """Get the 2nd Sunday of a specific month/year."""
        first_day = datetime(year, month, 1)
        
        # Find the first Sunday of the month
        days_to_first_sunday = (6 - first_day.weekday()) % 7
        if first_day.weekday() == 6:  # First day is Sunday
            days_to_first_sunday = 0
        first_sunday = first_day + timedelta(days=days_to_first_sunday)
        
        # The second Sunday is 7 days later
        return first_sunday + timedelta(days=7)
    
    def mark_donation_message_sent(self):
        """Mark donation message as sent."""
        status = self.get_donation_status()
        now = datetime.now().isoformat()
        status["last_donation_message"] = now
        status["donation_messages_sent"].append(now)
        
        # Keep only last 10 entries
        status["donation_messages_sent"] = status["donation_messages_sent"][-10:]
        
        self.save_donation_status(status)
    
    def create_donation_embed(self, is_automatic: bool = False) -> discord.Embed:
        """Create the donation embed message."""
        if is_automatic:
            title = f"☕ {_('Support DockerDiscordControl')}"
            description = f"{_('Hello! If you like DockerDiscordControl and want to support the development, I would be very happy about a small donation!')} 💙"
        else:
            title = f"☕ {_('Support DockerDiscordControl')}"
            description = f"{_('Hello! If you like DockerDiscordControl and want to support the development, I would be very happy about a small donation!')} 💙"
        
        embed = discord.Embed(
            title=title,
            description=description,
            color=0x00ff41  # Nice green color
        )
        
        embed.add_field(
            name=f"☕ {_('Buy me a Coffee')}",
            value=f"[{_('Click here for Buy me a Coffee')}]({self.buymeacoffee_link})",
            inline=True
        )
        
        embed.add_field(
            name="💳 PayPal",
            value=f"[{_('Click here for PayPal')}]({self.paypal_link})",
            inline=True
        )
        
        if is_automatic:
            embed.set_footer(text=f"{_('This message is only shown every 2nd Sunday of the month')} • https://ddc.bot")
        else:
            embed.set_footer(text=f"{_('Thank you for your support!')} • https://ddc.bot")
            
        return embed
    
    def get_all_connected_channels(self) -> List[int]:
        """Get all connected Discord channels (status + control channels)."""
        config = get_cached_config()
        channels = set()
        
        # New format: channel_permissions
        channel_permissions = config.get('channel_permissions', {})
        for channel_id, perms in channel_permissions.items():
            commands = perms.get('commands', {})
            if commands.get('serverstatus', False) or commands.get('control', False):
                try:
                    channels.add(int(channel_id))
                except ValueError:
                    logger.warning(f"Invalid channel ID: {channel_id}")
        
        # Old format fallback: channels array
        if not channels:
            for channel_config in config.get('channels', []):
                channel_id = channel_config.get('channel_id')
                permissions = channel_config.get('permissions', [])
                
                if channel_id and ('serverstatus' in permissions or 'control' in permissions):
                    try:
                        channels.add(int(channel_id))
                    except ValueError:
                        logger.warning(f"Invalid channel ID: {channel_id}")
        
        return list(channels)
    
    async def send_donation_message(self, bot, force: bool = False) -> Dict[str, Any]:
        """Send donation message to all connected channels."""
        if not force and not self.should_send_donation_message():
            return {
                "success": False,
                "message": "Donation message not due yet",
                "channels_sent": 0
            }
        
        try:
            channels = self.get_all_connected_channels()
            
            if not channels:
                return {
                    "success": False,
                    "message": "No connected channels found",
                    "channels_sent": 0
                }
            
            embed = self.create_donation_embed(is_automatic=not force)
            sent_count = 0
            failed_channels = []
            
            for channel_id in channels:
                try:
                    channel = bot.get_channel(channel_id)
                    if channel:
                        await channel.send(embed=embed)
                        sent_count += 1
                        logger.info(f"Donation message sent to channel {channel_id}")
                    else:
                        failed_channels.append(channel_id)
                        logger.warning(f"Could not find channel {channel_id}")
                except Exception as e:
                    failed_channels.append(channel_id)
                    logger.error(f"Error sending donation message to channel {channel_id}: {e}")
            
            if sent_count > 0:
                self.mark_donation_message_sent()
                logger.info(f"Donation message sent to {sent_count} channels")
                
                return {
                    "success": True,
                    "message": f"Donation message sent to {sent_count} channels",
                    "channels_sent": sent_count,
                    "failed_channels": failed_channels
                }
            else:
                return {
                    "success": False,
                    "message": "Failed to send donation message to any channel",
                    "channels_sent": 0,
                    "failed_channels": failed_channels
                }
                
        except Exception as e:
            logger.error(f"Error in send_donation_message: {e}")
            return {
                "success": False,
                "message": f"Error: {str(e)}",
                "channels_sent": 0
            }

# Global instance
_donation_manager = None

def get_donation_manager() -> DonationManager:
    """Get the global donation manager instance."""
    global _donation_manager
    if _donation_manager is None:
        _donation_manager = DonationManager()
    return _donation_manager