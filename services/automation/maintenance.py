# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Maintenance: the watchdog leaves a container alone for a while (operator, 2026-09-26).

WHY. The only way to work on a container without an alarm - or, with a
RESTART rule, without DDC starting it again in the middle of a repair - was to
switch the rule off, for every container at once, and to remember to switch
it back on. A pause is per container and ends by itself.

WHAT IT DOES: container-state events for a paused container are dropped
before any rule sees them - no notice, no action. The watchers go on
observing it, so when the pause ends they compare with the state at that
moment, not with one from before the maintenance: ending a pause raises no
alarm about what was done during it.

Kept in config/watchdog_maintenance.json, so a DDC restart during the
maintenance does not end it. Set from the panel and from Discord.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Dict, Optional

FILE = "watchdog_maintenance.json"
MAX_MINUTES = 7 * 24 * 60      # a week: longer is not maintenance, it is switching off
_lock = threading.Lock()


def _path() -> Path:
    from utils.config_paths import get_config_dir

    return get_config_dir() / FILE


def _read() -> Dict[str, Dict]:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(data: Dict[str, Dict]) -> None:
    from utils.atomic_io import atomic_write_text

    atomic_write_text(_path(), json.dumps(data, indent=2, sort_keys=True))


def pauses(now: Optional[float] = None) -> Dict[str, Dict]:
    """{container: {"until": epoch, "by": who}} for the pauses still running."""
    moment = time.time() if now is None else now
    with _lock:
        data = _read()
        running = {name: entry for name, entry in data.items()
                   if isinstance(entry, dict) and float(entry.get("until", 0)) > moment}
        if running != data:
            _write(running)
        return running


def is_paused(container: str, now: Optional[float] = None) -> bool:
    return container in pauses(now)


def pause(container: str, minutes: int, by: str = "", now: Optional[float] = None) -> float:
    """Pause the watchdog for one container. Returns when the pause ends."""
    minutes = int(minutes)
    if not container or not 1 <= minutes <= MAX_MINUTES:
        raise ValueError(f"a pause is 1 to {MAX_MINUTES} minutes long")
    until = (time.time() if now is None else now) + minutes * 60
    with _lock:
        data = _read()
        data[container] = {"until": until, "by": by}
        _write(data)
    return until


def resume(container: str) -> bool:
    """End a pause early. True when there was one."""
    with _lock:
        data = _read()
        if container not in data:
            return False
        del data[container]
        _write(data)
        return True
