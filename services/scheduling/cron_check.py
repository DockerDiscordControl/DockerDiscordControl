# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Is this cron expression one croniter can read?

Its own module, and a tiny one: the web process asks this on every task it
saves, and schedule_helpers pulls in discord and docker to answer it.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger('ddc.scheduler')


def cron_is_valid(expression: Optional[str]) -> bool:
    """Whether croniter can read this expression.

    Checked before a task is stored: nothing else did, so "*/5 * * *" (four
    fields) or "0 25 * * *" was written to tasks.json and the panel reported
    it as switched off "because the time given is in the past" - about an
    expression that carries no time at all.
    """
    if not expression or not str(expression).strip():
        return False
    try:
        from croniter import croniter

        return bool(croniter.is_valid(str(expression).strip()))
    except ImportError:
        logger.warning("Cron validation needs croniter; the expression is taken as given")
        return True
    except (ValueError, TypeError, AttributeError):
        return False
