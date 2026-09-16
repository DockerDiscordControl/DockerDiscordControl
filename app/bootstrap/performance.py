# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Runtime performance helpers for memory-sensitive deployments.

These helpers consolidate the low-level knobs that we tune inside the
container image to keep memory pressure low.  They are deliberately kept in a
separate module so the rest of the bootstrap logic stays focused on
configuration and logging concerns.
"""

from __future__ import annotations

import gc
import logging
import os
from typing import Iterable, Tuple

DEFAULT_GC_THRESHOLDS: Tuple[int, int, int] = (700, 10, 10)


def apply_runtime_tweaks(
    logger: logging.Logger,
    *,
    gc_thresholds: Iterable[int] = DEFAULT_GC_THRESHOLDS,
) -> None:
    """Apply GC and allocator tuning for memory constrained containers.

    The tunings are intentionally conservative – they reduce how aggressively
    CPython allocates new arenas without disabling the collector completely.
    The helper is idempotent which keeps repeated imports from impacting the
    running process.
    """

    thresholds = tuple(gc_thresholds)
    if len(thresholds) != 3:
        raise ValueError("gc_thresholds must contain exactly three integers")

    current = gc.get_threshold()
    if current != thresholds:
        gc.set_threshold(*thresholds)
        logger.debug("Adjusted GC thresholds from %s to %s", current, thresholds)

    if os.getenv("DDC_DISABLE_GC_FREEZE", "false").lower() != "true" and hasattr(gc, "freeze"):
        gc.freeze()
        logger.debug("Froze GC to reduce long-term arena growth")

    # MALLOC_TRIM_THRESHOLD_ was set here. It had no effect twice over: glibc reads the value
    # when the allocator initialises, long before this runs, and the production image is Alpine
    # (musl), whose allocator ignores the variable entirely. Removed rather than left in place,
    # because a setting that looks like memory tuning but does nothing is worse than none.
