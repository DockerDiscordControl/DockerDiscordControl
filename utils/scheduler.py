# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #

import asyncio
import uuid
import os
import logging  # Added for logging.DEBUG constants
from typing import Dict, Any, List, Optional, Tuple, Union
import calendar
from functools import lru_cache  # Import for caching

# Use central import utilities
from utils.import_utils import import_ujson, import_uvloop, import_croniter, log_performance_status
from utils.time_utils import get_datetime_imports, get_current_time, get_utc_timestamp, timestamp_to_datetime, datetime_to_timestamp
from utils.logging_utils import get_module_logger
from utils.config_loader import load_config, CONFIG_DIR
from utils.docker_utils import docker_action
from utils.action_logger import log_user_action, user_action_logger

# Central datetime imports
datetime, timedelta, timezone, time = get_datetime_imports()
# Import time class from datetime module as datetime_time to avoid conflict
from datetime import time as datetime_time
import pytz

# Performance optimizations with central utilities
json, _using_ujson = import_ujson()
uvloop, _using_uvloop = import_uvloop()

# Logger for Scheduler
logger = get_module_logger('scheduler')

def initialize_logging():
    """Initialize or reinitialize the logger with the correct log level"""
    global logger
    # Logger is already configured through get_module_logger
    logger.info("Scheduler logging initialized")
    
    # Log performance optimizations
    log_performance_status()

# Initialize logging at module import
initialize_logging()

# Constants for cycle types
CYCLE_CRON = "cron"
CYCLE_ONCE = "once"
CYCLE_DAILY = "daily"
CYCLE_WEEKLY = "weekly"
CYCLE_MONTHLY = "monthly"
CYCLE_NEXT_WEEK = "next_week"
CYCLE_NEXT_MONTH = "next_month"
CYCLE_CUSTOM = "custom"
CYCLE_YEARLY = "yearly"  # Add yearly cycle type

# List of supported cycles
VALID_CYCLES = [
    CYCLE_ONCE,
    CYCLE_DAILY,
    CYCLE_WEEKLY,
    CYCLE_MONTHLY,
    CYCLE_YEARLY  # Add yearly to supported cycles
]

# Valid actions
VALID_ACTIONS = ["start", "stop", "restart"]

# System actions (not container-specific)
SYSTEM_ACTIONS = ["donation_message", "system_maintenance", "cleanup"]

# System task identifiers
SYSTEM_TASK_PREFIX = "SYSTEM_"
DONATION_TASK_ID = f"{SYSTEM_TASK_PREFIX}DONATION_MESSAGE"

# Constants for weekdays
DAYS_OF_WEEK = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

# Scheduler file path
TASKS_FILE_NAME = "tasks.json"
TASKS_FILE_PATH = os.path.join(CONFIG_DIR, TASKS_FILE_NAME)
MIN_TASK_INTERVAL_SECONDS = 10 * 60  # 10 minutes

# Task cache system
_tasks_cache = {}
_last_file_modified_time = 0

# System task functions will be defined after ScheduledTask class

# Timezone cache system
_timezone_cache = {}

def _get_timezone(timezone_str: str):
    """Get and cache timezone object to avoid repeated creation costs."""
    global _timezone_cache
    if timezone_str not in _timezone_cache:
        try:
            _timezone_cache[timezone_str] = pytz.timezone(timezone_str)
        except Exception as e:
            logger.error(f"Error loading timezone '{timezone_str}': {e}. Falling back to UTC.")
            _timezone_cache[timezone_str] = pytz.UTC
    return _timezone_cache[timezone_str]

def _is_tasks_file_modified() -> bool:
    """Check if the tasks file has been modified since last loaded."""
    global _last_file_modified_time
    if not os.path.exists(TASKS_FILE_PATH):
        return _last_file_modified_time != 0  # Force reload if previously had data but file now gone
    
    try:
        # Optimize stat access for network file systems by getting all stats at once
        file_stat = os.stat(TASKS_FILE_PATH)
        current_mtime = file_stat.st_mtime
        
        # Track file size as well for more accurate change detection
        if not hasattr(_is_tasks_file_modified, "_last_size"):
            _is_tasks_file_modified._last_size = 0
        
        current_size = file_stat.st_size
        size_changed = current_size != _is_tasks_file_modified._last_size
        time_changed = current_mtime > _last_file_modified_time
        
        # Update size tracking
        if size_changed:
            _is_tasks_file_modified._last_size = current_size
            
        return size_changed or time_changed
    except (IOError, OSError) as e:
        logger.warning(f"Error checking file modification for {TASKS_FILE_PATH}: {e}")
        return True  # Force reload on errors

