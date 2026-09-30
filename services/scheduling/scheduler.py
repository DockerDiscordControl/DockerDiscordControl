# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #

import asyncio
import copy
import os
import threading
from pathlib import Path
from typing import Dict, Any, List, Optional
from functools import lru_cache, wraps  # Import for caching

# Use central import utilities
from utils.import_utils import import_ujson, import_uvloop, import_croniter, log_performance_status
from utils.time_utils import get_datetime_imports, get_current_time, get_utc_timestamp, timestamp_to_datetime, datetime_to_timestamp
from utils.logging_utils import get_module_logger
from services.config.config_service import load_config
from services.scheduling.runtime import get_scheduler_runtime
# The write-back rules live next door; _persist_async keeps the write off the
# bot's event loop, _persist_executed_task is the blocking twin for sync callers.
from services.scheduling.task_writeback import (
    persist_executed_task as _persist_executed_task,
    persist_executed_task_async as _persist_async,
    store_system_task_state as _store_system_task_state,
)
# SERVICE FIRST: Use new Docker Action Service
from services.docker_service.docker_action_service import docker_action_service_first
from services.infrastructure.action_logger import log_user_action, user_action_logger

# Central datetime imports
datetime, timedelta, timezone, time = get_datetime_imports()
# Import time class from datetime module as datetime_time to avoid conflict
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
# The cycles, the task and its timing helpers live in scheduled_task.py, the
# input parsing in task_input.py since 2026-09-28; every name stays importable
# from here.
from services.scheduling.scheduled_task import (  # noqa: E402,F401
    CYCLE_CRON, CYCLE_CUSTOM, CYCLE_DAILY, CYCLE_MONTHLY, CYCLE_NEXT_MONTH, CYCLE_NEXT_WEEK,
    CYCLE_ONCE, CYCLE_WEEKLY, CYCLE_YEARLY, DAYS_OF_WEEK, DONATION_TASK_ID,
    NON_REPEATABLE_ACTIONS, STOP_TIMEOUT_MARGIN_SECONDS, SYSTEM_ACTIONS, SYSTEM_TASK_PREFIX,
    VALID_ACTIONS, VALID_CYCLES, WEB_UI_CREATOR, ScheduledTask, _get_timezone, _localize,
    normalize_weekday)
from services.scheduling.task_input import (  # noqa: E402,F401
    _validate_monthly_cycle, _validate_once_cycle, _validate_time_parameters,
    _validate_weekly_cycle, _validate_yearly_cycle, parse_month_string, parse_time_string,
    parse_weekday_string, validate_new_task_input)

# One lock for the read-modify-write cycles on tasks.json: reentrant in this
# process (add/update/delete call load_tasks, which may save on its own) AND
# taken across writers, because another thread - or an operator's editor -
# can be in the middle of the same cycle.
from services.scheduling.runtime import (  # noqa: E402
    TASKS_LOCK as _TASKS_LOCK, with_tasks_lock as _with_tasks_lock)

# Scheduler file path
TASKS_FILE_PATH = _runtime.tasks_file_path
MIN_TASK_INTERVAL_SECONDS = 10 * 60  # 10 minutes

def _is_tasks_file_modified() -> bool:
    """Check if the tasks file has been modified since last loaded."""

    try:
        return _runtime.is_tasks_file_modified()
    except (IOError, OSError) as exc:  # pragma: no cover - defensive guard
        logger.warning("Error checking file modification for %s: %s", TASKS_FILE_PATH, exc)
        return True

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
            #     the mode of tasks.json, and every save re-stamped it.
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


# Entries of tasks.json that ScheduledTask.from_dict could not build, as they
# stand in the file. They are not scheduled, but every save writes them back:
# skipped and forgotten, the next save of anything deleted them for good, with
# no backup (stage 4 review before v3.1.0, section 26 - the harm review E5
# forbade for tasks that fail is_valid()).
_unreadable_entries: List[Any] = []


@_with_tasks_lock
def load_tasks() -> List[ScheduledTask]:
    """Load all scheduled tasks from storage"""
    global _last_load_failed, _unreadable_entries
    # Maintain task persistence across restarts
    tasks = []

    # Always ensure task file exists
    if not TASKS_FILE_PATH.exists():
        _unreadable_entries = []  # nothing on disk any more to keep
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
        # Created: read it like any other file below. Returning here kept a
        # failed-read flag the operator had lifted by removing the file, and left
        # out the cache and the system tasks (stage 4 review before v3.1.0, 26)

    # eXecute task loading with error handling
    try:
        # strip(): a file holding only a newline ("echo > tasks.json") counted as
        # a failed read and refused every save (stage 4 review before v3.1.0, 26)
        data = json.loads(TASKS_FILE_PATH.read_text(encoding="utf-8").strip() or "[]")
        if not isinstance(data, list):
            # An object's keys would each fail below, and the next save would
            # write a file holding only the new task.
            raise ValueError(f"tasks.json holds a {type(data).__name__}, not a list")

        # Deserialize each task from stored data
        unreadable = []
        for task_data in data:
            try:
                task = ScheduledTask.from_dict(task_data)
                tasks.append(task)
                logger.debug(f"Loaded task: {task.task_id}")
            except (ValueError, TypeError, KeyError, AttributeError) as e:
                # Data errors (invalid task data structure, missing fields, type mismatches)
                logger.error(f"Task entry in {TASKS_FILE_PATH} cannot be read ({e}) - it is kept "
                             f"in the file but not scheduled: {str(task_data)[:200]}")
                unreadable.append(task_data)
        _unreadable_entries = unreadable

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
    tasks_data.extend(_unreadable_entries)  # kept as they stand - see _unreadable_entries

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

