# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""
Configuration Form Parser Service - Handles web form parsing
Part of ConfigService refactoring for Single Responsibility Principle
"""

import logging
from typing import Dict, Any, Tuple

logger = logging.getLogger('ddc.config_form_parser')


class ConfigFormParserService:
    """
    Handles all web form parsing operations.

    Responsibilities:
    - Parse server/container configurations from form data
    - Parse channel permissions from form data
    - Process complete config forms
    """

    @staticmethod
    def _parse_display_name(raw_value, fallback: str) -> str:
        """Extract a clean display name from potentially messy form data."""
        # If it's an array, take first element
        if isinstance(raw_value, list) and len(raw_value) > 0:
            raw_value = raw_value[0]

        if isinstance(raw_value, str):
            if raw_value.startswith('[') and raw_value.endswith(']'):
                # It's a stringified list like "['Name1', 'Name2']"
                try:
                    import ast
                    parsed_list = ast.literal_eval(raw_value)
                    if isinstance(parsed_list, list) and len(parsed_list) > 0:
                        name = str(parsed_list[0])
                    else:
                        name = raw_value.strip("[]'\"")
                except (ValueError, SyntaxError, TypeError):
                    name = raw_value.strip("[]'\"")
            else:
                name = raw_value.strip()

            return name if name else fallback

        return fallback

    @staticmethod
    def _parse_form_checkbox(form_data: Dict[str, Any], key: str) -> bool:
        """Check if a form checkbox/value is truthy, handling arrays."""
        value = form_data.get(key)
        if isinstance(value, list) and len(value) > 0:
            value = value[0]
        return value in ['1', 'on', True, 'true', 'True']

    @staticmethod
    def parse_servers_from_form(form_data: Dict[str, Any]) -> list:
        """
        Parse container/server configuration from web form data.

        Form fields:
        - selected_servers: list of selected container names
        - display_name_<container>: display name for container
        - allow_status_<container>, allow_start_<container>, etc.: allowed actions
        """
        servers = []

        logger.debug(f"[FORM_DEBUG] Form data keys: {list(form_data.keys())[:20]}")

        # Get list of selected containers
        selected_servers = form_data.getlist('selected_servers') if hasattr(form_data, 'getlist') else \
                          (form_data.get('selected_servers') if isinstance(form_data.get('selected_servers'), list) else \
                           [form_data.get('selected_servers')] if form_data.get('selected_servers') else [])

        # Deduplicate while preserving order
        seen = set()
        selected_servers = [s for s in selected_servers if s not in seen and not seen.add(s)]

        logger.info(f"[FORM_DEBUG] Selected servers (Active checkboxes): {selected_servers}")

        for container_name in selected_servers:
            if not container_name:
                continue

            display_name = ConfigFormParserService._parse_display_name(
                form_data.get(f'display_name_{container_name}', container_name),
                fallback=container_name
            )

            allowed_actions = [
                action for action in ['status', 'start', 'stop', 'restart']
                if ConfigFormParserService._parse_form_checkbox(form_data, f'allow_{action}_{container_name}')
            ]

            order_value = form_data.get(f'order_{container_name}', 999)
            try:
                order = int(order_value) if order_value else 999
            except (ValueError, TypeError):
                order = 999

            servers.append({
                'docker_name': container_name,
                'name': container_name,
                'container_name': container_name,
                'display_name': display_name,
                'allowed_actions': allowed_actions,
                'allow_detailed_status': True,
                'order': order
            })
            logger.info(f"[FORM_DEBUG] Parsed server: {container_name} - actions: {allowed_actions}, order: {order}")

        logger.info(f"[FORM_DEBUG] Total servers parsed: {len(servers)}")
        return servers

    @staticmethod
    def _parse_channel_type(form_data: Dict[str, Any], prefix: str,
                            default_commands: Dict[str, bool]) -> Dict[str, Any]:
        """
        Parse channels of a given type (status or control) from form data.

        Args:
            form_data: Form data from web request
            prefix: Field name prefix ('status' or 'control')
            default_commands: Default command permissions for this channel type
        """
        channels = {}
        count = 1

        while count <= 50:
            channel_id_key = f'{prefix}_channel_id_{count}'
            raw = form_data.get(channel_id_key, '')
            channel_id = raw.strip() if isinstance(raw, str) else str(raw).strip()

            # Skip invalid Discord IDs (must be 17-19 digit numeric string)
            if channel_id and (not channel_id.isdigit() or not (17 <= len(channel_id) <= 19)):
                logger.warning(f"Skipping invalid {prefix} channel ID: {channel_id}")
                count += 1
                continue

            if not channel_id:
                # Check if there are more (non-sequential gaps from deleted rows)
                found_more = False
                for i in range(count + 1, count + 10):
                    if form_data.get(f'{prefix}_channel_id_{i}'):
                        count = i
                        found_more = True
                        break
                if not found_more:
                    break
                continue

            # Build channel config
            name_raw = form_data.get(f'{prefix}_channel_name_{count}', '')
            channel_config = {
                'name': name_raw.strip() if isinstance(name_raw, str) else '',
                'commands': dict(default_commands),
                'post_initial': form_data.get(f'{prefix}_post_initial_{count}') in ['1', 'on', True],
                'enable_auto_refresh': form_data.get(f'{prefix}_enable_auto_refresh_{count}') in ['1', 'on', True],
                'update_interval_minutes': int(form_data.get(f'{prefix}_update_interval_minutes_{count}', 1) or 1),
                'recreate_messages_on_inactivity': form_data.get(f'{prefix}_recreate_messages_{count}') in ['1', 'on', True],
                'inactivity_timeout_minutes': int(form_data.get(f'{prefix}_inactivity_timeout_{count}', 1) or 1)
            }
            channels[channel_id] = channel_config
            count += 1

        return channels

    @staticmethod
    def parse_channel_permissions_from_form(form_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Parse channel permissions from the two-table format.
        Status channels: status_channel_* fields
        Control channels: control_channel_* fields
        """
        status_commands = {
            'serverstatus': True, 'ss': True,
            'control': False, 'schedule': False, 'info': False
        }
        control_commands = {
            'serverstatus': True, 'ss': True,
            'control': True, 'schedule': True, 'info': True
        }

        channel_permissions = {}
        channel_permissions.update(
            ConfigFormParserService._parse_channel_type(form_data, 'status', status_commands))
        channel_permissions.update(
            ConfigFormParserService._parse_channel_type(form_data, 'control', control_commands))

        logger.info(f"Parsed {len(channel_permissions)} channel configurations from form")
        return channel_permissions

    # Form field prefixes that are handled by dedicated parsers (servers, channels, heartbeat)
    _SKIP_PREFIXES = (
        'display_name_', 'allow_status_', 'allow_start_', 'allow_stop_', 'allow_restart_',
        'order_', 'status_channel_', 'control_channel_', 'status_', 'control_',
        'old_status_channel_', 'old_control_channel_',
    )
    _SKIP_KEYS = {'selected_servers', 'heartbeat_ping_url', 'heartbeat_interval', 'enableHeartbeatSection'}

    @staticmethod
    def _parse_heartbeat(form_data: Dict[str, Any]) -> Dict[str, Any]:
        """Parse heartbeat (Status Watchdog) settings from form data."""
        ping_url = form_data.get('heartbeat_ping_url', '')
        if isinstance(ping_url, str):
            ping_url = ping_url.strip()

        if ping_url and ping_url.startswith('https://'):
            try:
                interval = int(form_data.get('heartbeat_interval', 5))
                interval = max(1, min(60, interval))
            except (ValueError, TypeError):
                interval = 5
            return {'enabled': True, 'ping_url': ping_url, 'interval': interval}

        return {'enabled': False, 'ping_url': '', 'interval': 5}

    @staticmethod
    def _save_channel_permissions(channel_permissions: Dict[str, Any]) -> None:
        """Save channel permissions via ChannelConfigService for consistency."""
        try:
            from services.config.channel_config_service import get_channel_config_service
            channel_service = get_channel_config_service()
            save_result = channel_service.save_all_channels(channel_permissions)
            if save_result:
                logger.info(f"Saved {len(channel_permissions)} channels via ChannelConfigService")
            else:
                logger.error("ChannelConfigService.save_all_channels returned False")
        except (AttributeError, IOError, ImportError, KeyError, ModuleNotFoundError,
                OSError, PermissionError, RuntimeError, TypeError) as e:
            logger.error(f"Error saving channels via ChannelConfigService: {e}", exc_info=True)

    @staticmethod
    def _process_donation_key(form_data: Dict[str, Any], updated_config: Dict[str, Any]) -> None:
        """Handle donation_disable_key field with validation."""
        value = form_data.get('donation_disable_key')
        if not isinstance(value, str):
            return
        value = value.strip()
        if value:
            try:
                from services.donation.donation_utils import validate_donation_key
                if validate_donation_key(value):
                    updated_config['donation_disable_key'] = value
            except (ImportError, ModuleNotFoundError):
                logger.error("Could not import donation_utils for key validation")
        else:
            updated_config.pop('donation_disable_key', None)

    @staticmethod
    def process_config_form(form_data: Dict[str, Any], current_config: Dict[str, Any],
                           config_service) -> Tuple[Dict[str, Any], bool, str]:
        """
        Process web form configuration.

        Args:
            form_data: Form data from web request
            current_config: Current configuration
            config_service: ConfigService instance for saving

        Returns:
            Tuple of (updated_config, success, message)
        """
        try:
            updated_config = current_config.copy()

            # Parse servers
            servers = ConfigFormParserService.parse_servers_from_form(form_data)
            if servers:
                updated_config['servers'] = servers
            else:
                logger.warning("No servers parsed from form data!")

            # Parse channels
            channel_permissions = ConfigFormParserService.parse_channel_permissions_from_form(form_data)
            if channel_permissions:
                updated_config['channel_permissions'] = channel_permissions
                ConfigFormParserService._save_channel_permissions(channel_permissions)

            # Parse heartbeat
            updated_config['heartbeat'] = ConfigFormParserService._parse_heartbeat(form_data)
            updated_config.pop('heartbeat_channel_id', None)

            # Process donation key
            ConfigFormParserService._process_donation_key(form_data, updated_config)

            # Process remaining form fields
            for key, value in form_data.items():
                if key in ConfigFormParserService._SKIP_KEYS or key == 'donation_disable_key':
                    continue
                if any(key.startswith(p) for p in ConfigFormParserService._SKIP_PREFIXES):
                    continue
                if isinstance(value, str):
                    value = value.strip()
                updated_config[key] = value

            # Save
            result = config_service.save_config(updated_config)
            return updated_config, result.success, result.message or "Configuration saved"

        except (RuntimeError, ValueError, TypeError) as e:
            logger.error(f"Error processing config form: {e}", exc_info=True)
            return current_config, False, str(e)
