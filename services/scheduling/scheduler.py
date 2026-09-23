# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #

import asyncio
import copy
import uuid
import os
import threading
import logging  # Added for logging.DEBUG constants
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Union
import calendar
from functools import lru_cache, wraps  # Import for caching

# Use central import utilities
from utils.import_utils import import_ujson, import_uvloop, import_croniter, log_performance_status
from utils.time_utils import get_datetime_imports, get_current_time, get_utc_timestamp, timestamp_to_datetime, datetime_to_timestamp
from utils.logging_utils import get_module_logger
from services.config.config_service import load_config
from services.scheduling.runtime import get_scheduler_runtime
# SERVICE FIRST: Use new Docker Action Service
from services.docker_service.docker_action_service import docker_action_service_first
from services.infrastructure.action_logger import log_user_action, user_action_logger

# Central datetime imports
datetime, timedelta, timezone, time = get_datetime_imports()
# Import time class from datetime module as datetime_time to avoid conflict
from datetime import time as datetime_time
import pytz
from utils.atomic_io import atomic_write_json, atomic_write_text

json, _using_ujson = import_ujson()
uvloop, _using_uvloop = import_uvloop()

# Logger for Scheduler
logger = get_module_logger('scheduler')

# Shared runtime state
_runtime = get_scheduler_runtime()
TASKS_FILE_PATH: Path = _runtime.tasks_file_path

def initialize_logging():
    """Initialize or reinitialize the logger with the correct log level"""
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

# created_by of tasks created in the Web UI (admin); Discord tasks store the user name
WEB_UI_CREATOR = "Web UI"

# Actions that must not be sent twice after a timeout: the first stop/restart may
# still be in progress (long StopTimeout), a second one would interrupt it again
NON_REPEATABLE_ACTIONS = ("stop", "restart", "recreate")
# Time on top of a container's StopTimeout before a stop/restart counts as timed out
STOP_TIMEOUT_MARGIN_SECONDS = 30

# Constants for weekdays
DAYS_OF_WEEK = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

