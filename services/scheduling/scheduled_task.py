# -*- coding: utf-8 -*-
"""A scheduled task, the cycles it can have and the helpers its timing needs.

Moved out of services/scheduling/scheduler.py on 2026-09-28 - that file stood at
2,243 lines on the ceiling list (tests/spec/test_no_file_or_class_grows_past_its_
ceiling.py). The code is unchanged. scheduler.py imports every name back, so
`from services.scheduling.scheduler import ScheduledTask, CYCLE_DAILY` keeps
working; this module does not import scheduler.py.
"""

import calendar
import logging
import uuid
from datetime import time as datetime_time
from typing import Any, Dict, Optional, Union

import pytz

from services.config.config_service import load_config
from services.scheduling.runtime import get_scheduler_runtime
from utils.logging_utils import get_module_logger
from utils.time_utils import get_datetime_imports

datetime, timedelta, timezone, time = get_datetime_imports()

# The scheduler's logger: the moved lines keep logging as they did
logger = get_module_logger('scheduler')
_runtime = get_scheduler_runtime()

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


def _get_timezone(timezone_str: str):
    """Get and cache timezone object to avoid repeated creation costs."""

    return _runtime.get_timezone(timezone_str)


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
        'target_is_group', 'options'
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
        self.options = dict((schedule_details or {}).get('options') or {})  # services/scheduling/player_gate.py

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
        if self.options:  # "only when nobody plays", warning (services/scheduling/player_gate.py)
            details["options"] = self.options
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
            # Clamped per month, WITHOUT touching the stored day - "the 31st"
            # in a 30-day month is that month's last day. Skipping the short
            # months made a task the panel calls monthly run seven times a
            # year, said only at DEBUG. Operator decision 2026-09-23.
            day_in_month = min(day_int, calendar.monthrange(calc_year, calc_month)[1])
            localized_dt = _localize(tz, datetime(calc_year, calc_month, day_in_month,
                                                  task_hour, task_minute))
            if localized_dt > now:
                return localized_dt
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

    def runs_until(self, end_ts: float, limit: int = 400) -> list:
        """This task's runs from its next one up to ``end_ts``, at most ``limit``.

        For the collision check: a daily task at 04:00 and a weekly one at 04:05
        clash on the weekly one's day, which the NEXT runs alone do not show
        (stage 4 review before v3.1.0, section 26 pass 4 F11).
        """
        if not self.next_run_ts:
            return []
        runs = [self.next_run_ts]
        if self.cycle == CYCLE_ONCE or self.is_donation_task():
            return runs
        tz = _get_timezone(self.timezone_str)
        if self.cycle == CYCLE_CRON:
            try:
                from croniter import croniter
                runs_iter = croniter(self.cron_string, datetime.fromtimestamp(self.next_run_ts, tz))
                while len(runs) < limit:
                    following = runs_iter.get_next(datetime).timestamp()
                    if following > end_ts:
                        break
                    runs.append(following)
            except (ImportError, ValueError, TypeError, AttributeError) as e:
                logger.debug(f"Later runs of cron task {self.task_id}: {e}")
            return runs
        time_tuple = self._parse_task_time()
        if time_tuple is None:
            return runs
        hour, minute = time_tuple
        step = {
            CYCLE_DAILY: lambda now: self._calculate_daily_next_run(now, hour, minute, tz),
            CYCLE_WEEKLY: lambda now: self._calculate_weekly_next_run(tz, now, hour, minute),
            CYCLE_MONTHLY: lambda now: self._calculate_monthly_next_run(tz, now, hour, minute),
            CYCLE_YEARLY: lambda now: self._calculate_yearly_next_run(tz, now, hour, minute),
        }.get(self.cycle)
        while step is not None and len(runs) < limit:
            following_dt = step(datetime.fromtimestamp(runs[-1], tz))
            if following_dt is None:
                break
            following = following_dt.timestamp()
            if following <= runs[-1] or following > end_ts:
                break
            runs.append(following)
        return runs

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
        # Bound before the try: the fallbacks below read them.
        tz = pytz.UTC
        now = datetime.now(tz)
        try:
            # Get configured timezone - through _get_timezone, which falls back
            # to UTC like everywhere else in this class. A raw pytz.timezone()
            # raised on an unknown zone (a KeyError nothing caught), and since
            # load_tasks() builds this task, the scheduler ran nothing at all
            # (stage 4 review before v3.1.0, section 26b).
            config = load_config()
            timezone_str = config.get('timezone') or 'Europe/Berlin'
            tz = _get_timezone(timezone_str)
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
