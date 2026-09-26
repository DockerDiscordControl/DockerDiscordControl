# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Deciding when a container's state is worth a message (container watchdog, Phase 4a).

Fed one snapshot of all containers per poll, ContainerWatcher returns the
changes a user wants to hear about: a running container that stopped, a
health check that turned unhealthy, a container restarting in a loop. Only
transitions count - a container that stays stopped is reported once, not on
every poll - and the first sight of a container is a baseline, not an event.
A stop DDC itself was asked for (passed in as ``expected``) is not an alarm.

Pure logic without I/O; the status loop feeds it and the automation rules
decide what happens (notify, restart). Test:
tests/spec/test_a_container_that_dies_is_reported_once.py
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, Iterable, List, Optional, Tuple

STOPPED = "stopped"
UNHEALTHY = "unhealthy"
RESTART_LOOP = "restart_loop"
KINDS = (STOPPED, UNHEALTHY, RESTART_LOOP)


@dataclass(frozen=True)
class ContainerState:
    running: bool
    health: Optional[str] = None          # State.Health.Status, None without a healthcheck
    restart_count: Optional[int] = None   # RestartCount, None when unknown


# Docker statuses in which the container's process exists: State.Running is true.
_UP = ("running", "paused", "restarting")


def running_for_the_watchdog(result) -> bool:
    """Whether a container counts as up for the watchdog.

    NOT result.is_running, which is status == "running". A paused container and
    one Docker's own restart policy is bringing back have status "paused" and
    "restarting" - and until 2026-09-26 the watchdog reported both as "stopped
    (it was running)", so a restart rule restarted a container somebody had
    paused on purpose (measured live). Operator decision the same day: paused
    counts as running here. The panel shows what it always showed.
    """
    return bool(getattr(result, "is_running", False)) or getattr(result, "status", None) in _UP


@dataclass(frozen=True)
class WatchEvent:
    container: str
    kind: str
    reason: str
    # restart_loop only: the threshold and window that produced it, so a rule
    # reacts only to loops measured by its own settings.
    threshold: Optional[int] = None
    window_minutes: Optional[int] = None