def normalize_weekday(value: Any) -> Optional[str]:
    """Return the canonical weekday name ("monday".."sunday") or None if invalid.

    Accepts full names and abbreviations of at least 3 letters in any case
    ("Mon" from the Web UI form) and 0-6 indexes (Monday=0) as used by
    weekday_val. "7" is read as Sunday so older stored data stays valid.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return DAYS_OF_WEEK[value] if 0 <= value <= 6 else None
    if not isinstance(value, str):
        return None
    cleaned = value.strip().lower()
    if cleaned.isdigit():
        index = 6 if int(cleaned) == 7 else int(cleaned)
        return DAYS_OF_WEEK[index] if 0 <= index <= 6 else None
    if len(cleaned) >= 3:
        for day_name in DAYS_OF_WEEK:
            if day_name.startswith(cleaned):
                return day_name
    return None

def _localize(tz, naive_dt: datetime) -> datetime:
    """Attach tz to a naive local datetime using the UTC offset valid on that date.

    now.replace(...) + timedelta would keep the offset of "now", which is wrong
    across DST changes; pytz zones need localize().
    """
    if hasattr(tz, 'localize'):
        return tz.normalize(tz.localize(naive_dt))
    return naive_dt.replace(tzinfo=tz)

# One lock for the read-modify-write cycles on tasks.json: reentrant in this
# process (add/update/delete call load_tasks, which may save on its own) AND
# taken across processes, because the bot and the Web UI are two of them.
from services.scheduling.runtime import (  # noqa: E402
    TASKS_LOCK as _TASKS_LOCK, with_tasks_lock as _with_tasks_lock)

# Scheduler file path
TASKS_FILE_PATH = _runtime.tasks_file_path
MIN_TASK_INTERVAL_SECONDS = 10 * 60  # 10 minutes

def _get_timezone(timezone_str: str):
    """Get and cache timezone object to avoid repeated creation costs."""

    return _runtime.get_timezone(timezone_str)

def _is_tasks_file_modified() -> bool:
    """Check if the tasks file has been modified since last loaded."""

    try:
        return _runtime.is_tasks_file_modified()
    except (IOError, OSError) as exc:  # pragma: no cover - defensive guard
        logger.warning("Error checking file modification for %s: %s", TASKS_FILE_PATH, exc)
        return True

class ScheduledTask:
    """Class representing a scheduled task, compatible with Web UI and Discord bot."""

    # Use __slots__ to significantly reduce memory usage for many task instances
    __slots__ = [
        'task_id', 'container_name', 'action', 'cycle', 'status', 'is_active',
        'cron_string', 'time_str', 'year_val', 'month_val', 'day_val', 'weekday_val',
        'last_run_success', 'last_run_error', 'description', 'created_by',
        'timezone_str', 'created_at_dt', 'created_at_ts', 'last_run_ts', 'next_run_ts',
        # Whether the LAST is_valid() fell over rather than deciding. In slots
        # because this class has no __dict__ - setting it without declaring it
        # here raises inside __init__, which calls is_valid() (review E5).
        'validation_errored',
        # True when container_name names a GROUP, not a container: the name
        # stays there so list, log and validation keep working.
        'target_is_group'
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
                 last_run_error: Optional[str] = None,
                 target_is_group: bool = False):
        self.task_id = task_id or str(uuid.uuid4())
        self.container_name = container_name
        self.target_is_group = bool(target_is_group)
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

        # Weekly: keep the weekday canonical ("monday".."sunday") in day_val so
        # to_dict() persists it, with weekday_val as the matching 0-6 index.
        # Accepts "Mon" (Web UI) and a Discord 0-6 weekday, also next to schedule_details.
        if self.cycle == CYCLE_WEEKLY:
            weekday_name = normalize_weekday(self.day_val) or normalize_weekday(weekday)
            if weekday_name is not None:
                self.day_val = weekday_name
                self.weekday_val = DAYS_OF_WEEK.index(weekday_name)

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
                logger.debug("Parsed created_at from ISO string: %s", created_at)
            except ValueError:
                logger.warning(f"Could not parse created_at ISO string '{created_at}'. Using current time.")
                self.created_at_ts = time.time()
                self.created_at_dt = datetime.fromtimestamp(self.created_at_ts, tz)
        elif isinstance(created_at, (int, float)):
            self.created_at_ts = created_at
            # Create timezone-aware datetime
            self.created_at_dt = datetime.fromtimestamp(created_at, tz)
            logger.debug("Set created_at from timestamp: %s", created_at)
        else:
            self.created_at_ts = time.time()
            # Create timezone-aware datetime
            self.created_at_dt = datetime.fromtimestamp(self.created_at_ts, tz)
            logger.debug("Set created_at to current time")

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
        """Check if the task is valid.

        Sets ``validation_errored`` when the check itself fell over. Callers
        that REFUSE on a False may ignore that - nothing is lost by refusing.
        The cleanup in load_tasks() DELETES on a False and must not, because a
        check that could not be made is not a verdict (review E5).
        """
        self.validation_errored = False
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

        except (ValueError, TypeError, AttributeError) as e:
            # Data errors (cycle validation, method calls). Still False, because
            # every caller that REFUSES on a False is right to refuse - but the
            # reason is recorded, because the one caller that DELETES on a False
            # must not act on this (review E5).
            logger.error(f"Data error validating task {self.task_id}: {e}", exc_info=True)
            self.validation_errored = True
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
        # day_val holds the weekday name ("monday"; "Mon" from the Web UI is accepted),
        # weekday_val the 0-6 index (Discord format)
        if normalize_weekday(self.day_val) is not None or normalize_weekday(self.weekday_val) is not None:
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
            "target_is_group": self.target_is_group,  # then "container" names a group
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
        day_out = self.day_val
        if self.cycle == CYCLE_WEEKLY:
            # Always persist the weekday (a weekday_val alone used to be lost on save)
            day_out = normalize_weekday(self.day_val) or normalize_weekday(self.weekday_val) or self.day_val
        if day_out:
            details["day"] = day_out
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
            last_run_error=data.get("last_run_error"),
            target_is_group=bool(data.get("target_is_group", False))
        )

    def _parse_task_time(self) -> Optional[tuple]:
        """Parse time_str and return (hour, minute) tuple."""
        if not self.time_str:
            return None

        try:
            time_parts = self.time_str.split(':')
            if len(time_parts) == 2 and time_parts[0].isdigit() and time_parts[1].isdigit():
                # Fast path for standard HH:MM format
                return int(time_parts[0]), int(time_parts[1])
            else:
                # Fallback to datetime parsing
                time_obj = datetime.strptime(self.time_str, '%H:%M').time()
                return time_obj.hour, time_obj.minute
        except ValueError:
            logger.error(f"Invalid time_str format '{self.time_str}' for task {self.task_id}")
            return None

    def _calculate_cron_next_run(self, tz) -> Optional[float]:
        """Next run for a CRON cycle. Every failure clears next_run_ts: a stale one
        made a broken task read "active, next run yesterday" and never run."""
        self.next_run_ts = None
        try:
            from croniter import croniter
            now = datetime.now(tz)
            if self.cron_string:
                iter = croniter(self.cron_string, now)
                next_dt = iter.get_next(datetime)
                self.next_run_ts = next_dt.timestamp()
                logger.debug("Task %s - CRON - next execution: %s", self.task_id, next_dt)
                return self.next_run_ts
        except (ImportError, ValueError, TypeError, AttributeError) as e:
            logger.error(f"Cron next run for task {self.task_id} ({self.cron_string!r}): {e}")
            return None

    def _calculate_once_next_run(self, tz, now, task_hour, task_minute) -> Optional[datetime]:
        """Calculate next run for ONCE cycle."""
        if not (self.year_val and self.month_val and self.day_val):
            return None
        try:
            month_int = int(self.month_val) if isinstance(self.month_val, str) and self.month_val.isdigit() else self.month_val
            day_int = int(self.day_val) if isinstance(self.day_val, str) and self.day_val.isdigit() else self.day_val
            naive_dt = datetime(int(self.year_val), month_int, day_int, task_hour, task_minute)
            next_run_dt = tz.localize(naive_dt)
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(f"Task {self.task_id} - ONCE - Calculated time: {next_run_dt.strftime('%Y-%m-%d %H:%M:%S %Z')}")
            return next_run_dt if next_run_dt >= now else None
        except (ValueError, TypeError) as e:
            logger.error(f"Error creating date for ONCE task {self.task_id}: {e}")
            return None

    def _calculate_daily_next_run(self, now, task_hour, task_minute, tz=None) -> datetime:
        """Calculate next run for DAILY cycle."""
        # Build the wall-clock time for the date and localize it, so the UTC
        # offset is the one valid on that day (DST changes)
        tz = tz or now.tzinfo
        run_time = datetime_time(task_hour, task_minute)
        next_run_dt = _localize(tz, datetime.combine(now.date(), run_time))
        if next_run_dt <= now:
            next_run_dt = _localize(tz, datetime.combine(now.date() + timedelta(days=1), run_time))
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(f"Task {self.task_id} - DAILY - Time today already passed, using tomorrow: {next_run_dt.strftime('%Y-%m-%d %H:%M:%S %Z')}")
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(f"Task {self.task_id} - DAILY - Calculated time: {next_run_dt.strftime('%Y-%m-%d %H:%M:%S %Z')}")
        return next_run_dt

    def _calculate_weekly_next_run(self, tz, now, task_hour, task_minute) -> Optional[datetime]:
        """Calculate next run for WEEKLY cycle."""
        weekday_name = normalize_weekday(self.day_val) or normalize_weekday(self.weekday_val)
        if weekday_name is None:
            return None
        target_weekday = DAYS_OF_WEEK.index(weekday_name)
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(f"Task {self.task_id} - WEEKLY - Target weekday: {weekday_name} ({target_weekday})")

        # Next occurrence of the weekday after now, localized for DST. Deliberately
        # not based on last_run: that kept the old weekday after an edit and
        # drifted after a late run.
        run_time = datetime_time(task_hour, task_minute)
        days_ahead = (target_weekday - now.weekday()) % 7
        next_run_dt = _localize(tz, datetime.combine(now.date() + timedelta(days=days_ahead), run_time))
        if next_run_dt <= now:
            days_ahead += 7
            next_run_dt = _localize(tz, datetime.combine(now.date() + timedelta(days=days_ahead), run_time))
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(f"Task {self.task_id} - WEEKLY - Calculated time: {next_run_dt.strftime('%Y-%m-%d %H:%M:%S %Z')} (Days ahead: {days_ahead})")
        return next_run_dt

    def _calculate_monthly_next_run(self, tz, now, task_hour, task_minute) -> Optional[datetime]:
        """Calculate next run for MONTHLY cycle."""
        if not self.day_val:
            return None
        try:
            day_int = int(self.day_val)
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(f"Task {self.task_id} - MONTHLY - Day of month: {day_int}")
        except ValueError:
            return None
        if not (1 <= day_int <= 31):
            return None

        calc_month, calc_year = now.month, now.year
        for _ in range(24):  # Max 2 years ahead
            try:
                naive_dt = datetime(calc_year, calc_month, day_int, task_hour, task_minute)
                localized_dt = tz.localize(naive_dt)
                if localized_dt > now:
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(f"Task {self.task_id} - MONTHLY - Calculated time: {localized_dt.strftime('%Y-%m-%d %H:%M:%S %Z')}")
                    return localized_dt
            except ValueError:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(f"Task {self.task_id} - MONTHLY - Invalid day {day_int} in month {calc_month}/{calc_year}, trying next month")
            calc_month += 1
            if calc_month > 12:
                calc_month = 1
                calc_year += 1
        return None

    def _calculate_yearly_next_run(self, tz, now, task_hour, task_minute) -> Optional[datetime]:
        """Calculate next run for YEARLY cycle."""
        if not (self.month_val and self.day_val):
            return None
        try:
            month_int = int(self.month_val)
            day_int = int(self.day_val)
            if not (1 <= month_int <= 12 and 1 <= day_int <= 31):
                logger.error(f"Task {self.task_id} - YEARLY - Invalid date: {month_int}-{day_int}")
                return None

            # A stored past year (e.g. the creation year from the Web UI form) must
            # not push a recurring task past the current year; a future year is the
            # first year it runs in.
            first_year = now.year
            if self.year_val:
                stored_year = int(self.year_val)
                if self.cycle == CYCLE_ONCE and stored_year < now.year:
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(f"Task {self.task_id} - ONCE - Year in the past, task expired")
                    return None
                first_year = max(first_year, stored_year)

            for target_year in (first_year, first_year + 1):
                # Clamp the stored day per year (Feb 29 -> Feb 28 in non-leap years)
                # without changing the stored day, so leap years get Feb 29 again
                day_in_year = min(day_int, calendar.monthrange(target_year, month_int)[1])
                if day_in_year != day_int:
                    logger.info(f"Task {self.task_id} - YEARLY - Using {target_year}-{month_int:02d}-{day_in_year:02d} "
                                f"instead of day {day_int} (not in that month)")
                next_run_dt = _localize(tz, datetime(target_year, month_int, day_in_year, task_hour, task_minute))
                if next_run_dt > now:
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(f"Task {self.task_id} - YEARLY - Calculated time: {next_run_dt.strftime('%Y-%m-%d %H:%M:%S %Z')}")
                    return next_run_dt
            return None
        except (ValueError, TypeError) as e:
            logger.error(f"Error creating date for YEARLY task {self.task_id}: {e}")
            return None

    def calculate_next_run(self) -> Optional[float]:
        """Calculate the next execution time based on the cycle and details."""
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(f"Calculating next run for task {self.task_id} with cycle {self.cycle} and details: cron='{self.cron_string}', time='{self.time_str}', day='{self.day_val}', month='{self.month_val}', year='{self.year_val}'")

        # Handle CRON cycle (returns timestamp directly)
        if self.cycle == CYCLE_CRON:
            tz = _get_timezone(self.timezone_str)
            return self._calculate_cron_next_run(tz)

        try:
            # Initialize timezone and current time
            tz = _get_timezone(self.timezone_str)
            now = datetime.now(tz)
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(f"Task {self.task_id} - Timezone: {self.timezone_str}, Current local time: {now.strftime('%Y-%m-%d %H:%M:%S %Z')}")

            # Parse task time
            time_tuple = self._parse_task_time()
            if time_tuple is None:
                return None
            task_hour, task_minute = time_tuple
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(f"Task {self.task_id} - Extracted time: {task_hour}:{task_minute} (in {self.timezone_str})")

            # Calculate next run based on cycle type
            next_run_dt = None
            if self.cycle == CYCLE_ONCE:
                next_run_dt = self._calculate_once_next_run(tz, now, task_hour, task_minute)
            elif self.cycle == CYCLE_DAILY:
                next_run_dt = self._calculate_daily_next_run(now, task_hour, task_minute, tz)
            elif self.cycle == CYCLE_WEEKLY:
                next_run_dt = self._calculate_weekly_next_run(tz, now, task_hour, task_minute)
            elif self.cycle == CYCLE_MONTHLY:
                next_run_dt = self._calculate_monthly_next_run(tz, now, task_hour, task_minute)
            elif self.cycle == CYCLE_YEARLY:
                next_run_dt = self._calculate_yearly_next_run(tz, now, task_hour, task_minute)
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

            # Nothing to compute - a one-time or yearly date that has passed. The
            # OLD time used to stay: an edit that moved a task backwards kept it
            # armed for the date the operator had just removed, and the panel said
            # "updated successfully".
            self.next_run_ts = None
            return None
        except (ValueError, TypeError, AttributeError, OSError) as e:
            # Data/time errors (datetime calculations, timezone operations, timestamp conversion)
            logger.error(f"Error calculating next run for task {self.task_id} (cycle: {self.cycle}): {e}", exc_info=True)
            self.next_run_ts = None
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
        except (ValueError, OSError, AttributeError) as e:
            # Data/time errors (timestamp conversion, timezone operations)
            logger.error(f"Error converting timestamp {self.next_run_ts} to datetime: {e}", exc_info=True)
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
            config = load_config()
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

        except (ValueError, AttributeError, OSError) as e:
            # Data/time errors (datetime operations, timezone, timestamp conversion)
            logger.error(f"Error calculating next donation run: {e}", exc_info=True)
            # Fallback - set to next month's 10th at 13:37
            try:
                if now.month == 12:
                    fallback_naive = datetime(now.year + 1, 1, 10, 13, 37)
                else:
                    fallback_naive = datetime(now.year, now.month + 1, 10, 13, 37)
                fallback = tz.localize(fallback_naive)
                self.next_run_ts = fallback.timestamp()
            except (ValueError, AttributeError, OSError) as fallback_error:
                # Data/time errors (fallback datetime operations)
                logger.error(f"Even fallback calculation failed: {fallback_error}", exc_info=True)
                # Ultimate fallback - 30 days from now
                self.next_run_ts = (now + timedelta(days=30)).timestamp()

    def _was_run_this_month(self, now: datetime) -> bool:
        """Check if donation task was already run this month."""
        if not self.last_run_ts:
            return False

        try:
            last_run_dt = datetime.fromtimestamp(self.last_run_ts, tz=now.tzinfo)
            return last_run_dt.year == now.year and last_run_dt.month == now.month
        except (ValueError, OSError, AttributeError) as e:
            # Data/time errors (timestamp conversion, timezone access)
            logger.debug(f"Error checking if donation was run this month: {e}", exc_info=True)
            return False

# --- System Task Management Functions ---

def create_donation_system_task() -> ScheduledTask:
    """Create the hard-coded donation system task.

    The task is always created but marked as inactive if donations are disabled
    via premium key. This allows the task to appear in the Web UI but prevents
    execution.
    """
    try:
        # Check if donations are disabled via premium key
        from services.donation.donation_utils import is_donations_disabled
        donations_disabled = is_donations_disabled()

        if donations_disabled:
            logger.info("Donation system task created but marked INACTIVE - donations disabled by premium key")
        else:
            logger.debug("Donation system task created and ACTIVE")

        # Get configured timezone or fall back to default
        try:
            config = load_config()
            timezone_str = config.get('timezone', 'Europe/Berlin')
        except (ImportError, AttributeError, IOError, OSError) as e:
            # Service/file errors (config loading failed)
            logger.debug(f"Error loading timezone config: {e}", exc_info=True)
            timezone_str = 'Europe/Berlin'

        # Create task with simple configuration
        # The actual 2nd Sunday calculation happens in _calculate_next_donation_run()
        task = ScheduledTask(
            task_id=DONATION_TASK_ID,
            container_name="SYSTEM",  # Special container name for system tasks
            action="donation_message",
            cycle=CYCLE_MONTHLY,  # Display as monthly
            description="Automatic donation message (2nd Sunday @ 13:37)" +
                       (" [DISABLED by premium key]" if donations_disabled else ""),
            created_by="SYSTEM",
            timezone_str=timezone_str,
            schedule_details={"time": "13:37", "day": "2nd Sunday"}  # Special display for donation task
        )

        # Set active status based on whether donations are disabled
        task.is_active = not donations_disabled  # Active only if donations NOT disabled
        task.status = "active" if not donations_disabled else "disabled"

        # System tasks are rebuilt on every load_tasks(); restore their run state
        # so next_run stays stable until the task has run (it used to be
        # recalculated to the next month at the due time and never became due)
        state = _runtime.get_system_task_state(DONATION_TASK_ID)
        task.last_run_ts = state.get("last_run_ts")
        task.last_run_success = state.get("last_run_success")
        task.last_run_error = state.get("last_run_error")

        # Use our special donation calculation (only if active)
        if task.is_active:
            if state.get("next_run_ts"):
                task.next_run_ts = state["next_run_ts"]
            else:
                task._calculate_next_donation_run()
                _store_system_task_state(task)
        else:
            # Set next_run to None if inactive to prevent scheduling
            task.next_run_ts = None

        return task
    except (ImportError, AttributeError, RuntimeError) as e:
        # Service dependency errors (donation_utils, ScheduledTask class unavailable)
        logger.error(f"Service dependency error creating donation system task: {e}", exc_info=True)
        return None
    except (ValueError, TypeError) as e:
        # Data errors (task initialization)
        logger.error(f"Data error creating donation system task: {e}", exc_info=True)
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

    except (ImportError, AttributeError, RuntimeError) as e:
        # Service dependency errors (system task creation failed)
        logger.error(f"Service dependency error creating system tasks: {e}", exc_info=True)
        # Return empty list if system task creation fails - don't break the whole system
    except (ValueError, TypeError) as e:
        # Data errors (task list operations)
        logger.error(f"Data error creating system tasks: {e}", exc_info=True)

    return system_tasks

# --- Scheduler File I/O Functions --- (Now operating on TASKS_FILE_PATH)

def _load_raw_tasks_from_file() -> List[Dict[str, Any]]:
    """Loads raw task data directly from the TASKS_FILE_PATH."""
    max_retries = 3
    retry_delay = 0.5  # seconds
    last_error = None

    for attempt in range(max_retries):
        try:
            if not TASKS_FILE_PATH.exists():
                logger.info("Tasks file %s doesn't exist. Returning empty list.", TASKS_FILE_PATH)
                _runtime.mark_tasks_file_missing()
                return []

            file_stat = TASKS_FILE_PATH.stat()
            _runtime.update_tracked_file_state(
                modified_time=file_stat.st_mtime, size=file_stat.st_size
            )
            file_size = file_stat.st_size

            # Empty file check - skip unnecessary JSON parsing
            if file_size == 0:
                logger.info("Tasks file %s is empty.", TASKS_FILE_PATH)
                return []

            content = TASKS_FILE_PATH.read_text(encoding='utf-8').strip()
            if not content:
                return []

            # Use ujson which is much faster than standard json
            return json.loads(content)

        except json.JSONDecodeError as exc:
            logger.error("Error decoding JSON data from %s: %s", TASKS_FILE_PATH, exc)
            return []
        except (IOError, OSError) as exc:
            last_error = exc
            if attempt < max_retries - 1:
                logger.warning(
                    "Network/IO error reading %s, retrying (%s/%s): %s",
                    TASKS_FILE_PATH,
                    attempt + 1,
                    max_retries,
                    exc,
                )
                time.sleep(retry_delay * (attempt + 1))  # Exponential backoff
            else:
                logger.error("Failed to read tasks file after %s attempts: %s", max_retries, exc)
                return []
        except (ValueError, TypeError, AttributeError) as exc:
            # Data errors (unexpected data structure)
            logger.error("Data error reading tasks file %s: %s", TASKS_FILE_PATH, exc, exc_info=True)
            return []

    if last_error:
        logger.error("All retries failed when reading %s: %s", TASKS_FILE_PATH, last_error)
    return []

def _save_raw_tasks_to_file(tasks_data: List[Dict[str, Any]]) -> bool:
    """Saves raw task data directly to TASKS_FILE_PATH."""
    max_retries = 3
    retry_delay = 0.5  # seconds

    for attempt in range(max_retries):
        try:
            # Check if file already exists and compare content to avoid unnecessary writes
            if TASKS_FILE_PATH.exists():
                try:
                    current_content = TASKS_FILE_PATH.read_text(encoding='utf-8').strip()
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
                except (json.JSONDecodeError, KeyError, ValueError, TypeError) as e:
                    # JSON/data errors (comparison failed)
                    logger.debug(f"Data error comparing task data: {e}, proceeding with write", exc_info=True)

            # Create directory if needed
            _runtime.ensure_layout()

            # The shared helper, not a fourth hand-rolled temp-and-rename. This
            # one was written before utils/atomic_io.py existed and never moved
            # onto it, and it differed in three ways that matter (review E1):
            #
            #   - mkstemp creates its file 0600, and the rename then made THAT
            #     the mode of tasks.json. The file is written by two processes,
            #     the bot and the web panel, and every save re-stamped it.
            #   - the cleanup sat under (json.JSONDecodeError, ValueError,
            #     TypeError, UnicodeEncodeError), so a full disk during the dump
            #     or the fsync left the temp file behind - and the retry loop
            #     below then made three of them per save, on every save.
            #   - the non-posix branch used shutil.move onto an existing file,
            #     which is a copy and not a replace. atomic_io uses os.replace,
            #     which is atomic on both.
            #
            # indent=4 and ensure_ascii=False keep the file byte-for-byte the
            # shape it had, which the unchanged-check above compares against.
            atomic_write_json(TASKS_FILE_PATH, tasks_data, indent=4)

            # Update cache and modified time after successful save
            _runtime.invalidate_caches()
            _runtime.record_current_file_state()
            logger.debug("Tasks successfully saved to %s.", TASKS_FILE_PATH)
            return True

        except (IOError, OSError) as e:
            if attempt < max_retries - 1:
                logger.warning(f"Network/IO error writing to {TASKS_FILE_PATH}, retrying ({attempt+1}/{max_retries}): {e}")
                time.sleep(retry_delay * (attempt + 1))  # Exponential backoff
            else:
                logger.error(f"Failed to save tasks after {max_retries} attempts: {e}")
                return False
        except (ValueError, TypeError, AttributeError) as e:
            # Data errors (unexpected runtime errors during save process)
            logger.error(f"Data error saving tasks to {TASKS_FILE_PATH}: {e}", exc_info=True)
            return False

    return False

# --- Public Task Management API --- (Now using ScheduledTask objects and TASKS_FILE_PATH)

# Task ids whose cleanup could not be written back (read-only mount, permissions). Kept so the
# same failing rewrite is not attempted on every scheduler cycle (B5).
_failed_cleanup_ids: frozenset = frozenset()

# True while the last attempt to read tasks.json failed. Every writer builds its
# list from load_tasks(), and a failed read gives back an EMPTY one - so saving
# after it would write the schedule away. Cleared by the next read that works,
# so a passing glitch heals itself (review E4).
_last_load_failed: bool = False


@_with_tasks_lock
def load_tasks() -> List[ScheduledTask]:
    """Load all scheduled tasks from storage"""
    global _last_load_failed
    # Maintain task persistence across restarts
    tasks = []

    # Always ensure task file exists
    if not TASKS_FILE_PATH.exists():
        logger.debug("Tasks file %s does not exist, creating empty file", TASKS_FILE_PATH)
        # Create empty tasks file
        try:
            _runtime.ensure_layout()
            atomic_write_text(TASKS_FILE_PATH, "[]")
            _runtime.record_current_file_state()
            logger.info("Created empty tasks file at %s", TASKS_FILE_PATH)
        except (IOError, OSError, PermissionError) as e:
            # File I/O errors (cannot create file, permission denied)
            logger.error(f"File I/O error creating tasks file: {e}", exc_info=True)
        return tasks

    # eXecute task loading with error handling
    try:
        data = json.loads(TASKS_FILE_PATH.read_text(encoding="utf-8") or "[]")

        # Deserialize each task from stored data
        for task_data in data:
            try:
                task = ScheduledTask.from_dict(task_data)
                tasks.append(task)
                logger.debug(f"Loaded task: {task.task_id}")
            except (ValueError, TypeError, KeyError, AttributeError) as e:
                # Data errors (invalid task data structure, missing fields, type mismatches)
                logger.error(f"Data error creating ScheduledTask from data: {e}", exc_info=True)
                continue

        # Display successful loading information only on debug level to reduce log spam
        logger.debug(f"Loaded {len(tasks)} scheduled tasks")

        # The read worked: whatever went wrong before is over (review E4).
        _last_load_failed = False

    except (json.JSONDecodeError, ValueError, TypeError) as e:
        # JSON/data errors (malformed JSON, unexpected data types)
        logger.error(f"JSON/data error loading tasks from {TASKS_FILE_PATH}: {e}", exc_info=True)
        # Remembered, because this function answers with an EMPTY list and the
        # writers cannot tell that from "there are no tasks" (review E4).
        _last_load_failed = True
    except (IOError, OSError, UnicodeDecodeError) as e:
        # File I/O errors (cannot read file, encoding issues)
        logger.error(f"File I/O error loading tasks from {TASKS_FILE_PATH}: {e}", exc_info=True)
        _last_load_failed = True

    # Cleanup any invalid or expired tasks. The rewrite only happens when it can actually
    # stick: if saving fails (read-only config mount, wrong permissions), the same cleanup
    # would otherwise be retried on every load and rewrite tasks.json on every scheduler
    # cycle (B5). We remember the failing ids and stay quiet until the set changes.
    global _failed_cleanup_ids
    # A task is removed only when it is DEFINITELY invalid. is_valid() also
    # answers False when the check itself raised, and deleting on that would
    # take a task out of the operator's schedule for good because a validator
    # met an unexpected value - with no backup and nobody asked (review E5).
    def _is_definitely_invalid(task: ScheduledTask) -> bool:
        invalid = not task.is_valid()
        if invalid and getattr(task, 'validation_errored', False):
            logger.warning("Keeping task %s: its validation could not be completed, "
                           "which is not the same as invalid", task.task_id)
            return False
        return invalid

    valid_tasks = [task for task in tasks if not _is_definitely_invalid(task)]
    if len(valid_tasks) != len(tasks):
        removed_ids = frozenset(task.task_id for task in tasks if _is_definitely_invalid(task))
        if removed_ids == _failed_cleanup_ids:
            logger.debug("Skipping cleanup rewrite: the same %d invalid task(s) could not be "
                         "removed earlier", len(removed_ids))
        elif save_tasks(valid_tasks):
            logger.info(f"Removed {len(tasks) - len(valid_tasks)} invalid tasks")
            _failed_cleanup_ids = frozenset()
        else:
            logger.warning("Could not remove %d invalid task(s): writing %s failed. Not "
                           "retrying until the set of invalid tasks changes.",
                           len(removed_ids), TASKS_FILE_PATH)
            _failed_cleanup_ids = removed_ids

    # Cache the valid (user) tasks for faster lookups and drop stale container caches
    _runtime.replace_tasks_cache({task.task_id: task for task in valid_tasks})
    _runtime.clear_container_cache()

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

@_with_tasks_lock
def save_tasks(tasks: List[ScheduledTask]) -> bool:
    """Save all ScheduledTask objects to tasks.json."""

    # A read that failed must not become a write. Every caller builds its list
    # from load_tasks(), which answers with an EMPTY list when tasks.json could
    # not be read or parsed - so adding one task after a bad read wrote a file
    # with only that task in it, and there is no backup. The file on disk is
    # the only copy of the schedule there is (review E4).
    #
    # Refusing, not guessing: no stale list is written back and no repair is
    # attempted. The next read that works clears this by itself.
    if _last_load_failed:
        logger.error("Refusing to save tasks: the last read of %s failed, so the list to "
                     "be written may be missing everything. Fix or remove the file; the "
                     "next successful read lifts this by itself.", TASKS_FILE_PATH)
        return False

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
        _runtime.replace_tasks_cache({task.task_id: task for task in tasks})
        _runtime.clear_container_cache()

    return success

def find_task_by_id(task_id: str) -> Optional[ScheduledTask]:
    """Find a task by ID using the cache when possible."""

    tasks_cache = _runtime.tasks_cache

    # Try to get from cache if file hasn't changed.
    # Hand out a copy: callers such as the Web UI edit path mutate the task they get back and
    # then save it explicitly. Returning the cached object let those edits leak into the cache
    # before (and regardless of whether) the save succeeded (B7).
    if not _is_tasks_file_modified() and task_id in tasks_cache:
        return copy.deepcopy(tasks_cache[task_id])

    # For a single task lookup, try to avoid loading all tasks if possible
    # This optimization is helpful for large task lists
    if TASKS_FILE_PATH.exists():
        try:
            # First check if we need to reload by checking modification time
            if _is_tasks_file_modified():
                # Load all tasks (will update cache) and filter
                tasks = load_tasks()
                for task in tasks:
                    if task.task_id == task_id:
                        return task
            # File exists but hasn't been modified - do a targeted search
            elif not tasks_cache:
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
                            _runtime.store_task(task_id, task)
                            return task
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            # Data errors (task deserialization, dict access, validation failures)
            logger.error("Data error during optimized task lookup: %s", exc, exc_info=True)
        except (IOError, OSError, json.JSONDecodeError) as exc:
            # File I/O or JSON errors (file read failures, malformed JSON)
            logger.error("File/JSON error during optimized task lookup: %s", exc, exc_info=True)

    # Default fallback - load all tasks and search
    tasks = load_tasks()
    for task in tasks:
        if task.task_id == task_id:
            return task
    return None


def get_tasks_for_container(container_name: str) -> List[ScheduledTask]:
    """Get all tasks for a specific container, efficiently using the cache."""

    tasks_cache = _runtime.tasks_cache
    container_cache = _runtime.container_tasks_cache

    # Check if whole task cache is valid and container cache was recently updated
    if not _is_tasks_file_modified() and tasks_cache:
        current_time = time.time()
        # Container cache refresh period - 5 seconds
        container_cache_ttl = 5

        # Check if we have a recent container-specific cache
        cached_tasks = container_cache.get(container_name)
        cache_valid = (
            cached_tasks is not None
            and current_time - _runtime.container_cache_timestamp < container_cache_ttl
        )
        if cache_valid:
            # Own list, so a caller cannot append to or clear the cached one (B7). The task
            # objects stay shared on purpose: every caller of this function only reads them,
            # and this runs in the status loop where deep copies would cost real time.
            return list(cached_tasks)

        # Filter from main cache if available, update container cache
        container_tasks = [task for task in tasks_cache.values() if task.container_name == container_name]
        _runtime.update_container_cache(container_name, container_tasks, timestamp=current_time)
        return container_tasks

    # Otherwise load all tasks (will update cache) and filter
    tasks = load_tasks()
    container_tasks = [task for task in tasks if task.container_name == container_name]

    # Update container cache
    _runtime.update_container_cache(container_name, container_tasks)

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

@_with_tasks_lock
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

@_with_tasks_lock
def update_task(task_to_update: ScheduledTask, check_collision: bool = True) -> bool:
    """Update a stored task.

    check_collision=False skips the 10-minute collision check; used when the
    scheduler saves a task's own reschedule after (or instead of) a run.
    """
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
            # BUGFIX: Check for collisions before update (only for the same container, ignore the task itself).
            # Skipped for the scheduler's own reschedule (check_collision=False).
            if check_collision and task_to_update.next_run_ts is not None:
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

@_with_tasks_lock
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

def _store_system_task_state(task: ScheduledTask) -> None:
    """Remember a system task's run state across load_tasks() calls.

    System tasks are not stored in tasks.json and are rebuilt on every load;
    their last_run/next_run is kept in the scheduler runtime (per process).
    """
    _runtime.store_system_task_state(task.task_id, {
        "last_run_ts": task.last_run_ts,
        "next_run_ts": task.next_run_ts,
        "last_run_success": task.last_run_success,
        "last_run_error": task.last_run_error,
    })

def _persist_executed_task(task: ScheduledTask) -> bool:
    """Save the result and reschedule of an executed (or missed) task.

    No collision check: the new next_run comes from the task's own schedule, and
    a refused update would keep the old next_run (double execution, then stuck).
    """
    if task.is_system_task():
        _store_system_task_state(task)
        return True
    return update_task(task, check_collision=False)

def _format_task_time(task: ScheduledTask, timestamp: Optional[float]) -> str:
    """Format a timestamp in the task's timezone for log and error messages."""
    try:
        return datetime.fromtimestamp(timestamp, _get_timezone(task.timezone_str)).strftime('%Y-%m-%d %H:%M %Z')
    except (ValueError, TypeError, AttributeError, OSError):
        return str(timestamp)

