# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #

"""
Central utility for app_commands import handling.
This eliminates redundant import code across multiple modules.
"""

import logging
from typing import Any, Optional

# Create a logger for import operations
_import_logger = logging.getLogger("discord.app_commands_import")

# Global variables to store imported modules
app_commands = None
DiscordOption = None
app_commands_available = False

def initialize_app_commands():
    """
    Initializes app_commands and DiscordOption imports with fallbacks.
    This function should be called once at application startup.
    """
    global app_commands, DiscordOption, app_commands_available
    
    # Skip if already initialized
    if app_commands is not None:
        return app_commands, DiscordOption, app_commands_available
    
    # Try to import app_commands and Option
    try:
        from discord import app_commands as discord_app_commands, Option as DiscordOptionImported
        app_commands = discord_app_commands
        DiscordOption = DiscordOptionImported
        app_commands_available = True
        _import_logger.debug("Imported app_commands and Option directly from discord module (PyCord style)")
    except ImportError:
        _import_logger.debug("Could not import app_commands and Option from discord directly. Trying discord.ext.commands.")
        try:
            from discord.ext.commands import app_commands as ext_app_commands
            app_commands = ext_app_commands
            app_commands_available = True 
            # Try to get Option from discord.commands
            try:
                from discord.commands import Option as DiscordOptionImported
                DiscordOption = DiscordOptionImported
                _import_logger.debug("Imported app_commands from discord.ext.commands and Option from discord.commands")
            except ImportError:
                DiscordOption = None
                _import_logger.warning("Imported app_commands from discord.ext.commands, but discord.commands.Option not found.")
        except ImportError:
            _import_logger.warning("Could not import app_commands from discord.ext.commands either.")
            app_commands_available = False

    # Create mock versions if imports failed
    if not app_commands_available:
        _import_logger.warning("Could not import app_commands module from any known location, creating mock version")
        
        class AppCommandsMock:
            def __init__(self):
                pass
            def command(self, *args, **kwargs):
                def decorator(func):
                    return func
                return decorator
            def describe(self, **kwargs):
                def decorator(func):
                    return func
                return decorator
            def autocomplete(self, **kwargs):
                def decorator(func):
                    return func
                return decorator
            class Choice:
                def __init__(self, name, value):
                    self.name = name
                    self.value = value
        
        app_commands = AppCommandsMock()
        _import_logger.debug("Created mock app_commands module as fallback")

    # Create mock DiscordOption if still None
    if DiscordOption is None:
        _import_logger.warning("DiscordOption was not successfully imported, creating ActualMockOption as fallback.")
        
        class ActualMockOption:
            def __init__(self, actual_input_type: type, description: str = "", name: Optional[str] = None, autocomplete: Optional[Any] = None, **kwargs):
                self._actual_input_type = actual_input_type
                self.description = description
                self.name = name 
                self.autocomplete = autocomplete
                self.kwargs = kwargs

                if hasattr(actual_input_type, '__name__'):
                    self.__name__ = actual_input_type.__name__
                else:
                    self.__name__ = str(actual_input_type)

            @property
            def input_type(self) -> type:
                return self._actual_input_type

        DiscordOption = ActualMockOption
        _import_logger.debug("Replaced DiscordOption with ActualMockOption as fallback.")

    return app_commands, DiscordOption, app_commands_available

def get_app_commands():
    """Returns the initialized app_commands module."""
    if app_commands is None:
        initialize_app_commands()
    return app_commands

def get_discord_option():
    """Returns the initialized DiscordOption class."""
    if DiscordOption is None:
        initialize_app_commands()
    return DiscordOption

def is_app_commands_available():
    """Returns whether real app_commands is available (not mocked)."""
    if app_commands is None:
        initialize_app_commands()
    return app_commands_available 