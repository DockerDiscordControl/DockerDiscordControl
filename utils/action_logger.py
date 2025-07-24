# -*- coding: utf-8 -*-
"""
Central logging functionality for user actions.
This file is used by both the Web UI and the Discord bot.
"""
import logging
import os
import time
from datetime import datetime
import pytz
import sys
from typing import Optional

# Define the path to the log file directly here
_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_MODULE_DIR, ".."))
_LOG_DIR = os.path.join(_PROJECT_ROOT, 'logs')
_ACTION_LOG_FILE = os.path.join(_LOG_DIR, 'user_actions.log')

# Flag to avoid multiple initialization messages
_logger_initialized = False

# Stable configuration for the action_logger
user_action_logger = logging.getLogger('user_actions')
user_action_logger.setLevel(logging.INFO)
user_action_logger.propagate = False  # Prevents duplicate log entries

# Ensure the logger is configured with a FileHandler only once
if not any(isinstance(h, logging.FileHandler) and 
           getattr(h, 'baseFilename', '') == _ACTION_LOG_FILE 
           for h in user_action_logger.handlers):
    try:
        # Ensure the directory exists
        os.makedirs(_LOG_DIR, exist_ok=True)
        
        # Configure the FileHandler
        file_handler = logging.FileHandler(_ACTION_LOG_FILE, encoding='utf-8')
        
        # Try to load timezone from configuration, with fallback
        try:
            from utils.config_loader import load_config
            config = load_config()
            timezone_str = config.get('timezone', 'Europe/Berlin')
            tz = pytz.timezone(timezone_str)
        except Exception:
            # Fallback to UTC time
            timezone_str = 'UTC'
            tz = pytz.UTC
            
        # Configure custom formatter with correct timezone
        class TimezoneFormatter(logging.Formatter):
            def formatTime(self, record, datefmt=None):
                dt = datetime.fromtimestamp(record.created, tz=pytz.UTC)
                dt = dt.astimezone(tz)
                if datefmt:
                    return dt.strftime(datefmt)
                return dt.strftime("%Y-%m-%d %H:%M:%S %Z")
                
        formatter = TimezoneFormatter('%(asctime)s - %(message)s')
        file_handler.setFormatter(formatter)
        user_action_logger.addHandler(file_handler)
        
        # We remove the initialization message to avoid repeated entries
        _logger_initialized = True
    except Exception as e:
        # Fallback to logging to console
        print(f"CRITICAL: Failed to configure action logger: {e}", file=sys.stderr)

def log_user_action(action: str, target: str, user: str = "System", source: str = "Unknown", details: str = "-"):
    """
    Log user actions for audit purposes.
    
    Args:
        action: The action being performed (e.g., START, STOP, RESTART)
        target: The target of the action (e.g., container name)
        user: The user who initiated the action
        source: Source of the action (e.g., Web UI, Discord Command)
        details: Additional details about the action
    """
    try:
        # Sanitize all input parameters to prevent log injection attacks
        def sanitize_log_input(value: str, max_length: int = 200) -> str:
            """Sanitize input for logging to prevent injection attacks."""
            if not isinstance(value, str):
                value = str(value)
            # Remove or replace potentially dangerous characters
            sanitized = value.replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')
            # Limit length to prevent log file bloat
            return sanitized[:max_length] if len(sanitized) > max_length else sanitized
        
        # Sanitize all parameters
        safe_action = sanitize_log_input(action, 50)
        safe_target = sanitize_log_input(target, 100)
        safe_user = sanitize_log_input(user, 100)
        safe_source = sanitize_log_input(source, 50)
        safe_details = sanitize_log_input(details, 200)
        
        if user_action_logger:
            user_action_logger.info(f"{safe_action}|{safe_target}|{safe_user}|{safe_source}|{safe_details}")
        else:
            # Fallback to standard logger
            logging.getLogger("ddc.action_logger").warning(
                f"Unable to log user action: {safe_action} by {safe_user} on {safe_target}"
            )
    except Exception as e:
        # Silent error handling for robustness in all environments
        try:
            print(f"ERROR: Failed to log user action: {e}", file=sys.stderr)
        except:
            pass  # Last resort: Ignore all errors

# The test code has been removed as it is no longer needed 