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

import discord

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
    def parse_servers_from_form(form_data: Dict[str, Any]) -> list:
        """
        Parse container/server configuration from web form data.

        Form fields:
        - selected_servers: list of selected container names
        - display_name_<container>: display name for container
        - allow_status_<container>, allow_start_<container>, etc.: allowed actions
        """
        servers = []

        # DEBUG: Log all form keys to see what we receive
        logger.info(f"[FORM_DEBUG] Form data keys: {list(form_data.keys())[:20]}")  # First 20 keys

        # DEBUG: Log checkbox-related keys specifically
        checkbox_keys = [k for k in form_data.keys() if 'allow_' in k or 'display_' in k]
        logger.info(f"[FORM_DEBUG] Checkbox/display keys: {checkbox_keys[:30]}")

        # DEBUG: Log actual checkbox values
        checkbox_count = 0
        for k in form_data.keys():
            if 'allow_' in k:
                logger.info(f"[FORM_DEBUG] {k} = {repr(form_data.get(k))}")
                checkbox_count += 1
        logger.info(f"[FORM_DEBUG] Total allow_ checkboxes found: {checkbox_count}")

        # Get list of selected containers
        selected_servers = form_data.getlist('selected_servers') if hasattr(form_data, 'getlist') else \
                          (form_data.get('selected_servers') if isinstance(form_data.get('selected_servers'), list) else \
                           [form_data.get('selected_servers')] if form_data.get('selected_servers') else [])

        # Handle the case where selected_servers comes as arrays of duplicates
        # e.g., ['dockerdiscordcontrol', 'dockerdiscordcontrol'] -> ['dockerdiscordcontrol']
        selected_servers_clean = []
        seen = set()
        for server in selected_servers:
            if server not in seen:
                selected_servers_clean.append(server)
                seen.add(server)
        selected_servers = selected_servers_clean

        logger.info(f"[FORM_DEBUG] Selected servers (Active checkboxes): {selected_servers}")

        # DO NOT automatically add containers based on allow_status or other checkboxes
        # ONLY containers with the "Active" checkbox (selected_servers) should be shown in Discord
        # The other checkboxes (Status, Start, Stop, Restart) only control what actions are allowed
        # for ACTIVE containers

        for container_name in selected_servers:
            if not container_name:
                continue

            # Extract display name
            display_name_key = f'display_name_{container_name}'
            display_name_raw = form_data.get(display_name_key, container_name)
            logger.debug(f"[FORM_DEBUG] Raw display_name for {container_name}: {repr(display_name_raw)}")

            # Handle different display_name formats - now as single string!
            display_name = container_name  # Default to container name

            # If it's an array, take first element
            if isinstance(display_name_raw, list) and len(display_name_raw) > 0:
                display_name_raw = display_name_raw[0]

            if isinstance(display_name_raw, str):
                # Clean up any stringified list representations
                if display_name_raw.startswith('[') and display_name_raw.endswith(']'):
                    # It's a stringified list like "['Name1', 'Name2']"
                    try:
                        import ast
                        parsed_list = ast.literal_eval(display_name_raw)
                        if isinstance(parsed_list, list) and len(parsed_list) > 0:
                            # Take the first element
                            display_name = str(parsed_list[0])
                        else:
                            # Couldn't parse, use raw value
                            display_name = display_name_raw.strip("[]'\"")
                    except (ValueError, SyntaxError, TypeError):
                        # Failed to parse, treat as regular string
                        display_name = display_name_raw.strip("[]'\"")
                else:
                    # It's a regular string, use as-is
                    display_name = display_name_raw.strip()

            # Ensure we have a valid display name
            if not display_name:
                display_name = container_name

            logger.debug(f"[FORM_DEBUG] Parsed display_name for {container_name}: {display_name}")

            # Extract allowed actions
            allowed_actions = []
            for action in ['status', 'start', 'stop', 'restart']:
                action_key = f'allow_{action}_{container_name}'
                # HTML checkboxes send "on" when checked, or don't exist when unchecked
                # Also handle '1' for compatibility
                value = form_data.get(action_key)
                logger.debug(f"[FORM_DEBUG] Checking {action_key}: value={repr(value)}")

                # Handle arrays (when value comes as ['1', '1'])
                if isinstance(value, list):
                    if len(value) > 0:
                        value = value[0]  # Take first element

                # Now check the actual value
                if value in ['1', 'on', True, 'true', 'True']:
                    allowed_actions.append(action)
                    logger.info(f"[FORM_DEBUG] ✓ Added action {action} for {container_name} (value={repr(value)})")
                elif value == '0':
                    logger.debug(f"[FORM_DEBUG] ✗ Action {action} for {container_name} is disabled (value='0')")

            # Extract order value
            order_key = f'order_{container_name}'
            order_value = form_data.get(order_key, 999)
            try:
                order = int(order_value) if order_value else 999
            except (ValueError, TypeError):
                order = 999

            # Build server config
            server_config = {
                'docker_name': container_name,
                'name': container_name,
                'container_name': container_name,
                'display_name': display_name,  # Now a single string!
                'allowed_actions': allowed_actions,
                'allow_detailed_status': True,  # Default to True
                'order': order
            }

            servers.append(server_config)
            logger.info(f"[FORM_DEBUG] Parsed server: {container_name} - actions: {allowed_actions}, order: {order}")

        logger.info(f"[FORM_DEBUG] Total servers parsed: {len(servers)}")
        return servers

    @staticmethod
    def parse_channel_permissions_from_form(form_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Parse channel permissions from the new two-table format.
        Status channels: status_channel_* fields
        Control channels: control_channel_* fields
        """
        channel_permissions = {}

        # Process Status Channels
        status_channel_count = 1
        while True:
            channel_id_key = f'status_channel_id_{status_channel_count}'
            channel_id = form_data.get(channel_id_key, '').strip() if isinstance(form_data.get(channel_id_key), str) else str(form_data.get(channel_id_key, '')).strip()

            if not channel_id:
                # Check if there are more (non-sequential)
                found_more = False
                for i in range(status_channel_count + 1, status_channel_count + 10):
                    if form_data.get(f'status_channel_id_{i}'):
                        status_channel_count = i
                        found_more = True
                        break
                if not found_more:
                    break
            else:
                # Build channel config for status channel
                channel_config = {
                    'name': form_data.get(f'status_channel_name_{status_channel_count}', '').strip() if isinstance(form_data.get(f'status_channel_name_{status_channel_count}'), str) else '',
                    'commands': {
                        'serverstatus': True,  # Always enabled for status channels
                        'ss': True,  # Alias for serverstatus
                        'control': False,  # Never enabled for status channels
                        'schedule': False,  # Will be checked against admin users
                        'info': False  # Will be checked against admin users
                    },
                    'post_initial': form_data.get(f'status_post_initial_{status_channel_count}') in ['1', 'on', True],
                    'enable_auto_refresh': form_data.get(f'status_enable_auto_refresh_{status_channel_count}') in ['1', 'on', True],
                    'update_interval_minutes': int(form_data.get(f'status_update_interval_minutes_{status_channel_count}', 1) or 1),
                    'recreate_messages_on_inactivity': form_data.get(f'status_recreate_messages_{status_channel_count}') in ['1', 'on', True],
                    'inactivity_timeout_minutes': int(form_data.get(f'status_inactivity_timeout_{status_channel_count}', 1) or 1)
                }
                channel_permissions[channel_id] = channel_config

            status_channel_count += 1
            if status_channel_count > 50:  # Safety limit
                break

        # Process Control Channels
        control_channel_count = 1
        while True:
            channel_id_key = f'control_channel_id_{control_channel_count}'
            channel_id = form_data.get(channel_id_key, '').strip() if isinstance(form_data.get(channel_id_key), str) else str(form_data.get(channel_id_key, '')).strip()

            if not channel_id:
                # Check if there are more (non-sequential)
                found_more = False
                for i in range(control_channel_count + 1, control_channel_count + 10):
                    if form_data.get(f'control_channel_id_{i}'):
                        control_channel_count = i
                        found_more = True
                        break
                if not found_more:
                    break
            else:
                # Build channel config for control channel
                channel_config = {
                    'name': form_data.get(f'control_channel_name_{control_channel_count}', '').strip() if isinstance(form_data.get(f'control_channel_name_{control_channel_count}'), str) else '',
                    'commands': {
                        'serverstatus': True,  # Enabled for control channels
                        'ss': True,  # Alias
                        'control': True,  # Always enabled for control channels
                        'schedule': True,  # Always enabled for control channels
                        'info': True  # Always enabled for control channels
                    },
                    'post_initial': form_data.get(f'control_post_initial_{control_channel_count}') in ['1', 'on', True],
                    'enable_auto_refresh': form_data.get(f'control_enable_auto_refresh_{control_channel_count}') in ['1', 'on', True],
                    'update_interval_minutes': int(form_data.get(f'control_update_interval_minutes_{control_channel_count}', 1) or 1),
                    'recreate_messages_on_inactivity': form_data.get(f'control_recreate_messages_{control_channel_count}') in ['1', 'on', True],
                    'inactivity_timeout_minutes': int(form_data.get(f'control_inactivity_timeout_{control_channel_count}', 1) or 1)
                }
                channel_permissions[channel_id] = channel_config

            control_channel_count += 1
            if control_channel_count > 50:  # Safety limit
                break

        logger.info(f"Parsed {len(channel_permissions)} channel configurations from form")
        return channel_permissions

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
            # Merge form data with current config
            updated_config = current_config.copy()

            # Parse servers from form data
            servers = ConfigFormParserService.parse_servers_from_form(form_data)
            logger.info(f"[PROCESS_DEBUG] parse_servers_from_form returned {len(servers)} servers")
            if servers:
                updated_config['servers'] = servers
                logger.info(f"[PROCESS_DEBUG] Added {len(servers)} servers to updated_config")
                # Log first server for debugging
                if servers:
                    logger.info(f"[PROCESS_DEBUG] First server: {servers[0].get('docker_name')} with actions: {servers[0].get('allowed_actions')}")
            else:
                logger.warning("[PROCESS_DEBUG] No servers parsed from form data!")

            # Parse channel permissions from the new two-table format
            channel_permissions = ConfigFormParserService.parse_channel_permissions_from_form(form_data)
            if channel_permissions:
                updated_config['channel_permissions'] = channel_permissions
                logger.info(f"[PROCESS_DEBUG] Added {len(channel_permissions)} channel permissions to updated_config")

                # IMPORTANT: Also save to ChannelConfigService for consistency
                try:
                    from services.config.channel_config_service import get_channel_config_service
                    channel_service = get_channel_config_service()
                    channel_service.save_all_channels(channel_permissions)
                    logger.info(f"[PROCESS_DEBUG] Saved {len(channel_permissions)} channels via ChannelConfigService")
                except (AttributeError, IOError, ImportError, KeyError, ModuleNotFoundError, OSError, PermissionError, RuntimeError, TypeError) as e:
                    logger.error(f"Error saving channels via ChannelConfigService: {e}", exc_info=True)

            # Process heartbeat (Status Watchdog) settings
            heartbeat_config = {}

            # Get ping URL
            ping_url = form_data.get('heartbeat_ping_url', '')
            if isinstance(ping_url, str):
                ping_url = ping_url.strip()

            # Only enable if valid HTTPS URL is provided
            if ping_url and ping_url.startswith('https://'):
                heartbeat_config['enabled'] = True
                heartbeat_config['ping_url'] = ping_url

                # Get interval (default 5 minutes)
                try:
                    interval = int(form_data.get('heartbeat_interval', 5))
                    heartbeat_config['interval'] = max(1, min(60, interval))  # Clamp 1-60
                except (ValueError, TypeError):
                    heartbeat_config['interval'] = 5
            else:
                heartbeat_config['enabled'] = False
                heartbeat_config['ping_url'] = ''
                heartbeat_config['interval'] = 5

            updated_config['heartbeat'] = heartbeat_config
            # Remove legacy fields if present
            updated_config.pop('heartbeat_channel_id', None)

            # Process each form field
            for key, value in form_data.items():
                # Skip server-related fields (already processed above)
                if key in ['selected_servers'] or key.startswith('display_name_') or \
                   key.startswith('allow_status_') or key.startswith('allow_start_') or \
                   key.startswith('allow_stop_') or key.startswith('allow_restart_'):
                    continue

                # Skip channel-related fields (already processed above)
                if key.startswith('status_channel_') or key.startswith('control_channel_') or \
                   key.startswith('status_') or key.startswith('control_') or \
                   key.startswith('old_status_channel_') or key.startswith('old_control_channel_'):
                    continue

                # Skip heartbeat fields (already processed above)
                if key in ['heartbeat_ping_url', 'heartbeat_interval', 'enableHeartbeatSection']:
                    continue

                if key == 'donation_disable_key':
                    # Special handling for donation key
                    if isinstance(value, str):
                        value = value.strip()
                        if value:
                            # Validate the key
                            from services.donation.donation_utils import validate_donation_key
                            if validate_donation_key(value):
                                updated_config[key] = value
                            # Invalid keys are silently ignored (not saved)
                        else:
                            # Empty key means remove it (reactivate donations)
                            updated_config.pop(key, None)
                    continue

                # Handle other form fields
                if isinstance(value, str):
                    value = value.strip()
                updated_config[key] = value

            # Save the configuration
            result = config_service.save_config(updated_config)

            # Debug: Log if servers are in the updated config
            if 'servers' in updated_config:
                logger.info(f"[PROCESS_DEBUG] Returning updated_config with {len(updated_config.get('servers', []))} servers")
            else:
                logger.warning("[PROCESS_DEBUG] Returning updated_config WITHOUT servers key!")

            return updated_config, result.success, result.message or "Configuration saved"

        except (RuntimeError, ValueError, TypeError) as e:
            logger.error(f"Error processing config form: {e}", exc_info=True)
            return current_config, False, str(e)