def reschedule_missed_task(task: ScheduledTask) -> bool:
    """Handle a task whose scheduled time passed longer ago than the grace period.

    Missed runs (host down, scheduler delayed) are not executed retroactively.
    Recurring tasks move to their next future occurrence; one-time tasks are
    deactivated with an explanatory error instead of staying active forever.
    """
    missed_at = _format_task_time(task, task.next_run_ts)
    if task.cycle == CYCLE_ONCE:
        task.is_active = False
        task.last_run_success = False
        task.last_run_error = f"Missed scheduled time {missed_at} (scheduler not running); not executed"
        logger.warning(f"One-time task {task.task_id} ({task.container_name} {task.action}) missed its time {missed_at}; deactivated")
    else:
        if task.is_donation_task():
            task._calculate_next_donation_run()
        else:
            task.calculate_next_run()
        logger.warning(f"Task {task.task_id} ({task.container_name} {task.action}) missed its run at {missed_at}; "
                       f"rescheduled to {_format_task_time(task, task.next_run_ts)}")
    return _persist_executed_task(task)

# --- One-time upgrade pass for long-dead tasks (audit R1-1) ---
#
# Older versions never ran a recurring task again once a run was missed by more
# than ~90 s (while still showing it as active). The missed-run handling now
# reschedules such tasks, which would revive tasks that were dead for months (and
# run them next to replacements users created meanwhile). Once per install, tasks
# that are overdue by more than about two cycles are paused with a note instead.

