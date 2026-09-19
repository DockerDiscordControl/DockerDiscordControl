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
        # {(user_id, ist_befehl): deque[timestamps]}. Separate buckets because
        # the panel has two limits (max_commands_per_minute and
        # max_buttons_per_minute). Own lock because this service is called from
        # the Waitress thread (main_routes.py) AND from the bot loop;
        # _user_cooldowns next to it is unguarded - a separate finding, not
        # changed along the way here.
        self._minutenfenster: Dict[tuple, deque] = {}
        self._fenster_sperre = threading.Lock()

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
            config = SpamProtectionConfig.from_dict(spam_data)
            # Fill in missing keys from the defaults; saved values win. Without
            # this, every real installation (the file always exists) read ONLY
            # the saved keys: anything missing was silently braked with the
            # 5-second fallback, a missing section braked everything with 5 - and
            # the panel showed its HTML start values meanwhile. Newly added keys
            # (edit_info, mech_details, ...) never reached existing
            # installations. Deliberately here and not in from_dict: from_dict
            # also builds the payload of the POST route, where nothing is added.
            vorgaben = self._get_default_config()
            config = replace(
                config,
                command_cooldowns={**vorgaben.command_cooldowns, **config.command_cooldowns},
                button_cooldowns={**vorgaben.button_cooldowns, **config.button_cooldowns},
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
            # Load existing channels_config.json
            if self.config_file.exists():
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    channels_data = json.load(f)
            else:
                channels_data = {}

            # Update spam_protection section
            channels_data['spam_protection'] = config.to_dict()

            # Atomic write
            temp_file = self.config_file.with_suffix('.tmp')
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(channels_data, f, indent=2, ensure_ascii=False)
            temp_file.replace(self.config_file)

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
    # default, and a command identifies itself with art="befehl". The list is
    # gone, along with its quirks ('ss' was in no dictionary, 'donatebroadcast'
    # and 'info_edit' were missing).
    _ARTEN = ("knopf", "befehl")

    _FENSTER_SEKUNDEN = 60.0

    @classmethod
    def _ist_befehl(cls, art: str) -> bool:
        """Checks the kind LOUDLY: a typo raises instead of silently counting as a button."""
        if art not in cls._ARTEN:
            raise ValueError(f"art must be one of {cls._ARTEN}, not {art!r}")
        return art == "befehl"

    @staticmethod
    def _schluessel(user_id: int, action_type: str, ist_befehl: bool) -> str:
        """Separate key space for commands.

        Buttons keep their key "<user>:<name>". Commands get
        "<user>:befehl:<name>" - otherwise /info and the info BUTTON would
        share a bucket as soon as both brake through this service.
        """
        if ist_befehl:
            return f"{user_id}:befehl:{action_type}"
        return f"{user_id}:{action_type}"

    def _abklingdauer(self, action_type: str, ist_befehl: bool) -> int:
        """Cooldown per action - from the dictionary of the given kind."""
        if ist_befehl:
            return self.get_command_cooldown(action_type)
        return self.get_button_cooldown(action_type)

    def _minutengrenze(self, ist_befehl: bool) -> int:
        """The limit from the panel. If reading it fails, the default applies."""
        ergebnis = self.get_config()
        config = ergebnis.data if ergebnis.success else self._get_default_config()
        return config.max_commands_per_minute if ist_befehl else config.max_buttons_per_minute

    @classmethod
    def _fenster_beschneiden(cls, eimer, jetzt: float) -> None:
        """Drops everything older than one minute - when READING as well as WRITING.

        Pruning only on write would be a bug: someone who reaches the limit and
        then does nothing would stay blocked forever, because without a new
        entry nothing would ever be pruned.
        """
        grenzzeit = jetzt - cls._FENSTER_SEKUNDEN
        while eimer and eimer[0] <= grenzzeit:
            eimer.popleft()

    def _fenster_ueberschritten(self, user_id: int, ist_befehl: bool, jetzt: float) -> bool:
        with self._fenster_sperre:
            eimer = self._minutenfenster.get((user_id, ist_befehl))
            if not eimer:
                return False
            self._fenster_beschneiden(eimer, jetzt)
            return len(eimer) >= self._minutengrenze(ist_befehl)

    def _fenster_restzeit(self, user_id: int, ist_befehl: bool, jetzt: float) -> float:
        """How long until there is room in the window again."""
        with self._fenster_sperre:
            eimer = self._minutenfenster.get((user_id, ist_befehl))
            if not eimer:
                return 0.0
            self._fenster_beschneiden(eimer, jetzt)
            if len(eimer) < self._minutengrenze(ist_befehl):
                return 0.0
            # The oldest entry drops out first.
            return max(0.0, self._FENSTER_SEKUNDEN - (jetzt - eimer[0]))

    def _fenster_eintragen(self, user_id: int, ist_befehl: bool, jetzt: float) -> None:
        with self._fenster_sperre:
            eimer = self._minutenfenster.setdefault((user_id, ist_befehl), deque())
            self._fenster_beschneiden(eimer, jetzt)
            eimer.append(jetzt)
            # Remove empty buckets, otherwise the outer store grows without
            # bound per user - the same precaution as the 300-second cleanup in
            # add_user_cooldown.
            for schluessel in [k for k, v in self._minutenfenster.items() if not v]:
                del self._minutenfenster[schluessel]

    def is_on_cooldown(self, user_id: int, action_type: str, art: str = "knopf") -> bool:
        """Check if user is on cooldown for specific action.

        Args:
            user_id: Discord user ID
            action_type: Name of the button or command
            art: "knopf" (default) or "befehl"

        Returns:
            True if user is on cooldown, False otherwise
        """
        ist_befehl = self._ist_befehl(art)
        if not self.is_enabled():
            return False

        current_time = time.time()

        # The per-minute limit from the panel. Until now max_commands_per_minute
        # and max_buttons_per_minute were saved, shown in the panel and passed
        # through to_dict/from_dict cleanly - but NEVER checked. No place counted
        # a press; the per-button cooldown only remembers the LAST time.
        if self._fenster_ueberschritten(user_id, ist_befehl, current_time):
            return True

        cooldown_key = self._schluessel(user_id, action_type, ist_befehl)
        last_used = self._user_cooldowns.get(cooldown_key, 0)
        return (current_time - last_used) < self._abklingdauer(action_type, ist_befehl)

    def get_remaining_cooldown(self, user_id: int, action_type: str, art: str = "knopf") -> float:
        """Get remaining cooldown time for user action.

        Args:
            user_id: Discord user ID
            action_type: Name of the button or command
            art: "knopf" (default) or "befehl"

        Returns:
            Remaining cooldown time in seconds
        """
        ist_befehl = self._ist_befehl(art)
        if not self.is_enabled():
            return 0.0

        current_time = time.time()

        cooldown_key = self._schluessel(user_id, action_type, ist_befehl)
        last_used = self._user_cooldowns.get(cooldown_key, 0)
        rest_aktion = max(0.0, self._abklingdauer(action_type, ist_befehl) - (current_time - last_used))

        # Without the window part the user would read "please wait 0.0 seconds"
        # when the refusal comes from the per-minute limit: a freshly pressed
        # button has no entry in _user_cooldowns at all. All callers ask here
        # right after is_on_cooldown.
        rest_fenster = self._fenster_restzeit(user_id, ist_befehl, current_time)

        return max(rest_aktion, rest_fenster)

    def add_user_cooldown(self, user_id: int, action_type: str, art: str = "knopf") -> None:
        """Add user to cooldown for specific action.

        Args:
            user_id: Discord user ID
            action_type: Name of the button or command
            art: "knopf" (default) or "befehl"
        """
        ist_befehl = self._ist_befehl(art)
        if not self.is_enabled():
            return

        current_time = time.time()
        cooldown_key = self._schluessel(user_id, action_type, ist_befehl)
        self._user_cooldowns[cooldown_key] = current_time

        # The ACCEPTED press is counted, not the check. If is_on_cooldown counted
        # as well, every refused retry would use up more quota - someone braked
        # once would never get out again.
        self._fenster_eintragen(user_id, ist_befehl, current_time)

        # Clean old cooldowns (older than 5 minutes)
        old_keys = [key for key, timestamp in self._user_cooldowns.items()
                   if current_time - timestamp > 300]
        for key in old_keys:
            del self._user_cooldowns[key]

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
                "start": 10,
                "stop": 10,
                "restart": 20,
                "info": 3,
                "refresh": 5,
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
                "mech_expand": 3,
                "mech_collapse": 2,
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
