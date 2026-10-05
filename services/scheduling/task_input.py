# -*- coding: utf-8 -*-
"""Reading and checking what a user typed for a task: times, months, weekdays.

Moved out of services/scheduling/scheduler.py on 2026-09-28 - that file stood at
2,243 lines on the ceiling list. The code is unchanged; scheduler.py imports
every name back.
"""

import logging
from functools import lru_cache
from typing import Optional, Tuple

from utils.logging_utils import get_module_logger
from utils.time_utils import get_datetime_imports

from services.scheduling.scheduled_task import (CYCLE_CRON, CYCLE_MONTHLY, CYCLE_ONCE, CYCLE_WEEKLY,
                                                CYCLE_YEARLY, VALID_ACTIONS, VALID_CYCLES)

datetime, timedelta, timezone, time = get_datetime_imports()

logger = get_module_logger('scheduler')

# --- Validation & Parsing Functions (Maintain and adjust if needed) ---

def date_exists(day: int, month: int, year: Optional[int] = None) -> bool:
    """Whether ``day``.``month`` is a date; without a year, in some year (29 February is).

    Without a year this is the rule _validate_yearly_cycle applies (it checks
    against a leap year); with one, the rule of _validate_once_cycle. The task
    dropdowns in Discord offer only what passes it (2026-10-05: they offered
    31 February, and a yearly task for it ran on the 28th without a word).
    """
    import calendar
    if not (1 <= month <= 12):
        return False
    return 1 <= day <= calendar.monthrange(year if year else 2024, month)[1]

def _validate_time_parameters(hour: Optional[int], minute: Optional[int]) -> Tuple[bool, str]:
    """Validate hour and minute parameters."""
    if hour is None or not (0 <= hour <= 23):
        return False, "Hour must be between 0 and 23."
    if minute is None or not (0 <= minute <= 59):
        return False, "Minute must be between 0 and 59."
    return True, ""

def _validate_once_cycle(year: Optional[int], month: Optional[int], day: Optional[int],
                         hour: int, minute: int) -> Tuple[bool, str]:
    """Validate parameters for ONCE cycle."""
    if year is None or not (2000 <= year <= 2100):
        return False, "Year must be between 2000 and 2100 for one-time tasks."
    if month is None or not (1 <= month <= 12):
        return False, "Month must be between 1 and 12 for one-time tasks."
    if day is None or not (1 <= day <= 31):
        return False, "Day must be between 1 and 31 for one-time tasks."
    try:
        datetime(year, month, day, hour, minute)
    except ValueError as e:
        return False, f"Invalid date for one-time task: {e}"
    return True, ""

def _validate_yearly_cycle(month: Optional[int], day: Optional[int],
                           hour: int, minute: int) -> Tuple[bool, str]:
    """Validate parameters for YEARLY cycle."""
    if month is None or not (1 <= month <= 12):
        return False, "Month must be between 1 and 12 for yearly tasks."
    if day is None or not (1 <= day <= 31):
        return False, "Day must be between 1 and 31 for yearly tasks."
    try:
        # Checked against a LEAP year, so 29 February passes: it is a real
        # date, and _calculate_yearly_next_run clamps it to the 28th in
        # ordinary years. Refusing it made Discord stricter than the panel
        # about the one date the calculation handles on purpose.
        datetime(2024, month, day, hour, minute)
    except ValueError as e:
        return False, f"Invalid date for yearly task: {e}"
    return True, ""

def _validate_weekly_cycle(weekday: Optional[int]) -> Tuple[bool, str]:
    """Validate parameters for WEEKLY cycle."""
    if weekday is None or not (0 <= weekday <= 6):
        return False, "Weekday for weekly tasks."
    return True, ""

def _validate_monthly_cycle(day: Optional[int]) -> Tuple[bool, str]:
    """Validate parameters for MONTHLY cycle."""
    if day is None or not (1 <= day <= 31):
        return False, "Day for monthly tasks."
    return True, ""

def validate_new_task_input( # Primarily used by the Discord Bot
    container_name: str, action: str, cycle: str,
    year: Optional[int] = None, month: Optional[int] = None,
    day: Optional[int] = None, hour: Optional[int] = None,
    minute: Optional[int] = None, weekday: Optional[int] = None,
    cron_string: Optional[str] = None # Added for Cron tasks
) -> Tuple[bool, str]:
    """Validates the input for creating a new task."""
    # Validate container name
    if not container_name:
        return False, "Container name is required"

    from utils.common_helpers import validate_container_name
    if not validate_container_name(container_name):
        return False, f"Invalid container name format: {container_name}"

    # Validate action
    if action not in VALID_ACTIONS:
        return False, f"Invalid action: {action}. Must be one of: {', '.join(VALID_ACTIONS)}"

    # Validate cycle
    if cycle not in VALID_CYCLES:
        return False, f"Invalid cycle: {cycle}. Must be one of: {', '.join(VALID_CYCLES)}"

    # Validate CRON cycle
    if cycle == CYCLE_CRON:
        if not cron_string:
            return False, "Cron string is required for cron cycle."
        return True, ""

    # Validate time parameters for non-CRON cycles
    is_valid, error_msg = _validate_time_parameters(hour, minute)
    if not is_valid:
        return False, error_msg

    # Validate cycle-specific parameters
    if cycle == CYCLE_ONCE:
        return _validate_once_cycle(year, month, day, hour, minute)
    elif cycle == CYCLE_YEARLY:
        return _validate_yearly_cycle(month, day, hour, minute)
    elif cycle == CYCLE_WEEKLY:
        return _validate_weekly_cycle(weekday)
    elif cycle == CYCLE_MONTHLY:
        return _validate_monthly_cycle(day)

    return True, ""