UPGRADE_PAUSE_NOTE_PREFIX = "Paused after upgrade"
UPGRADE_STATE_FILENAME = "tasks_upgrade_state.json"
_DEAD_TASK_PASS_KEY = "paused_long_dead_tasks"
_DAY_SECONDS = 24 * 60 * 60
_DEAD_TASK_THRESHOLDS = {
    CYCLE_DAILY: 2 * _DAY_SECONDS,
    CYCLE_WEEKLY: 14 * _DAY_SECONDS,
    CYCLE_MONTHLY: 62 * _DAY_SECONDS,
    CYCLE_YEARLY: 400 * _DAY_SECONDS,
}
_DEAD_TASK_DEFAULT_THRESHOLD = 2 * _DAY_SECONDS
# Frequent cron schedules: an update's own downtime must not pause them
_DEAD_TASK_MIN_THRESHOLD = 60 * 60

def _cron_interval_seconds(task: ScheduledTask) -> Optional[float]:
    """Interval between two runs of a cron task after its next_run, or None if unknown."""
    try:
        from croniter import croniter
        start = datetime.fromtimestamp(task.next_run_ts, _get_timezone(task.timezone_str))
        cron_iter = croniter(task.cron_string, start)
        first = cron_iter.get_next(float)
        second = cron_iter.get_next(float)
        return second - first if second > first else None
    except (ImportError, ValueError, TypeError, KeyError, AttributeError, OSError):
        return None