class ScheduledTask:
    """Class representing a scheduled task, compatible with Web UI and Discord bot."""
    
    # Use __slots__ to significantly reduce memory usage for many task instances
    __slots__ = [
        'task_id', 'container_name', 'action', 'cycle', 'status', 'is_active',
        'cron_string', 'time_str', 'year_val', 'month_val', 'day_val', 'weekday_val',
        'last_run_success', 'last_run_error', 'description', 'created_by',
        'timezone_str', 'created_at_dt', 'created_at_ts', 'last_run_ts', 'next_run_ts'
    ]
    
    def __init__(self, 
                 task_id: str = None,
                 container_name: str = None, 
                 action: str = None,
                 cycle: str = None,
                 schedule_details: Dict[str, Any] = None,
                 status: str = "pending",
                 description: str = "",
                 created_by: str = "",
                 created_at: Union[float, str] = None,
                 last_run: float = None,
                 next_run: float = None,
                 timezone_str: str = "Europe/Berlin",
                 year: Optional[int] = None,
                 month: Optional[int] = None,
                 day: Optional[int] = None,
                 hour: Optional[int] = None,
                 minute: Optional[int] = None,
                 weekday: Optional[int] = None,
                 is_active: bool = True,
                 last_run_success: Optional[bool] = None,
                 last_run_error: Optional[str] = None):
        self.task_id = task_id or str(uuid.uuid4())
        self.container_name = container_name
        self.action = action
        self.cycle = cycle
        self.status = status
        self.is_active = is_active  # New attribute: Indicates whether the task is active
        
        # Schedule Details - internal storage of time components
        self.cron_string = None
        self.time_str = None # HH:MM
        self.year_val = None
        self.month_val = None 
        self.day_val = None # Day of month or weekday string (Mo, Di etc. or 1-31)
        self.weekday_val = None # 0-6 for internal calculation if cycle is weekly from discord

        # New attributes for execution results
        self.last_run_success = last_run_success  # True/False when executed, None when not executed
        self.last_run_error = last_run_error  # Optional: Error message if not successful

        if schedule_details: # Primarily for loading from Web UI JSON
            self.cron_string = schedule_details.get('cron_string')
            self.time_str = schedule_details.get('time') # HH:MM
            self.day_val = schedule_details.get('day')    # Can be a number or string (weekday)
            self.month_val = schedule_details.get('month') # Can be a number or string
            self.year_val = schedule_details.get('year')   # Number
        else: # For creation from Discord bot parameters or internally
            if self.cycle == CYCLE_CRON and description: # Assumption: description could contain cron string if cycle=cron
                 # This is an assumption of how a cron task might come from the bot.
                 # If the bot directly provides cron_string, that's better.
                 self.cron_string = description 
            if hour is not None and minute is not None:
                self.time_str = f"{hour:02d}:{minute:02d}"
            self.year_val = year
            self.month_val = month
            self.day_val = day # For Discord, day is always day of month
            self.weekday_val = weekday # For Discord: 0-6

        self.description = description
        self.created_by = created_by
        
        # Initialize timezone - use cached timezone for better performance
        self.timezone_str = timezone_str
        tz = _get_timezone(self.timezone_str)
        
        # Process created_at with correct timezone
        if isinstance(created_at, str):
            try:
                # Parse ISO format in UTC timezone and then convert to local time
                self.created_at_dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                # Timestamp without conversion to local time
                self.created_at_ts = self.created_at_dt.timestamp()
                # Create local datetime object with timezone for display
                self.created_at_dt = datetime.fromtimestamp(self.created_at_ts, tz)
                if logger.isEnabledFor(logging.DEBUG):  # Conditional logging for performance
                    logger.debug(f"Parsed created_at from ISO string: {created_at} to {self.created_at_dt.strftime('%Y-%m-%d %H:%M:%S %Z')}")
            except ValueError:
                logger.warning(f"Could not parse created_at ISO string '{created_at}'. Using current time.")
                self.created_at_ts = time.time()
                self.created_at_dt = datetime.fromtimestamp(self.created_at_ts, tz)
        elif isinstance(created_at, (int, float)):
            self.created_at_ts = created_at
            # Create timezone-aware datetime
            self.created_at_dt = datetime.fromtimestamp(created_at, tz)
            if logger.isEnabledFor(logging.DEBUG):  # Conditional logging for performance
                logger.debug(f"Set created_at from timestamp: {created_at} to {self.created_at_dt.strftime('%Y-%m-%d %H:%M:%S %Z')}")
        else:
            self.created_at_ts = time.time()
            # Create timezone-aware datetime
            self.created_at_dt = datetime.fromtimestamp(self.created_at_ts, tz)
            if logger.isEnabledFor(logging.DEBUG):  # Conditional logging for performance
                logger.debug(f"Set created_at to current time: {self.created_at_dt.strftime('%Y-%m-%d %H:%M:%S %Z')}")

        self.last_run_ts = last_run # timestamp
        self.next_run_ts = next_run # timestamp
        
        if self.next_run_ts is None and self.is_valid():
            self.calculate_next_run()
    
    def is_system_task(self) -> bool:
        """Check if this is a system task."""
        return self.task_id and self.task_id.startswith(SYSTEM_TASK_PREFIX)
    
    def is_donation_task(self) -> bool:
        """Check if this is the donation system task."""
        return self.task_id == DONATION_TASK_ID
    
    def _validate_system_task(self) -> bool:
        """Validate system task."""
        if not self.action or self.action not in SYSTEM_ACTIONS:
            logger.warning(f"Invalid system action for task {self.task_id}: {self.action}")
            return False
        
        # System tasks don't need container names
        if not self.cycle:
            logger.warning(f"System task {self.task_id} missing cycle")
            return False
            
        return True
            
    def is_valid(self) -> bool:
        """Check if the task is valid."""
        try:
            # Check for system tasks first
            if self.is_system_task():
                return self._validate_system_task()
            
            # Basic validations - use early returns for performance
            if not self.container_name or not self.action or not self.cycle:
                logger.warning(f"Basic validation for task {self.task_id} failed: container={self.container_name}, action={self.action}, cycle={self.cycle}")
                return False
                
            if self.action not in VALID_ACTIONS:
                logger.warning(f"Invalid action for task {self.task_id}: {self.action} (must be in {VALID_ACTIONS})")
                return False
            
            # Check cycle-specific validations
            if self.cycle == CYCLE_CRON:
                # Cron just needs a cron string
                if not self.cron_string:
                    logger.warning(f"CRON task {self.task_id} has no cron_string")
                    return False
                return True
            
            # For all other cycles, validate time string
            if not self.time_str:
                logger.warning(f"Task {self.task_id}: time_str missing for cycle {self.cycle}")
                return False
                
            try:
                # Use faster string splitting for HH:MM format instead of datetime parsing
                time_parts = self.time_str.split(':')
                if len(time_parts) == 2 and time_parts[0].isdigit() and time_parts[1].isdigit():
                    hour = int(time_parts[0])
                    minute = int(time_parts[1])
                    if not (0 <= hour <= 23 and 0 <= minute <= 59):
                        logger.warning(f"Task {self.task_id}: invalid time values: {hour}:{minute}")
                        return False
                else:
                    # Fall back to slower datetime parsing for complex formats
                    datetime.strptime(self.time_str, '%H:%M')
            except ValueError:
                logger.warning(f"Task {self.task_id}: invalid time_str format '{self.time_str}'")
                return False
            
            # Cycle-specific validations
            if self.cycle == CYCLE_ONCE:
                return self._validate_once_or_yearly()
            if self.cycle == CYCLE_YEARLY:
                return self._validate_yearly()
            elif self.cycle == CYCLE_WEEKLY:
                return self._validate_weekly()
            elif self.cycle == CYCLE_MONTHLY:
                return self._validate_monthly()
            elif self.cycle == CYCLE_DAILY:
                # Daily only requires time_str which was already validated
                return True
            else:
                logger.warning(f"Task {self.task_id}: Unknown cycle type: {self.cycle}")
                return False
                
        except Exception as e:
            logger.error(f"Unexpected error validating task {self.task_id}: {e}")
            return False
    
    def _validate_once_or_yearly(self) -> bool:
        """Validate ONCE or YEARLY task types"""
        if not (self.year_val and self.month_val and self.day_val):
            logger.warning(f"Task {self.task_id}: year/month/day missing for cycle {self.cycle}")
            return False
            
        try:
            # Try to create a datetime object to validate the date
            year = int(self.year_val) if isinstance(self.year_val, str) else self.year_val
            month = int(self.month_val) if isinstance(self.month_val, str) else self.month_val
            day = int(self.day_val) if isinstance(self.day_val, str) else self.day_val
            
            hour, minute = map(int, self.time_str.split(':'))
            datetime(year, month, day, hour, minute)
            return True
        except (ValueError, TypeError) as e:
            logger.warning(f"Task {self.task_id}: Invalid date for {self.cycle} cycle: {e}")
            return False
    
    def _validate_weekly(self) -> bool:
        """Validate WEEKLY task type"""
        # First try day_val as weekday string or int
        if self.day_val is not None:
            if isinstance(self.day_val, str) and self.day_val.strip().lower() in DAYS_OF_WEEK:
                return True
                
            if isinstance(self.day_val, int) and 0 <= self.day_val <= 6:
                return True
                
            # Try parsing day_val if it's a string containing a number
            if isinstance(self.day_val, str) and self.day_val.strip().isdigit():
                day_int = int(self.day_val.strip())
                if 0 <= day_int <= 6 or 1 <= day_int <= 7:
                    return True
        
        # Then try weekday_val (Discord format)
        if self.weekday_val is not None and 0 <= self.weekday_val <= 6:
            return True
            
        logger.warning(f"Task {self.task_id}: No valid weekday found for cycle 'weekly'")
        return False
    
    def _validate_monthly(self) -> bool:
        """Validate MONTHLY task type"""
        if not self.day_val:
            logger.warning(f"Task {self.task_id}: day missing for cycle 'monthly'")
            return False
        # Check if the day is valid (1-31)
        try:
            day = int(self.day_val) if isinstance(self.day_val, str) else self.day_val
            if 1 <= day <= 31:
                return True
            logger.warning(f"Task {self.task_id}: Invalid day value {day} for monthly cycle (must be 1-31)")
            return False
        except (ValueError, TypeError):
            logger.warning(f"Task {self.task_id}: day_val cannot be converted to integer: {self.day_val}")
            return False

    def _validate_yearly(self) -> bool:
        """Validate YEARLY task type (month/day required, year optional)."""
        # Require month/day
        if self.month_val is None or self.day_val is None:
            logger.warning(f"Task {self.task_id}: month/day missing for cycle 'yearly'")
            return False

        # Validate month/day ranges
        try:
            month = int(self.month_val) if isinstance(self.month_val, str) else self.month_val
            day = int(self.day_val) if isinstance(self.day_val, str) else self.day_val
            if not (1 <= month <= 12):
                logger.warning(f"Task {self.task_id}: invalid month value {month} for yearly cycle (must be 1-12)")
                return False
            if not (1 <= day <= 31):
                logger.warning(f"Task {self.task_id}: invalid day value {day} for yearly cycle (must be 1-31)")
                return False
        except (ValueError, TypeError):
            logger.warning(f"Task {self.task_id}: month/day cannot be converted to integers for yearly cycle: month={self.month_val}, day={self.day_val}")
            return False

        return True
        
        # Check if the day is valid (1-31)
        try:
            day = int(self.day_val) if isinstance(self.day_val, str) else self.day_val
            if 1 <= day <= 31:
                return True
                
            logger.warning(f"Task {self.task_id}: Invalid day value {day} for monthly cycle (must be 1-31)")
            return False
        except (ValueError, TypeError):
            logger.warning(f"Task {self.task_id}: day_val cannot be converted to integer: {self.day_val}")
            return False

    def to_dict(self) -> Dict[str, Any]:
        """Converts task to dict for Web UI JSON storage (tasks.json)."""
        data = {
            "id": self.task_id, # Web UI uses 'id'
            "container": self.container_name, # Web UI uses 'container'
            "action": self.action,
            "cycle": self.cycle,
            "schedule_details": {},
            "created_at": self.created_at_dt.replace(microsecond=0).isoformat(), # ISO format without Z for better browser compatibility
            "created_at_local": self.created_at_dt.strftime("%Y-%m-%d %H:%M:%S %Z"), # Local time with timezone for display
            "status": self.status,
            "is_active": self.is_active,  # New field for active/inactive status
            # Internal fields for Discord etc. not in standard Web UI JSON format.
            # Could be added optionally if needed.
            "_description": self.description, 
            "_created_by": self.created_by,
            "_timezone_str": self.timezone_str,
            "_last_run_ts": self.last_run_ts,
            "_next_run_ts": self.next_run_ts,
            # New fields for execution results
            "last_run_success": self.last_run_success,
            "last_run_error": self.last_run_error
        }
        details = data["schedule_details"]
        if self.cycle == CYCLE_CRON:
            details["cron_string"] = self.cron_string
        
        if self.time_str: # For all except potentially cron
             details["time"] = self.time_str
        if self.day_val:
            details["day"] = self.day_val
        if self.month_val:
            details["month"] = self.month_val
        if self.year_val:
            details["year"] = self.year_val
        
        # If schedule_details is empty and it's not cron, could be a problem.
        # But the Web UI fills it based on the cycle.
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ScheduledTask':
        """Creates a task from a Web UI JSON-like dictionary."""
        # Mapping from Web UI field names to internal attribute names
        task_id = data.get("id") or data.get("task_id") # Accepts both ID forms
        container_name = data.get("container") or data.get("container_name")
        
        # Extract schedule_details
        schedule_details_data = data.get("schedule_details", {})
        
        # created_at: can be ISO string or timestamp.
        created_at_val = data.get("created_at") or data.get("_created_at_ts") # For compatibility
        
        return cls(
            task_id=task_id,
            container_name=container_name,
            action=data.get("action"),
            cycle=data.get("cycle"),
            schedule_details=schedule_details_data, # Will be processed in __init__
            status=data.get("status", "pending"),
            description=data.get("description") or data.get("_description", ""),
            created_by=data.get("created_by") or data.get("_created_by", ""),
            created_at=created_at_val,
            last_run=data.get("last_run") or data.get("_last_run_ts"),
            next_run=data.get("next_run") or data.get("_next_run_ts"),
            timezone_str=data.get("timezone_str") or data.get("_timezone_str", "Europe/Berlin"),
            # The following are for compatibility with old Discord format when loading, if needed
            # but are primarily controlled via schedule_details.
            year=schedule_details_data.get("year") or data.get("year"), 
            month=schedule_details_data.get("month") or data.get("month"),
            day=schedule_details_data.get("day") or data.get("day"),
            hour=data.get("hour"), # Extract hour/minute from time_str, if present
            minute=data.get("minute"),
            weekday=data.get("weekday"),
            is_active=data.get("is_active", True),  # Active by default, if not specified
            last_run_success=data.get("last_run_success"),
            last_run_error=data.get("last_run_error")
        )

    def calculate_next_run(self) -> Optional[float]:
        """Calculate the next execution time based on the cycle and details."""
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(f"Calculating next run for task {self.task_id} with cycle {self.cycle} and details: cron='{self.cron_string}', time='{self.time_str}', day='{self.day_val}', month='{self.month_val}', year='{self.year_val}'")  
        if self.cycle == CYCLE_CRON:
            try:
                from croniter import croniter
                # Use croniter for cron schedules
                tz = _get_timezone(self.timezone_str)
                now = datetime.now(tz)
                if self.cron_string:
                    iter = croniter(self.cron_string, now)
                    next_dt = iter.get_next(datetime)
                    self.next_run_ts = next_dt.timestamp()
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(f"Task {self.task_id} - CRON - Next execution: {next_dt.strftime('%Y-%m-%d %H:%M:%S %Z')}")
                    return self.next_run_ts
            except ImportError:
                logger.warning("Cron functionality requires croniter package. Run 'pip install croniter' to enable.")
                return None
            except Exception as e:
                logger.error(f"Error calculating cron next run for task {self.task_id}: {e}")
                return None

        try:
            # Initialize timezone - use cached timezone
            tz = _get_timezone(self.timezone_str)
            now = datetime.now(tz)
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(f"Task {self.task_id} - Timezone: {self.timezone_str}, Current local time: {now.strftime('%Y-%m-%d %H:%M:%S %Z')}")
            
            # Extract time, if present
            task_hour, task_minute = -1, -1
            if self.time_str:
                try:
                    # Important: Time is interpreted as local time in the specified timezone
                    time_parts = self.time_str.split(':')
                    if len(time_parts) == 2 and time_parts[0].isdigit() and time_parts[1].isdigit():
                        # Fast path for standard HH:MM format - avoid datetime parsing overhead
                        task_hour = int(time_parts[0])
                        task_minute = int(time_parts[1])
                    else:
                        # Fallback to slower datetime parsing for complex formats
                        time_obj = datetime.strptime(self.time_str, '%H:%M').time()
                        task_hour, task_minute = time_obj.hour, time_obj.minute
                    
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(f"Task {self.task_id} - Extracted time from time_str: {task_hour}:{task_minute} (interpreted as time in {self.timezone_str})")
                except ValueError:
                    logger.error(f"Invalid time_str format '{self.time_str}' for task {self.task_id}")
                    return None
            else: # Should be caught by is_valid() for non-cron cycles
                return None

            # Initialize variable for next execution
            next_run_dt = None
            current_year = self.year_val or now.year
            current_month = self.month_val # Can be string or int
            current_day = self.day_val # Can be string or int

            if self.cycle == CYCLE_ONCE:
                if not (self.year_val and self.month_val and self.day_val):
                    return None
                try:
                    month_int = int(self.month_val) if isinstance(self.month_val, str) and self.month_val.isdigit() else self.month_val
                    day_int = int(self.day_val) if isinstance(self.day_val, str) and self.day_val.isdigit() else self.day_val
                    # Create a naive datetime and then add the timezone
                    naive_dt = datetime(int(self.year_val), month_int, day_int, task_hour, task_minute)
                    next_run_dt = tz.localize(naive_dt)
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(f"Task {self.task_id} - ONCE - Calculated time: {next_run_dt.strftime('%Y-%m-%d %H:%M:%S %Z')}")
                    if next_run_dt < now: return None
                except (ValueError, TypeError) as e:
                    logger.error(f"Error creating date for ONCE task {self.task_id}: {e}") 
                    return None

            elif self.cycle == CYCLE_DAILY:
                # Daily cycle - just use the time of the next day if today's time has already passed
                next_run_dt = now.replace(hour=task_hour, minute=task_minute, second=0, microsecond=0)
                if next_run_dt <= now: 
                    next_run_dt += timedelta(days=1)
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(f"Task {self.task_id} - DAILY - Time today already passed, using tomorrow: {next_run_dt.strftime('%Y-%m-%d %H:%M:%S %Z')}")
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(f"Task {self.task_id} - DAILY - Calculated time: {next_run_dt.strftime('%Y-%m-%d %H:%M:%S %Z')}")

            elif self.cycle == CYCLE_WEEKLY:
                target_weekday = -1
                if isinstance(self.day_val, str):
                    try: 
                        target_weekday = DAYS_OF_WEEK.index(self.day_val.lower())
                        if logger.isEnabledFor(logging.DEBUG):
                            logger.debug(f"Task {self.task_id} - WEEKLY - Weekday from string '{self.day_val}': {target_weekday}")
                    except ValueError: return None
                elif isinstance(self.weekday_val, int) and 0 <= self.weekday_val <= 6: # from Discord
                     target_weekday = self.weekday_val
                     if logger.isEnabledFor(logging.DEBUG):
                         logger.debug(f"Task {self.task_id} - WEEKLY - Weekday from weekday_val: {target_weekday}")
                else: return None
                
                # CRITICAL FIX: If we have a last_run_ts, calculate from there instead of now
                # This prevents the task from being scheduled for "today" again after execution
                if self.last_run_ts:
                    # Task was executed, calculate next run from last execution + 7 days
                    last_run_dt = datetime.fromtimestamp(self.last_run_ts, tz)
                    next_run_dt = last_run_dt.replace(hour=task_hour, minute=task_minute, second=0, microsecond=0) + timedelta(days=7)
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(f"Task {self.task_id} - WEEKLY - Calculated from last run: {next_run_dt.strftime('%Y-%m-%d %H:%M:%S %Z')}")
                else:
                    # First time calculation or manual calculation
                    days_ahead = target_weekday - now.weekday()
                    if days_ahead < 0 : days_ahead += 7 # Target is this week, but already passed
                    elif days_ahead == 0 and now.time() >= datetime_time(task_hour, task_minute): days_ahead +=7 # Today, but time already passed
                    
                    next_run_dt = now.replace(hour=task_hour, minute=task_minute, second=0, microsecond=0) + timedelta(days=days_ahead)
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(f"Task {self.task_id} - WEEKLY - Calculated time: {next_run_dt.strftime('%Y-%m-%d %H:%M:%S %Z')} (Days ahead: {days_ahead})")

            elif self.cycle == CYCLE_MONTHLY:
                if not self.day_val: return None
                try: 
                    day_int = int(self.day_val)
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(f"Task {self.task_id} - MONTHLY - Day of month: {day_int}")
                except ValueError: return None
                if not (1 <= day_int <= 31): return None

                calc_month, calc_year = now.month, now.year
                while True:
                    try:
                        # Create a naive datetime and then add the timezone
                        naive_dt = datetime(calc_year, calc_month, day_int, task_hour, task_minute)
                        localized_dt = tz.localize(naive_dt)
                        if localized_dt > now: 
                            next_run_dt = localized_dt
                            if logger.isEnabledFor(logging.DEBUG):
                                logger.debug(f"Task {self.task_id} - MONTHLY - Calculated time: {next_run_dt.strftime('%Y-%m-%d %H:%M:%S %Z')}")
                            break
                    except ValueError: # Day doesn't exist in month (e.g., February 31)
                        if logger.isEnabledFor(logging.DEBUG):
                            logger.debug(f"Task {self.task_id} - MONTHLY - Invalid day {day_int} in month {calc_month}/{calc_year}, trying next month")
                        pass 
                    calc_month += 1
                    if calc_month > 12: calc_month = 1; calc_year +=1
                    if calc_year > now.year + 2: return None # Protection against infinite loop
            
            elif self.cycle == CYCLE_YEARLY: # Web UI specific
                # For yearly tasks, we need month and day, but year is optional
                if not (self.month_val and self.day_val): return None
                try:
                    month_int = int(self.month_val) if isinstance(self.month_val, str) and self.month_val.isdigit() else self.month_val
                    day_int = int(self.day_val) if isinstance(self.day_val, str) and self.day_val.isdigit() else self.day_val
                    
                    # Use current year if no year specified, or the specified year
                    target_year = int(self.year_val) if self.year_val else now.year
                    
                    # Create a naive datetime and then add the timezone
                    try:
                        naive_dt = datetime(target_year, month_int, day_int, task_hour, task_minute)
                        next_run_dt = tz.localize(naive_dt)
                        if logger.isEnabledFor(logging.DEBUG):
                            logger.debug(f"Task {self.task_id} - YEARLY - Initial date: {next_run_dt.strftime('%Y-%m-%d %H:%M:%S %Z')}")
                    except ValueError:
                        # Handle Feb 29 in non-leap years
                        if month_int == 2 and day_int == 29 and not calendar.isleap(target_year):
                            # Use Feb 28 instead
                            naive_dt = datetime(target_year, 2, 28, task_hour, task_minute)
                            next_run_dt = tz.localize(naive_dt)
                            logger.info(f"Task {self.task_id} - YEARLY - Using Feb 28 instead of Feb 29 in non-leap year {target_year}")
                        else:
                            # Some other invalid date
                            logger.error(f"Task {self.task_id} - YEARLY - Invalid date: {target_year}-{month_int}-{day_int}")
                            return None
                            
                    # If date is in the past, use next occurrence
                    if next_run_dt < now:
                        # If explicit year in the past, and it's a one-time task, then expired
                        if self.cycle == CYCLE_ONCE and self.year_val and int(self.year_val) < now.year: 
                            if logger.isEnabledFor(logging.DEBUG):
                                logger.debug(f"Task {self.task_id} - ONCE - Year in the past, task expired")
                            return None
                            
                        # For yearly recurring tasks or one-time tasks with current year
                        try: 
                            # If date already passed this year, use next year
                            next_year = now.year + 1
                            next_run_dt = next_run_dt.replace(year=next_year)
                            if logger.isEnabledFor(logging.DEBUG):
                                logger.debug(f"Task {self.task_id} - YEARLY - Date already passed, using next year: {next_run_dt.strftime('%Y-%m-%d %H:%M:%S %Z')}")
                        except ValueError: 
                            # Handle Feb 29 on next year if it's not a leap year
                            if month_int == 2 and day_int == 29 and not calendar.isleap(next_year):
                                # Use Feb 28 for non-leap years
                                next_run_dt = next_run_dt.replace(year=next_year, day=28)
                                logger.info(f"Task {self.task_id} - YEARLY - Using Feb 28 instead of Feb 29 in non-leap year {next_year}")
                            else:
                                logger.error(f"Task {self.task_id} - YEARLY - Error adjusting to next year")
                                return None
                except (ValueError, TypeError) as e: 
                    logger.error(f"Error creating date for YEARLY task {self.task_id}: {e}")
                    return None
            else:
                logger.error(f"Unknown cycle type '{self.cycle}' for task {self.task_id} in calculate_next_run")
                return None

            if next_run_dt:
                # Convert the timezone-aware datetime to a UTC timestamp
                self.next_run_ts = next_run_dt.timestamp()
                
                # Only perform debug logging if debug is enabled
                if logger.isEnabledFor(logging.DEBUG):
                    # Convert back for debug output
                    # First UTC
                    utc_time = datetime.utcfromtimestamp(self.next_run_ts).replace(tzinfo=pytz.UTC)
                    # Then local time
                    local_time = utc_time.astimezone(tz)
                    
                    logger.debug(f"Task {self.task_id} - Timestamps for comparison:")
                    logger.debug(f"- Original input: {task_hour}:{task_minute} in {self.timezone_str}")
                    logger.debug(f"- Calculated local datetime: {next_run_dt.strftime('%Y-%m-%d %H:%M:%S %Z')}")
                    logger.debug(f"- As UTC timestamp: {self.next_run_ts}")
                    logger.debug(f"- Converted back to UTC: {utc_time.strftime('%Y-%m-%d %H:%M:%S %Z')}")
                    logger.debug(f"- Converted back to local: {local_time.strftime('%Y-%m-%d %H:%M:%S %Z')}")
                    
                    # Check if the back-conversion is correct
                    if local_time.hour != task_hour or local_time.minute != task_minute:
                        logger.warning(f"Task {self.task_id} - WARNING: Back-converted time ({local_time.hour}:{local_time.minute}) "
                                     f"does not match original input ({task_hour}:{task_minute})!")
                
                return self.next_run_ts
            return None
        except Exception as e:
            logger.error(f"Error calculating next run for task {self.task_id} (cycle: {self.cycle}): {e}", exc_info=True)
            return None

    def get_next_run_datetime(self) -> Optional[datetime]:
        if self.next_run_ts is None: return None
        try:
            # Convert the UTC timestamp back to the local timezone for display
            tz = _get_timezone(self.timezone_str)
            utc_dt = datetime.utcfromtimestamp(self.next_run_ts).replace(tzinfo=pytz.UTC)
            local_dt = utc_dt.astimezone(tz)
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(f"get_next_run_datetime for Task {self.task_id}: " 
                           f"UTC={utc_dt.strftime('%Y-%m-%d %H:%M:%S %Z')}, " 
                           f"Local={local_dt.strftime('%Y-%m-%d %H:%M:%S %Z')}")
            return local_dt
        except Exception as e:
            logger.error(f"Error converting timestamp {self.next_run_ts} to datetime: {e}")
            return None
            
    def should_run(self) -> bool:
        if not self.next_run_ts: return False
        return time.time() >= self.next_run_ts

    def update_after_execution(self) -> None:
        self.last_run_ts = time.time()
        if self.cycle == CYCLE_ONCE:
            self.next_run_ts = None # One-time tasks don't run again
            self.status = "completed" # or "executed"
            self.is_active = False # Deactivate one-time tasks after execution
            logger.info(f"Task {self.task_id} marked as completed and deactivated (one-time task)")
        else:
            # Special handling for donation task
            if self.is_donation_task():
                self._calculate_next_donation_run()
            else:
                self.calculate_next_run() # For recurring tasks
            self.status = "pending" # Reset to pending for next run
    
    def _calculate_next_donation_run(self) -> None:
        """Calculate next run for donation task - always 2nd Sunday at 13:37."""
        try:
            # Get configured timezone
            from utils.config_cache import get_cached_config
            config = get_cached_config()
            timezone_str = config.get('timezone', 'Europe/Berlin')
            
            import pytz
            tz = pytz.timezone(timezone_str)
            now = datetime.now(tz)
            
            # Start with current month
            target_year = now.year
            target_month = now.month
            
            # Calculate 2nd Sunday of current month at 13:37
            def get_second_sunday(year: int, month: int) -> datetime:
                """Get 2nd Sunday of given month at 13:37."""
                first_day = datetime(year, month, 1)
                # Find first Sunday
                days_to_first_sunday = (6 - first_day.weekday()) % 7
                if first_day.weekday() == 6:  # First day is Sunday
                    days_to_first_sunday = 0
                first_sunday = first_day + timedelta(days=days_to_first_sunday)
                second_sunday = first_sunday + timedelta(days=7)
                # Set time to 13:37
                return second_sunday.replace(hour=13, minute=37, second=0, microsecond=0)
            
            next_run_naive = get_second_sunday(target_year, target_month)
            next_run = tz.localize(next_run_naive)
            
            # If this month's 2nd Sunday has already passed, or we already ran this month, use next month
            if next_run <= now or (self.last_run_ts and self._was_run_this_month(now)):
                # Go to next month
                if target_month == 12:
                    target_month = 1
                    target_year += 1
                else:
                    target_month += 1
                
                next_run_naive = get_second_sunday(target_year, target_month)
                next_run = tz.localize(next_run_naive)
            
            self.next_run_ts = next_run.timestamp()
            logger.debug(f"Donation task scheduled for 2nd Sunday: {next_run.strftime('%Y-%m-%d %H:%M:%S %Z')}")
            
        except Exception as e:
            logger.error(f"Error calculating next donation run: {e}")
            # Fallback - set to next month's 10th at 13:37
            try:
                if now.month == 12:
                    fallback_naive = datetime(now.year + 1, 1, 10, 13, 37)
                else:
                    fallback_naive = datetime(now.year, now.month + 1, 10, 13, 37)
                fallback = tz.localize(fallback_naive)
                self.next_run_ts = fallback.timestamp()
            except Exception as fallback_error:
                logger.error(f"Even fallback calculation failed: {fallback_error}")
                # Ultimate fallback - 30 days from now
                self.next_run_ts = (now + timedelta(days=30)).timestamp()
    
    def _was_run_this_month(self, now: datetime) -> bool:
        """Check if donation task was already run this month."""
        if not self.last_run_ts:
            return False
        
        try:
            last_run_dt = datetime.fromtimestamp(self.last_run_ts, tz=now.tzinfo)
            return last_run_dt.year == now.year and last_run_dt.month == now.month
        except Exception:
            return False

