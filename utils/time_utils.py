# -*- coding: utf-8 -*-
import time
import pytz
import logging
from datetime import datetime, timedelta, timezone
from typing import Union, Tuple, List, Dict, Any, Optional
from utils.logging_utils import setup_logger

logger = setup_logger('ddc.time_utils')

# Zentrale datetime-Imports für konsistente Verwendung im gesamten Projekt
def get_datetime_imports():
    """
    Zentrale Funktion für datetime-Imports.
    Eliminiert redundante 'from datetime import datetime' Statements.
    
    Returns:
        Tuple mit (datetime, timedelta, timezone, time)
    """
    return datetime, timedelta, timezone, time

def get_current_time(tz_name: Optional[str] = None) -> datetime:
    """
    Gibt die aktuelle Zeit in der angegebenen Zeitzone zurück.
    
    Args:
        tz_name: Name der Zeitzone (z.B. 'Europe/Berlin'), None für UTC
        
    Returns:
        Aktuelle Zeit als timezone-aware datetime
    """
    if tz_name:
        try:
            tz = pytz.timezone(tz_name)
            return datetime.now(tz)
        except Exception as e:
            logger.warning(f"Invalid timezone '{tz_name}', falling back to UTC: {e}")
    
    return datetime.now(timezone.utc)

def get_utc_timestamp() -> float:
    """Gibt den aktuellen UTC-Timestamp zurück"""
    return time.time()

def timestamp_to_datetime(timestamp: float, tz_name: Optional[str] = None) -> datetime:
    """
    Konvertiert einen Timestamp zu einem datetime-Objekt.
    
    Args:
        timestamp: Unix-Timestamp
        tz_name: Ziel-Zeitzone (None für UTC)
        
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
    Konvertiert ein datetime-Objekt zu einem Timestamp.
    
    Args:
        dt: datetime object (timezone-aware oder naive)
        
    Returns:
        Unix timestamp
    """
    # Wenn naive datetime, als UTC interpretieren
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    
    return dt.timestamp()

def format_duration(seconds: float) -> str:
    """
    Formatiert eine Dauer in Sekunden zu einem lesbaren String.
    
    Args:
        seconds: Dauer in Sekunden
        
    Returns:
        Formatierte Dauer (z.B. "2h 30m 15s")
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
    Prüft, ob zwei datetime-Objekte am selben Tag liegen.
    
    Args:
        dt1: Erstes datetime
        dt2: Zweites datetime
        tz_name: Zeitzone für Vergleich (None für UTC)
        
    Returns:
        True wenn beide am selben Tag liegen
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
    Gibt den Zeitzone-Offset als String zurück.
    
    Args:
        tz_name: Name der Zeitzone
        
    Returns:
        Offset-String (z.B. "+01:00")
    """
    try:
        tz = pytz.timezone(tz_name)
        now = datetime.now(tz)
        return now.strftime('%z')
    except Exception as e:
        logger.warning(f"Could not get offset for timezone '{tz_name}': {e}")
        return "+00:00"

def format_datetime_with_timezone(dt: datetime, 
                                  timezone_name: Optional[str] = None,
                                  fmt: str = "%Y-%m-%d %H:%M:%S %Z") -> str:
    """
    SIMPLE BUT DYNAMIC VERSION - Gets timezone from config!
    """
    
    if not dt:
        return "N/A"
    
    # Get timezone from config if not specified
    if timezone_name is None:
        timezone_name = _get_timezone_safe()
    
    # Default to Europe/Berlin if config fails
    if not timezone_name:
        timezone_name = 'Europe/Berlin'
    
    try:
        # STEP 1: Ensure we have a UTC datetime
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        elif dt.tzinfo != timezone.utc:
            dt = dt.astimezone(timezone.utc)
        
        # STEP 2: Convert to target timezone (DYNAMIC!)
        target_tz = pytz.timezone(timezone_name)
        target_time = dt.astimezone(target_tz)
        
        # STEP 3: Format and return
        return target_time.strftime(fmt)
        
    except Exception as e:
        # FALLBACK: Try Europe/Berlin if configured timezone fails
        try:
            if timezone_name != 'Europe/Berlin':
                berlin_tz = pytz.timezone('Europe/Berlin')
                berlin_time = dt.astimezone(berlin_tz)
                return berlin_time.strftime(fmt)
            else:
                # Even Berlin failed, manual calculation
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                # Add 2 hours manually (approximate for Berlin)
                berlin_manual = dt + timedelta(hours=2)
                return berlin_manual.strftime(fmt.replace("%Z", "CEST"))
                
        except Exception:
            return "Zeit nicht verfügbar"


def _get_timezone_safe() -> str:
    """
    Safely get timezone from config without causing circular dependencies.
    Returns Europe/Berlin as fallback.
    """
    try:
        # Try to read timezone directly from config file without using the logging system
        import os
        import json
        
        config_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config")
        config_file = os.path.join(config_dir, "bot_config.json")
        
        if os.path.exists(config_file):
            with open(config_file, 'r') as f:
                config = json.load(f)
            return config.get('timezone', 'Europe/Berlin')
    except Exception:
        # Any error -> fallback silently
        pass
    
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