def _dead_task_threshold_seconds(task: ScheduledTask) -> float:
    """How far in the past a task's next run may lie before it counts as long dead."""
    if task.cycle == CYCLE_CRON:
        interval = _cron_interval_seconds(task)
        if interval:
            return max(2 * interval, _DEAD_TASK_MIN_THRESHOLD)
        return _DEAD_TASK_DEFAULT_THRESHOLD
    return _DEAD_TASK_THRESHOLDS.get(task.cycle, _DEAD_TASK_DEFAULT_THRESHOLD)

def is_upgrade_pause_note(note: Any) -> bool:
    """True if note is the explanation written by pause_long_dead_tasks_once()."""
    return isinstance(note, str) and note.startswith(UPGRADE_PAUSE_NOTE_PREFIX)

@_with_tasks_lock
def pause_long_dead_tasks_once(now_ts: Optional[float] = None) -> int:
    """Pause recurring tasks that were dead long before this version (runs once per install).

    Active recurring tasks whose next run lies more than about two cycles in the
    past are deactivated with an explanatory last_run_error. Shorter misses are
    left to the normal missed-run handling (rescheduled). A marker in the config
    directory keeps the pass from running again. Returns the number of paused tasks.
    """
    state_path = _runtime.config_dir / UPGRADE_STATE_FILENAME
    state: Dict[str, Any] = {}
    try:
        if state_path.exists():
            loaded = json.loads(state_path.read_text(encoding='utf-8') or '{}')
            if isinstance(loaded, dict):
                if _DEAD_TASK_PASS_KEY in loaded:
                    return 0
                state = loaded
    except (OSError, ValueError, TypeError) as e:
        # Unreadable marker: better skip than risk pausing tasks on every start
        logger.warning(f"Could not read {state_path}: {e}; skipping the one-time check for long-dead tasks")
        return 0

    now_ts = time.time() if now_ts is None else now_ts
    tasks = load_tasks()
    paused = []
    for task in tasks:
        if task.is_system_task() or not task.is_active or task.cycle == CYCLE_ONCE or not task.next_run_ts:
            continue
        if now_ts - task.next_run_ts <= _dead_task_threshold_seconds(task):
            continue
        # Last run if known, otherwise the run that was missed first
        since_ts = task.last_run_ts if task.last_run_ts and task.last_run_ts < task.next_run_ts else task.next_run_ts
        task.is_active = False
        task.last_run_error = (f"{UPGRADE_PAUSE_NOTE_PREFIX}: had not run since {_format_task_time(task, since_ts)}; "
                               f"re-enable if still wanted")
        paused.append(task)

    if paused and not save_tasks(tasks):
        logger.error(f"Could not save {len(paused)} long-dead task(s) as paused; retrying at the next start")
        return 0

    state[_DEAD_TASK_PASS_KEY] = {
        "done_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "paused": [task.task_id for task in paused],
    }
    try:
        _runtime.ensure_layout()
        atomic_write_text(state_path, json.dumps(state, indent=4))
    except (OSError, TypeError, ValueError) as e:
        logger.warning(f"Could not write {state_path}: {e}; the check for long-dead tasks runs again at the next start")

    if paused:
        summary = ", ".join(f"{task.container_name} {task.action} ({task.cycle}, {task.task_id})" for task in paused)
        logger.warning(f"Upgrade check: paused {len(paused)} scheduled task(s) that had not run for more than "
                       f"two cycles; re-enable them in the Web UI if still wanted: {summary}")
    else:
        logger.info("Upgrade check: no long-dead scheduled tasks found")
    return len(paused)

