# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""
Spam Protection Service - Clean service architecture for rate limiting and spam protection
"""

import json
import threading
import time
from collections import deque
from pathlib import Path
from dataclasses import dataclass, replace
from typing import Dict, Any, Optional
import discord
from utils.atomic_io import atomic_write_json, cross_process_lock
from utils.logging_utils import get_module_logger

logger = get_module_logger('spam_protection_service')

@dataclass(frozen=True)
class SpamProtectionConfig:
    """Immutable spam protection configuration data structure."""
    command_cooldowns: Dict[str, int]
    button_cooldowns: Dict[str, int]
    global_enabled: bool
    max_commands_per_minute: int
    max_buttons_per_minute: int
    cooldown_message: bool
    log_violations: bool

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SpamProtectionConfig':
        """Create SpamProtectionConfig from dictionary data."""
        return cls(
            command_cooldowns=dict(data.get('command_cooldowns', {})),
            button_cooldowns=dict(data.get('button_cooldowns', {})),
            global_enabled=bool(data.get('global_settings', {}).get('enabled', True)),
            max_commands_per_minute=int(data.get('global_settings', {}).get('max_commands_per_minute', 20)),
            max_buttons_per_minute=int(data.get('global_settings', {}).get('max_buttons_per_minute', 30)),
            cooldown_message=bool(data.get('global_settings', {}).get('cooldown_message', True)),
            log_violations=bool(data.get('global_settings', {}).get('log_violations', True))
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert SpamProtectionConfig to dictionary for storage."""
        return {
            'command_cooldowns': self.command_cooldowns,
            'button_cooldowns': self.button_cooldowns,
            'global_settings': {
                'enabled': self.global_enabled,
                'max_commands_per_minute': self.max_commands_per_minute,
                'max_buttons_per_minute': self.max_buttons_per_minute,
                'cooldown_message': self.cooldown_message,
                'log_violations': self.log_violations
            }
        }

@dataclass(frozen=True)
class ServiceResult:
    """Standard service result wrapper."""
    success: bool
    data: Optional[Any] = None
    error: Optional[str] = None

