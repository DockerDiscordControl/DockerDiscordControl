# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Which configured channels play which role - decided in one place."""

import logging
from typing import Any, Dict, List

logger = logging.getLogger("ddc.channel_roles")


def control_channel_ids(config: Dict[str, Any]) -> List[int]:
    """The channels with the control permission, in both config formats.

    Used by the update notice and by the container watchdog's default notice
    channel (tests/spec/test_control_channels_are_found_in_one_place.py).
    """
    channels: List[int] = []
    # New format: channel_permissions
    for channel_id, perms in (config.get('channel_permissions') or {}).items():
        # Guarded like status_channel_ids: a null "commands" or a list entry (hand
        # edits) raised AttributeError here (stage 4 review before v3.1.0, 13).
        commands = perms.get('commands') if isinstance(perms, dict) else None
        if isinstance(commands, dict) and commands.get('control', False):
            try:
                channels.append(int(channel_id))
            except ValueError:
                logger.debug(f"Invalid channel ID: {channel_id}")
    # Old format fallback: channels array
    if not channels:
        for channel_config in config.get('channels', []) or []:
            if 'control' in channel_config.get('permissions', []):
                try:
                    channels.append(int(channel_config['channel_id']))
                except (ValueError, KeyError):
                    pass
    return channels


def status_channel_ids(config: Dict[str, Any]) -> List[int]:
    """The channels with the serverstatus permission - where the players look.

    The same question the donation appeal and the member count ask; the player
    warning of v3.1.0 (services/scheduling/player_gate.py) asks it here.
    """
    channels: List[int] = []
    for channel_id, perms in (config.get('channel_permissions') or {}).items():
        commands = (perms or {}).get('commands', {}) if isinstance(perms, dict) else {}
        if isinstance(commands, dict) and commands.get('serverstatus', False):
            try:
                channels.append(int(channel_id))
            except ValueError:
                logger.debug(f"Invalid channel ID: {channel_id}")
    return channels
