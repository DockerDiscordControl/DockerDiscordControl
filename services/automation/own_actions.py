# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""What DDC itself just did to a container - so the watchdog keeps quiet.

The container watchdog must not report a stop DDC carried out. It used to
read that from the cog's ``pending_actions``, which only the single-container
button writes and which is emptied the moment the Docker call returns - a
second or two later, while the status loop polls every 30 seconds or more.
"Stop All", the stack restart, the scheduler and the auto-action system's own
actions never appeared there at all, so a rule that stops a container could
set off a second rule that restarts it.

Both ways into Docker record here instead: DockerActionService (buttons, bulk
actions, scheduler, stack restart) and docker_action (the auto-action
system). An entry lives for window_seconds() - long enough for the watchdog to
see the new state through the status cache, short enough that a container
stopped by hand later is still watched.

Test: tests/spec/test_a_stop_ddc_did_itself_is_not_an_alarm.py
"""

import threading
import time
from typing import Dict, Optional, Set

# A stop or restart DDC ordered is not an alarm for at least this long.
WINDOW_SECONDS = 300.0

# The status cache keeps an answer for 2.5 poll intervals (cogs/background_loops.py,
# status_update_loop: cache_duration * 2.5), so the watchdog may see a new state up
# to that plus one interval late.
_CACHE_INTERVALS = 2.5


def window_seconds(poll_seconds: Optional[float] = None) -> float:
    """How long a note of DDC's own stop is kept: longer than the watchdog can lag.

    A FIXED 300 s WAS SHORTER THAN THE LAG. Measured live on 2026-09-26 with
    DDC_DOCKER_CACHE_DURATION=120 (a poll every 2 min, answers cached for 5):
    a stop by hand was reported 300 s after it happened, a pause 359 s after.
    A stop DDC ordered could therefore outlive its note and be reported as an
    alarm - and a restart rule would undo it. Operator decision the same day:
    tie the window to the poll interval. One minute of margin on top.
    """
    if poll_seconds is None:
        from utils.settings import get_setting

        poll_seconds = get_setting("DDC_DOCKER_CACHE_DURATION", 30)
    return max(WINDOW_SECONDS, poll_seconds * (_CACHE_INTERVALS + 1) + 60)

# Only these change a container's running state; a start needs no silence.
_WATCHED = ("stop", "restart")

_recent: Dict[str, float] = {}
_lock = threading.Lock()


def note_own_action(container: str, action: str, now: Optional[float] = None) -> None:
    """Remember that DDC stopped or restarted ``container`` just now."""
    if not container or (action or "").lower() not in _WATCHED:
        return
    with _lock:
        # monotonic: the status loop compares these with time.monotonic(), and a
        # wall-clock correction must not make a note look hours old
        _recent[container] = time.monotonic() if now is None else now


def expected_stops(now: Optional[float] = None, poll_seconds: Optional[float] = None) -> Set[str]:
    """The containers whose stop DDC ordered recently; older entries are dropped."""
    moment = time.monotonic() if now is None else now
    window = window_seconds(poll_seconds)
    with _lock:
        for name in [n for n, when in _recent.items() if moment - when > window]:
            del _recent[name]
        return set(_recent)


def forget(container: str) -> None:
    """Drop the note once the poll has seen the state DDC asked for - so a
    later stop by hand within the same window is watched again."""
    with _lock:
        _recent.pop(container, None)


def reset() -> None:
    """Forget everything - for tests."""
    with _lock:
        _recent.clear()
