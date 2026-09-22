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


@dataclass(frozen=True)
class WatchEvent:
    container: str
    kind: str
    reason: str


class ContainerWatcher:
    def __init__(self, restart_threshold: int = 3, restart_window_seconds: float = 600):
        self.restart_threshold = restart_threshold
        self.restart_window = restart_window_seconds
        self._last: Dict[str, ContainerState] = {}
        self._restarts: Dict[str, Deque[Tuple[float, int]]] = {}
        self._loop_alerted_at: Dict[str, float] = {}

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
            if before is None:
                continue
            if before.running and not state.running and name not in expected:
                events.append(WatchEvent(name, STOPPED, f"Container '{name}' stopped (it was running)."))
            if state.health == "unhealthy" and before.health != "unhealthy":
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
                              f"Container '{name}' restarted {in_window} times within {minutes} min.")
        return None
