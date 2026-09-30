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
- silent      (supported=False, a server that ANSWERED once, was demoted after failed live
               final=True,      queries and then stayed silent for the 15 min - it has query
               demoted=True)    support, its game is just not running. Probed again every
                                DEMOTED_RETRY_SECONDS, so a game that comes back is seen again.
                                Found 2026-09-28: without this, a crashed Enshrouded server
                                that came back would have stayed "unreachable" for good - and
                                the info display now says so to everyone.
"""

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

from utils.logging_utils import get_module_logger
import fcntl
from contextlib import contextmanager

logger = get_module_logger('game_query_support_service')

# Re-probe an as-yet-unconfirmed online container at most this often.
PROBE_RETRY_SECONDS = 60.0
# How long a container may stay online-without-answering before we give up and mark it a
# FINAL "unsupported" (15 minutes - generous enough for any game server to finish booting).
PROBE_WINDOW_SECONDS = 900.0
# A gap larger than this since the last probe of a container (DDC downtime, or the container
# was offline) starts a FRESH 15-min window instead of counting the dead time.
WINDOW_GAP_RESET_SECONDS = 300.0

# How many consecutive failed live queries demote a FINAL positive verdict back into probing.
# A positive verdict is otherwise permanent (should_probe skips final entries), so a server that
# answered once and later stopped - query port no longer published, moved behind a firewall -
# kept costing a full query timeout on every status cycle. At a 120 s cycle three in a row is
# about six minutes, which comfortably survives a container restart.
QUERY_FAILURE_DEMOTE_THRESHOLD = 3
# A demoted server that went FINAL silent is asked again this often. Only those: a container
# that never answered (an ordinary app) stays final and costs nothing.
DEMOTED_RETRY_SECONDS = 1800.0

_SUPPORT_FILENAME = 'query_support.json'
# Fields that define the verdict (used for change detection; 'updated' is excluded so a
# still-probing container doesn't rewrite the file every cycle).
_VERDICT_FIELDS = ('supported', 'final', 'protocol', 'port', 'probing_since', 'demoted')


def _config_dir() -> Path:
    # The rule lives in utils/config_paths.py; this was a copy of it.
    from utils.config_paths import get_config_dir
    return get_config_dir()


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


@contextmanager
def _cross_process_lock(path: Path):
    """Serialise the read-modify-write ACROSS PROCESSES.

    The bot and the web process both write this file, and an atomic write alone
    does not make a read-modify-write atomic: if both read before either writes,
    the second write replaces the file with a state that never saw the first
    one's key. A manual re-test could lose its verdict to the bot's next probe,
    and the panel's checkbox stayed locked until the bot re-probed on its own
    schedule (review C29).

    flock blocks the OS thread, which under gevent means the hub - the critical
    section is one small JSON read and write, which is the right trade here.
    """
    lock_path = path.with_name(path.name + '.lock')
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def _atomic_update(mutate, path: Optional[Path] = None) -> None:
    """Read-modify-write a SINGLE key of the verdicts file without clobbering the others.

    All writers (the bot's per-key _set/note_offline AND the web process's manual re-test)
    go through this, so neither ever overwrites verdicts owned by the other. That
    promise is kept by the lock below - without it, the sentence was simply untrue.
    """
    path = path or (_config_dir() / _SUPPORT_FILENAME)
    try:
        with _cross_process_lock(path):
            state = _read_verdicts_at(path)
            mutate(state)
            path.parent.mkdir(parents=True, exist_ok=True)
            # Per process: a fixed ".tmp" name is shared by every writer, so two
            # concurrent writes could tear even a single key update (review C29).
            tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}")
            tmp.write_text(json.dumps(state), encoding='utf-8')
            tmp.replace(path)
    except Exception as e:  # noqa: BLE001
        # ERROR, not DEBUG: this file carries the verdicts AND the 'testing' flag
        # behind the panel's re-test spinner. A swallowed write leaves the spinner
        # turning for good, and the caller in main_routes.py cannot notice - its own
        # "except Exception: pass" never sees anything, because everything ends here
        # (SPEC.md Z8, review A10).
        logger.error(f"[QUERY_SUPPORT] verdicts file could not be written: {e}", exc_info=True)


def set_testing(name: str, testing: bool = True, path: Optional[Path] = None) -> None:
    """Flag a container as currently being (manually) tested - drives the UI spinner.

    ``path`` defaults to the shared location, which is what the web process
    wants. It exists because ``GameQuerySupportService`` can be pointed at
    another file, and these two helpers used to write to the default one
    regardless - so a holder of such an instance wrote to a different file
    than the one it reads back, with both writes reporting success
    (review C66).
    """
    def _m(state):
        entry = dict(state.get(name) or {})
        entry['testing'] = bool(testing)
        state[name] = entry
    _atomic_update(_m, path)


def record_manual_success(name: str, protocol: Optional[str] = None,
                          port: Optional[int] = None,
                          path: Optional[Path] = None) -> None:
    """A manual re-test answered -> mark FINAL supported (unlocks the checkbox, permanent).

    ``path`` as in :func:`set_testing`.
    """
    def _m(state):
        state[name] = {'supported': True, 'final': True, 'protocol': protocol,
                       'port': port, 'probing_since': None, 'testing': False,
                       'updated': time.time()}
    _atomic_update(_m, path)


def _final_yes(entry: Optional[Dict[str, Any]]) -> bool:
    return isinstance(entry, dict) and bool(entry.get('final')) and bool(entry.get('supported'))


def _keeping_testing(on_disk: Optional[Dict[str, Any]], entry: Dict[str, Any]) -> Dict[str, Any]:
    """The bot's new entry, with the web process's 'testing' flag if it is set.

    A manual re-test sets the flag and the panel polls it; the bot replaced
    the whole key without it, so the panel stopped and said "No response"
    while the re-test was still running (stage 4 review before v3.1.0, 20).
    """
    if isinstance(on_disk, dict) and on_disk.get('testing'):
        return {**entry, 'testing': True}
    return entry


class GameQuerySupportService:
    """Singleton (in the bot) holding support verdicts; persists to a file for the web UI."""

    def __init__(self, path: Optional[Path] = None):
        self._path = path or (_config_dir() / _SUPPORT_FILENAME)
        self._state: Dict[str, Dict[str, Any]] = {}   # name -> verdict dict
        self._last_probe: Dict[str, float] = {}        # name -> monotonic ts (in-memory only)
        # name -> consecutive failed live queries. In memory only on purpose: persisting it
        # would rewrite the verdict file on every status cycle for no benefit.
        self._failures: Dict[str, int] = {}
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
        # A FINAL verdict (supported, or gave-up-after-15-min) is never probed again -
        # except a server that answered once and then fell silent (see the module doc).
        interval = PROBE_RETRY_SECONDS
        if self.is_final(name):
            entry = self._state.get(name) or {}
            if entry.get('supported') or not entry.get('demoted'):
                return False
            interval = DEMOTED_RETRY_SECONDS
        last = self._last_probe.get(name)
        if last is None:
            return True
        return (now_mono - last) >= interval

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
            return  # already final (a silent server's re-probe failed again) - leave as-is
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
                  port=None, probing_since=since, demoted=bool(prev.get('demoted')))

    def note_query_success(self, name: str) -> None:
        """A live query answered - clear any failure streak."""
        self._failures.pop(name, None)

    def note_query_failure(self, name: str,
                           threshold: int = QUERY_FAILURE_DEMOTE_THRESHOLD) -> bool:
        """Count a failed live query and demote a stale positive verdict after `threshold`.

        Only FINAL POSITIVE verdicts are affected. Those are the ones nothing ever re-checks:
        should_probe() skips final entries, so before this a server that used to answer and no
        longer does was queried to full timeout forever. Unknown and already-negative containers
        are left alone (the probe path owns those).

        After demotion the container is back in the probing window, so it is re-tested and either
        recovers or becomes a final negative - at which point the status loop skips it entirely.

        Returns True when the verdict was demoted.
        """
        if not self.is_final(name) or self.is_supported(name) is not True:
            return False
        count = self._failures.get(name, 0) + 1
        self._failures[name] = count
        if count < threshold:
            return False
        self._failures.pop(name, None)
        self._last_probe.pop(name, None)  # allow an immediate re-probe
        self._set(name, supported=False, final=False, protocol=None, port=None,
                  probing_since=time.time(), demoted=True)
        logger.info("[GAME_QUERY] %s failed %d live queries in a row - resetting its verdict so "
                    "it gets probed again", name, count)
        return True

    def set_testing(self, name: str, testing: bool = True) -> None:
        """Flag a container as being tested, in THIS instance's file.

        The module-level helper of the same name writes to the shared default
        location; an instance that was pointed elsewhere needs this one, or it
        writes to a file it never reads back (review C66).
        """
        set_testing(name, testing, self._path)

    def record_manual_success(self, name: str, protocol: Optional[str] = None,
                              port: Optional[int] = None) -> None:
        """A manual re-test answered, recorded in THIS instance's file."""
        record_manual_success(name, protocol, port, self._path)

    def note_offline(self, name: str) -> None:
        """Container observed offline: reset the probe window for a not-yet-final container
        (a fresh 15-min window on next boot). FINAL verdicts are untouched (sticky)."""
        entry = self._state.get(name)
        if entry is not None and not entry.get('final') and entry.get('demoted'):
            # A server that answered once keeps that knowledge: dropping the flag
            # with the entry made it final "unsupported" after its next window,
            # never asked again (stage 4 review before v3.1.0, 20). Only the
            # window is reset.
            if entry.get('probing_since') is not None:
                self._last_probe.pop(name, None)
                self._set(name, supported=False, final=False, protocol=None, port=None,
                          probing_since=None, demoted=True)
        elif entry is not None and not entry.get('final'):
            del self._state[name]
            self._last_probe.pop(name, None)
            def _forget(state):   # per-key RMW: never clobber others
                if (state.get(name) or {}).get('testing'):
                    state[name] = {'testing': True}   # a running re-test keeps its flag
                else:
                    state.pop(name, None)
            _atomic_update(_forget, self._path)

    def reload(self) -> None:
        """Re-read the on-disk verdicts (e.g. web-process manual re-test results) into memory,
        so the bot's decisions and per-key writes never revert externally-written verdicts.
        Call this before each probe pass."""
        mine = self._state
        self._load_file()
        # Keep this process's 'updated' where the file says the same verdict. The
        # file's 'updated' is the time of the last WRITE, and a probing entry is
        # written only when a verdict field changes: taking the file's time made
        # record_result see a "gap" 300 s after every write and restart the
        # window, so no window ever closed (stage 4 review before v3.1.0, 20).
        for name, entry in self._state.items():
            own = mine.get(name)
            if own and own.get('updated') and all(
                    (own.get(f) or None) == (entry.get(f) or None) for f in _VERDICT_FIELDS):
                entry['updated'] = max(own['updated'], entry.get('updated') or 0)

    # --- internal ----------------------------------------------------------
    def _set(self, name: str, **fields: Any) -> None:
        entry = {
            'supported': bool(fields.get('supported')),
            'final': bool(fields.get('final')),
            'protocol': fields.get('protocol'),
            'port': fields.get('port'),
            'probing_since': fields.get('probing_since'),
            'demoted': bool(fields.get('demoted')),
            'updated': time.time(),
        }
        prev = self._state.get(name)
        self._state[name] = entry
        # Persist ONLY this key via read-modify-write, so the bot never overwrites verdicts
        # owned by the web process (manual re-test) or other containers' entries.
        if prev is None or any(prev.get(f) != entry.get(f) for f in _VERDICT_FIELDS):
            adopted = []

            def _write(state):
                on_disk = state.get(name)
                # A manual re-test answered after this pass's reload: its success is
                # news to the bot and beats the bot's older negative result - the
                # decision has to be taken here, under the lock (stage 4 review
                # before v3.1.0, 20). A demotion starts from the bot's own positive
                # verdict and still goes through.
                if _final_yes(on_disk) and not entry['supported'] and not _final_yes(prev):
                    adopted.append(dict(on_disk))
                    return
                state[name] = _keeping_testing(on_disk, entry)
            _atomic_update(_write, self._path)
            if adopted:
                self._state[name] = adopted[0]

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
