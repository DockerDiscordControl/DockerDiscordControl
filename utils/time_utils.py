# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
import time
import pytz
import logging
from datetime import datetime, timedelta, timezone
from typing import Union, Tuple, List, Dict, Any, Optional
from utils.logging_utils import setup_logger
import os
import json
from datetime import datetime, timezone, timedelta
import logging
from zoneinfo import ZoneInfo
import pytz

logger = setup_logger('ddc.time_utils')

# Central datetime imports for consistent usage throughout the project
def get_datetime_imports():
    """
    Central function for datetime imports.
    Eliminates redundant 'from datetime import datetime' statements.

    Returns:
        Tuple with (datetime, timedelta, timezone, time)
    """
    return datetime, timedelta, timezone, time

def get_current_time(tz_name: Optional[str] = None) -> datetime:
    """
    Returns the current time in the specified timezone.

    Args:
        tz_name: Name of the timezone (e.g. 'Europe/Berlin'), None for UTC

    Returns:
        Current time as timezone-aware datetime
    """
    if tz_name:
        try:
            tz = pytz.timezone(tz_name)
            return datetime.now(tz)
        except Exception as e:
            logger.warning(f"Invalid timezone '{tz_name}', falling back to UTC: {e}")
    
    return datetime.now(timezone.utc)

def get_utc_timestamp() -> float:
    """Returns the current UTC timestamp"""
    return time.time()

def timestamp_to_datetime(timestamp: float, tz_name: Optional[str] = None) -> datetime:
    """
    Converts a timestamp to a datetime object.

    Args:
        timestamp: Unix timestamp
        tz_name: Target timezone (None for UTC)

    Returns:
        Timezone-aware datetime object
    """
    dt = datetime.fromtimestamp(timestamp, timezone.utc)
    
    if tz_name:
        try:
            target_tz = pytz.timezone(tz_name)
            return dt.astimezone(target_tz)
        except Exception as e:
            logger.warning(f"Invalid timezone '{tz_name}', returning UTC: {e}")
    
    return dt

def datetime_to_timestamp(dt: datetime) -> float:
    """
    Converts a datetime object to a timestamp.

    Args:
        dt: datetime object (timezone-aware or naive)

    Returns:
        Unix timestamp
    """
    # If naive datetime, interpret as UTC
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    
    return dt.timestamp()

