# -*- coding: utf-8 -*-
import logging
import sys
import os
import time
from typing import Optional
from datetime import datetime, timezone

# Constants for logging
DEFAULT_LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
DEBUG_LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s [%(filename)s:%(lineno)d]'

# Global variable for debug status
_debug_mode_enabled = None
# New variables for temporary debug mode
_temp_debug_mode_enabled = False
_temp_debug_expiry = 0  # Timestamp when temp debug expires
_last_debug_status_log = None

def is_debug_mode_enabled() -> bool:
    """
    Checks if debug mode is enabled.
    This is loaded directly from the configuration file to ensure the latest value is used.
    
    Returns:
        bool: True if debug mode is enabled, otherwise False
    """
    global _debug_mode_enabled, _temp_debug_mode_enabled, _temp_debug_expiry, _last_debug_status_log
    
    # Check if temporary debug mode is active and not expired
    current_time = time.time()
    if _temp_debug_mode_enabled and current_time < _temp_debug_expiry:
        # Print a message every few seconds to confirm temp debug is active
        if _last_debug_status_log is None or (current_time - _last_debug_status_log > 10):
            print(f"TEMP DEBUG MODE IS ACTIVE! Expires in {int((_temp_debug_expiry - current_time) / 60)} minutes and {int((_temp_debug_expiry - current_time) % 60)} seconds")
            _last_debug_status_log = current_time
        return True
    elif _temp_debug_mode_enabled and current_time >= _temp_debug_expiry:
        # Temp debug mode has expired, reset it
        _temp_debug_mode_enabled = False
        print(f"Temporary debug mode expired")
    
    # Use a non-blocking approach to get debug status
    try:
        # Store previous value to detect changes
        previous_value = _debug_mode_enabled
        
        # Load config without force invalidation (cache will be used if available)
        from utils.config_manager import get_config_manager
        config = get_config_manager().get_config(force_reload=False)
        
        # Use the cached value of debug mode if available
        _debug_mode_enabled = config.get('scheduler_debug_mode', False)
        
        # Only output debug message when loaded for the first time or when the value changes
        if previous_value != _debug_mode_enabled or (_last_debug_status_log is None) or (current_time - _last_debug_status_log > 300):
            # Only log if debug mode actually changed or it's the first time loading
            if previous_value != _debug_mode_enabled or _last_debug_status_log is None:
                print(f"Debug status loaded from configuration: {_debug_mode_enabled}")
            _last_debug_status_log = current_time
            
    except Exception as e:
        # Fallback on errors
        print(f"Error loading debug status: {e}")
        if _debug_mode_enabled is None:  # Only set to False if currently None
            _debug_mode_enabled = False
    
    # Check once more if temporary debug mode is active
    result = _debug_mode_enabled or _temp_debug_mode_enabled
    return result

# A filter that only allows DEBUG logs when debug mode is enabled
class DebugModeFilter(logging.Filter):
    """
    Filter that only allows DEBUG messages when debug mode is enabled.
    INFO and higher levels are always allowed.
    """
    def filter(self, record):
        # Check if log level is lower than INFO (i.e., DEBUG)
        if record.levelno < logging.INFO:
            # Explicitly call is_debug_mode_enabled to check both permanent and temporary debug mode
            debug_enabled = is_debug_mode_enabled()
            
            # Every 100 DEBUG logs that are filtered out, print a note
            if not debug_enabled and hasattr(self, '_filter_count'):
                self._filter_count += 1
                if self._filter_count % 100 == 0:
                    print(f"Note: {self._filter_count} DEBUG logs filtered out because debug mode is disabled. Enable via web UI.")
            elif not debug_enabled:
                self._filter_count = 1
            
            return debug_enabled
        # Always allow all other levels (INFO and higher)
        return True

# A custom formatter class that uses the configured timezone
class TimezoneFormatter(logging.Formatter):
    """
    A custom formatter that uses the local timezone for timestamps in logs.
    """
    def __init__(self, fmt=None, datefmt=None, tz=None):
        super().__init__(fmt, datefmt)
        self.tz = tz

    def formatTime(self, record, datefmt=None):
        """
        Overrides the formatTime method to use the configured timezone.
        """
        if datefmt is None:
            datefmt = self.datefmt or '%Y-%m-%d %H:%M:%S'
        
        # We use record creation time as UTC timestamp
        ct = self.converter(record.created)
        
        try:
            from utils.config_loader import load_config
            import pytz
            
            # Try to load the timezone from the configuration
            config = load_config()
            timezone_str = config.get('timezone', 'Europe/Berlin')
            
            # Convert the timestamp to the configured timezone
            tz = pytz.timezone(timezone_str)
            dt = datetime.fromtimestamp(record.created, tz)
            
            # Format with the correct timezone
            formatted_time = dt.strftime(datefmt) + f" {dt.tzname()}"
            return formatted_time
        except Exception as e:
            # Fall back to standard formatting on errors
            return super().formatTime(record, datefmt)

