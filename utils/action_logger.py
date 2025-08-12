# -*- coding: utf-8 -*-
"""
Central logging functionality for user actions.
This file is used by both the Web UI and the Discord bot.
Supports both plain text and JSON format logging.
"""
import logging
import os
import time
import json
from datetime import datetime
import pytz
import sys
from typing import Optional, Dict, Any

# Define the path to the log files directly here
_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_MODULE_DIR, ".."))
_LOG_DIR = os.path.join(_PROJECT_ROOT, 'logs')
_ACTION_LOG_FILE = os.path.join(_LOG_DIR, 'user_actions.log')
_ACTION_JSON_FILE = os.path.join(_LOG_DIR, 'user_actions.json')

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

def log_user_action_to_json(action_data: Dict[str, Any]) -> bool:
    """
    Append a single action to the JSON log file.
    
    Args:
        action_data: Dictionary containing the action data
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Ensure the directory exists
        os.makedirs(_LOG_DIR, exist_ok=True)
        
        # Read existing data or initialize empty list
        actions = []
        if os.path.exists(_ACTION_JSON_FILE):
            try:
                with open(_ACTION_JSON_FILE, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
                    if content:
                        actions = json.loads(content)
            except (json.JSONDecodeError, IOError):
                # If JSON is corrupted, start fresh
                actions = []
        
        # Append new action
        actions.append(action_data)
        
        # Keep only last 10000 entries to prevent huge files
        if len(actions) > 10000:
            actions = actions[-10000:]
        
        # Write back to file
        with open(_ACTION_JSON_FILE, 'w', encoding='utf-8') as f:
            json.dump(actions, f, indent=2, ensure_ascii=False)
        
        return True
        
    except Exception as e:
        print(f"ERROR: Failed to write to JSON log: {e}", file=sys.stderr)
        return False

def log_user_action(action: str, target: str, user: str = "System", source: str = "Unknown", details: str = "-"):
    """
    Log user actions for audit purposes in both text and JSON format.
    
    Args:
        action: The action being performed (e.g., START, STOP, RESTART)
        target: The target of the action (e.g., container name)
        user: The user who initiated the action
        source: Source of the action (e.g., Web UI, Discord Command)
        details: Additional details about the action
    """
    try:
        # Get timezone for consistent timestamping
        try:
            from utils.config_loader import load_config
            config = load_config()
            timezone_str = config.get('timezone', 'Europe/Berlin')
            tz = pytz.timezone(timezone_str)
        except Exception:
            timezone_str = 'UTC'
            tz = pytz.UTC
        
        now = datetime.now(tz)
        
        # Log to traditional text file (existing functionality)
        if user_action_logger:
            user_action_logger.info(f"{action}|{target}|{user}|{source}|{details}")
        else:
            # Fallback to standard logger
            logging.getLogger("ddc.action_logger").warning(
                f"Unable to log user action: {action} by {user} on {target}"
            )
        
        # Log to JSON file (new functionality)
        action_data = {
            "timestamp": now.isoformat(),
            "timestamp_unix": int(now.timestamp()),
            "timezone": timezone_str,
            "action": action,
            "target": target,
            "user": user,
            "source": source,
            "details": details,
            "id": f"{int(now.timestamp())}-{hash(f'{action}{target}{user}{source}') % 10000:04d}"
        }
        
        log_user_action_to_json(action_data)
        
    except Exception as e:
        # Silent error handling for robustness in all environments
        try:
            print(f"ERROR: Failed to log user action: {e}", file=sys.stderr)
        except (OSError, IOError):
            pass  # Last resort: Ignore I/O errors only

def get_action_logs_json(limit: int = 500) -> list:
    """
    Retrieve action logs from JSON file.
    
    Args:
        limit: Maximum number of entries to return (default: 500)
        
    Returns:
        list: List of action log entries, newest first
    """
    try:
        if not os.path.exists(_ACTION_JSON_FILE):
            return []
        
        with open(_ACTION_JSON_FILE, 'r', encoding='utf-8') as f:
            content = f.read().strip()
            if not content:
                return []
                
            actions = json.loads(content)
            
            # Sort by timestamp (newest first) and limit results
            actions.sort(key=lambda x: x.get('timestamp_unix', 0), reverse=True)
            return actions[:limit]
            
    except Exception as e:
        print(f"ERROR: Failed to read JSON log: {e}", file=sys.stderr)
        return []

def get_action_logs_text(limit: int = 500) -> str:
    """
    Retrieve action logs as formatted text (for backward compatibility).
    First tries JSON format, then falls back to traditional text log.
    
    Args:
        limit: Maximum number of entries to return (default: 500)
        
    Returns:
        str: Formatted log text
    """
    try:
        # First try JSON format
        actions = get_action_logs_json(limit)
        if actions:
            lines = []
            for action in actions:
                # Convert ISO timestamp back to readable format
                try:
                    dt = datetime.fromisoformat(action['timestamp'].replace('Z', '+00:00'))
                    timestamp_str = dt.strftime('%Y-%m-%d %H:%M:%S %Z')
                except:
                    timestamp_str = action.get('timestamp', 'Unknown')
                
                line = f"{timestamp_str} - {action['action']}|{action['target']}|{action['user']}|{action['source']}|{action['details']}"
                lines.append(line)
            
            return '\n'.join(lines)
        
        # Fallback to traditional text log file
        if os.path.exists(_ACTION_LOG_FILE):
            try:
                with open(_ACTION_LOG_FILE, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                    # Return last 'limit' lines
                    lines = lines[-limit:] if len(lines) > limit else lines
                    return ''.join(lines).strip()
            except Exception as e:
                print(f"ERROR: Failed to read text log file: {e}", file=sys.stderr)
        
        return "No action logs available"
        
    except Exception as e:
        print(f"ERROR: Failed to format action logs: {e}", file=sys.stderr)
        return "Error loading action logs"

def migrate_text_logs_to_json():
    """
    Migrate existing text logs to JSON format (one-time migration).
    This preserves existing log entries when upgrading to JSON format.
    """
    if not os.path.exists(_ACTION_LOG_FILE):
        return False
    
    if os.path.exists(_ACTION_JSON_FILE):
        # JSON file already exists, don't overwrite
        return False
    
    try:
        with open(_ACTION_LOG_FILE, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        actions = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # Parse old format: "2025-08-10 18:14:19 CEST - DOCKER_STOP|Valheim|maxzeichen (maxzeichen)|Discord Button|Container: Valheim"
            try:
                if ' - ' in line:
                    timestamp_part, action_part = line.split(' - ', 1)
                    
                    # Parse action part: ACTION|target|user|source|details
                    parts = action_part.split('|')
                    if len(parts) >= 5:
                        action, target, user, source = parts[:4]
                        details = '|'.join(parts[4:])  # Join remaining parts for details
                        
                        # Try to parse timestamp
                        try:
                            # Handle different timezone formats
                            if ' CEST ' in timestamp_part or ' CET ' in timestamp_part:
                                dt = datetime.strptime(timestamp_part.replace(' CEST', '').replace(' CET', ''), '%Y-%m-%d %H:%M:%S')
                                dt = dt.replace(tzinfo=pytz.timezone('Europe/Berlin'))
                            else:
                                # Fallback parsing
                                dt = datetime.strptime(timestamp_part[:19], '%Y-%m-%d %H:%M:%S')
                                dt = dt.replace(tzinfo=pytz.UTC)
                        except:
                            # Fallback to current time if parsing fails
                            dt = datetime.now(pytz.UTC)
                        
                        # Create JSON entry
                        action_data = {
                            "timestamp": dt.isoformat(),
                            "timestamp_unix": int(dt.timestamp()),
                            "timezone": str(dt.tzinfo),
                            "action": action.strip(),
                            "target": target.strip(),
                            "user": user.strip(),
                            "source": source.strip(),
                            "details": details.strip(),
                            "id": f"{int(dt.timestamp())}-{hash(f'{action}{target}{user}{source}') % 10000:04d}",
                            "migrated": True
                        }
                        
                        actions.append(action_data)
            except Exception as e:
                print(f"WARNING: Failed to parse log line: {line} - {e}", file=sys.stderr)
                continue
        
        if actions:
            # Write to JSON file
            with open(_ACTION_JSON_FILE, 'w', encoding='utf-8') as f:
                json.dump(actions, f, indent=2, ensure_ascii=False)
            
            print(f"INFO: Migrated {len(actions)} log entries to JSON format", file=sys.stderr)
            return True
        
    except Exception as e:
        print(f"ERROR: Failed to migrate logs to JSON: {e}", file=sys.stderr)
        return False
    
    return False

# Auto-migrate on first import (if needed)
if os.path.exists(_ACTION_LOG_FILE) and not os.path.exists(_ACTION_JSON_FILE):
    try:
        migrate_text_logs_to_json()
    except Exception as e:
        print(f"WARNING: Auto-migration failed: {e}", file=sys.stderr)

# The test code has been removed as it is no longer needed 