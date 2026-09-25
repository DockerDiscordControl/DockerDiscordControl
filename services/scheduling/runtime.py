# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #

"""Shared runtime helpers for the scheduler service.

This module centralises the mutable state that used to live as module-level
globals in :mod:`services.scheduling.scheduler`.  By keeping the caches and
filesystem bookkeeping in one place we make it easier to reason about when the
tasks file needs to be reloaded, ensure tests can run against an isolated
configuration directory and avoid surprise side effects during imports.
"""

from __future__ import annotations

import functools
import threading
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import pytz

from utils.logging_utils import get_module_logger

logger = get_module_logger("scheduler.runtime")


@dataclass(slots=True)
class _SchedulerRuntimeState:
    """Container for scheduler caches and file tracking metadata."""

    tasks_cache: Dict[str, object] = field(default_factory=dict)
    container_cache: Dict[str, List[object]] = field(default_factory=dict)
    container_cache_timestamp: float = 0.0
    last_modified_time: float = 0.0
    last_file_size: int = 0
    timezone_cache: Dict[str, object] = field(default_factory=dict)
    # Run state of system tasks (not stored in tasks.json), keyed by task id
    system_task_state: Dict[str, Dict[str, object]] = field(default_factory=dict)


class SchedulerRuntime:
    """Mutable runtime state shared across scheduler helpers."""

    def __init__(self) -> None:
        base_dir = os.environ.get("DDC_SCHEDULER_CONFIG_DIR")
        if base_dir:
            self._config_dir = Path(base_dir)
        else:
            # Fallback via utils/config_paths.py (DDC_CONFIG_DIR); the dedicated
            # DDC_SCHEDULER_CONFIG_DIR above keeps priority. Derived from
            # __file__ before: tasks.json ignored DDC_CONFIG_DIR.
            from utils.config_paths import get_config_dir
            self._config_dir = get_config_dir()

        self._tasks_file = self._config_dir / "tasks.json"
        self._state = _SchedulerRuntimeState()

    # ------------------------------------------------------------------
    # Path helpers
    # ------------------------------------------------------------------
    @property
    def config_dir(self) -> Path:
        return self._config_dir

    @property
    def tasks_file_path(self) -> Path:
        return self._tasks_file

    def ensure_layout(self) -> None:
        """Ensure the scheduler configuration directory exists."""

        self._tasks_file.parent.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Cache helpers
    # ------------------------------------------------------------------
    @property
    def tasks_cache(self) -> Dict[str, object]:
        return self._state.tasks_cache

    def replace_tasks_cache(self, mapping: Dict[str, object]) -> None:
        self._state.tasks_cache = dict(mapping)

    def clear_tasks_cache(self) -> None:
        self._state.tasks_cache.clear()

    def store_task(self, task_id: str, task: object) -> None:
        self._state.tasks_cache[task_id] = task

    @property
    def container_tasks_cache(self) -> Dict[str, List[object]]:
        return self._state.container_cache

    @property
    def container_cache_timestamp(self) -> float:
        return self._state.container_cache_timestamp

    def update_container_cache(
        self, container_name: str, tasks: List[object], *, timestamp: Optional[float] = None
    ) -> None:
        self._state.container_cache[container_name] = tasks
        self._state.container_cache_timestamp = timestamp or time.time()

    def clear_container_cache(self) -> None:
        self._state.container_cache.clear()
        self._state.container_cache_timestamp = 0.0

    def invalidate_caches(self) -> None:
        self.clear_tasks_cache()
        self.clear_container_cache()

    # ------------------------------------------------------------------
    # File tracking helpers
    # ------------------------------------------------------------------
    def mark_tasks_file_missing(self) -> None:
        self._state.last_modified_time = 0.0
        self._state.last_file_size = 0

    def update_tracked_file_state(self, *, modified_time: float, size: int) -> None:
        self._state.last_modified_time = modified_time
        self._state.last_file_size = size

    def record_current_file_state(self) -> None:
        try:
            stat = self._tasks_file.stat()
        except FileNotFoundError:
            self.mark_tasks_file_missing()
        else:
            self.update_tracked_file_state(modified_time=stat.st_mtime, size=stat.st_size)

    def is_tasks_file_modified(self) -> bool:
        """Return ``True`` when the tasks file changed since the last check."""

        path = self._tasks_file
        if not path.exists():
            if self._state.last_modified_time != 0.0 or self._state.last_file_size != 0:
                logger.debug("Tasks file %s disappeared; clearing tracked state", path)
                self.mark_tasks_file_missing()
                return True
            return False

        stat = path.stat()
        size_changed = stat.st_size != self._state.last_file_size
        time_changed = stat.st_mtime > self._state.last_modified_time

        if size_changed or time_changed:
            self.update_tracked_file_state(modified_time=stat.st_mtime, size=stat.st_size)
            return True
        return False

    # ------------------------------------------------------------------
    # Timezone helpers
    # ------------------------------------------------------------------
    def get_timezone(self, timezone_str: str):
        cache = self._state.timezone_cache
        if timezone_str not in cache:
            try:
                cache[timezone_str] = pytz.timezone(timezone_str)
            except (IOError, OSError, PermissionError, RuntimeError,
                    pytz.exceptions.UnknownTimeZoneError) as e:
                logger.error(
                    "Error loading timezone '%s': %s. Falling back to UTC.", timezone_str, e,
                    exc_info=True
                )
                cache[timezone_str] = pytz.UTC
        return cache[timezone_str]

    def clear_timezone_cache(self) -> None:
        self._state.timezone_cache.clear()

    # ------------------------------------------------------------------
    # System task state
    # ------------------------------------------------------------------
    def get_system_task_state(self, task_id: str) -> Dict[str, object]:
        """Return the remembered run state of a system task (empty if none)."""
        return dict(self._state.system_task_state.get(task_id, {}))

    def store_system_task_state(self, task_id: str, state: Dict[str, object]) -> None:
        self._state.system_task_state[task_id] = dict(state)


TASKS_LOCK = threading.RLock()  # also imported by scheduler.py under its old name
_FILE_LOCK_DEPTH = 0  # flock is per fd: only the outermost call may open it


def with_tasks_lock(func):
    """Hold the tasks.json lock - in this process AND across processes.

    A lock held inside one writer serialises nothing against another, and an
    atomic write makes the swap atomic, not the read-modify-write: both read,
    both write, and the second replaces a file that never saw the first one's
    change (a deleted task comes back).
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        global _FILE_LOCK_DEPTH
        with TASKS_LOCK:
            if _FILE_LOCK_DEPTH:
                return func(*args, **kwargs)
            from utils.atomic_io import cross_process_lock
            with cross_process_lock(get_scheduler_runtime().tasks_file_path):
                _FILE_LOCK_DEPTH += 1
                try:
                    return func(*args, **kwargs)
                finally:
                    _FILE_LOCK_DEPTH -= 1
    return wrapper


_runtime: Optional[SchedulerRuntime] = None


def get_scheduler_runtime() -> SchedulerRuntime:
    global _runtime
    if _runtime is None:
        _runtime = SchedulerRuntime()
    return _runtime


def reset_scheduler_runtime() -> None:
    global _runtime
    _runtime = None

