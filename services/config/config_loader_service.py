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

import logging
from pathlib import Path
from typing import Dict, Any

logger = logging.getLogger('ddc.config_loader')


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

    def has_real_modular_structure(self) -> bool:
        """Check if we have real modular file structure."""
        return ((self.channels_dir.exists() and len(list(self.channels_dir.glob("*.json"))) > 0) or
                (self.containers_dir.exists() and len(list(self.containers_dir.glob("*.json"))) > 0))

    def load_real_modular_config(self) -> Dict[str, Any]:
        """Load configuration from real modular file structure."""
        config = {}

        # 1. Load main system config
        if self.main_config_file.exists():
            main_config = self._load_json_file(self.main_config_file, {})
            config.update(main_config)

        # 2. Load auth config
        if self.auth_config_file.exists():
            auth_config = self._load_json_file(self.auth_config_file, {})
            config.update(auth_config)

        # 3. Load heartbeat config
        if self.heartbeat_config_file.exists():
            heartbeat_config = self._load_json_file(self.heartbeat_config_file, {})
            config.update(heartbeat_config)

        # 4. Load web UI config
        if self.web_ui_config_file.exists():
            web_ui_config = self._load_json_file(self.web_ui_config_file, {})
            config.update(web_ui_config)

        # 5. Load advanced settings (from web_config.json)
        web_config = self._load_json_file(self.web_config_file, {})
        config['advanced_settings'] = web_config.get('advanced_settings', {})

        # 6. Load Docker settings
        if self.docker_settings_file.exists():
            docker_settings = self._load_json_file(self.docker_settings_file, {})
            config.update(docker_settings)

        # 7. Load all containers from individual files
        servers = self.load_all_containers_from_files()
        config['servers'] = servers

        # 8. Load all channels from individual files
        channel_data = self.load_all_channels_from_files()
        config.update(channel_data)

        # 9. Load other existing configs
        self.load_existing_configs_virtual(config)

        logger.debug(f"Real modular config loaded: {len(servers)} servers, {len(channel_data.get('channel_permissions', {}))} channels")
        return config

    def load_all_containers_from_files(self) -> list:
        """Load all container configurations from individual files."""
        servers = []

        if not self.containers_dir.exists():
            return servers

        for container_file in self.containers_dir.glob("*.json"):
            try:
                container_config = self._load_json_file(container_file, {})
                # ONLY include containers that are marked as active
                if container_config.get('active', False):
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
            return channel_data

        for channel_file in self.channels_dir.glob("*.json"):
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

        return channel_data

    def load_virtual_modular_config(self) -> Dict[str, Any]:
        """Virtual modular config - uses existing files but structured as modular."""
        config = {}

        # 1. Bot config (contains: language, timezone, guild_id, bot_token, heartbeat)
        if self.bot_config_file.exists():
            bot_config = self._load_json_file(self.bot_config_file, {})

            # Extract system settings (virtual config.json)
            config.update({
                'language': bot_config.get('language', 'en'),
                'timezone': bot_config.get('timezone', 'UTC'),
                'guild_id': bot_config.get('guild_id')
            })

            # Extract auth settings (virtual auth.json)
            config.update({
                'bot_token': bot_config.get('bot_token')
            })

            # Extract heartbeat settings (virtual heartbeat.json)
            config.update({
                'heartbeat_channel_id': bot_config.get('heartbeat_channel_id')
            })

        # 2. Docker config (contains: servers + docker settings)
        if self.docker_config_file.exists():
            docker_config = self._load_json_file(self.docker_config_file,
                                                 self._validation_service.get_default_docker_config())

            # Extract containers (virtual containers/*.json)
            config['servers'] = docker_config.get('servers', [])

            # Extract docker settings (virtual docker_settings.json)
            config.update({
                'docker_socket_path': docker_config.get('docker_socket_path', '/var/run/docker.sock'),
                'container_command_cooldown': docker_config.get('container_command_cooldown', 5),
                'docker_api_timeout': docker_config.get('docker_api_timeout', 30),
                'max_log_lines': docker_config.get('max_log_lines', 50)
            })

        # 3. Web config (contains: web UI + advanced settings)
        if self.web_config_file.exists():
            web_config = self._load_json_file(self.web_config_file, {})

            # Extract web UI settings (virtual web_ui.json)
            config.update({
                'web_ui_user': web_config.get('web_ui_user', 'admin'),
                'web_ui_password_hash': web_config.get('web_ui_password_hash'),
                'admin_enabled': web_config.get('admin_enabled', True),
                'session_timeout': web_config.get('session_timeout', 3600),
                'donation_disable_key': web_config.get('donation_disable_key', ''),
                'scheduler_debug_mode': web_config.get('scheduler_debug_mode', False)
            })

            # Extract advanced settings (from web_config.json)
            config['advanced_settings'] = web_config.get('advanced_settings', {})

        # 4. Channels config (contains: channel permissions + channel data)
        if self.channels_config_file.exists():
            channels_config = self._load_json_file(self.channels_config_file, {})

            # Extract channel data (virtual channels/*.json)
            config['channel_permissions'] = channels_config.get('channel_permissions', {})
            config['default_channel_permissions'] = channels_config.get('default_channel_permissions', {})
            config['channels'] = channels_config.get('channels', {})
            config['server_selection'] = channels_config.get('server_selection', {})

        # 5. Load other existing configs
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
