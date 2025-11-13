"""Runtime helpers for the progress service.

This module centralises the shared runtime state that the progress service
needs (paths, configuration, timezone and synchronisation primitives).  By
collecting these pieces in one place we avoid re-import side effects and give
other components a clean way to interrogate or refresh the runtime without
reaching into module globals.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from threading import RLock
from typing import Dict, Optional
from zoneinfo import ZoneInfo

from services.mech.progress_paths import ProgressPaths, clear_progress_paths_cache, get_progress_paths

logger = logging.getLogger("ddc.progress.runtime")


@dataclass
class ProgressRuntime:
    """Container for shared progress service runtime state."""

    paths: ProgressPaths = field(default_factory=get_progress_paths)
    lock: RLock = field(default_factory=RLock)
    _default_config: Optional[Dict[str, object]] = field(default=None, init=False, repr=False)
    _config_cache: Optional[Dict[str, object]] = field(default=None, init=False, repr=False)
    _timezone: Optional[ZoneInfo] = field(default=None, init=False, repr=False)

    def configure_defaults(self, default_config: Dict[str, object]) -> None:
        """Register the default configuration used to seed new installs."""

        if not isinstance(default_config, dict):  # Defensive guard for callers.
            raise TypeError("default_config must be a dictionary")

        if self._default_config != default_config:
            logger.debug("Updating progress runtime default configuration")
            self._default_config = default_config
            # If defaults change we want subsequent loads to re-read the file.
            self.invalidate_cache()
        self.ensure_layout()

    # ------------------------------------------------------------------
    # Filesystem helpers
    # ------------------------------------------------------------------
    def ensure_layout(self) -> None:
        """Ensure the backing directory structure and config file exist."""

        # ``get_progress_paths`` already creates the base directories, event log
        # and sequence file for us.  We only need to create the config file when
        # missing, honouring the registered defaults if we have them.
        paths = self.paths
        if not paths.config_file.exists():
            if self._default_config is None:
                logger.debug("Creating empty progress config at %s", paths.config_file)
                paths.config_file.write_text("{}\n", encoding="utf-8")
            else:
                logger.debug("Seeding progress config with defaults at %s", paths.config_file)
                paths.config_file.write_text(json.dumps(self._default_config, indent=2), encoding="utf-8")
            self.invalidate_cache()

    def reset_paths(self) -> None:
        """Drop cached paths so tests can simulate different layouts."""

        clear_progress_paths_cache()
        self.paths = get_progress_paths()
        self.invalidate_cache()

    # ------------------------------------------------------------------
    # Configuration accessors
    # ------------------------------------------------------------------
    def invalidate_cache(self) -> None:
        """Clear cached config/timezone information."""

        self._config_cache = None
        self._timezone = None

    def load_config(self, *, refresh: bool = False, default_config: Optional[Dict[str, object]] = None) -> Dict[str, object]:
        """Load the persisted configuration, optionally forcing a refresh."""

        if default_config is not None:
            self.configure_defaults(default_config)
        if refresh:
            self.invalidate_cache()

        if self._config_cache is None:
            self.ensure_layout()
            try:
                with self.paths.config_file.open("r", encoding="utf-8") as fh:
                    self._config_cache = json.load(fh) or {}
            except FileNotFoundError:
                logger.warning("Progress config file disappeared; recreating")
                self.ensure_layout()
                with self.paths.config_file.open("r", encoding="utf-8") as fh:
                    self._config_cache = json.load(fh) or {}
            except json.JSONDecodeError as exc:
                logger.error("Invalid JSON in progress config (%s); resetting to defaults", exc)
                if self._default_config is None:
                    self._config_cache = {}
                    self.paths.config_file.write_text("{}\n", encoding="utf-8")
                else:
                    self._config_cache = dict(self._default_config)
                    self.paths.config_file.write_text(
                        json.dumps(self._default_config, indent=2), encoding="utf-8"
                    )
        return self._config_cache

    def timezone(self, *, refresh: bool = False, default_tz: str = "Europe/Zurich") -> ZoneInfo:
        """Return the configured timezone, defaulting to Europe/Zurich."""

        if refresh:
            self._timezone = None

        if self._timezone is None:
            config = self.load_config()
            tz_name = config.get("timezone", default_tz)
            try:
                self._timezone = ZoneInfo(str(tz_name))
            except (AttributeError, IOError, KeyError, OSError, PermissionError, RuntimeError, TypeError):
                logger.warning("Unknown timezone '%s'; falling back to %s", tz_name, default_tz)
                self._timezone = ZoneInfo(default_tz)
        return self._timezone


_runtime: Optional[ProgressRuntime] = None


def get_progress_runtime() -> ProgressRuntime:
    """Return the singleton :class:`ProgressRuntime` instance."""

    global _runtime
    if _runtime is None:
        _runtime = ProgressRuntime()
    return _runtime


def reset_progress_runtime() -> None:
    """Reset the cached runtime (primarily for tests)."""

    global _runtime
    _runtime = None