async def _get_container_stop_timeout(container_name: str) -> Optional[int]:
    """Return the container's configured StopTimeout in seconds, or None if unset or unknown."""
    try:
        import docker
        from services.docker_service.docker_client_pool import get_docker_client_async
        from services.docker_service.docker_action_service import get_stop_timeout_kwargs
        from services.exceptions import DockerServiceError
    except ImportError as e:
        logger.debug(f"StopTimeout lookup unavailable: {e}")
        return None

    async def _lookup() -> Optional[int]:
        async with get_docker_client_async(timeout=10, operation='info', container_name=container_name) as client:
            container = await asyncio.to_thread(client.containers.get, container_name)
            return get_stop_timeout_kwargs(container).get('timeout')

    try:
        return await asyncio.wait_for(_lookup(), timeout=15)
    except (asyncio.TimeoutError, docker.errors.DockerException, DockerServiceError,
            OSError, RuntimeError, AttributeError, TypeError, ValueError) as e:
        logger.debug(f"Could not read StopTimeout of '{container_name}': {e}")
        return None

async def _get_action_timeout(task: ScheduledTask, timeout: float) -> float:
    """Timeout for a task's Docker action: at least StopTimeout + margin for stop/restart."""
    if task.action not in NON_REPEATABLE_ACTIONS:
        return timeout
    stop_timeout = await _get_container_stop_timeout(task.container_name)
    if stop_timeout is None:
        return timeout
    return max(timeout, stop_timeout + STOP_TIMEOUT_MARGIN_SECONDS)