# --- System Task Management Functions ---

def create_donation_system_task() -> ScheduledTask:
    """Create the hard-coded donation system task."""
    try:
        # Check if donations are disabled
        from utils.donation_utils import is_donations_disabled
        if is_donations_disabled():
            logger.debug("Donation system task skipped - donations disabled by premium key")
            return None
        
        # Get configured timezone or fall back to default
        try:
            from utils.config_cache import get_cached_config
            config = get_cached_config()
            timezone_str = config.get('timezone', 'Europe/Berlin')
        except Exception:
            timezone_str = 'Europe/Berlin'
        
        # Create task with simple configuration
        # The actual 2nd Sunday calculation happens in _calculate_next_donation_run()
        task = ScheduledTask(
            task_id=DONATION_TASK_ID,
            container_name="SYSTEM",  # Special container name for system tasks
            action="donation_message",
            cycle=CYCLE_MONTHLY,  # Display as monthly
            description="Automatic donation message (2nd Sunday @ 13:37)",
            created_by="SYSTEM",
            timezone_str=timezone_str,
            schedule_details={"time": "13:37", "day": "2nd Sunday"}  # Special display for donation task
        )
        
        # Mark as system task and active
        task.is_active = True
        task.status = "active"
        
        # Use our special donation calculation
        task._calculate_next_donation_run()
        
        return task
    except Exception as e:
        logger.error(f"Error creating donation system task: {e}")
        return None

