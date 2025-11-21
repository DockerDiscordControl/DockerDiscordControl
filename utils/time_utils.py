# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
import time
import os
import json
import logging
import pytz
from datetime import datetime, timedelta, timezone
from typing import Union, Tuple, List, Dict, Any, Optional
from zoneinfo import ZoneInfo
from utils.logging_utils import setup_logger

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
        except (pytz.exceptions.UnknownTimeZoneError, AttributeError, TypeError) as e:
            logger.warning(f"Invalid timezone '{tz_name}', falling back to UTC: {e}", exc_info=True)

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
        except (pytz.exceptions.UnknownTimeZoneError, AttributeError, TypeError) as e:
            logger.warning(f"Invalid timezone '{tz_name}', returning UTC: {e}", exc_info=True)

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
        except (pytz.exceptions.UnknownTimeZoneError, pytz.exceptions.AmbiguousTimeError, pytz.exceptions.NonExistentTimeError, AttributeError, TypeError) as e:
            logger.warning(f"Invalid timezone '{tz_name}', using UTC: {e}", exc_info=True)

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
    except (pytz.exceptions.UnknownTimeZoneError, AttributeError, TypeError, ValueError) as e:
        logger.warning(f"Could not get offset for timezone '{tz_name}': {e}", exc_info=True)
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

    # Get target timezone using the public API
    tz_name = timezone_name or get_configured_timezone()
    
    try:
        # First attempt: Try zoneinfo (Python 3.9+)
        target_tz = ZoneInfo(tz_name)
        local_time = dt.astimezone(target_tz)
        format_str = "%H:%M:%S" if time_only else "%d.%m.%Y %H:%M:%S"
        return local_time.strftime(format_str)
    except (ImportError, AttributeError, TypeError, ValueError, OSError) as e1:
        logger.warning(f"zoneinfo conversion failed: {e1}", exc_info=True)
        try:
            # Second attempt: Try pytz
            target_tz = pytz.timezone(tz_name)
            local_time = dt.astimezone(target_tz)
            return local_time.strftime("%d.%m.%Y %H:%M:%S")
        except (pytz.exceptions.UnknownTimeZoneError, AttributeError, TypeError, ValueError) as e2:
            logger.warning(f"pytz conversion failed: {e2}", exc_info=True)
            try:
                # Third attempt: Manual offset for Europe/Berlin
                if tz_name == 'Europe/Berlin':
                    # Manually handle DST - rough approximation
                    now = datetime.now()
                    is_dst = now.month > 3 and now.month < 10
                    offset = 2 if is_dst else 1
                    local_time = dt.astimezone(timezone(timedelta(hours=offset)))
                    return local_time.strftime("%d.%m.%Y %H:%M:%S")
            except (AttributeError, TypeError, ValueError, OSError) as e3:
                logger.warning(f"Manual timezone conversion failed: {e3}", exc_info=True)

            # Final fallback: Just use UTC
            try:
                utc_time = dt.astimezone(timezone.utc)
                return utc_time.strftime("%d.%m.%Y %H:%M:%S UTC")
            except (AttributeError, TypeError, ValueError) as e4:
                logger.error(f"UTC fallback failed: {e4}", exc_info=True)
                return dt.strftime("%d.%m.%Y %H:%M:%S") + " (timezone unknown)"


# Global timezone cache for performance
_cached_timezone = None
_cache_timestamp = None
_CACHE_DURATION = 300  # 5 minutes cache

def get_configured_timezone() -> str:
    """
    Public API to get the configured timezone from the Web UI.
    This is the SINGLE SOURCE OF TRUTH for timezone throughout the application.

    Returns:
        str: The configured timezone string (e.g., 'Europe/Berlin', 'UTC')
    """
    global _cached_timezone, _cache_timestamp

    # Check cache first (valid for 5 minutes)
    if _cached_timezone and _cache_timestamp:
        if time.time() - _cache_timestamp < _CACHE_DURATION:
            return _cached_timezone

    # Get fresh timezone
    tz = _get_timezone_safe()

    # Update cache
    _cached_timezone = tz
    _cache_timestamp = time.time()

    return tz

def _get_timezone_safe():
    """Get timezone from config with multiple fallbacks - SERVICE FIRST compliant."""
    try:
        # First priority: Environment variable (for container-level override)
        tz = os.environ.get('TZ')
        if tz:
            logger.debug(f"Using timezone from TZ environment variable: {tz}")
            return tz

        # Second priority: Service First - Use load_config from config_service
        try:
            from services.config.config_service import load_config
            config = load_config()

            # Look for 'timezone' (correct key name)
            if config and config.get('timezone'):
                tz = config['timezone']
                logger.debug(f"Using timezone from config service: {tz}")
                return tz
        except ImportError:
            logger.warning("Config service not available, trying alternate methods")
        except (AttributeError, TypeError, KeyError, RuntimeError) as e:
            logger.debug(f"Could not get timezone from config service: {e}", exc_info=True)

        # Third priority: Use ConfigManager if available (for legacy support)
        try:
            from services.config.config_service import get_config_service as get_config_manager
            config = get_config_manager().get_config()
            if config and config.get('timezone'):
                tz = config['timezone']
                logger.debug(f"Using timezone from ConfigManager: {tz}")
                return tz
        except (ImportError, AttributeError, TypeError, KeyError, RuntimeError) as e:
            logger.debug(f"Could not get timezone from ConfigManager: {e}", exc_info=True)

        # Final fallback: Default to UTC (safer than hardcoded Europe/Berlin)
        logger.warning("All timezone detection methods failed, falling back to UTC")
        return 'UTC'

    except (RuntimeError, SystemError) as e:
        logger.error(f"Critical error in _get_timezone_safe: {e}", exc_info=True)
        return 'UTC'
            
def clear_timezone_cache():
    """
    Clear the cached timezone to force a fresh load from config.
    Call this when the timezone setting is changed in the Web UI.
    """
    global _cached_timezone, _cache_timestamp
    _cached_timezone = None
    _cache_timestamp = None
    logger.info("Timezone cache cleared - will reload from config on next access")

def get_log_timestamp(include_tz: bool = True) -> str:
    """
    Get a formatted timestamp string for logging purposes.
    Uses the configured timezone from Web UI.

    Args:
        include_tz: Whether to include timezone name in the output

    Returns:
        str: Formatted timestamp (e.g., '2024-01-15 14:30:45' or '2024-01-15 14:30:45 CET')
    """
    tz_name = get_configured_timezone()

    try:
        tz = pytz.timezone(tz_name)
        now = datetime.now(tz)

        if include_tz:
            return now.strftime('%Y-%m-%d %H:%M:%S %Z')
        else:
            return now.strftime('%Y-%m-%d %H:%M:%S')
    except (pytz.exceptions.UnknownTimeZoneError, AttributeError, TypeError, ValueError) as e:
        logger.error(f"Error formatting log timestamp: {e}", exc_info=True)
        # Fallback to UTC
        now = datetime.now(timezone.utc)
        return now.strftime('%Y-%m-%d %H:%M:%S UTC')

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