def get_tasks_in_timeframe(start_time: float, end_time: float) -> List[ScheduledTask]:
    """Get all tasks scheduled within a specific timeframe, using cache when possible."""

    tasks_cache = _runtime.tasks_cache

    if not _is_tasks_file_modified() and tasks_cache:
        # Filter from cache if available
        result = [
            task
            for task in tasks_cache.values()
            if task.next_run_ts and start_time <= task.next_run_ts <= end_time
        ]
        # Sort results by execution time for better usability
        return sorted(result, key=lambda t: t.next_run_ts)

    # Otherwise load all tasks and filter
    tasks = load_tasks()
    result = [task for task in tasks if task.next_run_ts and start_time <= task.next_run_ts <= end_time]
    return sorted(result, key=lambda t: t.next_run_ts)

def get_next_week_tasks() -> List[ScheduledTask]:
    now = time.time()
    week_later = now + (7 * 24 * 60 * 60)
    return get_tasks_in_timeframe(now, week_later)

def _is_discord_created(task: ScheduledTask) -> bool:
    """True for tasks created in Discord (not by the Web UI admin or the system).

    A task without a creator marker predates the marker (older installs) and must NOT be
    treated as Discord-created: combined with the ['status'] default for container configs
    that lack allowed_actions, it would be skipped on every run, forever (V2 review B4).
    """
    if not task.created_by:
        return False
    return task.created_by not in (WEB_UI_CREATOR, "SYSTEM")