def _get_system_tasks() -> List[ScheduledTask]:
    """Get all hard-coded system tasks."""
    system_tasks = []
    
    try:
        # Add donation system task
        donation_task = create_donation_system_task()
        if donation_task:
            system_tasks.append(donation_task)
        
        # Future system tasks can be added here
        # maintenance_task = create_maintenance_system_task()
        # if maintenance_task:
        #     system_tasks.append(maintenance_task)
        
    except Exception as e:
        logger.error(f"Error creating system tasks: {e}")
        # Return empty list if system task creation fails - don't break the whole system
    
    return system_tasks

# --- Scheduler File I/O Functions --- (Now operating on TASKS_FILE_PATH)

def _load_raw_tasks_from_file() -> List[Dict[str, Any]]:
    """Loads raw task data directly from the TASKS_FILE_PATH."""
    global _last_file_modified_time
    max_retries = 3
    retry_delay = 0.5  # seconds
    last_error = None
    
    for attempt in range(max_retries):
        try:
            if not os.path.exists(TASKS_FILE_PATH):
                logger.info(f"Tasks file {TASKS_FILE_PATH} doesn't exist. Returning empty list.")
                _last_file_modified_time = 0
                return []
                
            file_stat = os.stat(TASKS_FILE_PATH)
            _last_file_modified_time = file_stat.st_mtime
            file_size = file_stat.st_size
            
            # Empty file check - skip unnecessary JSON parsing
            if file_size == 0:
                logger.info(f"Tasks file {TASKS_FILE_PATH} is empty.")
                return []
                
            with open(TASKS_FILE_PATH, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                if not content: return []
                # Use ujson which is much faster than standard json
                return json.loads(content)
                
        except json.JSONDecodeError as e:
            logger.error(f"Error decoding JSON data from {TASKS_FILE_PATH}: {e}")
            return []
        except (IOError, OSError) as e:
            last_error = e
            if attempt < max_retries - 1:
                logger.warning(f"Network/IO error reading {TASKS_FILE_PATH}, retrying ({attempt+1}/{max_retries}): {e}")
                time.sleep(retry_delay * (attempt + 1))  # Exponential backoff
            else:
                logger.error(f"Failed to read tasks file after {max_retries} attempts: {e}")
                return []
        except Exception as e:
            logger.error(f"Unexpected error reading tasks file {TASKS_FILE_PATH}: {e}")
            return []
    
    if last_error:
        logger.error(f"All retries failed when reading {TASKS_FILE_PATH}: {last_error}")
    return []

def _save_raw_tasks_to_file(tasks_data: List[Dict[str, Any]]) -> bool:
    """Saves raw task data directly to TASKS_FILE_PATH."""
    global _tasks_cache, _last_file_modified_time
    max_retries = 3
    retry_delay = 0.5  # seconds
    
    for attempt in range(max_retries):
        try:
            # Check if file already exists and compare content to avoid unnecessary writes
            if os.path.exists(TASKS_FILE_PATH):
                try:
                    with open(TASKS_FILE_PATH, 'r', encoding='utf-8') as f:
                        current_content = f.read().strip()
                        if current_content:
                            current_data = json.loads(current_content)
                            # Convert new data to JSON for comparison
                            new_content = json.dumps(tasks_data, indent=4, ensure_ascii=False)
                            new_data = json.loads(new_content)
                            
                            # Sort both data sets by ID for reliable comparison
                            if len(current_data) == len(new_data):
                                # Sort both lists for comparison
                                current_sorted = sorted(current_data, key=lambda x: x.get('id', ''))
                                new_sorted = sorted(new_data, key=lambda x: x.get('id', ''))
                                
                                if current_sorted == new_sorted:
                                    logger.debug("Tasks data unchanged, skipping file write")
                                    return True
                except Exception as e:
                    # If comparison fails, proceed with write
                    logger.debug(f"Error comparing task data: {e}, proceeding with write")
                    
            # Create directory if needed                
            os.makedirs(os.path.dirname(TASKS_FILE_PATH), exist_ok=True)
            
            # Use a proper atomic write pattern for more resilience on network file systems
            import tempfile
            
            # Create temporary file in the same directory
            temp_dir = os.path.dirname(TASKS_FILE_PATH)
            fd, temp_path = tempfile.mkstemp(dir=temp_dir, text=True)
            
            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as f:
                    json.dump(tasks_data, f, indent=4, ensure_ascii=False)
                    f.flush()
                    os.fsync(f.fileno())  # Ensure data is written to disk
                
                # Perform atomic rename (on Unix systems) or copy+delete (on Windows)
                if os.name == 'posix':
                    os.rename(temp_path, TASKS_FILE_PATH)
                else:
                    import shutil
                    shutil.move(temp_path, TASKS_FILE_PATH)
                
                # Update cache and modified time after successful save
                _tasks_cache.clear()  # Clear cache to force reload
                _last_file_modified_time = os.path.getmtime(TASKS_FILE_PATH)
                logger.debug(f"Tasks successfully saved to {TASKS_FILE_PATH}.")
                return True
                
            except Exception as e:
                # Clean up the temporary file in case of error
                try:
                    os.unlink(temp_path)
                except (OSError, IOError) as cleanup_error:
                    logger.debug(f"Failed to cleanup temporary file {temp_path}: {cleanup_error}")
                raise e
                
        except (IOError, OSError) as e:
            if attempt < max_retries - 1:
                logger.warning(f"Network/IO error writing to {TASKS_FILE_PATH}, retrying ({attempt+1}/{max_retries}): {e}")
                time.sleep(retry_delay * (attempt + 1))  # Exponential backoff
            else:
                logger.error(f"Failed to save tasks after {max_retries} attempts: {e}")
                return False
        except Exception as e:
            logger.error(f"Error saving tasks to {TASKS_FILE_PATH}: {e}")
            return False
    
    return False

# --- Public Task Management API --- (Now using ScheduledTask objects and TASKS_FILE_PATH)

def load_tasks() -> List[ScheduledTask]:
    """Load all scheduled tasks from storage"""
    # Maintain task persistence across restarts
    tasks = []
    
    # Always ensure task file exists
    if not os.path.exists(TASKS_FILE_PATH):
        logger.debug(f"Tasks file {TASKS_FILE_PATH} does not exist, creating empty file")
        # Create empty tasks file
        try:
            os.makedirs(os.path.dirname(TASKS_FILE_PATH), exist_ok=True)
            with open(TASKS_FILE_PATH, 'w', encoding='utf-8') as f:
                json.dump([], f)
            logger.info(f"Created empty tasks file at {TASKS_FILE_PATH}")
        except Exception as e:
            logger.error(f"Failed to create tasks file: {e}")
        return tasks
    
    # eXecute task loading with error handling
    try:
        with open(TASKS_FILE_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        # Deserialize each task from stored data
        for task_data in data:
            try:
                task = ScheduledTask.from_dict(task_data)
                tasks.append(task)
                logger.debug(f"Loaded task: {task.task_id}")
            except Exception as e:
                logger.error(f"Error creating ScheduledTask object from data: {e}")
                continue
                
        # Display successful loading information only on debug level to reduce log spam
        logger.debug(f"Loaded {len(tasks)} scheduled tasks")
        
    except Exception as e:
        logger.error(f"Error loading tasks from {TASKS_FILE_PATH}: {e}")
        
    # Cleanup any invalid or expired tasks
    valid_tasks = [task for task in tasks if task.is_valid()]
    if len(valid_tasks) != len(tasks):
        logger.info(f"Removed {len(tasks) - len(valid_tasks)} invalid tasks")
        save_tasks(valid_tasks)
    
    # Add system tasks (hard-coded, always present)
    system_tasks = _get_system_tasks()
    
    # Merge system tasks with user tasks, avoiding duplicates
    all_tasks = valid_tasks.copy()
    for system_task in system_tasks:
        # Only add if not already present (by task_id)
        if not any(task.task_id == system_task.task_id for task in all_tasks):
            all_tasks.append(system_task)
            logger.debug(f"Added system task: {system_task.task_id}")
        
    return all_tasks

@lru_cache(maxsize=8)
def _get_task_grouping_key(task):
    """Helper function to generate a key for task grouping in save_tasks.
    Uses LRU cache to speed up repeated sorting operations."""
    return (task.container_name, task.action)

def save_tasks(tasks: List[ScheduledTask]) -> bool:
    """Save all ScheduledTask objects to tasks.json."""
    global _tasks_cache
    
    # Filter out system tasks - they should never be saved to file
    user_tasks = [task for task in tasks if not task.is_system_task()]
    logger.debug(f"Saving {len(user_tasks)} user tasks (filtered out {len(tasks) - len(user_tasks)} system tasks)")
    
    # Convert all tasks to dict first, to avoid redundant to_dict calls
    tasks_data = [task.to_dict() for task in user_tasks]
    
    # Sort tasks by container and action to keep file content more stable
    # This improves diff-based version control and makes visual inspection easier
    tasks_data.sort(key=lambda t: (t.get('container', ''), t.get('action', '')))
    
    success = _save_raw_tasks_to_file(tasks_data)
    
    # Update cache if save was successful
    if success:
        _tasks_cache = {task.task_id: task for task in tasks}
    
    return success

def find_task_by_id(task_id: str) -> Optional[ScheduledTask]:
    """Find a task by ID using the cache when possible."""
    global _tasks_cache
    
    # Try to get from cache if file hasn't changed
    if not _is_tasks_file_modified() and task_id in _tasks_cache:
        return _tasks_cache[task_id]
    
    # For a single task lookup, try to avoid loading all tasks if possible
    # This optimization is helpful for large task lists
    if os.path.exists(TASKS_FILE_PATH):
        try:
            # First check if we need to reload by checking modification time
            if _is_tasks_file_modified():
                # Load all tasks (will update cache) and filter
                tasks = load_tasks()
                for task in tasks:
                    if task.task_id == task_id:
                        return task
            # File exists but hasn't been modified - do a targeted search
            elif not _tasks_cache:
                # Cache is empty but file exists and hasn't changed
                # Load raw data and only process the task we need
                raw_tasks_data = _load_raw_tasks_from_file()
                for task_data in raw_tasks_data:
                    # Fast check for the ID before full processing
                    data_id = task_data.get('id') or task_data.get('task_id')
                    if data_id == task_id:
                        task = ScheduledTask.from_dict(task_data)
                        if task.is_valid():
                            # Update cache with just this task
                            _tasks_cache[task_id] = task
                            return task
        except Exception as e:
            logger.error(f"Error during optimized task lookup: {e}")
    
    # Default fallback - load all tasks and search
    tasks = load_tasks()
    for task in tasks:
        if task.task_id == task_id:
            return task
    return None

# Cache for get_tasks_for_container
_container_tasks_cache = {}
_container_cache_timestamp = 0

def get_tasks_for_container(container_name: str) -> List[ScheduledTask]:
    """Get all tasks for a specific container, efficiently using the cache."""
    global _tasks_cache, _container_tasks_cache, _container_cache_timestamp
    
    # Check if whole task cache is valid and container cache was recently updated
    if not _is_tasks_file_modified() and _tasks_cache:
        current_time = time.time()
        # Container cache refresh period - 5 seconds
        container_cache_ttl = 5
        
        # Check if we have a recent container-specific cache
        cache_valid = (container_name in _container_tasks_cache and 
                       current_time - _container_cache_timestamp < container_cache_ttl)
        if cache_valid:
            return _container_tasks_cache[container_name]
        
        # Filter from main cache if available, update container cache
        container_tasks = [task for task in _tasks_cache.values() if task.container_name == container_name]
        _container_tasks_cache[container_name] = container_tasks
        _container_cache_timestamp = current_time
        return container_tasks
    
    # Otherwise load all tasks (will update cache) and filter
    tasks = load_tasks()
    container_tasks = [task for task in tasks if task.container_name == container_name]
    
    # Update container cache
    _container_tasks_cache[container_name] = container_tasks
    _container_cache_timestamp = time.time()
    
    return container_tasks

def check_task_time_collision(container_name: str, new_task_next_run_ts: float, 
                                existing_tasks_for_container: Optional[List[ScheduledTask]] = None,
                                task_id_to_ignore: Optional[str] = None) -> bool:
    """
    Checks if a new or updated task conflicts with existing tasks for the same container
    within a 10-minute window.
    """
    if existing_tasks_for_container is None:
        existing_tasks_for_container = get_tasks_for_container(container_name)

    for existing_task in existing_tasks_for_container:
        if task_id_to_ignore and existing_task.task_id == task_id_to_ignore:
            continue # Ignore the task being updated
        
        if existing_task.next_run_ts is not None and new_task_next_run_ts is not None:
            time_difference = abs(existing_task.next_run_ts - new_task_next_run_ts)
            if time_difference < MIN_TASK_INTERVAL_SECONDS:
                logger.warning(f"Task time collision for container '{container_name}'. New at {new_task_next_run_ts} vs existing {existing_task.task_id} at {existing_task.next_run_ts}")
                return True
    return False

def add_task(task: ScheduledTask) -> bool:
    """Adds a new ScheduledTask, checking for time collisions and existing ID."""
    if not isinstance(task, ScheduledTask):
        logger.error(f"Attempt to add an object that is not a ScheduledTask: {type(task)}")
        return False
    if not task.is_valid():
        logger.error(f"Attempt to add an invalid task: {task.task_id}")
        return False
    if task.next_run_ts is None and task.cycle != CYCLE_CRON and task.cycle != CYCLE_ONCE : # Cron calculates differently, Once can be in the past
        logger.error(f"Task {task.task_id} for {task.container_name} has no next_run_ts before adding (cycle: {task.cycle}). Recalculating...")
        task.calculate_next_run()
        if task.next_run_ts is None and task.cycle != CYCLE_ONCE: # If still None and not 'once' (once can be in the past)
             logger.error(f"Task {task.task_id} still has no next_run_ts after recalculation. Cannot add.")
             return False

    tasks = load_tasks()
    if any(t.task_id == task.task_id for t in tasks):
        logger.warning(f"Task with ID {task.task_id} already exists. Not adding.")
        return False
    
    # BUGFIX: Check collision only for the same container, not all tasks
    if task.next_run_ts is not None:
        # Get only tasks for the same container for collision check
        existing_tasks_for_same_container = [t for t in tasks if t.container_name == task.container_name]
        if check_task_time_collision(task.container_name, task.next_run_ts, existing_tasks_for_container=existing_tasks_for_same_container):
            logger.warning(f"Failed to add task {task.task_id} due to time collision with another task for container '{task.container_name}'.")
            return False
        
    tasks.append(task)
    logger.info(f"Task {task.task_id} ({task.container_name} - {task.action}) added. Total tasks: {len(tasks)}")
    return save_tasks(tasks)

def update_task(task_to_update: ScheduledTask) -> bool:
    # Prevent updating system tasks
    if task_to_update.is_system_task():
        logger.warning(f"Cannot update system task: {task_to_update.task_id}")
        return False
        
    if not isinstance(task_to_update, ScheduledTask):
        logger.error(f"Attempt to update an object that is not a ScheduledTask: {type(task_to_update)}")
        return False
    if not task_to_update.is_valid():
        logger.error(f"Attempt to update with an invalid task object: {task_to_update.task_id}")
        return False
    
    # For recurring tasks, ensure there is a next execution time
    if task_to_update.cycle != CYCLE_ONCE and task_to_update.cycle != CYCLE_CRON and task_to_update.next_run_ts is None:
        logger.warning(f"Recurring task {task_to_update.task_id} has no next_run_ts. Recalculating before update.")
        task_to_update.calculate_next_run()
        if task_to_update.next_run_ts is None:
            logger.error(f"Cannot update recurring task {task_to_update.task_id} as next_run_ts is still None after recalculation.")
            return False

    tasks = load_tasks()
    task_found = False
    for i, t in enumerate(tasks):
        if t.task_id == task_to_update.task_id:
            # BUGFIX: Check for collisions before update (only for the same container, ignore the task itself)
            if task_to_update.next_run_ts is not None:
                # Get only tasks for the same container, excluding the task being updated
                existing_tasks_for_same_container = [ex_task for ex_task in tasks 
                                                   if ex_task.container_name == task_to_update.container_name 
                                                   and ex_task.task_id != task_to_update.task_id]
                if check_task_time_collision(task_to_update.container_name, task_to_update.next_run_ts, 
                                           existing_tasks_for_container=existing_tasks_for_same_container):
                    logger.warning(f"Update for task {task_to_update.task_id} aborted due to time collision with another task for container '{task_to_update.container_name}'.")
                    return False
            tasks[i] = task_to_update
            task_found = True
            break
    if not task_found:
        logger.warning(f"Task with ID {task_to_update.task_id} not found for update.")
        return False
    return save_tasks(tasks)

def delete_task(task_id: str) -> bool:
    # Prevent deletion of system tasks
    if task_id.startswith(SYSTEM_TASK_PREFIX):
        logger.warning(f"Cannot delete system task: {task_id}")
        return False
    
    tasks = load_tasks()
    original_count = len(tasks)
    tasks = [t for t in tasks if t.task_id != task_id]
    if len(tasks) == original_count:
        logger.warning(f"Task with ID {task_id} not found for deletion.")
        return False
    return save_tasks(tasks)

def get_tasks_in_timeframe(start_time: float, end_time: float) -> List[ScheduledTask]:
    """Get all tasks scheduled within a specific timeframe, using cache when possible."""
    global _tasks_cache
    
    if not _is_tasks_file_modified() and _tasks_cache:
        # Filter from cache if available
        result = [t for t in _tasks_cache.values() if t.next_run_ts and start_time <= t.next_run_ts <= end_time]
        # Sort results by execution time for better usability
        return sorted(result, key=lambda t: t.next_run_ts)
    
    # Otherwise load all tasks and filter
    tasks = load_tasks()
    result = [t for t in tasks if t.next_run_ts and start_time <= t.next_run_ts <= end_time]
    return sorted(result, key=lambda t: t.next_run_ts)

def get_next_week_tasks() -> List[ScheduledTask]:
    now = time.time()
    week_later = now + (7 * 24 * 60 * 60)
    return get_tasks_in_timeframe(now, week_later)

async def execute_task(task: ScheduledTask, timeout: int = 60) -> bool:
    """
    Execute a scheduled task with timeout handling and robust error management.
    
    Args:
        task: The ScheduledTask to execute
        timeout: Maximum execution time in seconds before considering the task failed
    
    Returns:
        True if execution was successful, False otherwise
    """
    execution_start = time.time()
    logger.info(f"Executing scheduled task ID: {task.task_id} ({task.container_name} {task.action})")
    
    # Check if this is a donation task and donations are disabled
    if task.action == "donation_message":
        from utils.donation_utils import is_donations_disabled
        if is_donations_disabled():
            logger.info(f"Skipping donation task {task.task_id} - donations disabled by premium key")
            # Update task as if it ran successfully to reschedule it
            task.last_run_success = True
            task.last_run_error = None
            task.update_after_execution()
            update_task(task)
            return True  # Return true so it reschedules normally
    
    try:
        # Create a timeout for the docker action
        try:
            # Try to execute with increasing timeouts if needed
            for retry_count, current_timeout in enumerate([timeout, timeout * 1.5]):
                try:
                    # Only retry once and with increased timeout
                    if retry_count > 0:
                        logger.warning(f"Retrying task {task.task_id} with increased timeout {current_timeout}s")
                    
                    result = await asyncio.wait_for(
                        docker_action(task.container_name, task.action),
                        timeout=current_timeout
                    )
                    
                    # If successful, no need to retry
                    break
                except asyncio.TimeoutError:
                    if retry_count == 0:
                        # First timeout, will retry with increased timeout
                        logger.warning(f"Task {task.task_id} timed out after {current_timeout}s, retrying with increased timeout")
                        continue
                    else:
                        # Final timeout
                        raise
            
        except asyncio.TimeoutError:
            error_msg = f"Docker action timed out after {timeout * 1.5} seconds"
            logger.error(f"Task {task.task_id} - {error_msg}")
            task.last_run_success = False
            task.last_run_error = error_msg
            log_user_action(
                action=f"{task.action.upper()}_TIMEOUT", 
                target=task.container_name, 
                user="Scheduled Task", 
                source="Scheduled Task", 
                details=f"Task ID: {task.task_id}, Cycle: {task.cycle}, Error: {error_msg}"
            )
            task.update_after_execution()
            update_task(task)
            return False
            
        if result:
            execution_time = time.time() - execution_start
            logger.info(f"Task {task.task_id} successfully executed in {execution_time:.2f}s.")
            # Save success
            task.last_run_success = True
            task.last_run_error = None
            
            # Log in User Action Log
            log_user_action(
                action=task.action.upper(), 
                target=task.container_name, 
                user="Scheduled Task", 
                source="Scheduled Task", 
                details=f"Task ID: {task.task_id}, Cycle: {task.cycle}, Result: Success, Duration: {execution_time:.2f}s"
            )
            
            task.update_after_execution()
            update_task(task)
            return True
        else:
            logger.error(f"Execution failed for task {task.task_id}.")
            # Store error
            task.last_run_success = False
            task.last_run_error = "Docker action failed"
            
            # Log in User Action Log (also for errors)
            log_user_action(
                action=f"{task.action.upper()}_FAILED", 
                target=task.container_name, 
                user="Scheduled Task", 
                source="Scheduled Task", 
                details=f"Task ID: {task.task_id}, Cycle: {task.cycle}, Error: Docker action failed"
            )
            
            task.update_after_execution()
            update_task(task)
            return False
    except Exception as e:
        execution_time = time.time() - execution_start
        error_msg = f"Unexpected error executing task {task.task_id}: {e}"
        logger.error(error_msg, exc_info=True)
        
        # Save error
        task.last_run_success = False
        task.last_run_error = str(e)
        
        # Log in User Action Log (also for errors)
        log_user_action(
            action=f"{task.action.upper()}_ERROR", 
            target=task.container_name, 
            user="Scheduled Task", 
            source="Scheduled Task", 
            details=f"Task ID: {task.task_id}, Cycle: {task.cycle}, Duration: {execution_time:.2f}s, Error: {str(e)}"
        )
        
        task.update_after_execution()
        update_task(task)
        return False

# --- Validation & Parsing Functions (Maintain and adjust if needed) ---

def validate_new_task_input( # Primarily used by the Discord Bot
    container_name: str, action: str, cycle: str, 
    year: Optional[int] = None, month: Optional[int] = None, 
    day: Optional[int] = None, hour: Optional[int] = None, 
    minute: Optional[int] = None, weekday: Optional[int] = None,
    cron_string: Optional[str] = None # Added for Cron tasks
) -> Tuple[bool, str]:
    """Validates the input for creating a new task."""
    # Validating the basics: Container name, action, cycle
    validation_errors = []
    
    if not container_name:
        return False, "Container name is required"
    
    # Import and validate container name format
    from utils.common_helpers import validate_container_name
    if not validate_container_name(container_name):
        return False, f"Invalid container name format: {container_name}"
    
    if action not in VALID_ACTIONS:
        return False, f"Invalid action: {action}. Must be one of: {', '.join(VALID_ACTIONS)}"
    
    if cycle not in VALID_CYCLES:
        return False, f"Invalid cycle: {cycle}. Must be one of: {', '.join(VALID_CYCLES)}"
    
    # Check parameters required for different cycles 
    # but may be less used internally by ScheduledTask when time_str etc. are used directly.
    
    if hour is not None and (hour < 0 or hour > 23):
        validation_errors.append(f"Hour must be between 0 and 23, not {hour}")
    
    if minute is not None and (minute < 0 or minute > 59):
        validation_errors.append(f"Minute must be between 0 and 59, not {minute}")

    if cycle == CYCLE_CRON:
        if not cron_string:
            return False, "Cron string is required for cron cycle."
        # A basic validation for cron strings could be done here, but it's complex.
    elif cycle not in VALID_CYCLES:
        return False, f"Cycle must be one of {VALID_CYCLES} (or 'cron' with cron_string)."
    
    if cycle != CYCLE_CRON: # Time validation for non-Cron tasks
        if hour is None or not (0 <= hour <= 23): return False, "Hour must be between 0 and 23."
        if minute is None or not (0 <= minute <= 59): return False, "Minute must be between 0 and 59."
        if cycle == CYCLE_ONCE:
            # For once tasks, we need a specific year
            if year is None or not (2000 <= year <= 2100): return False, f"Year must be between 2000 and 2100 for one-time tasks."
            if month is None or not (1 <= month <= 12): return False, f"Month must be between 1 and 12 for one-time tasks."
            if day is None or not (1 <= day <= 31): return False, f"Day must be between 1 and 31 for one-time tasks."
            try: datetime(year, month, day, hour, minute)
            except ValueError as e: return False, f"Invalid date for one-time task: {e}"
        elif cycle == CYCLE_YEARLY:
            # For yearly tasks, year is optional (will use current year or next year)
            if month is None or not (1 <= month <= 12): return False, f"Month must be between 1 and 12 for yearly tasks."
            if day is None or not (1 <= day <= 31): return False, f"Day must be between 1 and 31 for yearly tasks."
            try: 
                # Validate the date with current year to ensure it's valid (e.g., Feb 29 would fail in non-leap years)
                current_year = datetime.now(timezone.utc).year
                datetime(current_year, month, day, hour, minute)
            except ValueError as e: 
                # Check if it's Feb 29 in a non-leap year
                if month == 2 and day == 29:
                    return False, "February 29 is only valid in leap years. Use day 28 for yearly tasks."
                return False, f"Invalid date for yearly task: {e}"
        elif cycle == CYCLE_WEEKLY:
            if weekday is None or not (0 <= weekday <= 6): return False, "Weekday for weekly tasks."
        elif cycle == CYCLE_MONTHLY:
            if day is None or not (1 <= day <= 31): return False, "Day for monthly tasks."
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
    except Exception as e:
        logger.warning(f"Error parsing time string '{time_str}': {e}")
    
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
    except Exception: return None

@lru_cache(maxsize=32)
def parse_weekday_string(weekday_str: str) -> Optional[int]:
    """
    Parse a weekday string to an integer (0=Monday, 6=Sunday).
    
    Args:
        weekday_str: String representation of a weekday (e.g., 'monday', 'mon', '0', etc.)
        
    Returns:
        Integer representation of the weekday (0-6) or None if invalid
    """
    weekday_str = weekday_str.strip().lower()
    
    # Direct numeric input (0-6)
    if weekday_str.isdigit():
        weekday = int(weekday_str)
        if 0 <= weekday <= 6:
            return weekday
        # For 1-7 format (Monday=1), convert to 0-6
        elif 1 <= weekday <= 7:
            # Modulo for the case 7->0 instead of 7->6
            result = (weekday - 1) % 7
            return result
    
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