class ContainerWatcher:
    def __init__(self, restart_threshold: int = 3, restart_window_seconds: float = 600):
        self.restart_threshold = restart_threshold
        self.restart_window = restart_window_seconds
        self._last: Dict[str, ContainerState] = {}
        self._restarts: Dict[str, Deque[Tuple[float, int]]] = {}
        self._loop_alerted_at: Dict[str, float] = {}
        # Names whose last state came from before this process started (restore);
        # their first event says so.
        self._restored: set = set()

    # THE STATE SURVIVES A RESTART (operator decision 2026-09-26). Until then
    # every start began with a silent baseline, so a container that went down
    # while DDC was offline - a rebuild, a host reboot - was never reported.
    # Only running and health are kept: restart counts start afresh.
    def export(self) -> Dict[str, Dict]:
        return {name: {"running": state.running, "health": state.health}
                for name, state in self._last.items()}

    def restore(self, saved: Dict[str, Dict]) -> None:
        for name, entry in (saved or {}).items():
            if isinstance(entry, dict) and name not in self._last:
                self._last[name] = ContainerState(bool(entry.get("running")), entry.get("health"))
                self._restored.add(name)

    def observe(self, states: Dict[str, ContainerState], now: float,
                expected: Iterable[str] = ()) -> List[WatchEvent]:
        expected = set(expected)
        events: List[WatchEvent] = []
        for name, state in states.items():
            if state is None:
                continue
            before = self._last.get(name)
            # The state is remembered before any decision: the next poll compares
            # against THIS one, so a state that does not change is reported once.
            self._last[name] = state
            restored = name in self._restored
            self._restored.discard(name)
            if before is None:
                continue
            if before.running and not state.running and name not in expected:
                events.append(WatchEvent(name, STOPPED, (
                    f"Container '{name}' stopped while DDC was offline (it was running before)."
                    if restored else f"Container '{name}' stopped (it was running).")))
            # UNHEALTHY ONLY WHILE RUNNING. Docker reports a stopped (or paused)
            # container with a health check as "unhealthy"; until 2026-09-26 that
            # made every stop an unhealthy alarm - DDC's own scheduled stops too,
            # which a "restart on unhealthy" rule would have undone. The last
            # state counts as unhealthy only if it was a running one, so a
            # container that comes back up still failing is reported.
            if (state.running and state.health == "unhealthy"
                    and not (before.running and before.health == "unhealthy")):
                events.append(WatchEvent(name, UNHEALTHY, f"Container '{name}' is unhealthy (its health check fails)."))
            loop = self._restart_loop(name, before, state, now)
            if loop:
                events.append(loop)
        return events

    def _restart_loop(self, name: str, before: ContainerState, state: ContainerState,
                      now: float) -> Optional[WatchEvent]:
        if before.restart_count is None or state.restart_count is None:
            return None
        increase = state.restart_count - before.restart_count
        history = self._restarts.setdefault(name, deque())
        if increase > 0:
            history.append((now, increase))
        while history and now - history[0][0] > self.restart_window:
            history.popleft()
        in_window = sum(count for _, count in history)
        last_alert = self._loop_alerted_at.get(name)
        if in_window >= self.restart_threshold and (last_alert is None or now - last_alert > self.restart_window):
            self._loop_alerted_at[name] = now
            minutes = int(self.restart_window // 60)
            return WatchEvent(name, RESTART_LOOP,
                              f"Container '{name}' restarted {in_window} times within {minutes} min.",
                              threshold=self.restart_threshold, window_minutes=minutes)
        return None


HIGH_CPU = "high_cpu"
HIGH_MEMORY = "high_memory"
RESOURCE_KINDS = {"cpu": HIGH_CPU, "memory": HIGH_MEMORY}


class ResourceWatcher:
    """CPU or memory above a threshold for a while - once, with hysteresis (Phase 4b).

    A container is reported when its value stays at or above ``threshold_percent``
    for ``minutes``. It is then not reported again until the value has fallen
    below the threshold minus ``hysteresis_percent`` - a value hovering at the
    line would otherwise report every poll. A missing measurement (None: the
    container is stopped, or stats were not available) resets the timer.
    Test: tests/spec/test_a_container_that_runs_hot_is_reported_once.py
    """

    def __init__(self, metric: str, threshold_percent: float, minutes: int,
                 hysteresis_percent: float = 10, unit: str = "%"):
        """``unit`` is "%" or "MB" - the yardstick, not a second mode.

        A container started without --memory has no limit, so Docker reports the
        HOST's memory as the limit and a percentage of it can never be reached:
        measured on one server, 20 of 26 containers, the largest at 13 % of the
        host. Those are watched in MB instead (operator decision 2026-09-23).

        The split is made by the CALLER, which hands this watcher None for the
        containers the other one is for - and None already means "not measured"
        here. So nothing about deciding when to alert changes; only what the
        message says.
        """
        self.metric = metric
        self.kind = RESOURCE_KINDS[metric]
        self.unit = unit
        self.threshold = threshold_percent
        self.minutes = minutes
        # Never more than half the threshold: with the panel's lowest setting (10)
        # a fixed margin of 10 asked for a value below zero, and the watcher stayed
        # latched for the life of the process.
        self.hysteresis = min(hysteresis_percent, threshold_percent / 2)
        self._high_since: Dict[str, float] = {}
        self._alerted: set = set()

    def observe(self, values: Dict[str, Optional[float]], now: float) -> List[WatchEvent]:
        events: List[WatchEvent] = []
        for name, value in values.items():
            if value is None:
                self._high_since.pop(name, None)
                self._alerted.discard(name)
                continue
            if name in self._alerted:
                if value < self.threshold - self.hysteresis:
                    self._alerted.discard(name)
                    self._high_since.pop(name, None)
                continue
            # "at or above": a container pinned at exactly the threshold is what
            # the panel's highest setting (100 percent) is for, and > never saw it
            if value >= self.threshold:
                since = self._high_since.setdefault(name, now)
                if now - since >= self.minutes * 60:
                    self._alerted.add(name)
                    label = "CPU" if self.metric == "cpu" else "Memory"
                    # "90%" but "4096 MB" - a space where the unit is a word.
                    unit = self.unit if self.unit == "%" else f" {self.unit}"
                    events.append(WatchEvent(
                        name, self.kind,
                        f"{label} of '{name}' at or above {self.threshold:g}{unit} for "
                        f"{self.minutes} min (now {value:.0f}{unit}).",
                        threshold=int(self.threshold), window_minutes=self.minutes))
            else:
                self._high_since.pop(name, None)
        return events