def format_duration(seconds: float) -> str:
    """
    Formats a duration in seconds to a readable string.

    Args:
        seconds: Duration in seconds

    Returns:
        Formatted duration (e.g. "2h 30m 15s")
    """
    if seconds < 60:
        return f"{seconds:.1f}s"
    
    minutes = int(seconds // 60)
    remaining_seconds = int(seconds % 60)
    
    if minutes < 60:
        return f"{minutes}m {remaining_seconds}s"
    
    hours = minutes // 60
    remaining_minutes = minutes % 60
    
    if hours < 24:
        return f"{hours}h {remaining_minutes}m"
    
    days = hours // 24
    remaining_hours = hours % 24
    
    return f"{days}d {remaining_hours}h"

def is_same_day(dt1: datetime, dt2: datetime, tz_name: Optional[str] = None) -> bool:
    """
    Checks if two datetime objects are on the same day.

    Args:
        dt1: First datetime
        dt2: Second datetime
        tz_name: Timezone for comparison (None for UTC)

    Returns:
        True if both are on the same day
    """
    if tz_name:
        try:
            tz = pytz.timezone(tz_name)
            dt1 = dt1.astimezone(tz) if dt1.tzinfo else tz.localize(dt1)
            dt2 = dt2.astimezone(tz) if dt2.tzinfo else tz.localize(dt2)
        except Exception as e:
            logger.warning(f"Invalid timezone '{tz_name}', using UTC: {e}")
    
    return dt1.date() == dt2.date()

def get_timezone_offset(tz_name: str) -> str:
    """
    Returns the timezone offset as a string.

    Args:
        tz_name: Name of the timezone

    Returns:
        Offset string (e.g. "+01:00")
    """
    try:
        tz = pytz.timezone(tz_name)
        now = datetime.now(tz)
        return now.strftime('%z')
    except Exception as e:
        logger.warning(f"Could not get offset for timezone '{tz_name}': {e}")
        return "+00:00"

def format_datetime_with_timezone(dt, timezone_name=None, time_only=False):
    """
    Format a datetime with timezone awareness and multiple fallback mechanisms.
    
    Args:
        dt: The datetime to format
        timezone_name: Optional timezone name to use
        time_only: If True, return only the time part
        
    Returns:
        Formatted datetime string
    """
    if not isinstance(dt, datetime):
        try:
            if isinstance(dt, (int, float)):
                dt = datetime.fromtimestamp(float(dt))
            else:
                logger.error(f"Invalid datetime value (not a number or datetime): {dt}")
                return "Time not available (error)"
        except (TypeError, ValueError) as e:
            logger.error(f"Invalid datetime value: {dt} - {e}")
            return "Time not available (error)"

    # Ensure dt is timezone-aware
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    # Get target timezone
    tz_name = timezone_name or _get_timezone_safe()
    
    try:
        # First attempt: Try zoneinfo (Python 3.9+)
        target_tz = ZoneInfo(tz_name)
        local_time = dt.astimezone(target_tz)
        format_str = "%H:%M:%S" if time_only else "%d.%m.%Y %H:%M:%S"
        return local_time.strftime(format_str)
    except Exception as e1:
        logger.warning(f"zoneinfo conversion failed: {e1}")
        try:
            # Second attempt: Try pytz
            target_tz = pytz.timezone(tz_name)
            local_time = dt.astimezone(target_tz)
            return local_time.strftime("%d.%m.%Y %H:%M:%S")
        except Exception as e2:
            logger.warning(f"pytz conversion failed: {e2}")
            try:
                # Third attempt: Manual offset for Europe/Berlin
                if tz_name == 'Europe/Berlin':
                    # Manually handle DST - rough approximation
                    now = datetime.now()
                    is_dst = now.month > 3 and now.month < 10
                    offset = 2 if is_dst else 1
                    local_time = dt.astimezone(timezone(timedelta(hours=offset)))
                    return local_time.strftime("%d.%m.%Y %H:%M:%S")
            except Exception as e3:
                logger.warning(f"Manual timezone conversion failed: {e3}")
            
            # Final fallback: Just use UTC
            try:
                utc_time = dt.astimezone(timezone.utc)
                return utc_time.strftime("%d.%m.%Y %H:%M:%S UTC")
            except Exception as e4:
                logger.error(f"UTC fallback failed: {e4}")
                return dt.strftime("%d.%m.%Y %H:%M:%S") + " (timezone unknown)"


def _get_timezone_safe():
    """Get timezone from config with multiple fallbacks."""
    try:
        # First try: Environment variable
        tz = os.environ.get('TZ')
        if tz:
            return tz
            
        # Second try: Use ConfigManager for centralized config access
        try:
            from services.config.config_service import get_config_service as get_config_manager
            config = get_config_manager().get_config()
            if config.get('timezone_str'):
                return config['timezone_str']
        except Exception as e:
            logger.debug(f"Could not get timezone from ConfigManager: {e}")
            
        # Third try: Direct config file read (fallback)
        config_path = os.path.join('/app/config', 'bot_config.json')
        if os.path.exists(config_path):
            with open(config_path, 'r') as f:
                config = json.load(f)
                if config.get('timezone_str'):
                    return config['timezone_str']
                
        # Third try: Default to Europe/Berlin
        return 'Europe/Berlin'
    except Exception as e:
        logger.error(f"Error in _get_timezone_safe: {e}")
        return 'Europe/Berlin'
            
def parse_timestamp(timestamp_str: str) -> Optional[datetime]:
    """
    Parse a timestamp string into a datetime object.
    Supports multiple common formats.
    
    Args:
        timestamp_str: String containing a timestamp
        
    Returns:
        Datetime object or None if parsing fails
    """
    # List of formats to try, most specific first
    formats = [
        "%Y-%m-%dT%H:%M:%S.%fZ",  # ISO 8601 with microseconds and Z
        "%Y-%m-%dT%H:%M:%SZ",     # ISO 8601 with Z
        "%Y-%m-%d %H:%M:%S.%f",   # Python datetime default with microseconds
        "%Y-%m-%d %H:%M:%S",      # Python datetime default
        "%Y-%m-%d %H:%M",         # Date with hours and minutes
        "%Y-%m-%d",               # Just date
    ]
    
    for fmt in formats:
        try:
            dt = datetime.strptime(timestamp_str, fmt)
            # For formats without timezone, assume UTC
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
            
    # If no format matched
    logger.warning(f"Could not parse timestamp string: {timestamp_str}")
    return None 