# Add caching to validation and parsing methods
@lru_cache(maxsize=128)
def parse_time_string(time_str: str) -> Tuple[Optional[int], Optional[int]]:
    """Parse a time string into hour and minute components. Supports HH:MM format and others."""
    if not time_str:
        return None, None

    # Clean the input
    time_str = time_str.strip()

    # Direct HH:MM format (preferred for Discord scheduling)
    if ':' in time_str:
        try:
            parts = time_str.split(':')
            if len(parts) == 2:
                hour_part = parts[0].strip()
                minute_part = parts[1].strip()

                # Ensure it's numbers
                if hour_part.isdigit() and minute_part.isdigit():
                    hour = int(hour_part)
                    minute = int(minute_part)

                    # Range validation
                    if 0 <= hour <= 23 and 0 <= minute <= 59:
                        if logger.isEnabledFor(logging.DEBUG):
                            logger.debug(f"Parsed time from HH:MM format '{time_str}' to {hour:02d}:{minute:02d}")
                        return hour, minute
                    else:
                        logger.warning(f"Time values out of range in '{time_str}': hour={hour}, minute={minute}")
        except ValueError as e:
            logger.warning(f"Could not parse HH:MM time format '{time_str}': {e}")

    # Try other common formats if the above doesn't work
    try:
        # Try different formats with datetime
        for fmt in ['%H:%M', '%I:%M %p', '%I:%M%p', '%H.%M', '%I.%M %p', '%I.%M%p']:
            try:
                dt = datetime.strptime(time_str, fmt)
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(f"Parsed time '{time_str}' with format '{fmt}' to {dt.hour:02d}:{dt.minute:02d}")
                return dt.hour, dt.minute
            except ValueError:
                continue
    except (ValueError, TypeError, AttributeError) as e:
        # Data errors (invalid time format, type mismatches, datetime operations)
        logger.warning(f"Data error parsing time string '{time_str}': {e}")

    # Fallback: Try simple number as hour (e.g. "14" -> 14:00)
    if time_str.isdigit():
        hour = int(time_str)
        if 0 <= hour <= 23:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(f"Parsed single-number time '{time_str}' as {hour:02d}:00")
            return hour, 0

    logger.warning(f"Could not parse time string '{time_str}' with any known format")
    return None, None

@lru_cache(maxsize=64)
def parse_month_string(month_str: str) -> Optional[int]:
    month_names = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
    month_map = {name.lower(): i+1 for i, name in enumerate(month_names)}
    short_month_map = {name[:3].lower(): i+1 for i, name in enumerate(month_names)}
    month_map.update(short_month_map)

    # German month names to support international date formats
    german_months = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"]
    german_short_months = [m[:3] for m in german_months]
    month_map.update({name.lower(): i+1 for i, name in enumerate(german_months)})
    month_map.update({name.lower(): i+1 for i, name in enumerate(german_short_months)})
    try:
        month_str = month_str.lower().strip()
        if month_str.isdigit():
            month = int(month_str)
            return month if 1 <= month <= 12 else None
        return month_map.get(month_str)
    except (ValueError, TypeError, AttributeError):
        # Data errors (invalid month string, type mismatches, string operations)
        return None

@lru_cache(maxsize=32)
def parse_weekday_string(weekday_str: str) -> Optional[int]:
    """
    Parse a weekday string to an integer (0=Monday, 6=Sunday).

    Args:
        weekday_str: String representation of a weekday (e.g., 'monday', 'mon', or '1'-'7' with Monday=1)

    Returns:
        Integer representation of the weekday (0-6) or None if invalid
    """
    weekday_str = weekday_str.strip().lower()

    # Numeric input uses 1-7 with Monday=1 (as the command help documents);
    # anything else, including 0, is invalid
    if weekday_str.isdigit():
        weekday = int(weekday_str)
        return weekday - 1 if 1 <= weekday <= 7 else None

    # Text input (weekday names)
    weekday_map = {
        # English names
        'monday': 0, 'mon': 0, 'm': 0,
        'tuesday': 1, 'tue': 1, 'tu': 1,
        'wednesday': 2, 'wed': 2, 'w': 2,
        'thursday': 3, 'thu': 3, 'th': 3,
        'friday': 4, 'fri': 4, 'f': 4,
        'saturday': 5, 'sat': 5, 'sa': 5,
        'sunday': 6, 'sun': 6, 'su': 6,
    }

    # Direct match
    if weekday_str in weekday_map:
        return weekday_map[weekday_str]

    # Partial match (startswith)
    # This is useful if the user only enters part of the name
    for name, value in weekday_map.items():
        if name.startswith(weekday_str) and len(weekday_str) >= 2:
            return value

    return None