def _get_disallowed_action_reason(container_name: str, action: str) -> Optional[str]:
    """Return why a scheduled action may no longer run, or None if it may run.

    Only a configured container whose allowed_actions lack the action blocks the
    run. If the container config cannot be read or the container is not
    configured, the task runs as before (logged).
    """
    try:
        from services.config.server_config_service import get_server_config_service
        servers = get_server_config_service().get_all_servers()
    except (ImportError, AttributeError, RuntimeError, OSError, ValueError) as e:
        # REFUSES, where this used to return None and let the action through.
        # None means "may run" here, so an unreadable config was granting a
        # permission it could not check - and SPEC.md Z5 says start, stop and
        # restart happen only if the container allows the action, on every path
        # including this one. It is also the answer this programme gave the same
        # question elsewhere: D36 for the admin list, D32 for the container
        # assignment, E5 for the validity check. A permission that cannot be
        # read is not a permission granted (review E6).
        #
        # Since E3 a skipped run is written on the task, so this does not
        # vanish into the log the way it would have before.
        logger.error(f"Could not check allowed actions for '{container_name}': {e}", exc_info=True)
        return (f"The container configuration could not be read, so it is not known whether "
                f"'{action}' is still allowed for '{container_name}'")

    for server in servers:
        if isinstance(server, dict) and server.get('docker_name') == container_name:
            allowed_actions = server.get('allowed_actions') or []
            if action in allowed_actions:
                return None
            return (f"Action '{action}' is no longer allowed for container '{container_name}' "
                    f"(allowed: {', '.join(allowed_actions) or 'none'})")

    logger.warning(f"Container '{container_name}' of a scheduled task is not in the container config; running it anyway")
    return None

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
        from services.donation.donation_utils import is_donations_disabled
        if is_donations_disabled():
            logger.info(f"Skipping donation task {task.task_id} - donations disabled by premium key")
            # Update task as if it ran successfully to reschedule it
            task.last_run_success = True
            task.last_run_error = None
            task.update_after_execution()
            _persist_executed_task(task)
            return True  # Return true so it reschedules normally

        # Execute donation message task
        try:
            from services.scheduling.donation_message_service import execute_donation_message_task, get_bot_instance

            # Get bot instance
            bot = get_bot_instance()
            if not bot:
                logger.warning("Bot instance not available for donation message task")

            # Execute the donation message task
            result = await execute_donation_message_task(bot=bot)

            execution_time = time.time() - execution_start
            if result:
                logger.info(f"Donation message task {task.task_id} completed successfully in {execution_time:.2f}s")
                task.last_run_success = True
                task.last_run_error = None

                # Log in User Action Log
                log_user_action(
                    action="DONATION_MESSAGE",
                    target="SYSTEM",
                    user="Scheduled Task",
                    source="Scheduled Task",
                    details=f"Task ID: {task.task_id}, Result: Success, Duration: {execution_time:.2f}s"
                )
            else:
                logger.error(f"Donation message task {task.task_id} failed")
                task.last_run_success = False
                task.last_run_error = "Donation message execution failed"

                # Log in User Action Log
                log_user_action(
                    action="DONATION_MESSAGE_FAILED",
                    target="SYSTEM",
                    user="Scheduled Task",
                    source="Scheduled Task",
                    details=f"Task ID: {task.task_id}, Error: Execution failed"
                )

            task.update_after_execution()
            _persist_executed_task(task)
            return result

        except (ImportError, AttributeError, RuntimeError) as e:
            execution_time = time.time() - execution_start
            error_msg = f"Error executing donation message task: {e}"
            logger.error(error_msg, exc_info=True)

            task.last_run_success = False
            task.last_run_error = str(e)

            log_user_action(
                action="DONATION_MESSAGE_ERROR",
                target="SYSTEM",
                user="Scheduled Task",
                source="Scheduled Task",
                details=f"Task ID: {task.task_id}, Duration: {execution_time:.2f}s, Error: {str(e)}"
            )

            task.update_after_execution()
            _persist_executed_task(task)
            return False

    if task.target_is_group:
        # Imported here: group_tasks needs names from this module
        from services.scheduling.group_tasks import execute_group_task
        return await execute_group_task(task, timeout)

    # Re-check the container's allowed actions at execution time for tasks created
    # in Discord: the config may have changed since the task was created. Disallowed
    # runs are skipped and recorded as failed (audit A10). Web UI tasks are admin
    # tasks and always run (R4-1).
    disallowed_reason = None
    if _is_discord_created(task):
        disallowed_reason = _get_disallowed_action_reason(task.container_name, task.action)
    if disallowed_reason:
        logger.warning(f"Skipping task {task.task_id}: {disallowed_reason}")
        task.last_run_success = False
        task.last_run_error = disallowed_reason
        log_user_action(
            action=f"{task.action.upper()}_SKIPPED",
            target=task.container_name,
            user="Scheduled Task",
            source="Scheduled Task",
            details=f"Task ID: {task.task_id}, Cycle: {task.cycle}, Error: {disallowed_reason}"
        )
        task.update_after_execution()
        _persist_executed_task(task)
        return False

    # BEFORE the action: a DDC restart mid-action acted a second time. A begun
    # run is not retried - see test_a_restart_does_not_run_a_task_twice.py
    task.last_run_ts = time.time()
    _persist_executed_task(task)

    try:
        # Stop/restart get at least the container's StopTimeout + margin and are
        # never sent a second time after a timeout (the first may still be running,
        # R5-1). Idempotent actions (start) are retried once with a longer timeout.
        action_timeout = await _get_action_timeout(task, timeout)
        if task.action in NON_REPEATABLE_ACTIONS:
            attempt_timeouts = [action_timeout]
        else:
            attempt_timeouts = [action_timeout, action_timeout * 1.5]
        try:
            for retry_count, current_timeout in enumerate(attempt_timeouts):
                try:
                    if retry_count > 0:
                        logger.warning(f"Retrying task {task.task_id} with increased timeout {current_timeout}s")

                    result = await asyncio.wait_for(
                        docker_action_service_first(task.container_name, task.action, timeout=current_timeout),
                        timeout=current_timeout
                    )

                    # If successful, no need to retry
                    break
                except asyncio.TimeoutError:
                    if retry_count + 1 < len(attempt_timeouts):
                        logger.warning(f"Task {task.task_id} timed out after {current_timeout}s, retrying with increased timeout")
                        continue
                    raise

        except asyncio.TimeoutError:
            if task.action in NON_REPEATABLE_ACTIONS:
                error_msg = (f"Docker {task.action} timed out after {attempt_timeouts[-1]:g} seconds; "
                             f"it may still be in progress and was not sent again")
            else:
                error_msg = f"Docker action timed out after {attempt_timeouts[-1]:g} seconds"
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
            _persist_executed_task(task)
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
            _persist_executed_task(task)
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
            _persist_executed_task(task)
            return False
    except (ImportError, AttributeError, RuntimeError) as e:
        # Service dependency errors (docker service unavailable, action execution failures)
        execution_time = time.time() - execution_start
        error_msg = f"Service error executing task {task.task_id}: {e}"
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
        _persist_executed_task(task)
        return False
    except (ValueError, TypeError, KeyError) as e:
        # Data errors (invalid task parameters, type mismatches, missing attributes)
        execution_time = time.time() - execution_start
        error_msg = f"Data error executing task {task.task_id}: {e}"
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
        _persist_executed_task(task)
        return False
    except asyncio.CancelledError:
        # The scheduler is going down; this is not the task's failure.
        raise
    except BaseException as e:
        # Deliberately not a type list, and it belongs here rather than in a
        # wider tuple above: the one error a scheduled container action really
        # fails with is a DDC exception, and DDCBaseException descends from
        # Exception and from nothing the four handlers above name. The chain is
        # execute_task -> docker_action_service_first -> execute_docker_action
        # -> get_docker_client_async -> raise DockerConnectionError, and not
        # one link catches it.
        #
        # It escaped all the way to the scheduler service's broad handler,
        # which logs it - C6 saw to that. What it did NOT do was write anything
        # on the TASK, so the panel kept showing the previous run, quite
        # possibly a success, while the nightly restart was not happening. The
        # log had it; the operator did not (review E3).
        execution_time = time.time() - execution_start
        error_msg = f"Error executing task {task.task_id}: {e}"
        logger.error(error_msg, exc_info=True)

        task.last_run_success = False
        task.last_run_error = str(e)

        log_user_action(
            action=f"{task.action.upper()}_ERROR",
            target=task.container_name,
            user="Scheduled Task",
            source="Scheduled Task",
            details=f"Task ID: {task.task_id}, Cycle: {task.cycle}, Duration: {execution_time:.2f}s, Error: {str(e)}"
        )

        # Moved on to its next run like every other failure here. A connection
        # error is not more retryable than "Docker action failed", and that one
        # has never been retried on the next cycle either.
        task.update_after_execution()
        _persist_executed_task(task)
        return False

# --- Validation & Parsing Functions (Maintain and adjust if needed) ---

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
        current_year = datetime.now(timezone.utc).year
        datetime(current_year, month, day, hour, minute)
    except ValueError as e:
        if month == 2 and day == 29:
            return False, "February 29 is only valid in leap years. Use day 28 for yearly tasks."
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
