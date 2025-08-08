# -*- coding: utf-8 -*-
"""
Rate Limit Helper - Provides dynamic rate limiting for Discord commands
"""

from discord.ext import commands
from functools import wraps
from utils.spam_protection_manager import get_spam_protection_manager
import logging

logger = logging.getLogger(__name__)

def dynamic_cooldown(command_name: str):
    """Decorator that applies dynamic cooldown based on spam protection settings.
    
    Args:
        command_name: Name of the command in spam protection settings
        
    Usage:
        @dynamic_cooldown('serverstatus')
        @commands.slash_command(name="serverstatus")
        async def serverstatus(self, ctx):
            ...
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(self, ctx, *args, **kwargs):
            # Get spam protection manager
            spam_manager = get_spam_protection_manager()
            
            # Check if spam protection is enabled
            if not spam_manager.is_enabled():
                # If disabled, execute command without cooldown
                return await func(self, ctx, *args, **kwargs)
            
            # Get cooldown for this command
            cooldown_seconds = spam_manager.get_command_cooldown(command_name)
            
            # Apply cooldown dynamically
            # Note: This is a simplified version. In production, you'd want to track cooldowns per user
            # For now, we'll use the built-in cooldown decorator functionality
            
            # Execute the original function
            return await func(self, ctx, *args, **kwargs)
            
        # Apply Discord.py cooldown decorator dynamically
        spam_manager = get_spam_protection_manager()
        cooldown_seconds = spam_manager.get_command_cooldown(command_name)
        
        # Apply the cooldown decorator
        cooldown_decorator = commands.cooldown(1, cooldown_seconds, commands.BucketType.user)
        wrapper = cooldown_decorator(wrapper)
        
        return wrapper
    return decorator

def get_dynamic_cooldown(command_name: str):
    """Get a cooldown decorator with dynamic rate from spam protection settings.
    
    Args:
        command_name: Name of the command in spam protection settings
        
    Returns:
        Discord.py cooldown decorator
    """
    spam_manager = get_spam_protection_manager()
    
    # Check if spam protection is enabled
    if not spam_manager.is_enabled():
        # Return a no-op decorator
        return lambda func: func
    
    # Get cooldown for this command
    cooldown_seconds = spam_manager.get_command_cooldown(command_name)
    
    # Return the cooldown decorator
    return commands.cooldown(1, cooldown_seconds, commands.BucketType.user)