# How far ahead the collision check compares runs: a year and a bit, so a
# yearly task meets every daily one once.
COLLISION_HORIZON_SECONDS = 400 * 24 * 3600


def _first_clash(runs_a: List[float], runs_b: List[float]) -> Optional[tuple]:
    """The first pair of runs (both lists sorted) less than 10 minutes apart."""
    i = j = 0
    while i < len(runs_a) and j < len(runs_b):
        if abs(runs_a[i] - runs_b[j]) < MIN_TASK_INTERVAL_SECONDS:
            return runs_a[i], runs_b[j]
        if runs_a[i] < runs_b[j]:
            i += 1
        else:
            j += 1
    return None


def check_task_time_collision(container_name: str, new_task_next_run_ts: float,
                                existing_tasks_for_container: Optional[List[ScheduledTask]] = None,
                                task_id_to_ignore: Optional[str] = None,
                                new_task: Optional[ScheduledTask] = None) -> bool:
    """
    Checks if a new or updated task conflicts with existing tasks for the same container
    within a 10-minute window.

    Paused tasks never run, so they collide with nothing; and with ``new_task``
    the later runs of recurring tasks are compared too, not only the next ones
    (operator, 2026-09-29; stage 4 review, section 26).
    """
    if new_task is not None and not new_task.is_active:
        return False
    if existing_tasks_for_container is None:
        existing_tasks_for_container = get_tasks_for_container(container_name)

    horizon = time.time() + COLLISION_HORIZON_SECONDS
    if new_task is not None:
        new_runs = new_task.runs_until(horizon)
    else:
        new_runs = [new_task_next_run_ts] if new_task_next_run_ts is not None else []
    for existing_task in existing_tasks_for_container:
        if task_id_to_ignore and existing_task.task_id == task_id_to_ignore:
            continue # Ignore the task being updated
        if not existing_task.is_active:
            continue  # paused: it never runs

        clash = _first_clash(new_runs, existing_task.runs_until(horizon))
        if clash:
            logger.warning(f"Task time collision for container '{container_name}'. New at {clash[0]} vs existing {existing_task.task_id} at {clash[1]}")
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
        if check_task_time_collision(task.container_name, task.next_run_ts, existing_tasks_for_container=existing_tasks_for_same_container,
                                     new_task=task):
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
                                           existing_tasks_for_container=existing_tasks_for_same_container,
                                           new_task=task_to_update):
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

def _format_task_time(task: ScheduledTask, timestamp: Optional[float]) -> str:
    """Format a timestamp in the task's timezone for log and error messages."""
    try:
        return datetime.fromtimestamp(timestamp, _get_timezone(task.timezone_str)).strftime('%Y-%m-%d %H:%M %Z')
    except (ValueError, TypeError, AttributeError, OSError):
        return str(timestamp)

def reschedule_missed_task(task: ScheduledTask, interrupted: bool = False) -> bool:
    """Handle a task whose scheduled time passed longer ago than the grace period.

    Missed runs are not executed retroactively, and BOTH kinds are marked
    not-successful with the reason (last_run_ts stays put - no run happened):
    the last REAL result otherwise kept a green badge on a week-dead task.

    ``interrupted``: the run was BEGUN (last_run_ts written) and DDC was
    stopped before it finished. It is not repeated either - but it must move
    on: the scheduler's "already begun" guard skipped it with a bare
    ``continue`` every cycle, so a daily task never ran again (stage 4 review
    before v3.1.0, section 49).
    """
    missed_at = _format_task_time(task, task.next_run_ts)
    task.last_run_success = False
    task.last_run_error = (
        f"Begun at {missed_at}, DDC was stopped before it finished; not repeated" if interrupted
        else f"Missed scheduled time {missed_at} (scheduler not running); not executed")
    if task.cycle == CYCLE_ONCE:
        task.is_active = False
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
    if _last_load_failed:
        # An empty list from a failed read: writing the marker now spent the
        # pass, and the long-dead tasks came back once the file was readable
        # (stage 4 review before v3.1.0, 26)
        logger.warning(f"Could not read {TASKS_FILE_PATH}; the one-time check for long-dead "
                       f"tasks runs again at the next start")
        return 0
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
            # Rescheduled, not run - see the spec test of the same name.
            task.last_run_success = False
            task.last_run_error = "Skipped: donations are switched off"
            task._calculate_next_donation_run()
            await _persist_async(task)
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
            await _persist_async(task)
            return result

        except Exception as e:  # noqa: BLE001 - see below
            # Any error, not three listed ones: an OSError from the mech state (a
            # full disk) left the task untouched and due, and it was tried again
            # every cycle for ever (stage 4 review before v3.1.0, section 26).
            # CancelledError is a BaseException and still passes.
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
            await _persist_async(task)
            return False

    if task.target_is_group:
        # Written down BEFORE the group is touched, like the single container
        # below: returning first, a DDC restart during a group action ran the
        # whole group action again (stage 4 review before v3.1.0, section 26).
        task.last_run_ts = time.time()
        await _persist_async(task)
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
        await _persist_async(task)
        return False

    # BEFORE the action: a DDC restart mid-action acted a second time. A begun
    # run is not retried - see test_a_restart_does_not_run_a_task_twice.py
    task.last_run_ts = time.time()
    await _persist_async(task)

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
            await _persist_async(task)
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
            await _persist_async(task)
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
            await _persist_async(task)
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
        await _persist_async(task)
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
        await _persist_async(task)
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
        await _persist_async(task)
        return False
