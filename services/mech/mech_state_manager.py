# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #

"""
Minimal Mech State Manager - Simple JSON persistence for Discord bot state
"""
from utils.logging_utils import get_module_logger
import json
import os
import logging
from typing import Dict, Any

logger = get_module_logger('mech_state_manager')

class MechStateManager:
    """Minimal state manager for Discord bot persistence"""

    def __init__(self, state_file: str = None):
        # Default via utils/config_paths.py (DDC_CONFIG_DIR). Was the RELATIVE
        # "config/mech_state.json": dependent on the working directory, blind to
        # the variable - and the file is created right here (_ensure_state_file).
        if state_file is None:
            from utils.config_paths import get_config_dir
            state_file = str(get_config_dir() / "mech_state.json")
        self.state_file = state_file
        self.state_cache: Dict[str, Any] = {}
        self._cleanup_tmp_files()
        self._ensure_state_file()
        # Read before anyone writes. Every setter mutates state_cache and then
        # hands the WHOLE cache to save_state, which REPLACES the file - so a
        # manager that starts with an empty cache destroys the file with its
        # first write: other channels' expanded states, every remembered Glvl,
        # the overview message ids that exist precisely to survive a restart.
        # docker_control.py happened to repair this from outside by calling
        # load_state() right after building the singleton; that made the class
        # safe only for that one caller (review C5).
        self.load_state()

    def _cleanup_tmp_files(self):
        """Remove orphaned atomic-write temp files (e.g. from a crash between write and replace)."""
        import glob
        directory = os.path.dirname(self.state_file)
        if directory and not os.path.isdir(directory):
            return
        basename = os.path.basename(self.state_file)
        for tmp in glob.glob(os.path.join(directory or ".", f"{basename}.tmp.*")):
            try:
                os.remove(tmp)
                logger.info(f"Removed orphaned state temp file {tmp}")
            except OSError:
                pass

    def _ensure_state_file(self):
        """Ensure state file exists"""
        if not os.path.exists(self.state_file):
            os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
            self.save_state({})

    def load_state(self) -> Dict[str, Any]:
        """Load state from file, and never raise at the caller.

        The caller is ``DockerControlCog.__init__`` step 1, which re-raises -
        correctly, since a half-built cog is worse than none. But that means
        anything this method lets through costs DDC its container commands
        entirely, for a file that holds which mech panels were expanded
        (review E21).

        The old tuple was ``(FileNotFoundError, json.JSONDecodeError)``: a
        missing file and a corrupt one. It did not cover a file that exists, is
        valid, and cannot be OPENED. ``PermissionError`` is an ``OSError``, not
        a ``FileNotFoundError`` - and a root-owned file has broken this
        installation before, which is why every ``docker exec`` here runs
        ``-u ddc``.

        A missing file is the normal first start and stays quiet. Anything else
        is logged at ERROR with its reason, because that is a thing an operator
        can actually go and fix - and because what is being dropped is real:
        mech expand states, Glvl tracking, and the overview message ids that let
        a restart delete the old overview instead of posting a duplicate.
        """
        try:
            with open(self.state_file, 'r') as f:
                self.state_cache = json.load(f)
            self._read_failed = False
            return self.state_cache
        except FileNotFoundError:
            logger.debug(f"No state file at {self.state_file} yet, starting empty")
            self._read_failed = False        # nothing there is not a read error
            return {}
        except (OSError, ValueError) as e:
            # Only an OSError means "the file may be perfectly good, we just
            # could not read it" - and then a write must not replace it with the
            # empty cache plus one key (see _writable_state). Invalid JSON is
            # unusable content, and replacing THAT cleanly is the documented
            # behaviour (tests/unit/services/mech/test_mech_state_manager_atomic.py).
            self._read_failed = isinstance(e, OSError)
            # ValueError covers json.JSONDecodeError; OSError covers permissions,
            # a directory in the file's place, and an I/O error on the mount.
            logger.error(
                "Could not read the persisted state from %s (%s: %s) - continuing "
                "with empty state. Mech panel states and the tracked overview "
                "message ids are lost until this is fixed, which can mean a "
                "duplicate overview after a restart.",
                self.state_file, type(e).__name__, e, exc_info=True)
            return {}

    def save_state(self, state: Dict[str, Any]):
        """Save state to file atomically.

        Writes to a temp file in the same directory and os.replace()s it into place so a
        crash or partial write can never leave a truncated/corrupt state file (which
        load_state would discard, wiping ALL persisted state - mech expand, glvl, etc.).
        """
        tmp_path = f"{self.state_file}.tmp.{os.getpid()}"
        try:
            target_dir = os.path.dirname(self.state_file)
            if target_dir:
                os.makedirs(target_dir, exist_ok=True)
            with open(tmp_path, 'w') as f:
                json.dump(state, f, indent=2)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except OSError:
                    # Some network filesystems (e.g. SMB) may not support fsync - the
                    # atomic os.replace below still gives us all-or-nothing semantics.
                    pass
            os.replace(tmp_path, self.state_file)
            self.state_cache = state
        except (IOError, OSError) as e:
            # File I/O errors (file write)
            logger.error(f"File I/O error saving state: {e}", exc_info=True)
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except OSError:
                pass

    def _writable_state(self):
        """The state to change - or None when it must not be written.

        After a read that failed, the cache is empty while the FILE is still
        good; writing then replaced the tracked overview ids and every channel's
        state with a single key. One more read is tried; if that fails too, the
        change is refused and said so.
        """
        if getattr(self, '_read_failed', False):
            self.load_state()
            if getattr(self, '_read_failed', False):
                logger.error(
                    "Not writing %s: it could not be read, and writing now would replace "
                    "the state that is still in it with almost nothing.", self.state_file)
                return None
        return self.state_cache

    def get_state(self, key: str, default=None):
        """Get specific state value"""
        return self.state_cache.get(key, default)

    def set_state(self, key: str, value: Any):
        """Set specific state value and save"""
        state = self._writable_state()
        if state is None:
            return
        state[key] = value
        self.save_state(state)

    def set_expanded_state(self, channel_id: str, expanded: bool):
        """Set expanded state for a channel"""
        state = self._writable_state()
        if state is None:
            return
        state.setdefault('mech_expanded_states', {})[str(channel_id)] = expanded
        self.save_state(state)

    def get_expanded_state(self, channel_id: str) -> bool:
        """Get expanded state for a channel"""
        return self.state_cache.get('mech_expanded_states', {}).get(str(channel_id), False)

    def set_last_glvl(self, channel_id: str, glvl: int):
        """Set last glvl for a channel"""
        state = self._writable_state()
        if state is None:
            return
        state.setdefault('last_glvl_per_channel', {})[str(channel_id)] = glvl
        self.save_state(state)

    def get_last_glvl(self, channel_id: str) -> int:
        """Get last glvl for a channel"""
        return self.state_cache.get('last_glvl_per_channel', {}).get(str(channel_id), 0)

    def should_force_recreate(self, channel_id: str) -> bool:
        """Check if force recreate should be triggered (rate limited)"""
        import time
        current_time = time.time()
        last_recreate = self.state_cache.get('last_force_recreate', {}).get(str(channel_id), 0)

        # Rate limit: 30 seconds between force recreates
        return current_time - last_recreate > 30

    def mark_force_recreate(self, channel_id: str):
        """Mark that force recreate was triggered"""
        import time
        if 'last_force_recreate' not in self.state_cache:
            self.state_cache['last_force_recreate'] = {}
        self.state_cache['last_force_recreate'][str(channel_id)] = time.time()
        self.save_state(self.state_cache)

# Singleton instance
_mech_state_manager = None

def get_mech_state_manager() -> MechStateManager:
    """Get singleton MechStateManager instance"""
    global _mech_state_manager
    if _mech_state_manager is None:
        _mech_state_manager = MechStateManager()
    return _mech_state_manager
