# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""
Configuration Loader Service - Handles modular config loading
Part of ConfigService refactoring for Single Responsibility Principle
"""

import discord
import docker
import logging
from pathlib import Path
from typing import Dict, Any, Optional, Set, Tuple

from services.config.channel_config_service import ALL_CHANNELS_REMOVED_MARKER

logger = logging.getLogger('ddc.config_loader')

# Written by ConfigService.fold_legacy_settings_once() when the legacy settings files have been
# folded into config.json (one-time upgrade step). From then on config.json is the only source
# for these settings; without the marker the pre-fold (v2.3) precedence applies.
LEGACY_FOLD_MARKER = '.legacy_settings_folded'


class ConfigLoaderService:
    """
    Handles all configuration loading operations.

    Responsibilities:
    - Load modular config structures (real/virtual)
    - Load containers from files
    - Load channels from files
    - Load legacy configs
    """

    def __init__(self, config_dir: Path, channels_dir: Path, containers_dir: Path,
                 main_config_file: Path, auth_config_file: Path, heartbeat_config_file: Path,
                 web_ui_config_file: Path, docker_settings_file: Path,
                 bot_config_file: Path, docker_config_file: Path,
                 web_config_file: Path, channels_config_file: Path,
                 load_json_func, validation_service):
        """Initialize loader service."""
        self.config_dir = config_dir
        self.channels_dir = channels_dir
        self.containers_dir = containers_dir

        self.main_config_file = main_config_file
        self.auth_config_file = auth_config_file
        self.heartbeat_config_file = heartbeat_config_file
        self.web_ui_config_file = web_ui_config_file
        self.docker_settings_file = docker_settings_file

        self.bot_config_file = bot_config_file
        self.docker_config_file = docker_config_file
        self.web_config_file = web_config_file
        self.channels_config_file = channels_config_file

        self._load_json_file = load_json_func
        self._validation_service = validation_service

    def load_modular_config(self) -> Dict[str, Any]:
        """Load configuration using modular structure (real or virtual)."""
        if self.has_real_modular_structure():
            return self.load_real_modular_config()
        else:
            return self.load_virtual_modular_config()

    @property
    def legacy_settings_files(self) -> Tuple[Path, ...]:
        """Settings files written only by the v2.0 modular migration (real modular layout)."""
        return (self.auth_config_file, self.web_ui_config_file, self.docker_settings_file)

    @property
    def fold_marker_file(self) -> Path:
        return self.config_dir / LEGACY_FOLD_MARKER

    def legacy_settings_folded(self) -> bool:
        """True once the legacy settings files were folded into config.json."""
        return self.fold_marker_file.exists()

    def read_fold_marker(self) -> Optional[Dict[str, Any]]:
        """Content of the fold marker, None without marker ({} if unreadable)."""
        if not self.fold_marker_file.exists():
            return None
        marker = self._load_json_file(self.fold_marker_file, {})
        return marker if isinstance(marker, dict) else {}

    def load_pre_fold_real_settings(self) -> Dict[str, Any]:
        """Settings as v2.3 resolved them in the real modular layout: config.json with the
        legacy settings files applied on top.

        Exception to v2.3's precedence: a ``null`` in a legacy file does NOT overwrite a real
        value from config.json. The migration writes ``{"bot_token": null}`` /
        ``{"web_ui_password_hash": null}`` when the v1 file had none, and folding that null back
        into config.json would destroy the last usable copy of the token or the password hash
        (v2.3 kept it on disk, it was only shadowed at runtime).
        """
        settings = self._load_json_file(self.main_config_file, {})
        for legacy_file in self.legacy_settings_files:
            if legacy_file.exists():
                for key, value in self._load_json_file(legacy_file, {}).items():
                    if value is None and settings.get(key) is not None:
                        continue
                    settings[key] = value
        return settings

    def _v1_setting_sources(self) -> Tuple[Tuple[Path, Dict[str, Any]], ...]:
        """v1 split files and the settings (with defaults) the virtual layout takes from them."""
        return (
            (self.bot_config_file, {'language': 'en', 'timezone': 'UTC', 'guild_id': None,
                                    'bot_token': None}),
            (self.docker_config_file, {'docker_socket_path': '/var/run/docker.sock',
                                       'container_command_cooldown': 5, 'docker_api_timeout': 30,
                                       'max_log_lines': 50}),
            (self.web_config_file, {'web_ui_user': 'admin', 'web_ui_password_hash': None,
                                    'admin_enabled': True, 'session_timeout': 3600,
                                    'donation_disable_key': '', 'scheduler_debug_mode': False}),
        )

    def load_v1_settings(self) -> Tuple[Dict[str, Any], Set[str]]:
        """Settings from the v1 split files (virtual layout).

        Returns the values (defaults for keys an existing file lacks) and the set of keys a
        v1 file really contains.
        """
        settings: Dict[str, Any] = {}
        present: Set[str] = set()
        for path, defaults in self._v1_setting_sources():
            if not path.exists():
                continue
            raw = self._load_json_file(path, {})
            for key, default in defaults.items():
                if key in raw:
                    settings[key] = raw[key]
                    present.add(key)
                else:
                    settings[key] = default
        return settings, present

    def _legacy_advanced_settings(self) -> Dict[str, Any]:
        """advanced_settings kept in the legacy web_config.json (migration-only file)."""
        if not self.web_config_file.exists():
            return {}
        return dict(self._load_json_file(self.web_config_file, {}).get('advanced_settings') or {})

    def load_pre_fold_virtual_settings(self) -> Dict[str, Any]:
        """config.json with the settings of the v1 split files on top: before the fold,
        config.json only fills keys the v1 files lack (advanced settings per key)."""
        settings = self._load_json_file(self.main_config_file, {})
        v1_settings, v1_present = self.load_v1_settings()
        for key in v1_present:
            # Same rule as in load_pre_fold_real_settings: a null in a v1 file must not fold
            # over a real value in config.json (it would destroy the last usable copy).
            if v1_settings[key] is None and settings.get(key) is not None:
                continue
            settings[key] = v1_settings[key]
        legacy_advanced = self._legacy_advanced_settings()
        if legacy_advanced:
            settings['advanced_settings'] = {**(settings.get('advanced_settings') or {}), **legacy_advanced}
        return settings

    def has_real_modular_structure(self) -> bool:
        """Check if we have real modular file structure."""
        return ((self.channels_dir.exists() and len(list(self.channels_dir.glob("*.json"))) > 0) or
                (self.containers_dir.exists() and len(list(self.containers_dir.glob("*.json"))) > 0))

    def load_real_modular_config(self) -> Dict[str, Any]:
        """Load configuration from real modular file structure."""
        config = {}

        # 1. Settings. Legacy auth.json / web_ui.json / docker_settings.json are written only by
        # the one-time modular migration. ConfigService folds them into config.json once at
        # startup and renames them, so config.json (the live save target) is the only source;
        # leftover legacy files only fill keys it lacks. Until that fold has run (e.g. read-only
        # config dir) the v2.3 precedence stays: legacy files override config.json.
        if self.legacy_settings_folded():
            for legacy_file in self.legacy_settings_files:
                if legacy_file.exists():
                    config.update(self._load_json_file(legacy_file, {}))
            # 2. Load main system config (wins over the legacy files)
            self._overlay_main_config(config)
        else:
            config.update(self.load_pre_fold_real_settings())

        # 3. Heartbeat config (Status Watchdog) - now stored in main config.json
        # Legacy heartbeat.json is no longer used - cleanup removes it during migration

        # 5. Load advanced settings. save_config() writes advanced_settings into config.json
        # (already merged via config.update(main_config) above). The legacy web_config.json is
        # written only at v1.1.x migration and never updated, so config.json (the live save
        # target) MUST win on collision; web_config.json only fills keys config.json lacks.
        web_config = self._load_json_file(self.web_config_file, {})
        config['advanced_settings'] = {
            **(web_config.get('advanced_settings') or {}),   # legacy fallback
            **(config.get('advanced_settings') or {}),       # live config.json wins
        }

        # 7. Load all containers from individual files
        servers = self.load_all_containers_from_files()
        config['servers'] = servers

        # 8. Load all channels from individual files
        channel_data = self.load_all_channels_from_files()
        # Preserve any channel_permissions from config.json (step 1) as a fallback
        main_config_channels = config.get('channel_permissions', {})
        config.update(channel_data)

        # 8b. Fallback: If no individual channel files found, try other sources
        # This handles migration from virtual modular (channels_config.json) to real modular,
        # and recovery if individual channel files are lost but config.json still has them.
        # Not when the last channel was removed on purpose (marker written by ChannelConfigService).
        channels_removed = (self.channels_dir / ALL_CHANNELS_REMOVED_MARKER).exists()
        if not channel_data.get('channel_permissions') and channels_removed:
            config['channel_permissions'] = {}
            logger.debug("All channels were removed on purpose - legacy channel fallbacks skipped")
        elif not channel_data.get('channel_permissions'):
            # First try: config.json might have channel_permissions
            if main_config_channels:
                logger.info(f"No individual channel files found - recovered {len(main_config_channels)} channels from config.json")
                config['channel_permissions'] = main_config_channels

                # Auto-migrate to individual files
                try:
                    from services.config.channel_config_service import get_channel_config_service
                    channel_service = get_channel_config_service()
                    if not channel_service.save_all_channels(main_config_channels):
                        logger.warning("Auto-migration from config.json partially failed - some channels may not have been saved")
                    else:
                        logger.info(f"Auto-migrated {len(main_config_channels)} channels from config.json to individual files")
                except (AttributeError, ImportError, IOError, KeyError, OSError, PermissionError, RuntimeError, TypeError, ValueError) as migrate_err:
                    logger.warning(f"Could not auto-migrate channels from config.json: {migrate_err}")

            # Second try: channels_config.json (legacy virtual modular)
            elif self.channels_config_file.exists():
                channels_config = self._load_json_file(self.channels_config_file, {})
                fallback_permissions = channels_config.get('channel_permissions', {})
                if fallback_permissions:
                    logger.info(f"No individual channel files found - loaded {len(fallback_permissions)} channels from {self.channels_config_file.name} (migration fallback)")
                    config['channel_permissions'] = fallback_permissions
                    config['default_channel_permissions'] = channels_config.get('default_channel_permissions', {})

                    # Auto-migrate: save to individual files for next load
                    try:
                        from services.config.channel_config_service import get_channel_config_service
                        channel_service = get_channel_config_service()
                        if not channel_service.save_all_channels(fallback_permissions):
                            logger.warning("Auto-migration from channels_config.json partially failed - some channels may not have been saved")
                        else:
                            logger.info(f"Auto-migrated {len(fallback_permissions)} channels to individual files")
                    except (AttributeError, ImportError, IOError, KeyError, OSError, PermissionError, RuntimeError, TypeError, ValueError) as migrate_err:
                        logger.warning(f"Could not auto-migrate channels to individual files: {migrate_err}")

        # 9. Load other existing configs
        self.load_existing_configs_virtual(config)

        logger.info(f"Real modular config loaded: {len(servers)} servers, {len(config.get('channel_permissions', {}))} channels")
        return config

    def load_all_containers_from_files(self) -> list:
        """Load all container configurations from individual files."""
        servers = []

        if not self.containers_dir.exists():
            return servers

        for container_file in self.containers_dir.glob("*.json"):
            try:
                container_config = self._load_json_file(container_file, {})
                # A MISSING 'active' key means ACTIVE - the same default as
                # server_config_service.py:90 and cogs/admin_overview.py:464,
                # both of which spell it out as a comment. This said False, so
                # the same container file existed for some callers and not for
                # others. The key is by no means only missing in theory:
                # config_migration_service.py:230 writes legacy entries from
                # docker_config.json verbatim, and the word 'active' does not
                # occur once in that file. The loss was reported only via
                # logger.debug (below), which appears nowhere at the normal INFO
                # level. An explicit active: False still filters.
                if container_config.get('active', True):
                    servers.append(container_config)
                    logger.debug(f"Loading active container: {container_config.get('container_name', container_file.stem)}")
                else:
                    logger.debug(f"Skipping inactive container: {container_config.get('container_name', container_file.stem)}")
            except (AttributeError, IOError, KeyError, OSError, PermissionError, RuntimeError, TypeError, docker.errors.APIError, docker.errors.DockerException) as e:
                logger.error(f"Error loading container {container_file}: {e}", exc_info=True)

        # Sort by order if available
        servers.sort(key=lambda x: x.get('order', 999))
        logger.info(f"Loaded {len(servers)} active containers for Discord")
        return servers

    def load_all_channels_from_files(self) -> Dict[str, Any]:
        """Load all channel configurations from individual files."""
        channel_data = {
            'channel_permissions': {},
            'default_channel_permissions': {}
        }

        if not self.channels_dir.exists():
            logger.info(f"Channels directory does not exist: {self.channels_dir}")
            return channel_data

        json_files = list(self.channels_dir.glob("*.json"))
        logger.info(f"Found {len(json_files)} JSON files in {self.channels_dir}")

        for channel_file in json_files:
            try:
                channel_config = self._load_json_file(channel_file, {})

                if channel_file.name == "default.json":
                    # Remove fields that don't belong in default
                    default_config = channel_config.copy()
                    default_config.pop('channel_id', None)
                    default_config.pop('name', None)
                    channel_data['default_channel_permissions'] = default_config
                else:
                    # Regular channel
                    channel_id = channel_config.get('channel_id', channel_file.stem)
                    channel_data['channel_permissions'][channel_id] = channel_config

            except (AttributeError, IOError, KeyError, OSError, PermissionError, RuntimeError, TypeError, discord.Forbidden, discord.HTTPException, discord.NotFound) as e:
                logger.error(f"Error loading channel {channel_file}: {e}", exc_info=True)

        logger.info(f"Loaded {len(channel_data['channel_permissions'])} channel configurations from individual files")
        return channel_data

    def _overlay_main_config(self, config: Dict[str, Any], skip_keys=frozenset()) -> None:
        """Apply config.json on top of ``config`` - it is the only file save_config() writes.

        A null in config.json must not wipe a real legacy value (e.g. a missing
        web_ui_password_hash would reopen the unauthenticated /setup page).
        Keys in ``skip_keys`` keep their current value.
        """
        if not self.main_config_file.exists():
            return
        main_config = self._load_json_file(self.main_config_file, {})
        for key, value in main_config.items():
            if key in skip_keys:
                continue
            if value is None and config.get(key) is not None:
                continue
            config[key] = value

    def load_virtual_modular_config(self) -> Dict[str, Any]:
        """Virtual modular config - uses existing files but structured as modular."""
        config = {}

        # Settings of the v1 split files: bot_config.json (language, timezone, guild_id,
        # bot_token), docker_config.json (docker settings), web_config.json (web UI settings)
        v1_settings, v1_present = self.load_v1_settings()
        config.update(v1_settings)

        # 1. Bot config (contains: language, timezone, guild_id, bot_token, heartbeat)
        if self.bot_config_file.exists():
            # Status Watchdog config - new format (old heartbeat_channel_id no longer used)
            if 'heartbeat' not in config:
                config['heartbeat'] = {
                    'enabled': False,
                    'ping_url': '',
                    'interval': 5
                }

        # 2. Docker config (contains: servers + docker settings)
        if self.docker_config_file.exists():
            docker_config = self._load_json_file(self.docker_config_file,
                                                 self._validation_service.get_default_docker_config())

            # Extract containers (virtual containers/*.json)
            config['servers'] = docker_config.get('servers', [])

        # 3. Web config (web UI settings: see load_v1_settings) - advanced settings
        legacy_advanced = self._legacy_advanced_settings()
        if self.web_config_file.exists():
            config['advanced_settings'] = dict(legacy_advanced)

        # 4. Channels config (contains: channel permissions + channel data)
        if self.channels_config_file.exists():
            channels_config = self._load_json_file(self.channels_config_file, {})

            # Extract channel data (virtual channels/*.json)
            config['channel_permissions'] = channels_config.get('channel_permissions', {})
            config['default_channel_permissions'] = channels_config.get('default_channel_permissions', {})
            config['channels'] = channels_config.get('channels', {})
            config['server_selection'] = channels_config.get('server_selection', {})
        if (self.channels_dir / ALL_CHANNELS_REMOVED_MARKER).exists():
            config['channel_permissions'] = {}  # last channel removed on purpose

        # 5. config.json. Containers and channels keep coming from the v1 structure files.
        # After the one-time fold (ConfigService) config.json holds the settings and wins, same
        # as in load_real_modular_config; legacy advanced_settings stay a fallback. Before it,
        # config.json only fills keys the v1 files lack (the v2.3 effective values stay).
        virtual_structure = {key: config[key] for key in
                             ('servers', 'channel_permissions', 'default_channel_permissions',
                              'channels', 'server_selection') if key in config}
        if self.legacy_settings_folded():
            self._overlay_main_config(config)
            config.update(virtual_structure)
            config['advanced_settings'] = {**legacy_advanced, **(config.get('advanced_settings') or {})}
        else:
            self._overlay_main_config(config, skip_keys=v1_present | set(virtual_structure))
            config['advanced_settings'] = {**(config.get('advanced_settings') or {}), **legacy_advanced}

        # 6. Load other existing configs
        self.load_existing_configs_virtual(config)

        logger.debug("Virtual modular config loaded successfully")
        return config

    def load_existing_configs_virtual(self, config: Dict[str, Any]) -> None:
        """Load existing configs for virtual modular structure."""
        # Load spam protection from channels_config.json
        channels_config = self._load_json_file(self.channels_config_file, {})
        config['spam_protection'] = channels_config.get('spam_protection', {})

        # Load server order
        server_order_file = self.config_dir / "server_order.json"
        if server_order_file.exists():
            server_order = self._load_json_file(server_order_file, {})
            config.update(server_order)
        else:
            config['server_order'] = []

        # Add missing fields with defaults
        if 'channels' not in config:
            config['channels'] = {}
        if 'server_selection' not in config:
            config['server_selection'] = {}

    def has_legacy_configs(self) -> bool:
        """Check if legacy config files exist."""
        return (self.bot_config_file.exists() or
               self.docker_config_file.exists() or
               self.web_config_file.exists() or
               self.channels_config_file.exists())

    def load_legacy_config(self) -> Dict[str, Any]:
        """Load configuration using legacy method (backward compatibility)."""
        config = {}

        # Bot configuration
        if self.bot_config_file.exists():
            bot_config = self._load_json_file(self.bot_config_file,
                                             self._validation_service.get_default_bot_config())
            config.update(bot_config)

        # Docker configuration
        if self.docker_config_file.exists():
            docker_config = self._load_json_file(self.docker_config_file,
                                                 self._validation_service.get_default_docker_config())
            config.update(docker_config)

        # Web configuration
        if self.web_config_file.exists():
            web_config = self._load_json_file(self.web_config_file,
                                             self._validation_service.get_default_web_config())
            config.update(web_config)

        # Channels configuration
        if self.channels_config_file.exists():
            channels_config = self._load_json_file(self.channels_config_file,
                                                   self._validation_service.get_default_channels_config())
            config.update(channels_config)

        return config
