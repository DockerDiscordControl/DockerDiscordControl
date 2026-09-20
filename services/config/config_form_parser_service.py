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
from typing import Dict, Any, List, Optional, Tuple

from services.exceptions import ConfigServiceError

logger = logging.getLogger('ddc.config_form_parser')

# The panel's channel table has at most this many rows (it numbers them from 1).
MAX_CHANNEL_ROWS = 50


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
    def _form_str(form_data: Dict[str, Any], key: str) -> str:
        """Return a form value as a single string ('' if missing), handling arrays."""
        value = form_data.get(key, '')
        if isinstance(value, list):
            value = value[0] if value else ''
        return value if isinstance(value, str) else ''

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

            # Game-server query (opengsq) per-container settings - sanitized/validated
            from services.config.config_validation_service import ConfigValidationService
            query_config = ConfigValidationService.sanitize_query_config(
                query_enabled=ConfigFormParserService._parse_form_checkbox(form_data, f'query_enabled_{container_name}'),
                query_protocol=form_data.get(f'query_protocol_{container_name}', 'source'),
                query_host=form_data.get(f'query_host_{container_name}', ''),
                query_port=form_data.get(f'query_port_{container_name}', 0),
                query_token=form_data.get(f'query_token_{container_name}', ''),
            )

            servers.append({
                'docker_name': container_name,
                'name': container_name,
                'container_name': container_name,
                'display_name': display_name,
                'allowed_actions': allowed_actions,
                'allow_detailed_status': True,
                'order': order,
                **query_config,
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

        # Every slot, not "until a gap": an empty row used to make this look ahead
        # only NINE slots and stop otherwise. Rows deleted in the panel can leave a
        # bigger gap, and the channels behind it never reached the parser - saving
        # then deleted exactly their permission files (save_all_channels removes every
        # <channel_id>.json that is not in the parsed set). Review B, section 11 F4.
        for count in range(1, MAX_CHANNEL_ROWS + 1):
            channel_id_key = f'{prefix}_channel_id_{count}'
            raw = form_data.get(channel_id_key, '')
            channel_id = raw.strip() if isinstance(raw, str) else str(raw).strip()

            # Skip invalid Discord IDs (must be 17-19 digit numeric string)
            if channel_id and (not channel_id.isdigit() or not (17 <= len(channel_id) <= 19)):
                logger.warning(f"Skipping invalid {prefix} channel ID: {channel_id}")
                continue

            if not channel_id:
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

        status_channels = ConfigFormParserService._parse_channel_type(
            form_data, 'status', status_commands)
        control_channels = ConfigFormParserService._parse_channel_type(
            form_data, 'control', control_commands)

        duplicates = sorted(set(status_channels) & set(control_channels))
        if duplicates:
            logger.warning(
                f"Channel ID(s) {', '.join(duplicates)} were submitted as status AND control "
                "channel. The control entry wins, so /serverstatus and /ss stay blocked there."
            )

        channel_permissions = {}
        channel_permissions.update(status_channels)
        channel_permissions.update(control_channels)

        logger.info(f"Parsed {len(channel_permissions)} channel configurations from form")
        return channel_permissions

    @staticmethod
    def find_duplicate_channel_ids(form_data: Dict[str, Any]) -> List[str]:
        """
        Return channel IDs submitted in BOTH the status and the control table.

        Such an ID is parsed twice and the control entry overwrites the status one, which
        silently turns the channel into a control channel where /serverstatus and /ss are
        denied. The web UI blocks this before saving. Server-side (e.g. direct API calls)
        the save still goes through; process_config_form only appends a warning about the
        duplicates to the save response.
        """
        status_ids = set(ConfigFormParserService._parse_channel_type(form_data, 'status', {}))
        control_ids = set(ConfigFormParserService._parse_channel_type(form_data, 'control', {}))
        return sorted(status_ids & control_ids)

    # Form field prefixes that are handled by dedicated parsers (servers, channels, heartbeat)
    _SKIP_PREFIXES = (
        'display_name_', 'allow_status_', 'allow_start_', 'allow_stop_', 'allow_restart_',
        'order_', 'status_channel_', 'control_channel_', 'status_', 'control_',
        'old_status_channel_', 'old_control_channel_',
        'query_enabled_', 'query_protocol_', 'query_host_', 'query_port_', 'query_token_',
        'env_',  # advanced settings -> folded into config['advanced_settings'] separately
        'info_',  # container info (incl. info_protected_password_*) -> config/containers/*.json
    )
    _SKIP_KEYS = {'selected_servers', 'heartbeat_ping_url', 'heartbeat_interval', 'enableHeartbeatSection',
                  # Defensive: bare modal field names must never become top-level config keys.
                  # The container-info modal lives (per HTML5 parsing) inside the main config-form,
                  # so any name= on its inputs would otherwise leak — notably query_token (a secret).
                  'query_protocol', 'query_host', 'query_port', 'query_token', 'container_name'}

    # Keys the generic form loop must never write: auth values only change through
    # change_web_ui_password(), and the structured values are built by the parsers above
    # and must not be replaced by a posted string.
    _PROTECTED_KEYS = frozenset({
        'web_ui_password_hash', 'web_ui_user',
        'encrypted_bot_token', 'bot_token_encrypted',
        'secret_key', 'SECRET_KEY', 'FLASK_SECRET_KEY',
        'servers', 'channel_permissions', 'default_channel_permissions', 'heartbeat', 'advanced_settings',
    })

    # Request-only values that are never settings. Earlier versions stored them in config.json
    # through the generic loop (the new password in cleartext, the decrypted bot token, the task
    # editor fields), so they are also dropped from the loaded config before saving.
    # 'timezone_str' is deliberately not listed: cogs/status_handlers.py reads it from the config.
    _NEVER_PERSIST_KEYS = frozenset({
        'new_web_ui_password', 'confirm_web_ui_password', 'password', 'confirm_password',
        'bot_token_decrypted_for_usage', 'csrf_token', 'csrf-token',
        # Task editor (tasks/form.html, tasks/list.html) - saved via the tasks API, not here
        'container', 'action', 'cycle', 'time', 'year', 'month', 'day', 'weekday',
        'cron_string', 'task_id', 'is_active',
        # Request options / markers
        'config_split_enabled', 'channel_tables_submitted',
    })

    @staticmethod
    def _is_never_persisted(key) -> bool:
        """True for keys that must not end up in config.json (see _NEVER_PERSIST_KEYS)."""
        return (not key or key in ConfigFormParserService._NEVER_PERSIST_KEYS
                or (isinstance(key, str) and key.startswith('info_')))

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
            # The page's on/off switch (sent as '0' when off). Switched off keeps the URL, so
            # switching it back on needs no retyping. Older clients don't send it: URL = on.
            enabled = ('enableHeartbeatSection' not in form_data or
                       ConfigFormParserService._parse_form_checkbox(form_data, 'enableHeartbeatSection'))
            return {'enabled': enabled, 'ping_url': ping_url, 'interval': interval}

        return {'enabled': False, 'ping_url': '', 'interval': 5}

    @staticmethod
    def _save_channel_permissions(channel_permissions: Dict[str, Any]) -> bool:
        """Save channel permissions via ChannelConfigService; True if they are on disk.

        The result used to be dropped by the caller, so a failed write (service
        returned False, or an exception in here) still answered the operator with
        "Configuration saved": the panel showed the new rights, the bot kept the old
        ones (SPEC.md Z3, review B5).
        """
        try:
            from services.config.channel_config_service import get_channel_config_service
            channel_service = get_channel_config_service()
            # process_config_form only passes an empty dict when the form explicitly
            # submitted zero channels, so an empty dict here means "remove all channels".
            save_result = channel_service.save_all_channels(
                channel_permissions, allow_empty=not channel_permissions)
            if save_result:
                logger.info(f"Saved {len(channel_permissions)} channels via ChannelConfigService")
                return True
            logger.error("ChannelConfigService.save_all_channels returned False")
            return False
        except (AttributeError, IOError, ImportError, KeyError, ModuleNotFoundError,
                OSError, PermissionError, RuntimeError, TypeError) as e:
            logger.error(f"Error saving channels via ChannelConfigService: {e}", exc_info=True)
            return False

    @staticmethod
    def _process_donation_key(form_data: Dict[str, Any],
                              updated_config: Dict[str, Any]) -> Optional[str]:
        """Handle donation_disable_key field with validation.

        Returns a sentence for the operator when the key was NOT taken over,
        and None when there is nothing to report. A key that the validator
        refuses - or cannot even be asked about - used to be dropped here
        without a word while the save went on to answer "Configuration
        saved"; the operator typed a key, was told all was well and had
        nothing stored (review C53).
        """
        value = form_data.get('donation_disable_key')
        if not isinstance(value, str):
            return None
        value = value.strip()
        if not value:
            updated_config.pop('donation_disable_key', None)
            return None

        try:
            from services.donation.donation_utils import validate_donation_key
        except (ImportError, ModuleNotFoundError) as e:
            logger.error(f"Could not import donation_utils for key validation: {e}")
            return ("The donation key could not be checked - the key check is "
                    "unavailable in this installation. The key was not saved, the "
                    "previous setting is unchanged.")

        if validate_donation_key(value):
            updated_config['donation_disable_key'] = value
            return None

        logger.warning("A donation key was entered that the validation refused")
        return ("The donation key was not accepted and was not saved - the previous "
                "setting is unchanged. See the log for the reason.")

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
            # Web UI password change ("New Password" in _auth_settings.html). Runs before
            # anything is written, so a rejected password aborts the whole save.
            password_changed = False
            # Token as stored before a possible password change (see the bot_token handling below)
            previous_token = current_config.get('bot_token')
            new_password = ConfigFormParserService._form_str(form_data, 'new_web_ui_password')
            if new_password:
                if ('confirm_web_ui_password' in form_data and
                        ConfigFormParserService._form_str(form_data, 'confirm_web_ui_password') != new_password):
                    return current_config, False, "The new Web UI passwords do not match. Nothing was saved."
                try:
                    from services.config.config_service import change_web_ui_password
                except ImportError as e:
                    logger.error(f"change_web_ui_password unavailable: {e}", exc_info=True)
                    return current_config, False, "The Web UI password could not be changed. Nothing was saved."
                try:
                    change_web_ui_password(new_password)
                except ValueError as e:
                    return current_config, False, f"Web UI password not changed: {e}. Nothing was saved."
                password_changed = True
                logger.info("Web UI password changed via configuration form")
                # The hash and the re-encrypted bot token changed on disk. Continue from the
                # fresh config so the save below doesn't write the old values back.
                current_config = config_service.get_config(force_reload=True)

            updated_config = current_config.copy()
            for key in [k for k in updated_config if ConfigFormParserService._is_never_persisted(k)]:
                updated_config.pop(key, None)

            # Parse servers
            servers = ConfigFormParserService.parse_servers_from_form(form_data)
            if servers:
                updated_config['servers'] = servers
            else:
                logger.warning("No servers parsed from form data!")

            # Parse channels. An empty result only means "delete all channels" when the form
            # says it contained the channel tables; a form without them must not wipe channels.
            channel_permissions = ConfigFormParserService.parse_channel_permissions_from_form(form_data)
            channels_saved = True
            if channel_permissions or ConfigFormParserService._parse_form_checkbox(form_data, 'channel_tables_submitted'):
                updated_config['channel_permissions'] = channel_permissions
                channels_saved = ConfigFormParserService._save_channel_permissions(channel_permissions)

            # Parse heartbeat
            updated_config['heartbeat'] = ConfigFormParserService._parse_heartbeat(form_data)
            updated_config.pop('heartbeat_channel_id', None)

            # Process donation key
            donation_warning = ConfigFormParserService._process_donation_key(
                form_data, updated_config)

            # Advanced settings: the advanced modal's saveAdvancedSettings() JS copies its
            # env_* inputs (checkboxes as '1'/'0', so the off-state is submitted too) into the
            # main config form. Map those env_<KEY> fields into config['advanced_settings'][<KEY>]
            # so they actually round-trip (read back by _prepare_advanced_settings and
            # _get_advanced_setting). Without this, env_ toggles never persisted.
            advanced = dict(updated_config.get('advanced_settings', {})) \
                if isinstance(updated_config.get('advanced_settings'), dict) else {}
            for key, value in form_data.items():
                if key.startswith('env_') and len(key) > 4:
                    if isinstance(value, str):
                        value = value.strip()
                    advanced[key[4:]] = value
            if advanced:
                updated_config['advanced_settings'] = advanced

            # Process remaining form fields
            for key, value in form_data.items():
                if key in ConfigFormParserService._SKIP_KEYS or key == 'donation_disable_key':
                    continue
                if key in ConfigFormParserService._PROTECTED_KEYS or ConfigFormParserService._is_never_persisted(key):
                    logger.debug(f"Ignoring non-setting form field: {key!r}")
                    continue
                if any(key.startswith(p) for p in ConfigFormParserService._SKIP_PREFIXES):
                    continue
                if isinstance(value, str):
                    value = value.strip()
                if key == 'bot_token' and (not value or (password_changed and value == previous_token)):
                    # An empty token field means "keep the current token", never "delete it".
                    # After a password change the page still posts the token encrypted with the
                    # old key; it was just re-encrypted, so keep the fresh value.
                    continue
                updated_config[key] = value

            # Save
            result = config_service.save_config(updated_config)
            message = result.message or "Configuration saved"

            if password_changed:
                message += " Web UI password changed; log in again with the new password."

            duplicates = ConfigFormParserService.find_duplicate_channel_ids(form_data)
            if result.success and duplicates:
                message += (
                    f" Warning: channel ID(s) {', '.join(duplicates)} are listed as both a status "
                    "and a control channel. They were saved as control channels, where "
                    "/serverstatus and /ss are not allowed. Use a separate channel for the "
                    "status overview."
                )

            if result.success and donation_warning:
                message += " " + donation_warning

            if not channels_saved:
                # Z3: the main configuration may well have been saved, but the channel
                # permission files were not - the bot keeps the old rights. Do not call
                # that a success (review B5).
                return updated_config, False, (
                    "The channel permissions could not be saved - the bot keeps the "
                    "previous channel rights. See the log for the reason.")

            return updated_config, result.success, message

        except ConfigServiceError as e:
            # Persistence errors (disk full, permission denied) raised by save_config or
            # change_web_ui_password
            logger.error(f"Config service error processing config form: {e}", exc_info=True)
            return current_config, False, e.message
        except (RuntimeError, ValueError, TypeError) as e:
            logger.error(f"Error processing config form: {e}", exc_info=True)
            return current_config, False, str(e)
