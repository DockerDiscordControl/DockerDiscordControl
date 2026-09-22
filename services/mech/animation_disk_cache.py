# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Keeping cached_animations/ inside its limit, least-RECENTLY-used first.

Its own module so the rule can be read and tested on its own - the cache
service is large enough already.

Test: tests/spec/test_the_animation_cache_stays_inside_its_limit.py
"""

import logging
import os
from pathlib import Path

logger = logging.getLogger("ddc.animation_disk_cache")


def note_cache_hit(path) -> None:
    """Mark a cached file as used.

    Eviction sorts by modification time, which a read never changes, so the
    variant served on every refresh was the oldest file in the directory and
    the first to be deleted - only to be re-encoded on the next request.
    """
    try:
        os.utime(path, None)
    except OSError as exc:
        logger.debug("Could not mark %s as used: %s", path, exc)


def enforce_disk_cache_limit(cache_dir: Path, max_mb: int = 200) -> int:
    """Evict speed-adjusted ``.webp`` files, least recently used first, until
    their total size is inside *max_mb*. Base ``.cache`` files (the
    pre-generated 100%-speed animations) are kept. Returns how many went.
    """
    max_bytes = max(0, int(max_mb)) * 1024 * 1024
    if max_bytes <= 0:
        return 0

    try:
        entries = []
        total = 0
        for path in Path(cache_dir).glob("*.webp"):
            try:
                stat = path.stat()
            except (FileNotFoundError, PermissionError):
                continue
            entries.append((stat.st_mtime, stat.st_size, path))
            total += stat.st_size

        if total <= max_bytes:
            return 0

        entries.sort(key=lambda entry: entry[0])  # least recently used first
        removed = 0
        for _used_at, size, path in entries:
            if total <= max_bytes:
                break
            try:
                path.unlink()
                total -= size
                removed += 1
            except (FileNotFoundError, PermissionError, OSError) as exc:
                logger.debug("Skipping eviction of %s: %s", path.name, exc)
        if removed:
            logger.info("Animation disk cache trimmed: removed %d webp files (limit=%d MB)",
                        removed, max_mb)
        return removed
    except OSError as exc:
        logger.warning("Disk cache eviction failed: %s", exc)
        return 0
