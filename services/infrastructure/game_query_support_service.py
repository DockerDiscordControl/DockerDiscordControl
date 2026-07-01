# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""
Game-query SUPPORT detection store.

Tracks, per container, whether it actually answers a player-count query (A2S / Minecraft).
The verdict gates the web UI's "Spieler" checkbox: only containers proven to answer can be
enabled. State is persisted to a small JSON file (read by the separate web process), so a
FINAL verdict survives a DDC restart.

Lifecycle per container:
- unknown (absent)            never probed yet.
- probing (supported=False,   online but no port/protocol answered *yet*. We keep probing
           final=False)        while it stays online, up to PROBE_WINDOW_SECONDS (15 min).
                               The window is measured from "first probe while online" and is
                               RESET if the container goes offline (a crash/restart mid-boot
                               gets a fresh window). Probing containers are locked in the UI.
- supported (supported=True,   answered at least once -> FINAL. Never probed again (even
             final=True)        offline / after restart), never downgraded. Unlocks the UI.
- unsupported (supported=False, stayed online 15 min without answering -> FINAL. Never probed
               final=True)      again. Stays locked. (No A2S/Minecraft support.)
"""

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

from utils.logging_utils import get_module_logger

logger = get_module_logger('game_query_support_service')

# Re-probe an as-yet-unconfirmed online container at most this often.
PROBE_RETRY_SECONDS = 60.0
# How long a container may stay online-without-answering before we give up and mark it a
# FINAL "unsupported" (15 minutes - generous enough for any game server to finish booting).
PROBE_WINDOW_SECONDS = 900.0
# A gap larger than this since the last probe of a container (DDC downtime, or the container
# was offline) starts a FRESH 15-min window instead of counting the dead time.
WINDOW_GAP_RESET_SECONDS = 300.0

_SUPPORT_FILENAME = 'query_support.json'
# Fields that define the verdict (used for change detection; 'updated' is excluded so a
# still-probing container doesn't rewrite the file every cycle).
_VERDICT_FIELDS = ('supported', 'final', 'protocol', 'port', 'probing_since')


def _config_dir() -> Path:
    override = os.environ.get('DDC_CONFIG_DIR', '').strip()
    if override:
        return Path(override)
    return Path(__file__).resolve().parent.parent.parent / 'config'


def _read_verdicts_at(path: Path) -> Dict[str, Dict[str, Any]]:
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding='utf-8'))
            if isinstance(data, dict):
                return {k: v for k, v in data.items() if isinstance(v, dict)}
    except Exception as e:  # noqa: BLE001 - best-effort read
        logger.debug(f"[QUERY_SUPPORT] read failed: {e}")
    return {}


def read_support_verdicts() -> Dict[str, Dict[str, Any]]:
    """Read the verdicts file fresh from the default path (used by the web process, which
    does not run the prober). Returns {container_name: {supported, final, ...}}."""
    return _read_verdicts_at(_config_dir() / _SUPPORT_FILENAME)


def _atomic_update(mutate, path: Optional[Path] = None) -> None:
    """Read-modify-write a SINGLE key of the verdicts file without clobbering the others.

    All writers (the bot's per-key _set/note_offline AND the web process's manual re-test)
    go through this, so neither ever overwrites verdicts owned by the other.
    """
    path = path or (_config_dir() / _SUPPORT_FILENAME)
    state = _read_verdicts_at(path)
    try:
        mutate(state)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix('.tmp')
        tmp.write_text(json.dumps(state), encoding='utf-8')
        tmp.replace(path)
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[QUERY_SUPPORT] atomic update failed: {e}")


def set_testing(name: str, testing: bool = True) -> None:
    """Flag a container as currently being (manually) tested - drives the UI spinner."""
    def _m(state):
        entry = dict(state.get(name) or {})
        entry['testing'] = bool(testing)
        state[name] = entry
    _atomic_update(_m)


def record_manual_success(name: str, protocol: Optional[str] = None,
                          port: Optional[int] = None) -> None:
    """A manual re-test answered -> mark FINAL supported (unlocks the checkbox, permanent)."""
    def _m(state):
        state[name] = {'supported': True, 'final': True, 'protocol': protocol,
                       'port': port, 'probing_since': None, 'testing': False,
                       'updated': time.time()}
    _atomic_update(_m)


class GameQuerySupportService:
    """Singleton (in the bot) holding support verdicts; persists to a file for the web UI."""

    def __init__(self, path: Optional[Path] = None):
        self._path = path or (_config_dir() / _SUPPORT_FILENAME)
        self._state: Dict[str, Dict[str, Any]] = {}   # name -> verdict dict
        self._last_probe: Dict[str, float] = {}        # name -> monotonic ts (in-memory only)
        self._load_file()

    # --- verdict access ----------------------------------------------------
    def is_supported(self, name: str) -> Optional[bool]:
        entry = self._state.get(name)
        return None if entry is None else bool(entry.get('supported'))

    def is_final(self, name: str) -> bool:
        entry = self._state.get(name)
        return bool(entry and entry.get('final'))

    def get_protocol(self, name: str) -> Optional[str]:
        """The protocol that actually answered during detection (source/minecraft), or None."""
        entry = self._state.get(name)
        return entry.get('protocol') if entry else None

    def all_verdicts(self) -> Dict[str, Dict[str, Any]]:
        return dict(self._state)

    # --- probe scheduling --------------------------------------------------
    def should_probe(self, name: str, now_mono: float) -> bool:
        # A FINAL verdict (supported, or gave-up-after-15-min) is never probed again.
        if self.is_final(name):
            return False
        last = self._last_probe.get(name)
        if last is None:
            return True
        return (now_mono - last) >= PROBE_RETRY_SECONDS

    def mark_probed(self, name: str, now_mono: float) -> None:
        self._last_probe[name] = now_mono

    def record_result(self, name: str, success: bool, protocol: Optional[str] = None,
                      port: Optional[int] = None, now_wall: Optional[float] = None) -> None:
        """Record one probe outcome, advancing the container's lifecycle."""
        now_wall = now_wall if now_wall is not None else time.time()
        if success:
            self._set(name, supported=True, final=True, protocol=protocol,
                      port=port, probing_since=None)
            return
        prev = self._state.get(name) or {}
        if prev.get('final'):
            return  # already final (should not have been probed) - leave as-is
        since = prev.get('probing_since') or now_wall
        # If there was a long gap since we last touched this container (DDC downtime, or the
        # container was offline and just came back), start a FRESH window instead of counting
        # that dead time toward the 15 min - a slow-booting server must not be failed after
        # one post-restart probe.
        last = prev.get('updated')
        if last and (now_wall - last) > WINDOW_GAP_RESET_SECONDS:
            since = now_wall
        gave_up = (now_wall - since) >= PROBE_WINDOW_SECONDS
        self._set(name, supported=False, final=gave_up, protocol=None,
                  port=None, probing_since=since)

    def note_offline(self, name: str) -> None:
        """Container observed offline: reset the probe window for a not-yet-final container
        (a fresh 15-min window on next boot). FINAL verdicts are untouched (sticky)."""
        entry = self._state.get(name)
        if entry is not None and not entry.get('final'):
            del self._state[name]
            self._last_probe.pop(name, None)
            _atomic_update(lambda s: s.pop(name, None), self._path)   # per-key RMW: never clobber others

    def reload(self) -> None:
        """Re-read the on-disk verdicts (e.g. web-process manual re-test results) into memory,
        so the bot's decisions and per-key writes never revert externally-written verdicts.
        Call this before each probe pass."""
        self._load_file()

    # --- internal ----------------------------------------------------------
    def _set(self, name: str, **fields: Any) -> None:
        entry = {
            'supported': bool(fields.get('supported')),
            'final': bool(fields.get('final')),
            'protocol': fields.get('protocol'),
            'port': fields.get('port'),
            'probing_since': fields.get('probing_since'),
            'updated': time.time(),
        }
        prev = self._state.get(name)
        self._state[name] = entry
        # Persist ONLY this key via read-modify-write, so the bot never overwrites verdicts
        # owned by the web process (manual re-test) or other containers' entries.
        if prev is None or any(prev.get(f) != entry.get(f) for f in _VERDICT_FIELDS):
            _atomic_update(lambda s: s.update({name: entry}), self._path)

    def _load_file(self) -> None:
        try:
            if self._path.exists():
                data = json.loads(self._path.read_text(encoding='utf-8'))
                if isinstance(data, dict):
                    self._state = {k: v for k, v in data.items() if isinstance(v, dict)}
                    for entry in self._state.values():
                        # Migrate pre-'final' entries: a legacy confirmed-supported verdict is
                        # final (trust it); a legacy False is treated as still-probing.
                        if 'final' not in entry:
                            entry['final'] = bool(entry.get('supported'))
        except Exception as e:  # noqa: BLE001
            logger.debug(f"[QUERY_SUPPORT] load failed: {e}")


_instance: Optional[GameQuerySupportService] = None


def get_game_query_support_service() -> GameQuerySupportService:
    global _instance
    if _instance is None:
        _instance = GameQuerySupportService()
    return _instance


def reset_game_query_support_service() -> None:
    global _instance
    _instance = None
