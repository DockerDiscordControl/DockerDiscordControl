# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""One log line when the mech runs dry, one when it has power again.

Two loops look at the mech's power every 30 seconds - the decay worker
(app/utils/web_helpers.py) and the status cache refresh
(services/mech/mech_status_cache_service.py) - and each wrote "Mech is
OFFLINE" at INFO on every pass while it was empty: 5,760 lines a day that
buried the ones that mean something (2026-10-02). They share this note of
the last state, so a change is said once, by whichever loop sees it first.
"""

import threading
from typing import Optional

from utils.logging_utils import get_module_logger

logger = get_module_logger('mech_power_notice')

_lock = threading.Lock()
_last_offline: Optional[bool] = None   # None: not looked at since the start


def note_power_state(state) -> None:
    """Say the mech's power state if it changed since the last look (or on the first)."""
    global _last_offline
    offline = bool(getattr(state, 'is_offline', False))
    with _lock:
        if offline == _last_offline:
            return
        first = _last_offline is None
        _last_offline = offline
    if offline:
        logger.info("Mech has no power - offline animation active until the next donation")
    elif not first:
        logger.info(f"Mech has power again: ${getattr(state, 'power_current', 0.0):.2f}")
