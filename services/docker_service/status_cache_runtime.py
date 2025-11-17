# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Runtime helpers for sharing Docker status cache information.

The Discord cog keeps an in-memory snapshot of the most recent container
status information.  Historically this snapshot lived in module level
globals (`docker_status_cache` and `docker_status_cache_lock`) inside the
``cogs.docker_control`` module.  That made the data difficult to reason about
and encouraged other modules to reach into the cog directly which breaks the
``service first`` boundaries the project is aiming for.

This module provides a light-weight runtime container that owns both the
cache and the synchronisation primitive needed to access it safely from
different threads.  Consumers can depend on this module without having to
import the heavy Discord cog, and the cog itself can publish refreshed
snapshots in a single place.
"""

from __future__ import annotations

import copy
import logging
from dataclasses import dataclass, field
from threading import RLock
from typing import Any, Dict, Iterable, Optional, Tuple

logger = logging.getLogger("ddc.docker.status_cache_runtime")


@dataclass
class DockerStatusCacheRuntime:
    """Container that manages the Docker status cache snapshot."""

    _cache: Dict[str, Any] = field(default_factory=dict, repr=False)
    _lock: RLock = field(default_factory=RLock, repr=False)

    # ------------------------------------------------------------------
    # Cache publication helpers
    # ------------------------------------------------------------------
    def publish(self, cache: Dict[str, Any]) -> None:
        """Replace the stored snapshot with a deep copy of *cache*."""

        if not isinstance(cache, dict):  # Defensive check for unexpected callers.
            raise TypeError("cache must be a dictionary")

        with self._lock:
            logger.debug("Publishing docker status cache with %d entries", len(cache))
            self._cache = copy.deepcopy(cache)

    def clear(self) -> None:
        """Reset the stored snapshot to an empty cache."""

        with self._lock:
            logger.debug("Clearing docker status cache runtime snapshot")
            self._cache = {}

    # ------------------------------------------------------------------
    # Cache read helpers
    # ------------------------------------------------------------------
    def snapshot(self) -> Dict[str, Any]:
        """Return a deep copy of the stored cache."""

        with self._lock:
            return copy.deepcopy(self._cache)

    def lookup(self, docker_name: str) -> Optional[Any]:
        """Return a deep copy of the entry for *docker_name*, if present."""

        with self._lock:
            value = self._cache.get(docker_name)
        return copy.deepcopy(value)

    def items(self) -> Iterable[Tuple[str, Any]]:
        """Iterate over ``(docker_name, data)`` pairs as deep copies."""

        with self._lock:
            return tuple((name, copy.deepcopy(data)) for name, data in self._cache.items())


_runtime: Optional[DockerStatusCacheRuntime] = None


def get_docker_status_cache_runtime() -> DockerStatusCacheRuntime:
    """Return the singleton :class:`DockerStatusCacheRuntime` instance."""

    global _runtime
    if _runtime is None:
        _runtime = DockerStatusCacheRuntime()
    return _runtime


def reset_docker_status_cache_runtime() -> None:
    """Reset the cached runtime instance (useful for tests)."""

    global _runtime
    _runtime = None
