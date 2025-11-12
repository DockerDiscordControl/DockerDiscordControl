"""Utilities for resolving progress service storage locations.

This module centralizes how the progress service determines where its
snapshots, event log and configuration live.  It embraces the
SERVICE-FIRST "single point of truth" guideline by funnelling every
consumer through the same resolver that honours environment overrides
and configuration service preferences.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Optional

from services.config.config_service import ConfigService, GetConfigRequest

logger = logging.getLogger("ddc.progress_paths")


@dataclass(frozen=True, slots=True)
class ProgressPaths:
    """Concrete filesystem locations used by the progress service."""

    data_dir: Path
    event_log: Path
    snapshot_dir: Path
    config_file: Path
    seq_file: Path
    member_count_file: Path

    @classmethod
    def from_base_dir(cls, base_dir: Path, *, create_missing: bool = True) -> "ProgressPaths":
        """Create a :class:`ProgressPaths` instance rooted at ``base_dir``.

        Parameters
        ----------
        base_dir:
            Directory that should contain all progress artefacts.
        create_missing:
            When ``True`` (default) the required directories and files are
            created on demand.  Existing files are left untouched.
        """

        base_dir = base_dir.expanduser()
        if create_missing:
            base_dir.mkdir(parents=True, exist_ok=True)

        snapshot_dir = base_dir / "snapshots"
        if create_missing:
            snapshot_dir.mkdir(parents=True, exist_ok=True)

        event_log = base_dir / "events.jsonl"
        if create_missing and not event_log.exists():
            event_log.touch()

        seq_file = base_dir / "last_seq.txt"
        if create_missing and not seq_file.exists():
            seq_file.write_text("0", encoding="utf-8")

        config_file = base_dir / "config.json"
        member_count_file = _resolve_member_count_path(base_dir)

        if create_missing:
            member_count_file.parent.mkdir(parents=True, exist_ok=True)

        return cls(
            data_dir=base_dir,
            event_log=event_log,
            snapshot_dir=snapshot_dir,
            config_file=config_file,
            seq_file=seq_file,
            member_count_file=member_count_file,
        )

    def snapshot_for(self, mech_id: str) -> Path:
        """Return the snapshot path for ``mech_id``."""

        return self.snapshot_dir / f"{mech_id}.json"


_paths_cache: Optional[ProgressPaths] = None
_paths_lock = Lock()


def _config_base_dir() -> Optional[Path]:
    """Attempt to fetch the progress directory from the config service."""

    try:
        service = ConfigService()
        result = service.get_config_service(GetConfigRequest())
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.debug("Failed to load configuration while resolving progress paths: %s", exc, exc_info=True)
        return None

    if not result.success or not result.config:
        return None

    progress_settings = result.config.get("progress")
    if not isinstance(progress_settings, dict):
        return None

    base_dir = progress_settings.get("data_dir")
    if not base_dir:
        return None

    return Path(base_dir)


def _resolve_base_dir() -> Path:
    """Determine the base directory honouring env and config overrides."""

    env_override = os.getenv("DDC_PROGRESS_DATA_DIR")
    if env_override:
        logger.debug("Using progress data directory from DDC_PROGRESS_DATA_DIR=%s", env_override)
        return Path(env_override)

    config_dir = _config_base_dir()
    if config_dir:
        logger.debug("Using progress data directory from configuration: %s", config_dir)
        return config_dir

    default_dir = Path("config/progress")
    logger.debug("Falling back to default progress data directory: %s", default_dir)
    return default_dir


def _resolve_member_count_path(base_dir: Path) -> Path:
    """Determine the member count file path honouring overrides."""

    env_override = os.getenv("DDC_PROGRESS_MEMBER_COUNT_PATH")
    if env_override:
        path = Path(env_override).expanduser()
        logger.debug(
            "Using member count data file from DDC_PROGRESS_MEMBER_COUNT_PATH=%s", path
        )
        return path

    default_path = base_dir / "member_count.json"
    legacy_path = base_dir.parent / "member_count.json"

    if legacy_path.exists() and not default_path.exists():
        logger.debug("Using legacy member count location at %s", legacy_path)
        return legacy_path

    return default_path


def _build_paths(create_missing: bool) -> ProgressPaths:
    base_dir = _resolve_base_dir()
    paths = ProgressPaths.from_base_dir(base_dir, create_missing=create_missing)
    return paths


def get_progress_paths(*, create_missing: bool = True) -> ProgressPaths:
    """Return cached progress paths, ensuring the layout exists when required."""

    global _paths_cache
    with _paths_lock:
        if _paths_cache is None:
            _paths_cache = _build_paths(create_missing=create_missing)
        elif create_missing:
            # Ensure existing cache still points to valid files
            _paths_cache = ProgressPaths.from_base_dir(_paths_cache.data_dir, create_missing=True)
        return _paths_cache


def clear_progress_paths_cache() -> None:
    """Reset the cached progress paths (useful for tests)."""

    global _paths_cache
    with _paths_lock:
        _paths_cache = None
