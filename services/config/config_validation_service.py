# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""
Configuration Validation Service - Handles config validation and extraction
Part of ConfigService refactoring for Single Responsibility Principle
"""

import logging
from typing import Dict, Any

logger = logging.getLogger('ddc.config_validation')


class ConfigValidationService:
    """
    Handles all configuration validation and extraction operations.

    Responsibilities:
    - Validate Discord tokens
    - Extract config sections from legacy configs
    - Validate config data types
    - Provide default configs
    """

    # Allowed game-query protocols (mirrors GameQueryService.SUPPORTED_PROTOCOLS).
    _ALLOWED_QUERY_PROTOCOLS = ('source', 'minecraft', 'satisfactory', 'palworld')
    # Max stored length for a per-server access token (e.g. Satisfactory app token).
    _MAX_QUERY_TOKEN_LEN = 1024

    @staticmethod
    def sanitize_query_config(query_enabled, query_protocol, query_host, query_port,
                              query_token='') -> Dict[str, Any]:
        """Sanitize per-container game-query (opengsq) settings to safe, stored values.

        - protocol: coerced to the supported whitelist (default 'source').
        - port: clamped to 0 (=auto-discover) or a valid 1-65535 host port.
        - host: trimmed; a scheme/path is stripped (we only ever query host:port).
          NOTE: a manually configured host is TRUSTED VERBATIM and is NOT validated against
          the container's Docker bindings. When left empty (the default) the target is
          auto-discovered from the container's own IP/ports. Setting a manual host for a
          token protocol sends the token/password to that host, so this is an admin-only,
          accepted risk (the web UI is authenticated). There is no query-time SSRF guard.
        - token: trimmed access token / admin password; length-capped.
        Returns a dict with the cleaned fields.
        """
        protocol = str(query_protocol or 'source').strip().lower()
        if protocol not in ConfigValidationService._ALLOWED_QUERY_PROTOCOLS:
            logger.warning(f"Unsupported game-query protocol '{protocol}', defaulting to 'source'")
            protocol = 'source'

        try:
            port = int(query_port or 0)
        except (TypeError, ValueError):
            port = 0
        if port < 0 or port > 65535:
            port = 0

        host = str(query_host or '').strip()
        # Strip any scheme/path - we only ever use a bare host or IP.
        if '://' in host:
            host = host.split('://', 1)[1]
        host = host.split('/', 1)[0].strip()

        token = str(query_token or '').strip()[:ConfigValidationService._MAX_QUERY_TOKEN_LEN]

        return {
            'query_enabled': bool(query_enabled),
            'query_protocol': protocol,
            'query_host': host,
            'query_port': port,
            'query_token': token,
        }

    @staticmethod
    def looks_like_discord_token(token: str) -> bool:
        """Check if a token looks like a valid Discord bot token."""
        if not token or len(token) < 50:
            return False
        # Discord bot tokens typically start with certain patterns and contain dots
        # Bot tokens: start with MTA, MTI, etc. (base64 encoded user ID)
        # App tokens: Usually 64+ chars with specific patterns
        return ('.' in token and len(token) > 50) or token.startswith(('MTA', 'MTI', 'MTM', 'MTQ', 'MTU'))

    @staticmethod
    def extract_bot_config(config: Dict[str, Any]) -> Dict[str, Any]:
        """Extract bot-specific configuration with type safety."""
        try:
            return {
                'bot_token': str(config.get('bot_token', '')) if config.get('bot_token') else None,
                'bot_token_encrypted': str(config.get('bot_token_encrypted', '')) if config.get('bot_token_encrypted') else None,
                'guild_id': str(config.get('guild_id', '')) if config.get('guild_id') else None,
                'language': str(config.get('language', 'en')),
                'ui_language': str(config.get('ui_language', 'en')),
                'timezone': str(config.get('timezone', 'UTC')),
                'heartbeat': config.get('heartbeat', {'enabled': False, 'ping_url': '', 'interval': 5})
            }
        except (TypeError, ValueError) as e:
            logger.warning(f"Type conversion error in bot config: {e}")
            return ConfigValidationService.get_default_bot_config()

    @staticmethod
    def extract_docker_config(config: Dict[str, Any]) -> Dict[str, Any]:
        """Extract Docker-specific configuration."""
        return {
            'docker_socket_path': config.get('docker_socket_path', '/var/run/docker.sock'),
            'container_command_cooldown': config.get('container_command_cooldown', 5),
            'docker_api_timeout': config.get('docker_api_timeout', 30),
            'max_log_lines': config.get('max_log_lines', 50),
            'servers': list(config.get('servers', [])) if isinstance(config.get('servers'), list) else []
        }

    @staticmethod
    def extract_web_config(config: Dict[str, Any]) -> Dict[str, Any]:
        """Extract web UI configuration with type safety."""
        try:
            return {
                'web_ui_password_hash': str(config.get('web_ui_password_hash', '')) if isinstance(config.get('web_ui_password_hash'), str) else None,
                'web_ui_user': str(config.get('web_ui_user', 'admin')),
                'admin_enabled': bool(config.get('admin_enabled', True)),
                'session_timeout': int(config.get('session_timeout', 3600)) if isinstance(config.get('session_timeout'), (int, str)) else 3600,
                'donation_disable_key': str(config.get('donation_disable_key', '')),
                'advanced_settings': dict(config.get('advanced_settings', {})) if isinstance(config.get('advanced_settings'), dict) else {}
            }
        except (TypeError, ValueError) as e:
            logger.warning(f"Type conversion error in web config: {e}")
            return ConfigValidationService.get_default_web_config()

    @staticmethod
    def extract_channels_config(config: Dict[str, Any]) -> Dict[str, Any]:
        """Extract Discord channels configuration with type safety."""
        try:
            default_perms = ConfigValidationService.get_default_channels_config()['default_channel_permissions']
            return {
                'channels': dict(config.get('channels', {})) if isinstance(config.get('channels'), dict) else {},
                'server_selection': dict(config.get('server_selection', {})) if isinstance(config.get('server_selection'), dict) else {},
                'server_order': list(config.get('server_order', [])) if isinstance(config.get('server_order'), list) else [],
                'servers': list(config.get('servers', [])) if isinstance(config.get('servers'), list) else [],
                'channel_permissions': dict(config.get('channel_permissions', {})) if isinstance(config.get('channel_permissions'), dict) else {},
                'default_channel_permissions': dict(config.get('default_channel_permissions', default_perms)) if isinstance(config.get('default_channel_permissions'), dict) else default_perms,
                'spam_protection': dict(config.get('spam_protection', {})) if isinstance(config.get('spam_protection'), dict) else {}
            }
        except (TypeError, ValueError) as e:
            logger.warning(f"Type conversion error in channels config: {e}")
            return ConfigValidationService.get_default_channels_config()

    @staticmethod
    def get_default_bot_config() -> Dict[str, Any]:
        """Get default bot configuration."""
        return {
            'bot_token': None,
            'guild_id': None,
            'language': 'en',
            'ui_language': 'en',
            'timezone': 'UTC',
            'heartbeat': {
                'enabled': False,
                'ping_url': '',
                'interval': 5
            }
        }

    @staticmethod
    def get_default_docker_config() -> Dict[str, Any]:
        """Get default Docker configuration."""
        return {
            'docker_socket_path': '/var/run/docker.sock',
            'container_command_cooldown': 5,
            'docker_api_timeout': 30,
            'max_log_lines': 50,
            'servers': []
        }

    @staticmethod
    def get_default_web_config() -> Dict[str, Any]:
        """Get default web UI configuration."""
        return {
            'web_ui_password_hash': None,
            'web_ui_user': 'admin',
            'admin_enabled': True,
            'session_timeout': 3600,
            'donation_disable_key': '',
            'advanced_settings': {}
        }

    @staticmethod
    def get_default_channels_config() -> Dict[str, Any]:
        """Get default channels configuration."""
        return {
            'channels': {},
            'server_selection': {},
            'server_order': [],
            'channel_permissions': {},
            'spam_protection': {},
            'default_channel_permissions': {
                "commands": {
                    "serverstatus": True,
                    "command": False,
                    "control": False,
                    "schedule": False
                },
                "post_initial": False,
                "update_interval_minutes": 10,
                "inactivity_timeout_minutes": 10,
                "enable_auto_refresh": True,
                "recreate_messages_on_inactivity": True
            }
        }