class SpamProtectionService:
    """Clean service for managing spam protection and rate limiting."""

    def __init__(self, config_dir: Optional[str] = None):
        """Initialize the spam protection service.

        Args:
            config_dir: Directory to store config files. Defaults to config/
        """
        if config_dir is None:
            # Via utils/config_paths.py (DDC_CONFIG_DIR). Derived from __file__
            # before - but channels_config.json is shared with config_service,
            # which follows the variable: with it set there were TWO files, and
            # the spam settings went to the wrong one.
            from utils.config_paths import get_config_dir
            config_dir = get_config_dir()
        else:
            config_dir = Path(config_dir)

        self.config_dir = config_dir
        self.config_dir.mkdir(parents=True, exist_ok=True)
        # Updated: Use channels_config.json as single source for spam protection
        self.config_file = self.config_dir / "channels_config.json"

        # In-memory cooldown tracking
        self._user_cooldowns: Dict[str, float] = {}

        # Sliding one-minute window per user and kind:
        # {(user_id, is_command): deque[timestamps]}. Separate buckets because
        # the panel has two limits (max_commands_per_minute and
        # max_buttons_per_minute). Own lock because this service is called from
        # the Waitress thread (main_routes.py) AND from the bot loop;
        # _user_cooldowns next to it is unguarded - a separate finding, not
        # changed along the way here.
        self._minute_windows: Dict[tuple, deque] = {}
        self._window_lock = threading.Lock()

        logger.info(f"Spam protection service initialized: {self.config_dir}")

    def get_config(self) -> ServiceResult:
        """Get spam protection configuration from channels_config.json.

        Returns:
            ServiceResult with SpamProtectionConfig data or error
        """
        try:
            if not self.config_file.exists():
                # Return default config
                default_config = self._get_default_config()
                return ServiceResult(success=True, data=default_config)

            with open(self.config_file, 'r', encoding='utf-8') as f:
                channels_data = json.load(f)

            # Extract spam_protection section from channels_config.json
            spam_data = channels_data.get('spam_protection', {})
            try:
                config = SpamProtectionConfig.from_dict(spam_data)
            except (TypeError, ValueError) as e:
                # A stored value that is not the shape from_dict expects - a
                # limit that is not a number, say. from_dict stays strict,
                # because it is also the validator behind the POST route, where
                # a bad form value has to become a 400 rather than a silently
                # saved default. The READ path degrades instead: the clause
                # below named json.JSONDecodeError but not ValueError (naming
                # the subclass does not catch the parent), so the exception
                # left get_config and took every caller with it - is_enabled,
                # get_command_cooldown, get_button_cooldown, is_on_cooldown,
                # get_remaining_cooldown, add_user_cooldown, which is every
                # command and every button press that asks about spam
                # protection (review C64).
                logger.error(f"The stored spam protection settings could not be read as "
                             f"they are ({e}) - reading them without the unusable parts")
                try:
                    config = SpamProtectionConfig.from_dict(self._without_bad_numbers(spam_data))
                except (TypeError, ValueError) as e2:
                    logger.error(f"Nothing usable in the stored spam protection settings "
                                 f"({e2}) - the defaults apply. The values shown in the "
                                 f"panel are NOT in force.")
                    config = self._get_default_config()
            # Fill in missing keys from the defaults; saved values win. Without
            # this, every real installation (the file always exists) read ONLY
            # the saved keys: anything missing was silently braked with the
            # 5-second fallback, a missing section braked everything with 5 - and
            # the panel showed its HTML start values meanwhile. Newly added keys
            # (edit_info, mech_details, ...) never reached existing
            # installations. Deliberately here and not in from_dict: from_dict
            # also builds the payload of the POST route, where nothing is added.
            defaults = self._get_default_config()
            config = replace(
                config,
                command_cooldowns={**defaults.command_cooldowns, **config.command_cooldowns},
                button_cooldowns={**defaults.button_cooldowns, **config.button_cooldowns},
            )
            return ServiceResult(success=True, data=config)

        except (AttributeError, IOError, KeyError, OSError, PermissionError, RuntimeError, TypeError, discord.Forbidden, discord.HTTPException, discord.NotFound, json.JSONDecodeError) as e:
            error_msg = f"Error loading spam protection config: {e}"
            logger.error(error_msg)
            return ServiceResult(success=False, error=error_msg)

    def save_config(self, config: SpamProtectionConfig) -> ServiceResult:
        """Save spam protection configuration to channels_config.json.

        Args:
            config: SpamProtectionConfig to save

        Returns:
            ServiceResult indicating success or failure
        """
        try:
            # The whole read-modify-write under the file lock: DDC is two
            # processes and both hold this service (main_routes.py, the cogs).
            # Without it the later write replaced a file that never saw the
            # earlier one, and a setting saved in the panel disappeared.
            with cross_process_lock(self.config_file):
                # Load existing channels_config.json
                if self.config_file.exists():
                    with open(self.config_file, 'r', encoding='utf-8') as f:
                        channels_data = json.load(f)
                else:
                    channels_data = {}

                # This service owns one section of the file, not the file.
                channels_data['spam_protection'] = config.to_dict()

                # atomic_write_json, not a fixed "channels_config.tmp": two
                # writers shared that one name, so the target could be replaced
                # with a mixture of both.
                atomic_write_json(self.config_file, channels_data, indent=2)

            logger.info("Saved spam protection configuration to channels_config.json")
            return ServiceResult(success=True, data=config)

        except (IOError, OSError, PermissionError, RuntimeError, discord.Forbidden, discord.HTTPException, discord.NotFound, json.JSONDecodeError) as e:
            error_msg = f"Error saving spam protection config: {e}"
            logger.error(error_msg)
            return ServiceResult(success=False, error=error_msg)

    def is_enabled(self) -> bool:
        """Check if spam protection is enabled."""
        config_result = self.get_config()
        if config_result.success:
            return config_result.data.global_enabled
        return True  # Default to enabled if config can't be loaded

    def get_command_cooldown(self, command_name: str) -> int:
        """Get cooldown for a specific command."""
        config_result = self.get_config()
        if config_result.success:
            return config_result.data.command_cooldowns.get(command_name, 5)
        return 5

    def get_button_cooldown(self, button_name: str) -> int:
        """Get cooldown for a specific button."""
        config_result = self.get_config()
        if config_result.success:
            # Check for exact match first
            if button_name in config_result.data.button_cooldowns:
                return config_result.data.button_cooldowns[button_name]

            # Check for Mech button patterns (e.g., mech_donate_123456 -> mech_donate)
            if button_name.startswith('mech_'):
                parts = button_name.split('_')
                if len(parts) >= 2:
                    # Try patterns like mech_expand_channelid -> mech_expand
                    pattern = f"{parts[0]}_{parts[1]}"
                    if pattern in config_result.data.button_cooldowns:
                        return config_result.data.button_cooldowns[pattern]

            # Default cooldown
            return 5
        return 5

    def load_settings(self) -> ServiceResult:
        """Reload spam protection settings from config file.

        This method provides compatibility with the old manager interface.
        The service automatically loads settings on each access, so this just
        forces a config reload and returns the result.

        Returns:
            ServiceResult indicating success or failure
        """
        return self.get_config()

    # "Command or button?" is decided by the CALLER, not by the name.
    #
    # Until now a hard-wired list of names decided it (serverstatus, ss,
    # control, info, help, ping, donate, command, language, forceupdate, start,
    # stop, restart). A BUTTON named like a command was braked by the COMMAND
    # slider and counted into the command minute window: the info button 5 s
    # instead of 3 s, the help button 3 s instead of 5 s, the restart button
    # 15 s instead of 20 s. The operator set the button slider in the panel,
    # and it moved nothing. InfoDropdownButton and HelpButton were only sent
    # into this list by the switch to this service (commit 3785fc0) - before,
    # they asked get_button_cooldown explicitly.
    #
    # All callers of these methods are buttons (measured; commands brake via
    # _check_spam_protection in docker_control.py). Button is therefore the
    # default, and a command identifies itself with kind="command". The list is
    # gone, along with its quirks ('ss' was in no dictionary, 'donatebroadcast'
    # and 'info_edit' were missing).
    _KINDS = ("button", "command")

    _WINDOW_SECONDS = 60.0

    @classmethod
    def _is_command(cls, kind: str) -> bool:
        """Checks the kind LOUDLY: a typo raises instead of silently counting as a button."""
        if kind not in cls._KINDS:
            raise ValueError(f"kind must be one of {cls._KINDS}, not {kind!r}")
        return kind == "command"

    @staticmethod
    def _key(user_id: int, action_type: str, is_command: bool) -> str:
        """Separate key space for commands.

        Buttons keep their key "<user>:<name>". Commands get
        "<user>:command:<name>" - otherwise /info and the info BUTTON would
        share a bucket as soon as both brake through this service.
        """
        if is_command:
            return f"{user_id}:command:{action_type}"
        return f"{user_id}:{action_type}"

    def _cooldown_for(self, action_type: str, is_command: bool) -> int:
        """Cooldown per action - from the dictionary of the given kind."""
        if is_command:
            return self.get_command_cooldown(action_type)
        return self.get_button_cooldown(action_type)

    def _minute_limit(self, is_command: bool) -> int:
        """The limit from the panel. If reading it fails, the default applies."""
        result = self.get_config()
        config = result.data if result.success else self._get_default_config()
        return config.max_commands_per_minute if is_command else config.max_buttons_per_minute

    @classmethod
    def _prune_window(cls, bucket, now: float) -> None:
        """Drops everything older than one minute - when READING as well as WRITING.

        Pruning only on write would be a bug: someone who reaches the limit and
        then does nothing would stay blocked forever, because without a new
        entry nothing would ever be pruned.
        """
        cutoff = now - cls._WINDOW_SECONDS
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()

    def _window_exceeded(self, user_id: int, is_command: bool, now: float) -> bool:
        with self._window_lock:
            bucket = self._minute_windows.get((user_id, is_command))
            if not bucket:
                return False
            self._prune_window(bucket, now)
            return len(bucket) >= self._minute_limit(is_command)

    def _window_remaining(self, user_id: int, is_command: bool, now: float) -> float:
        """How long until there is room in the window again."""
        with self._window_lock:
            bucket = self._minute_windows.get((user_id, is_command))
            if not bucket:
                return 0.0
            self._prune_window(bucket, now)
            if len(bucket) < self._minute_limit(is_command):
                return 0.0
            # The oldest entry drops out first.
            return max(0.0, self._WINDOW_SECONDS - (now - bucket[0]))

    def _record_in_window(self, user_id: int, is_command: bool, now: float) -> None:
        with self._window_lock:
            bucket = self._minute_windows.setdefault((user_id, is_command), deque())
            self._prune_window(bucket, now)
            bucket.append(now)
            # Remove empty buckets, otherwise the outer store grows without
            # bound per user - the same precaution as the 300-second cleanup in
            # add_user_cooldown.
            for key in [k for k, v in self._minute_windows.items() if not v]:
                del self._minute_windows[key]

    def is_on_cooldown(self, user_id: int, action_type: str, kind: str = "button") -> bool:
        """Check if user is on cooldown for specific action.

        Args:
            user_id: Discord user ID
            action_type: Name of the button or command
            kind: "button" (default) or "command"

        Returns:
            True if user is on cooldown, False otherwise
        """
        is_command = self._is_command(kind)
        if not self.is_enabled():
            return False

        # MONOTONIC, not the wall clock. An NTP correction backwards made
        # (current_time - last_used) negative, so every button the user had
        # touched was on cooldown and the refusal read "please wait 3660.0
        # seconds" - for the size of the jump, with nothing in the log. Neither
        # store here is persisted or compared across restarts, so a clock that
        # only ever moves forward is all this arithmetic needs.
        current_time = time.monotonic()

        # The per-minute limit from the panel. Until now max_commands_per_minute
        # and max_buttons_per_minute were saved, shown in the panel and passed
        # through to_dict/from_dict cleanly - but NEVER checked. No place counted
        # a press; the per-button cooldown only remembers the LAST time.
        if self._window_exceeded(user_id, is_command, current_time):
            return True

        cooldown_key = self._key(user_id, action_type, is_command)
        last_used = self._user_cooldowns.get(cooldown_key, 0)
        return (current_time - last_used) < self._cooldown_for(action_type, is_command)

    def get_remaining_cooldown(self, user_id: int, action_type: str, kind: str = "button") -> float:
        """Get remaining cooldown time for user action.

        Args:
            user_id: Discord user ID
            action_type: Name of the button or command
            kind: "button" (default) or "command"

        Returns:
            Remaining cooldown time in seconds
        """
        is_command = self._is_command(kind)
        if not self.is_enabled():
            return 0.0

        current_time = time.monotonic()  # see is_on_cooldown

        cooldown_key = self._key(user_id, action_type, is_command)
        last_used = self._user_cooldowns.get(cooldown_key, 0)
        action_remaining = max(0.0, self._cooldown_for(action_type, is_command) - (current_time - last_used))

        # Without the window part the user would read "please wait 0.0 seconds"
        # when the refusal comes from the per-minute limit: a freshly pressed
        # button has no entry in _user_cooldowns at all. All callers ask here
        # right after is_on_cooldown.
        window_remaining = self._window_remaining(user_id, is_command, current_time)

        return max(action_remaining, window_remaining)

    def add_user_cooldown(self, user_id: int, action_type: str, kind: str = "button") -> None:
        """Add user to cooldown for specific action.

        Args:
            user_id: Discord user ID
            action_type: Name of the button or command
            kind: "button" (default) or "command"
        """
        is_command = self._is_command(kind)
        if not self.is_enabled():
            return

        current_time = time.monotonic()  # see is_on_cooldown
        cooldown_key = self._key(user_id, action_type, is_command)
        self._user_cooldowns[cooldown_key] = current_time

        # The ACCEPTED press is counted, not the check. If is_on_cooldown counted
        # as well, every refused retry would use up more quota - someone braked
        # once would never get out again.
        self._record_in_window(user_id, is_command, current_time)

        # Clean old cooldowns (older than 5 minutes)
        old_keys = [key for key, timestamp in self._user_cooldowns.items()
                   if current_time - timestamp > 300]
        for key in old_keys:
            del self._user_cooldowns[key]

    # The two global settings from_dict runs int() on.
    _NUMERIC_GLOBALS = ('max_commands_per_minute', 'max_buttons_per_minute')

    def _without_bad_numbers(self, spam_data: Dict[str, Any]) -> Dict[str, Any]:
        """The stored settings minus the global limits that are not numbers.

        Only the unusable value is dropped, not everything around it. The
        per-command cooldowns next to it are perfectly readable, and they are
        what the bot actually enforces - falling back to the defaults wholesale
        would throw away a working configuration over one bad number
        (review C64).
        """
        global_settings = dict(spam_data.get('global_settings') or {})
        for key in self._NUMERIC_GLOBALS:
            if key not in global_settings:
                continue
            try:
                int(global_settings[key])
            except (TypeError, ValueError):
                logger.error(f"spam_protection.global_settings.{key} is not a number "
                             f"({global_settings[key]!r}) - the default applies for it")
                global_settings.pop(key)
        repaired = dict(spam_data)
        repaired['global_settings'] = global_settings
        return repaired

    def _get_default_config(self) -> SpamProtectionConfig:
        """Get default spam protection configuration."""
        return SpamProtectionConfig(
            command_cooldowns={
                "control": 5,
                "serverstatus": 30,
                "info": 5,
                "info_edit": 10,
                "help": 3,
                "ping": 3,
                "donate": 5,
                "donatebroadcast": 60,
                "command": 5,
                "language": 30,
                "forceupdate": 60,
                "start": 10,
                "stop": 10,
                "restart": 15
            },
            button_cooldowns={
                # The five buttons of the /control admin overview. They asked
                # for no cooldown at all until 2026-09-23 - including the two
                # bulk actions that restart or stop every running container.
                # Named here AND in the modal's save list, so the operator can
                # see and change them instead of getting the silent fallback.
                "admin_overview_admin": 5,
                "admin_overview_restart_all": 30,
                "admin_overview_stop_all": 30,
                "admin_overview_restart_stack": 20,
                "admin_overview_donate": 10,
                "start": 10,
                "stop": 10,
                "restart": 20,
                "info": 3,
                "logs": 10,
                "live_refresh": 5,
                # "auto_refresh" was here without a consumer (no code asks for it)
                # and is removed: since get_config fills missing keys from the
                # defaults, it would have landed in every configuration.
                # These four are requested by live buttons
                # (control_ui.py:1791 admin, :2102 help, :1258 task_delete;
                # status_info_integration.py:1190 tasks) but were missing here.
                # get_button_cooldown:186 silently returned 5 seconds for them -
                # the operator could neither see nor change the value. "help" was
                # especially misleading: the panel shows a /help slider (3), but
                # it controls the COMMAND, not the button; same name, different
                # dictionaries.
                # Default 5 is exactly what the fallback returns today - NO
                # increase, only visibility. The panel decides any increase.
                "admin": 5,
                "help": 5,
                "tasks": 5,
                "task_delete": 5,
                # The three info buttons in status_info_integration.py kept their
                # own cooldowns (button_protected_edit_<n>, button_info_<n>,
                # button_protected_<n> in the cog's dictionary) and fetched the
                # DURATION together under "info". They have three SEPARATE buckets
                # with the same duration. So that the switch to the service
                # changes nothing, each gets its own name - and the value 3,
                # exactly that of "info". Without an entry the 5-second fallback
                # would apply, and the buttons would be slower than before without
                # a decision.
                "protected_info_edit": 3,
                "edit_info": 3,
                "protected_info": 3,
                "mech_donate": 10,
                "mech_history": 5,
                # MechDetailsButton used not to brake at all and had no slider.
                # 5 like mech_history, the related private view - also the
                # fallback value, so the entry only makes the value visible and
                # adjustable.
                "mech_details": 5,
                "mech_display": 3,
                "mech_story": 5,
                "mech_music": 8
            },
            global_enabled=True,
            max_commands_per_minute=20,
            # 30, not 35: for this one field three places named two different
            # defaults - from_dict (:41) and the panel
            # (_spam_protection_modal.html:51) say 30, this said 35. Which number
            # applied depended on whether config/channels_config.json exists:
            # without it the default comes from here (get_config:103-106), with it
            # from from_dict. The operator read a different number in the panel
            # than the one braking. The command limit next to it already agreed
            # in all three places (20) and stays untouched.
            # This unifies, it does NOT raise: the panel still decides the value.
            max_buttons_per_minute=30,
            cooldown_message=True,
            log_violations=True
        )

# Singleton instance
_spam_protection_service = None

def get_spam_protection_service() -> SpamProtectionService:
    """Get the global spam protection service instance.

    Returns:
        SpamProtectionService instance
    """
    global _spam_protection_service
    if _spam_protection_service is None:
        _spam_protection_service = SpamProtectionService()
    return _spam_protection_service