def setup_logger(name: str, level=logging.INFO, log_to_console=True, log_to_file=False, custom_formatter=None) -> logging.Logger:
    """
    Creates a logger with the specified name and logging level.
    
    Args:
        name: Logger name
        level: Logging level (default: INFO)
        log_to_console: Whether to output logs to console
        log_to_file: Whether to output logs to a file
        custom_formatter: Optional custom formatter for the logs
    
    Returns:
        Configured logger
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)
    
    # Avoid duplicate handlers in case of re-initialization
    if logger.handlers:
        return logger
    
    # Determine formatter to use
    if custom_formatter is None:
        if level <= logging.DEBUG:
            formatter = TimezoneFormatter(DEBUG_LOG_FORMAT)
        else:
            formatter = TimezoneFormatter(DEFAULT_LOG_FORMAT)
    else:
        formatter = custom_formatter
    
    # Console handler (stdout)
    if log_to_console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)
        
        # Add the debug filter to the handler
        console_handler.addFilter(DebugModeFilter())
        
        logger.addHandler(console_handler)
    
    # File handler
    if log_to_file:
        try:
            # Create logs directory if it doesn't exist
            logs_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
            os.makedirs(logs_dir, exist_ok=True)
            
            # Create log file path
            log_file_path = os.path.join(logs_dir, f"{name.replace('.', '_')}.log")
            
            file_handler = logging.FileHandler(log_file_path, encoding='utf-8')
            file_handler.setLevel(level)
            file_handler.setFormatter(formatter)
            
            # Add the filter to the file handler as well
            # This is optional - remove this line if you want debug messages
            # to always be written to the log file
            file_handler.addFilter(DebugModeFilter())
            
            logger.addHandler(file_handler)
        except Exception as e:
            print(f"Failed to set up file logging for {name}: {e}")
    
    return logger

def refresh_debug_status():
    """
    Refreshes the cached debug status.
    Should be called when the configuration changes.
    """
    global _debug_mode_enabled
    
    try:
        # Reset the cache
        _debug_mode_enabled = None
        
        # Force cache invalidation to ensure we get the latest config
        try:
            from utils.config_manager import get_config_manager
            get_config_manager().invalidate_cache()
        except Exception as e:
            print(f"Failed to invalidate config cache: {e}")
        
        # Reload the debug status
        debug_enabled = is_debug_mode_enabled()
        
        # Create a logger for this function
        logger = logging.getLogger('ddc.config')
        
        # Output the debug status
        if debug_enabled:
            logger.info("Debug mode has been ENABLED - DEBUG messages will be displayed")
        else:
            logger.info("Debug mode has been DISABLED - DEBUG messages will be suppressed")
        
        return debug_enabled
            
    except Exception as e:
        print(f"Error refreshing debug status: {e}")
        return False

def enable_temporary_debug(duration_minutes=10):
    """
    Enables temporary debug mode for a specified duration.
    Debug mode will automatically disable after the duration expires.
    
    Args:
        duration_minutes: How long to enable debug mode for (in minutes)
    
    Returns:
        tuple: (success, expiry_time) - success flag and timestamp when debug will expire
    """
    global _temp_debug_mode_enabled, _temp_debug_expiry
    
    try:
        # Set expiry time
        current_time = time.time()
        _temp_debug_expiry = current_time + (duration_minutes * 60)
        _temp_debug_mode_enabled = True
        
        # Print confirmation message
        expiry_time = datetime.fromtimestamp(_temp_debug_expiry).strftime('%Y-%m-%d %H:%M:%S')
        print(f"**** TEMPORARY DEBUG MODE ACTIVATED for {duration_minutes} minutes (until {expiry_time}) ****")
        print(f"**** Debug mode will now show detailed logs until it expires ****")
        
        # Create a special logger for this message to ensure it appears even before setup
        special_logger = logging.getLogger("ddc.config.temp_debug")
        if not special_logger.handlers:
            handler = logging.StreamHandler(sys.stdout)
            handler.setLevel(logging.INFO)
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            handler.setFormatter(formatter)
            special_logger.addHandler(handler)
            special_logger.setLevel(logging.INFO)
        
        # Log the change using the normal logger and the special logger
        special_logger.info(f"===== TEMPORARY DEBUG MODE ENABLED for {duration_minutes} minutes (until {expiry_time}) =====")
        
        # Try to use the regular logger too
        try:
            logger = logging.getLogger('ddc.config')
            logger.info(f"Temporary debug mode ENABLED for {duration_minutes} minutes (until {expiry_time})")
        except Exception as e:
            print(f"Note: Could not use regular logger to log debug mode activation: {e}")
        
        # Forcibly refresh all filters to recognize debug mode
        try:
            for name in logging.root.manager.loggerDict:
                logger_instance = logging.getLogger(name)
                for handler in logger_instance.handlers:
                    for filter_instance in handler.filters:
                        if isinstance(filter_instance, DebugModeFilter):
                            handler.removeFilter(filter_instance)
                            handler.addFilter(DebugModeFilter())
        except Exception as e:
            print(f"Error refreshing log filters: {e}")
        
        return True, _temp_debug_expiry
    except Exception as e:
        print(f"Error enabling temporary debug mode: {e}")
        return False, 0

def disable_temporary_debug():
    """
    Disables temporary debug mode immediately.
    
    Returns:
        bool: Success or failure
    """
    global _temp_debug_mode_enabled, _temp_debug_expiry
    
    try:
        _temp_debug_mode_enabled = False
        _temp_debug_expiry = 0
        
        # Log the change
        logger = logging.getLogger('ddc.config')
        logger.info("Temporary debug mode DISABLED manually")
        
        return True
    except Exception as e:
        print(f"Error disabling temporary debug mode: {e}")
        return False

def get_temporary_debug_status():
    """
    Gets the current status of temporary debug mode.
    
    Returns:
        tuple: (is_enabled, expiry_time, remaining_seconds) - status info for temp debug
    """
    global _temp_debug_mode_enabled, _temp_debug_expiry
    
    current_time = time.time()
    is_enabled = _temp_debug_mode_enabled and current_time < _temp_debug_expiry
    remaining_seconds = max(0, _temp_debug_expiry - current_time) if is_enabled else 0
    
    return is_enabled, _temp_debug_expiry, remaining_seconds

def setup_all_loggers(level: int = logging.INFO) -> None:
    """
    Configures all project loggers with consistent settings.

    Args:
        level: Log level for all loggers
    """
    # Setup root logger
    root_logger = setup_logger('ddc', level)

    # Setup module loggers
    setup_logger('ddc.bot', level)
    setup_logger('ddc.docker_utils', level)
    setup_logger('ddc.config_loader', level)
    setup_logger('ddc.web_ui', level)
    
    # Check debug status and display in log
    debug_enabled = is_debug_mode_enabled()
    if debug_enabled:
        root_logger.info("Debug mode is enabled - DEBUG messages will be displayed")
    else:
        root_logger.info("Debug mode is disabled - DEBUG messages will be suppressed")

    root_logger.info("All loggers have been configured")

class LoggerMixin:
    """
    Mixin class for classes that require a logger.
    Adds a self.logger attribute.
    """

    def __init__(self, logger_name: Optional[str] = None, *args, **kwargs):
        # Derive name from class name if not provided
        if logger_name is None:
            logger_name = f"ddc.{self.__class__.__name__}"

        self.logger = logging.getLogger(logger_name)
        super().__init__(*args, **kwargs) 

def get_logger(name: str, level: Optional[int] = None) -> logging.Logger:
    """
    Zentrale Funktion für Logger-Erstellung mit konsistenter Konfiguration.
    Ersetzt alle direkten logging.getLogger() Aufrufe im Projekt.
    
    Args:
        name: Logger-Name (z.B. 'ddc.module_name')
        level: Optional log level override
        
    Returns:
        Konfigurierter Logger
    """
    # Verwende setup_logger für konsistente Konfiguration
    if level is None:
        # Bestimme Level basierend auf Debug-Modus
        level = logging.DEBUG if is_debug_mode_enabled() else logging.INFO
    
    return setup_logger(name, level=level)

# Convenience-Funktionen für häufig verwendete Logger
def get_module_logger(module_name: str) -> logging.Logger:
    """Erstellt Logger für Module mit ddc. Prefix"""
    return get_logger(f'ddc.{module_name}')

def get_import_logger() -> logging.Logger:
    """Erstellt Logger für Import-Operationen"""
    return get_logger('discord.app_commands_import')

def get_action_logger() -> logging.Logger:
    """Erstellt Logger für User-Actions"""
    return get_logger('user_actions') 