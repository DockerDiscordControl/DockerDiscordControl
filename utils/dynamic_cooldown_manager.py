# -*- coding: utf-8 -*-
"""
Dynamic Cooldown Manager - Manages dynamic cooldowns for Discord commands
"""

import logging
from discord.ext import commands
from typing import Dict, Any, Optional
from utils.spam_protection_manager import get_spam_protection_manager
from utils.logging_utils import get_module_logger

logger = get_module_logger('dynamic_cooldown')

class DynamicCooldownManager:
    """Manages dynamic cooldowns for Discord commands."""
    
    def __init__(self):
        self.spam_manager = get_spam_protection_manager()
        self._cooldown_mappings = {}
        
    def before_invoke_check(self):
        """Create a before_invoke hook that checks dynamic cooldowns."""
        async def check_cooldown(ctx):
            # Get command name
            command_name = ctx.command.name
            
            # Check if spam protection is enabled
            if not self.spam_manager.is_enabled():
                return True
            
            # Get user-specific cooldown tracking
            user_id = ctx.author.id
            command_key = f"{command_name}:{user_id}"
            
            # This is a simplified check - in production you'd implement proper cooldown tracking
            return True
            
        return check_cooldown
    
    def get_cooldown_for_command(self, command_name: str) -> Optional[commands.Cooldown]:
        """Get a Cooldown object for a specific command based on current settings."""
        # Map Discord command names to our config keys
        command_mapping = {
            'serverstatus': 'serverstatus',
            'ss': 'serverstatus',  # ss uses same cooldown as serverstatus
            'control': 'control',
            'info': 'info',
            'info_edit': 'info_edit',
            'help': 'help',
            'ping': 'ping',
            'donate': 'donate',
            'task': 'task',          # Generic task command
            'task_info': 'task_info',
            'task_once': 'task_once',
            'task_daily': 'task_daily',
            'task_weekly': 'task_weekly',
            'task_monthly': 'task_monthly',
            'task_yearly': 'task_yearly',
            'task_delete': 'task_delete',
            'task_delete_panel': 'task_delete_panel',
            'task_panel': 'task_panel',
            'command': 'command',    # Container control command
            'ddc': 'ddc',           # Command group
            'language': 'language',
            'forceupdate': 'forceupdate',
            'start': 'start',
            'stop': 'stop',
            'restart': 'restart'
        }
        
        # Get the config key
        config_key = command_mapping.get(command_name)
        if not config_key:
            logger.debug(f"No cooldown mapping for command: {command_name} - skipping dynamic cooldown")
            return None
        
        # Check if spam protection is enabled
        if not self.spam_manager.is_enabled():
            return None
        
        # Get cooldown seconds from config
        cooldown_seconds = self.spam_manager.get_command_cooldown(config_key)
        
        # Create and return Cooldown object with compatibility for different Discord libraries
        try:
            # Try discord.py style first (rate, per, type)
            cooldown_obj = commands.Cooldown(1, float(cooldown_seconds), commands.BucketType.user)
            logger.debug(f"Created Cooldown using discord.py style for {config_key}: 1/{cooldown_seconds}s")
            return cooldown_obj
        except TypeError as e:
            logger.debug(f"discord.py style failed for {config_key}: {e}, trying PyCord style")
            try:
                # Try PyCord style (rate, per)
                cooldown_obj = commands.Cooldown(1, float(cooldown_seconds))
                logger.debug(f"Created Cooldown using PyCord style for {config_key}: 1/{cooldown_seconds}s")
                return cooldown_obj
            except Exception as e2:
                logger.error(f"Could not create Cooldown object for {config_key} with either style: discord.py={e}, PyCord={e2}")
                return None
    
    def apply_dynamic_cooldowns(self, bot):
        """Apply dynamic cooldowns to all bot commands."""
        logger.info("Applying dynamic cooldowns to bot commands...")
        
        # Reload settings to get latest values
        self.spam_manager.load_settings()
        
        # Handle different Discord library versions
        commands_to_process = []
        
        # Try discord.py style first
        if hasattr(bot, 'walk_commands'):
            commands_to_process = list(bot.walk_commands())
            logger.debug("Using discord.py style walk_commands")
        # Try PyCord style
        elif hasattr(bot, 'all_commands'):
            commands_to_process = list(bot.all_commands.values())
            logger.debug("Using PyCord style all_commands")
        # Try application_commands for slash commands
        elif hasattr(bot, 'application_commands'):
            commands_to_process = list(bot.application_commands)
            logger.debug("Using application_commands for slash commands")
        else:
            logger.warning("No compatible command iteration method found")
            return
        
        applied_count = 0
        for command in commands_to_process:
            # Simple check: if it has a name and _buckets attribute, it's probably a command
            if hasattr(command, 'name') and hasattr(command, '_buckets'):
                # Get cooldown for this command
                cooldown = self.get_cooldown_for_command(command.name)
                
                if cooldown:
                    # Apply the cooldown with compatibility for different Discord libraries
                    try:
                        # Try with BucketType.user for discord.py compatibility
                        command._buckets = commands.CooldownMapping(cooldown, commands.BucketType.user)
                        logger.debug(f"Applied {cooldown.rate}/{cooldown.per}s cooldown to command: {command.name}")
                        applied_count += 1
                    except (TypeError, AttributeError):
                        try:
                            # Try PyCord style (just the cooldown)
                            command._buckets = commands.CooldownMapping(cooldown)
                            logger.debug(f"Applied {cooldown.rate}/{cooldown.per}s cooldown to command: {command.name}")
                            applied_count += 1
                        except Exception as e:
                            logger.debug(f"Could not apply cooldown to {command.name}: {e}")
                else:
                    # Remove cooldown if disabled
                    try:
                        command._buckets = None
                        logger.debug(f"Removed cooldown from command: {command.name}")
                    except Exception as e:
                        logger.debug(f"Could not remove cooldown from {command.name}: {e}")
        
        logger.info(f"Applied dynamic cooldowns to {applied_count} commands")

# Global instance
_cooldown_manager = None

def get_dynamic_cooldown_manager() -> DynamicCooldownManager:
    """Get the global dynamic cooldown manager instance."""
    global _cooldown_manager
    if _cooldown_manager is None:
        _cooldown_manager = DynamicCooldownManager()
    return _cooldown_manager

def apply_dynamic_cooldowns_to_bot(bot):
    """Convenience function to apply dynamic cooldowns to a bot."""
    manager = get_dynamic_cooldown_manager()
    manager.apply_dynamic_cooldowns(bot)